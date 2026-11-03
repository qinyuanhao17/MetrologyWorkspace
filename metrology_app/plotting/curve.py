"""Dense curves cached outside the GUI process, with full-data native export.

Only detached arrays and QPainterPath/QPen values reach the workers. Qt widgets,
scene items, source arrays, axis labels and export painting stay with Qt's owner.
"""
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import multiprocessing
from time import monotonic
from weakref import finalize, ref

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QByteArray, QDataStream, QEvent, QIODevice, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsPixmapItem


_RENDERER = None
_SOLID_RENDERER = None


def _cancel_pending(holder):
    if holder[0] is not None:
        holder[0].cancel()


def _screen_path(x, y, transform, tolerance):
    """Simplify only dense screen geometry in physical pixels, preserving NaN gaps."""
    from matplotlib.path import Path
    from matplotlib.transforms import Affine2D
    source = Path(np.column_stack((x, y)))
    source.simplify_threshold = tolerance
    affine = Affine2D.from_values(transform.m11(), transform.m12(), transform.m21(),
                                 transform.m22(), transform.dx(), transform.dy())
    cleaned = source.cleaned(transform=affine, remove_nans=True, simplify=True, snap=False)
    vertices, codes = cleaned.vertices[:-1], cleaned.codes[:-1]  # omit STOP sentinel
    connect = np.zeros(len(codes), dtype=np.int32)
    connect[:-1] = codes[1:] == Path.LINETO
    return pg.functions.arrayToQPath(vertices[:, 0], vertices[:, 1], connect=connect, finiteCheck=False)


def _render_path(payload, width, height, antialias, segments=None, colored_segments=None, screen_error=0.0):
    buffer = QByteArray(payload)
    stream = QDataStream(buffer, QIODevice.OpenModeFlag.ReadOnly)
    path, pen, transform = QPainterPath(), QPen(), QTransform()
    stream >> path >> pen >> transform
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, antialias)
        painter.setPen(pen)
        painter.setWorldTransform(transform)
        if colored_segments is not None:
            from pyqtgraph.graphicsItems.PlotCurveItem import arrayToLineSegments
            simplify = screen_error and sum(len(x) for x, _, _ in colored_segments) > 32_000
            for x, y, pen_bytes in colored_segments:
                pen_buffer = QByteArray(pen_bytes)
                pen_stream = QDataStream(pen_buffer, QIODevice.OpenModeFlag.ReadOnly)
                color_pen = QPen()
                pen_stream >> color_pen
                painter.setPen(color_pen)
                if simplify:
                    # Native/export painting always keeps every source sample.
                    # Small or zoomed paths cost less to draw directly.
                    screen_path = _screen_path(x, y, transform, screen_error)
                    painter.save()
                    painter.resetTransform()
                    painter.drawPath(screen_path)
                    painter.restore()
                elif not antialias and color_pen.widthF() > 1:
                    lines = arrayToLineSegments(x, y, connect='finite', finiteCheck=True)
                    painter.drawLines(*lines.drawargs())
                else:
                    painter.drawPath(pg.functions.arrayToQPath(x, y, connect='finite', finiteCheck=True))
        elif segments is None:
            painter.drawPath(path)
        else:
            from pyqtgraph.graphicsItems.PlotCurveItem import arrayToLineSegments
            lines = arrayToLineSegments(*segments, connect='finite', finiteCheck=True)
            painter.drawLines(*lines.drawargs())
    finally:
        painter.end()
    return bytes(image.constBits().asstring(image.sizeInBytes()))


class _CurveRasterizer(QObject):
    rendering_changed = pyqtSignal()
    def __init__(self, curve, *, solid=False, screen_error=0.0):
        super().__init__(curve)
        self.curve = curve
        self._solid = solid
        self._screen_error = screen_error
        self._disposed = False
        self._visible = True
        self._native_export_mode = curve.setExportMode
        curve.setExportMode = self._set_export_mode
        self.image_item = QGraphicsPixmapItem(curve.parentItem())
        self.image_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.image_item.hide()
        self._viewport = None
        self._screen_enabled = False
        self._revision = 0
        self._cached = None
        self._future = None
        self._latest = None
        self._running = None
        self._failed = False
        self._needs_render = False
        self._resize_until = 0.0
        self._future_holder = [None]
        # This cache's Python QObject.destroyed cleanup crashes this Qt runtime
        # while native scene children are disposed. No Qt pointer is needed to
        # cancel a detached Future; finalize when its Python owner is released.
        finalize(self, _cancel_pending, self._future_holder)
        self._poll = QTimer(self, interval=16)
        self._poll.timeout.connect(self._finish)
        self._prepare = QTimer(self, singleShot=True)
        self._prepare.timeout.connect(self._request)
        curve.sigPlotChanged.connect(self._changed)
        # Keep the native curve's identity and paint method untouched. The
        # screen image is a native Qt item; no Python paint override is needed.
        self._changed()
        if solid:
            view = curve.getViewBox()
            if view is not None and view.scene() is not None and view.scene().views():
                self._viewport = view.scene().views()[0].viewport()
                self._viewport.installEventFilter(self)
                view.sigRangeChanged.connect(self._request_later)

    @property
    def opts(self):
        return self.curve.opts

    @property
    def xData(self):
        return self.curve.xData

    @property
    def _exportOpts(self):
        return self.curve._exportOpts

    def _changed(self, *_):
        if self._disposed:
            return
        self._revision += 1
        self._cached = None
        self._latest = None
        self.image_item.hide()
        pen = self.opts['pen']
        self._needs_render = bool(self.xData is not None and len(self.xData) >= 2000
                                  and pen is not None and pen.isCosmetic()
                                  and pen.style() != Qt.PenStyle.NoPen
                                  and (self._solid or pen.style() != Qt.PenStyle.SolidLine))
        if not self._visible:
            self.cancel()
            return
        if self._solid:
            # Suppress native paint before a synchronous viewport repaint can
            # run; the preparation timer installs the detached image job.
            self._show_curve(not self._needs_render)
        self._prepare.start(16 if self._solid else 0)

    def _show_curve(self, visible):
        if self._solid:
            # A standalone curve is also the ViewBox's bounds authority. Keep
            # it visible for auto-range, without invoking native screen paint.
            self.curve.setOpacity(1.0 if visible else 0.0)
        else:
            self.curve.setVisible(visible)

    def cancel(self):
        self._prepare.stop()
        self._poll.stop()
        _cancel_pending(self._future_holder)
        self._future_holder[0] = None
        self._future = self._latest = self._running = None
        self._needs_render = False

    def set_visible(self, visible):
        """Toggle a standalone curve and its sibling raster without losing data/cache."""
        visible = bool(visible)
        if self._visible == visible:
            return
        self._visible = visible
        if visible and self._solid and self.xData is not None and len(self.xData) >= 2000:
            # Suppress native million-point painting before exposing the item.
            # Otherwise one paint event can block the cache-preparation timer.
            self._show_curve(False)
        self.curve.setVisible(visible)
        if visible:
            self._request_later()
        else:
            self.image_item.hide()
            self.cancel()

    def dispose(self):
        self._disposed = True
        self.cancel()
        self.image_item.hide()
        if self.image_item.scene() is not None:
            self.image_item.scene().removeItem(self.image_item)
        self.image_item.setParentItem(None)

    @property
    def render_pending(self):
        return (self._prepare.isActive() or self._needs_render or self._future is not None or self._latest is not None
                and (self._cached is None or self._latest[0] != self._cached[0]))

    def eventFilter(self, watched, event):
        if self._disposed or not self._visible:
            return False
        if self._solid and event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Show):
            if event.type() == QEvent.Type.Resize:
                self._resize_until = monotonic() + .08
            self._request_later()
            return False
        if event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Show):
            self._request()
        return False

    def _request(self):
        if self._disposed or not self._visible:
            return
        pen = self.opts['pen']
        # File/PNG/vector export uses the original complete painting directly.
        # Unsupported styles also retain pyqtgraph's full implementation.
        eligible = not (self._failed or isinstance(self._exportOpts, dict)
                or self.xData is None or len(self.xData) < 2000
                or pen is None or not pen.isCosmetic() or pen.style() == Qt.PenStyle.NoPen
                or not self._solid and pen.style() == Qt.PenStyle.SolidLine
                or self.opts['fillLevel'] is not None or self.opts['shadowPen'] is not None
                or self.opts['compositionMode'] is not None or self.opts['segmentedLineMode'] == 'on'
                or getattr(self.curve, 'clickable', False))
        self._screen_enabled = eligible
        if not eligible:
            self._needs_render = False
            self.image_item.hide()
            self._show_curve(self.xData is not None and
                             (pen is not None or self.opts['fillLevel'] is not None))
            return
        view = self.curve.getViewBox()
        if view is None or view.scene() is None or not view.scene().views():
            self._needs_render = False
            return
        viewport_view = view.scene().views()[0]
        viewport = viewport_view.viewport()
        if self._viewport is not viewport:
            self._viewport = viewport
            viewport.installEventFilter(self)
            view.sigRangeChanged.connect(self._request_later)
        if not viewport.isVisible():
            self._needs_render = False
            return
        transform = self.curve.deviceTransform(viewport_view.viewportTransform())
        transform *= QTransform.fromScale(viewport.devicePixelRatioF(), viewport.devicePixelRatioF())
        rect = transform.mapRect(self.curve.mapRectFromScene(view.sceneBoundingRect())).toAlignedRect()
        if rect.width() < 1 or rect.height() < 1 or rect.width() * rect.height() > 4_000_000:
            self._needs_render = False
            self._screen_enabled = False
            self.image_item.hide()
            self._show_curve(True)
            return
        matrix = (transform.m11(), transform.m12(), transform.m21(), transform.m22(),
                  transform.dx(), transform.dy())
        # Moving the enclosing scroll area changes only the backing-store
        # origin. Reuse the image unless its local pixel geometry changed.
        local_matrix = (*matrix[:4], transform.dx() - rect.x(), transform.dy() - rect.y())
        segmented = self._solid and self.curve._shouldUseDrawLineSegments(pen)
        key = (self._revision, QPen(pen), bool(self.opts['antialias']), segmented,
               local_matrix, rect.width(), rect.height())
        if self._cached is None or self._cached[0] != key:
            if self._latest is None or self._latest[0] != key:
                if hasattr(self.curve, 'raster_components'):
                    path = self.curve.raster_components()
                else:
                    path = ((self.curve.xData.copy(), self.curve.yData.copy()) if segmented
                            else QPainterPath(self.curve.getPath()))
                self._latest = (key, QTransform(transform), rect, path, QPen(pen), bool(self.opts['antialias']))
                if self._solid and self._future is not None and self._future.cancel():
                    self._future = self._running = None
                    self._future_holder[0] = None
            self._start()
        self._needs_render = False
        self._show_curve(False)
        self.image_item.setZValue(self.curve.zValue())
        if self._cached is not None:
            self.image_item.show()

    def _request_later(self, *_args):
        if not self._disposed and self._visible:
            self._prepare.start(max(16, int((self._resize_until - monotonic()) * 1000)) if self._solid else 0)

    def _set_export_mode(self, export, opts=None):
        # Scene exporters do not deliver a QWidget paint event. Expose the
        # original full-data curve before their scene traversal, not the cache.
        self._native_export_mode(export, opts)
        if export:
            self.image_item.hide()
            if self._screen_enabled and self._visible:
                self._show_curve(True)
        elif self._visible:
            self._prepare.start(0)

    def _start(self):
        if self._future is not None or self._latest is None:
            return
        self._running = self._latest
        _, _, rect, path, pen, antialias = self._running
        payload = QByteArray()
        stream = QDataStream(payload, QIODevice.OpenModeFlag.WriteOnly)
        transform = self._running[1]
        local = QTransform(transform.m11(), transform.m12(), transform.m21(), transform.m22(),
                           transform.dx() - rect.x(), transform.dy() - rect.y())
        segments = path if isinstance(path, tuple) else None
        colored_segments = path if isinstance(path, list) else None
        stream << (QPainterPath() if segments is not None or colored_segments is not None else path) << pen << local
        global _RENDERER, _SOLID_RENDERER
        if self._solid:
            if _SOLID_RENDERER is None:
                _SOLID_RENDERER = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn'))
            renderer = _SOLID_RENDERER
        else:
            if _RENDERER is None:
                # QPainter retains the GIL in this runtime; isolate raster work.
                _RENDERER = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
            renderer = _RENDERER
        try:
            self._future = renderer.submit(_render_path, bytes(payload), rect.width(), rect.height(), antialias,
                                           segments, colored_segments, self._screen_error)
        except Exception:
            self._failed = True
            self._latest = None
            self._needs_render = False
            self._screen_enabled = False
            self._show_curve(True)
            self.curve.update()
            return
        self._poll.start()
        self._future_holder[0] = self._future
        self.rendering_changed.emit()

    def _finish(self):
        if self._future is None or not self._future.done():
            return
        self._poll.stop()
        future, self._future = self._future, None
        self._future_holder[0] = None
        request, self._running = self._running, None
        try:
            pixels = future.result()  # done() checked: never wait on GUI.
            rect = request[2]
            image = QImage(pixels, rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied).copy()
        except Exception:
            self._failed = True
            self._latest = None
            self._needs_render = False
            self._screen_enabled = False
            self._show_curve(True)
        else:
            if self._latest is not None and request[0] == self._latest[0]:
                self._cached = (*request[:3], image)
                inverse, valid = request[1].inverted()
                if valid:
                    self.image_item.setPixmap(QPixmap.fromImage(image))
                    self.image_item.setTransform(QTransform.fromTranslate(rect.x(), rect.y()) * inverse)
                    self.image_item.show()
            elif self._latest is not None:
                self._start()
        self.curve.update()
        self.rendering_changed.emit()


def cache_curve_image(curve, *, screen_error=0.0):
    """Cache a standalone dense curve in workers; retain native bounds/export.

    Call dispose() before removing the curve from its scene. render_pending
    exposes completion; only detached data and Qt values reach the workers.
    screen_error optionally enables display-only simplification at that physical
    pixel tolerance for dense multicolor paths. Native/export data is untouched.
    """
    return _CurveRasterizer(curve, solid=True, screen_error=screen_error)


class _UniformSymbolAtlas:
    """Coalesce equal style lookups; keep the native atlas, pixels and point data.

    PyQtGraph supplies one style tuple per point even for a uniform scatter.
    Resolve that symbol once and broadcast its rectangle. Mixed/hover styles,
    atlas rebuilding, display scale changes and rendering remain native.
    """

    def __init__(self, native):
        self._native = native

    def __len__(self):
        return len(self._native)

    def __getattr__(self, name):
        return getattr(self._native, name)

    def __getitem__(self, styles):
        if len(styles) > 1 and all(style == styles[0] for style in styles[1:]):
            return self._native[styles[:1]] * len(styles)
        return self._native[styles]


def _broadcast_uniform_styles(scatter):
    """Enumerate one atlas style only when every point uses its defaults.

    Native updateSpots broadcasts that one rectangle to its full sourceRect
    array. Point data, hit testing, bounds, atlas rebuilds and painting stay
    native. Per-point/hover/scaled styles retain the original enumeration.
    """
    owner, native = ref(scatter), type(scatter)._style

    def styles(opts, data=None, idx=None, scale=None):
        item = owner()
        data = item.data if data is None else data
        if (isinstance(opts, (list, tuple)) and tuple(opts) == ('symbol', 'size', 'pen', 'brush')
                and scale is None and not item.opts['hoverable'] and len(data)
                and all(name in data.dtype.names for name in opts)
                and all(np.all(data[name] == (-1 if name == 'size' else None)) for name in opts)):
            return tuple((item.opts[name],) for name in opts)
        return native(item, opts, data=data, idx=idx, scale=scale)

    return styles


class ResponsivePlotDataItem(pg.PlotDataItem):
    """Keep unchanged scatter/curve data when only the viewport changed."""
    rendering_changed = pyqtSignal()

    def __init__(self, *args, broadcast_uniform_symbols=False, **kwargs):
        if broadcast_uniform_symbols:
            # Install the adapter before the first dense scatter is registered.
            super().__init__()
        else:
            super().__init__(*args, **kwargs)
        self.scatter.fragmentAtlas = _UniformSymbolAtlas(self.scatter.fragmentAtlas)
        if broadcast_uniform_symbols:
            self.scatter._style = _broadcast_uniform_styles(self.scatter)
            self.setData(*args, **kwargs)
        self._rasterizer = _CurveRasterizer(self.curve)
        self._rasterizer.rendering_changed.connect(self.rendering_changed)

    @property
    def render_pending(self):
        return self._rasterizer.render_pending

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        if getattr(self, '_rasterizer', None) is not None and self._rasterizer._screen_enabled:
            # The hidden native curve remains the scientific bounds authority.
            bounds = self.curve.dataBounds(ax, frac, orthoRange)
            if self.scatter.isVisible():
                other = self.scatter.dataBounds(ax, frac, orthoRange)
                bounds = tuple(min((v for v in pair if v is not None), default=None)
                               for pair in zip(bounds, other))
            return bounds
        return super().dataBounds(ax, frac, orthoRange)

    def pixelPadding(self):
        if getattr(self, '_rasterizer', None) is not None and self._rasterizer._screen_enabled:
            return max(self.curve.pixelPadding(), self.scatter.pixelPadding() if self.scatter.isVisible() else 0)
        return super().pixelPadding()

    def viewRangeChanged(self, vb=None, ranges=None, changed=None):
        previous = self._datasetDisplay
        if changed is None or changed[0]:
            self.setProperty('xViewRangeWasChanged', True)
        if changed is None or changed[1]:
            self.setProperty('yViewRangeWasChanged', True)
        current = self._getDisplayDataset()
        if (previous is not None and current is not None
                and previous.x is current.x and previous.y is current.y
                and previous.connect is current.connect):
            return  # pyqtgraph's dynamic-range guard did not change any data.
        self.updateItems(styleUpdate=False)


@contextmanager
def complete_curve_painting(widget):
    """Capture QWidget PNGs from current data even during a pending screen job."""
    plots = ([widget] if isinstance(widget, pg.PlotWidget) else []) + widget.findChildren(pg.PlotWidget)
    previous = []
    try:
        for plot in plots:
            for item in plot.listDataItems():
                curve = getattr(item, 'curve', None)
                if curve is None:
                    continue
                renderer = getattr(item, '_rasterizer', None)
                previous.append((curve, curve._exportOpts, curve.isVisible(), renderer))
                curve.setExportMode(True, {'antialias': curve.opts['antialias']})
                if renderer is not None and renderer._screen_enabled:
                    renderer.image_item.hide()
                    curve.show()
        yield
    finally:
        for curve, state, visible, renderer in previous:
            curve.setExportMode(isinstance(state, dict), state if isinstance(state, dict) else None)
            curve.setVisible(visible)
            if renderer is not None and renderer._screen_enabled and renderer._cached is not None:
                renderer.image_item.show()

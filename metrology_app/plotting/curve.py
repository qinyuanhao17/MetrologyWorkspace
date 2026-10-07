"""Full-resolution dense dashed curves, rasterized off the GUI thread.

Only detached QPainterPath/QPen values are sent to the worker. Qt widgets,
scene items, source arrays, axis labels and export painting stay with Qt's owner.
"""
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import multiprocessing
from weakref import finalize

import pyqtgraph as pg
from PyQt6.QtCore import QByteArray, QDataStream, QEvent, QIODevice, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsPixmapItem


_RENDERER = None


def _cancel_pending(holder):
    if holder[0] is not None:
        holder[0].cancel()


def _render_path(payload, width, height, antialias):
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
        painter.drawPath(path)
    finally:
        painter.end()
    return bytes(image.constBits().asstring(image.sizeInBytes()))


class _CurveRasterizer(QObject):
    rendering_changed = pyqtSignal()
    def __init__(self, curve):
        super().__init__(curve)
        self.curve = curve
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
        self._revision += 1
        self._cached = None
        self._latest = None
        self.image_item.hide()
        pen = self.opts['pen']
        self._needs_render = bool(self.xData is not None and len(self.xData) >= 2000
                                  and pen is not None and pen.isCosmetic()
                                  and pen.style() not in (Qt.PenStyle.SolidLine, Qt.PenStyle.NoPen))
        self._prepare.start(0)

    @property
    def render_pending(self):
        return (self._needs_render or self._future is not None or self._latest is not None
                and (self._cached is None or self._latest[0] != self._cached[0]))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Show):
            self._request()
        return False

    def _request(self):
        pen = self.opts['pen']
        # File/PNG/vector export uses the original complete painting directly.
        # Unsupported styles also retain pyqtgraph's full implementation.
        eligible = not (self._failed or isinstance(self._exportOpts, dict)
                or self.xData is None or len(self.xData) < 2000
                or pen is None or not pen.isCosmetic() or pen.style() in (Qt.PenStyle.SolidLine, Qt.PenStyle.NoPen)
                or self.opts['fillLevel'] is not None or self.opts['shadowPen'] is not None
                or self.opts['compositionMode'] is not None or self.opts['segmentedLineMode'] == 'on'
                or getattr(self.curve, 'clickable', False))
        self._screen_enabled = eligible
        if not eligible:
            self._needs_render = False
            self.image_item.hide()
            self.curve.setVisible(self.xData is not None and
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
            self.curve.show()
            return
        matrix = (transform.m11(), transform.m12(), transform.m21(), transform.m22(),
                  transform.dx(), transform.dy())
        # Moving the enclosing scroll area changes only the backing-store
        # origin. Reuse the image unless its local pixel geometry changed.
        local_matrix = (*matrix[:4], transform.dx() - rect.x(), transform.dy() - rect.y())
        key = (self._revision, QPen(pen), bool(self.opts['antialias']),
               local_matrix, rect.width(), rect.height())
        if self._cached is None or self._cached[0] != key:
            if self._latest is None or self._latest[0] != key:
                path = QPainterPath(self.curve.getPath())
                self._latest = (key, QTransform(transform), rect, path, QPen(pen), bool(self.opts['antialias']))
            self._start()
        self._needs_render = False
        self.curve.hide()
        if self._cached is not None:
            self.image_item.show()

    def _request_later(self, *_args):
        self._prepare.start(0)

    def _set_export_mode(self, export, opts=None):
        # Scene exporters do not deliver a QWidget paint event. Expose the
        # original full-data curve before their scene traversal, not the cache.
        self._native_export_mode(export, opts)
        if export:
            self.image_item.hide()
            if self._screen_enabled:
                self.curve.show()
        else:
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
        stream << path << pen << local
        global _RENDERER
        if _RENDERER is None:
            # QPainter's long raster call retains the Python GIL in this Qt
            # runtime. A single persistent spawned process isolates that cost.
            _RENDERER = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
        try:
            self._future = _RENDERER.submit(_render_path, bytes(payload), rect.width(), rect.height(), antialias)
        except Exception:
            self._failed = True
            self._latest = None
            self._needs_render = False
            self._screen_enabled = False
            self.curve.show()
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
            self.curve.show()
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


class ResponsivePlotDataItem(pg.PlotDataItem):
    """Keep unchanged scatter/curve data when only the viewport changed."""
    rendering_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

"""Non-interactive pyqtgraph wafer array using the existing prepared surfaces.

No interpolation, sampling, colour limits or source records are changed here.
Qt draws the static annotations in batches; ImageItem owns the colour fields.
The Matplotlib renderer remains the independent vector/raster export backend.
"""
from functools import lru_cache
from copy import copy
from hashlib import sha256
from math import floor

import numpy as np
import contourpy
import pyqtgraph as pg
from matplotlib.colors import Normalize
from matplotlib.path import Path
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from matplotlib.ticker import MaxNLocator, ScalarFormatter
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTransform
from PyQt6.QtWidgets import QGraphicsView, QToolTip

from .plot import ValueLabels, contour_colour, display_colormap
from .plotting.identity_labels import measurement_caption

PAGE_ZOOM_PERCENTAGES = (1, 2, 5, 10, 15, 25, 50, 75, 100, 125, 150, 175, 200, 250, 300)


class StaticMapView(pg.GraphicsView):
    """A pyqtgraph scene with ordinary page scrollbars, never plot navigation."""
    def __init__(self):
        super().__init__(useOpenGL=False, background="white")
        self.setCentralItem(None)
        self.enableMouse(False)
        self.autoPixelRange = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def resizeEvent(self, event):
        # The page owns Fit-width; GraphicsView's default pixel-range reset
        # would replace the explicit scene transform and lose the scroll row.
        QGraphicsView.resizeEvent(self, event)

    def scale(self, sx, sy):
        # pyqtgraph's scale() changes its coordinate range; this static page
        # needs QGraphicsView's display transform, with ordinary scrollbars.
        QGraphicsView.scale(self, sx, sy)
        self.sigDeviceTransformChanged.emit(self)

    def zoom_page(self, event, control):
        """Scale the whole grid around the pointer, retaining every plot's data limits."""
        delta = event.angleDelta().y() or event.angleDelta().x() or event.pixelDelta().y()
        if not delta:
            return
        current = self.transform().m11() * 100
        if delta > 0:
            target = next((value for value in PAGE_ZOOM_PERCENTAGES if value > current + .01), PAGE_ZOOM_PERCENTAGES[-1])
        else:
            target = next((value for value in reversed(PAGE_ZOOM_PERCENTAGES) if value < current - .01), PAGE_ZOOM_PERCENTAGES[0])
        if abs(target - current) < .01:
            return
        cursor = event.position().toPoint()
        before = self.mapToScene(cursor)
        control.setCurrentText(f"{target}%")  # The page applies its transform, not new scientific limits.
        after = self.mapToScene(cursor)
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center + before - after)


def colour_limits(scene):
    """Use WaferPlot's measured/manual limits, including constant-value padding."""
    values, options = scene["layer"].value.to_numpy(float), scene["options"]
    manual = options.limits or (None, None)
    low = float(values.min()) if manual[0] is None else float(manual[0])
    high = float(values.max()) if manual[1] is None else float(manual[1])
    if options.difference and manual == (None, None):
        high = max(abs(low), abs(high), 1e-9)
        low = -high
    if high <= low:
        margin = max(abs(low) * .01, .01)
        low, high = low - margin, high + margin
    if not np.isfinite([low, high]).all():
        raise ValueError("色阶上下限必须为有限数值。")
    return low, high


def qt_path(vertices, codes):
    """Translate Matplotlib/ContourPy paths without resampling the geometry."""
    result = QPainterPath()
    for points, code in Path(vertices, codes).iter_segments(curves=True, simplify=False):
        if code == Path.MOVETO:
            result.moveTo(*points)
        elif code == Path.LINETO:
            result.lineTo(*points)
        elif code == Path.CURVE3:
            result.quadTo(*points)
        elif code == Path.CURVE4:
            result.cubicTo(*points)
        elif code == Path.CLOSEPOLY:
            result.closeSubpath()
    return result


@lru_cache(maxsize=2048)
def text_path(text, pixels, bold):
    """Cache font outlines, avoiding repeated platform text shaping per repaint."""
    glyph = TextPath((0, 0), text, size=pixels,
                     prop=FontProperties(weight="bold" if bold else "normal"))
    return QTransform(1, 0, 0, -1, 0, 0).map(qt_path(glyph.vertices, glyph.codes))


class _LabelBoxIndex:
    """Spatial candidates for the original ordered, strict overlap predicate."""
    def __init__(self, cell_size=24):
        self.cell_size = cell_size
        self.cells = {}

    def _keys(self, box):
        size = self.cell_size
        for x in range(floor(box[0] / size), floor(box[2] / size) + 1):
            for y in range(floor(box[1] / size), floor(box[3] / size) + 1):
                yield x, y

    def add_if_clear(self, box):
        keys = tuple(self._keys(box))
        for key in keys:
            for other in self.cells.get(key, ()):
                if box[0] < other[2] and box[2] > other[0] and box[1] < other[3] and box[3] > other[1]:
                    return False
        for key in keys:
            self.cells.setdefault(key, []).append(box)
        return True


class WaferImage(pg.ImageItem):
    """Smooth ImageItem clipped to the exact circular wafer, not its square."""
    def paint(self, painter, *args):
        painter.save()
        clip = QPainterPath()
        clip.addEllipse(self.boundingRect())
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        super().paint(painter, *args)
        painter.restore()


class WaferPanel(pg.GraphicsObject):
    _glyph_paths = {}

    def __init__(self, scene, settings, parent, *, template=None):
        super().__init__(parent)
        self.source = scene
        self.settings = settings
        self.box = QRectF()
        self.axis_rect = QRectF()
        self.bar_rect = QRectF()
        self.font_size = 10
        self.identity_labels = {"pad": True, "lot": True}
        self.image = None
        self.contours = None
        self.label_path = QPainterPath()
        self.drawn_indices = []
        self._pixel_positions = np.empty((0, 2))
        self._geometry_key = None
        self._label_key = None
        self.status_callback = None
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)
        if not scene.get("skip") and not scene["error"]:
            self.positions = scene["surface"][0]
            self.low, self.high = colour_limits(scene)
            self.values = scene["layer"].value.to_numpy(float)
            if (template is not None and template.image is not None
                    and tuple(self.values) == template.value_labels.values
                    and scene['options'].point_decimals == template.value_labels.decimals):
                # Decimal formatting is immutable here. A separate Artist keeps
                # any later precision change from mutating the old published page.
                self.value_labels = copy(template.value_labels)
            else:
                self.value_labels = ValueLabels(self.positions, self.values, 5.5,
                                                scene["options"].point_decimals)
            self.image = WaferImage(axisOrder="row-major")
            self.image.setParentItem(self)
            self.image.setZValue(-1)
            self.image.setFlag(self.GraphicsItemFlag.ItemStacksBehindParent, True)
            self.image.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.image.setAcceptHoverEvents(False)
            self.update_palette()

    def boundingRect(self):
        return self.box.adjusted(-75, -85, 85, 65)

    def update_palette(self):
        options = self.source["options"]
        palette = "coolwarm" if options.difference else options.cmap
        self.cmap = display_colormap(palette, *(options.cmap_range or (None, None)))
        data = self.source["surface"][3].data
        self.rgba = self.cmap(Normalize(self.low, self.high)(np.ma.masked_invalid(data)), bytes=True)
        # Qt's top row is Y-max; the numerical grid and export stay origin=lower.
        self.image.setImage(np.ascontiguousarray(self.rgba[::-1]), autoLevels=False)
        self.image.setOpacity(float(options.opacity))
        colours = self.cmap(np.linspace(0, 1, 256))
        self.bar_colours = []
        for value, rgba in zip(np.linspace(0, 1, 256), colours):
            colour = QColor.fromRgbF(*rgba)
            colour.setAlphaF(options.opacity)
            self.bar_colours.append((float(value), colour))
        if not self.bar_rect.isEmpty():
            self._prepare_bar()
        self.contours = None  # Re-colour iso-lines, retaining the original surface.
        self.update()

    def set_geometry(self, box, font_size, *, template=None):
        options = self.source.get("options")
        positions_key = (sha256(np.ascontiguousarray(self.positions).tobytes()).digest()
                         if self.image is not None else None)
        key = (tuple(box.getRect()), font_size, positions_key,
               (options.radius, options.center_x, options.center_y, options.show_colorbar)
               if self.image is not None else None)
        if key == self._geometry_key:
            if self.image is not None:
                self._prepare_labels()
            self.update()
            return
        self.prepareGeometryChange()
        self.box, self.font_size = QRectF(box), font_size
        main = QRectF(box)
        self.bar_rect = QRectF()
        if self.image is not None and options.show_colorbar:
            main.setWidth(box.width() * .91)
            height = box.height() * .86
            # Same fraction, pad, shrink and 20:1 colour-bar aspect as WaferPlot.
            width = min(box.width() * .045, height / 20)
            self.bar_rect = QRectF(box.right() - box.width()*.045,
                                  box.center().y() - height/2, width, height)
        side = min(main.width(), main.height())
        self.axis_rect = QRectF(main.center().x()-side/2, main.center().y()-side/2, side, side)
        if self.image is None:
            self.axis_rect = QRectF(box)
        if self.image is not None:
            self.image.setRect(self.axis_rect)
            self._geometry_key = key
            if template is not None and template._geometry_key == key:
                self._pixel_positions = template._pixel_positions
            else:
                transform = self.data_transform()
                self._pixel_positions = np.array(
                    [(mapped.x(), mapped.y()) for mapped in
                     (transform.map(QPointF(float(x), float(y))) for x, y in self.positions)],
                    dtype=float) if len(self.positions) else np.empty((0, 2))
            self._prepare_labels(template=template)
            self._prepare_bar()
        self._geometry_key = key
        self.update()

    def hover_text(self, point):
        """Nearest measured die and value under the cursor, or None."""
        if not len(self.positions) or not len(self._pixel_positions):
            return None
        delta = self._pixel_positions - np.array([point.x(), point.y()])
        distances = np.einsum("ij,ij->i", delta, delta)
        index = int(distances.argmin())
        if distances[index] > 12 * 12:
            return None
        row = self.source["layer"].iloc[index]
        die = str(row.get("die", "") or "").strip()
        label = str(self.source.get("label", self.source.get("wafer", ""))).replace("\n", " · ")
        text = [label]
        if die:
            text.append(f"Die {die}")
        text.append(f"{self.source['metric']} = {float(row['value']):.8g}")
        text.append(f"X = {float(row['x']):.6g}, Y = {float(row['y']):.6g}")
        return " · ".join(text)

    def hoverMoveEvent(self, event):
        text = self.hover_text(event.pos())
        if text:
            if self.status_callback is not None:
                self.status_callback(text)
            views = self.scene().views() if self.scene() is not None else []
            widget = views[0].viewport() if views else None
            position = event.screenPos()
            QToolTip.showText(position.toPoint() if hasattr(position, "toPoint") else position,
                              text, widget)
        else:
            QToolTip.hideText()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def data_transform(self):
        options, rect = self.source["options"], self.axis_rect
        scale = rect.width() / (options.radius * 2)
        return QTransform(scale, 0, 0, -scale,
                          rect.center().x() - options.center_x * scale,
                          rect.center().y() + options.center_y * scale)

    def _prepare_labels(self, *, template=None):
        labels = self.value_labels
        labels.set_decimals(self.source["options"].point_decimals)
        label_key = (self._geometry_key, tuple(labels.labels),
                     sha256(np.ascontiguousarray(self.values).tobytes()).digest())
        if label_key == self._label_key:
            return
        if template is not None and template._label_key == label_key:
            self.label_path = QPainterPath(template.label_path)
            self.drawn_indices = list(template.drawn_indices)
            self._label_key = label_key
            return
        size = max(4.5, self.font_size * .55)
        if len(self.values) > 100:
            size = max(4.5, size - 1)
        scale = size * 100/72
        gap = max(1.5, scale * .12)
        transform = self.data_transform()
        path, boxes, indices = QPainterPath(), _LabelBoxIndex(), []
        for index, (label, position) in enumerate(zip(labels.labels, self.positions)):
            point = transform.map(QPointF(*position))
            width = sum(labels._glyphs[c][1] for c in label) * scale
            # Mirror ValueLabels' baseline and overlap rule into Qt's Y-down space.
            baseline = point.y() + (labels._top + .75) * scale
            box = (point.x()-width/2-gap, baseline-labels._top*scale-gap,
                   point.x()+width/2+gap, baseline+gap)
            if not boxes.add_if_clear(box):
                continue
            indices.append(index)
            cursor = point.x() - width/2
            for character in label:
                glyph, advance = labels._glyphs[character]
                if character not in self._glyph_paths:
                    self._glyph_paths[character] = qt_path(glyph.vertices, glyph.codes)
                path.addPath(QTransform(scale, 0, 0, -scale, cursor, baseline).map(self._glyph_paths[character]))
                cursor += advance * scale
        self.label_path, self.drawn_indices = path, indices
        self._label_key = label_key

    def _prepare_contours(self):
        if self.contours is not None:
            return
        levels = MaxNLocator(nbins=9).tick_values(self.low, self.high)
        levels = levels[(levels >= self.low) & (levels <= self.high)]
        self.contours = []
        if len(levels) < 2:
            return
        _, gx, gy, surface, _ = self.source["surface"]
        generator = contourpy.contour_generator(x=gx, y=gy, z=surface,
            name="mpl2014", corner_mask=True, line_type="SeparateCode")
        for level in levels:
            vertices, codes = generator.lines(level)
            path = QPainterPath()
            for points, commands in zip(vertices, codes):
                path.addPath(qt_path(points, commands))
            self.contours.append((path, contour_colour(self.cmap, self.low, self.high, level)))

    @staticmethod
    def font(points, bold=False):
        # Scene units are 100 dpi, independent of the OS logical DPI.
        font = QFont("Segoe UI")
        font.setPointSizeF(points)
        font.setBold(bold)
        return font

    @staticmethod
    def text(painter, text, rect, alignment=Qt.AlignmentFlag.AlignCenter):
        if not str(text):
            return
        font = painter.font()
        if "\n" in str(text) or alignment & Qt.TextFlag.TextWordWrap:
            lines = []
            for paragraph in str(text).splitlines():
                line = ""
                for word in paragraph.split():
                    candidate = f"{line} {word}".strip()
                    width = text_path(candidate, font.pointSizeF()*100/72, font.bold()).boundingRect().width()
                    if line and width > rect.width():
                        lines.append(line)
                        line = word
                    else:
                        line = candidate
                lines.append(line)
            height = font.pointSizeF()*100/72*1.45
            for index, line in enumerate(lines):
                WaferPanel.text(painter, line, QRectF(rect.left(), rect.center().y()-height*len(lines)/2+index*height,
                                                     rect.width(), height), Qt.AlignmentFlag.AlignCenter)
            return
        path = text_path(str(text), font.pointSizeF()*100/72, font.bold())
        bounds = path.boundingRect()
        x = (rect.right()-bounds.right() if alignment & Qt.AlignmentFlag.AlignRight else
             rect.left()-bounds.left() if alignment & Qt.AlignmentFlag.AlignLeft else
             rect.center().x()-bounds.center().x())
        y = rect.center().y()-bounds.center().y()
        painter.save()
        painter.translate(x, y)
        painter.fillPath(path, painter.pen().color())
        painter.restore()

    def paint(self, painter, *args):
        if self.source.get("skip"):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        options = self.source.get("options")
        rect, base = self.axis_rect, self.font_size
        caption = measurement_caption(self.source["label"], self.identity_labels).replace("\n", " · ")
        painter.setPen(QColor("#17202a"))
        detail = max(6, base-1)
        line = detail * 1.45 * 100/72
        title_bottom = rect.top() - 5 * 100/72
        painter.setFont(self.font(base, True))
        heading = self.source["metric"] + ("  [A - B]" if options and options.difference else "")
        self.text(painter, heading, QRectF(rect.left()-35, title_bottom-3*line, rect.width()+70, line))
        painter.setFont(self.font(detail))
        self.text(painter, caption, QRectF(rect.left()-35, title_bottom-2*line, rect.width()+70, line))
        if self.source["error"]:
            painter.setPen(QColor("#985126"))
            self.text(painter, self.source["error"], self.box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
            painter.setPen(QPen(QColor("#303030"), .8*100/72))
            painter.drawRect(self.box)
            return
        stats = f"Min {self.values.min():.5g}   Max {self.values.max():.5g}   Mean {self.values.mean():.5g}"
        self.text(painter, stats, QRectF(rect.left()-35, title_bottom-line, rect.width()+70, line))
        painter.save()
        painter.setClipRect(rect)
        transform = self.data_transform()
        if options.contour:
            self._prepare_contours()
            painter.setOpacity(.9)
            for path, colour in self.contours:
                painter.setPen(QPen(QColor(colour), .5*100/72))
                painter.drawPath(transform.map(path))
            painter.setOpacity(1)
        if options.points:
            diameter = np.sqrt(13 if options.point_outline else 5) * 100/72
            painter.setPen(QPen(QColor("#f5f5f5"), .9*100/72) if options.point_outline else QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QColor("#101820"))
            for position in self.positions:
                painter.drawEllipse(transform.map(QPointF(*position)), diameter/2, diameter/2)
        if options.labels:
            painter.fillPath(self.label_path, QColor("#101820"))
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#343b45"), .8*100/72))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#303030"), .8*100/72))
        painter.drawRect(rect)
        self._paint_axes(painter)
        if options.show_colorbar:
            self._paint_bar(painter)

    def _ticks(self, center, name):
        radius = self.source["options"].radius
        normalized = "".join(c.lower() for c in name if c.isalnum())
        standard = next((r for r in (50, 100, 150) if np.isclose(radius, r)), None)
        names = ("".join(c.lower() for c in axis if c.isalnum())
                 for axis in (self.settings.x, self.settings.y))
        if standard and normalized.endswith("mm") and all(n.endswith("mm") for n in names):
            step = 25 if standard == 50 else 50
            return center + np.arange(-standard, standard+step/2, step)
        return MaxNLocator(nbins=5).tick_values(center-radius, center+radius)

    def _paint_axes(self, painter):
        options, rect = self.source["options"], self.axis_rect
        tick_font = self.font(max(5, self.font_size-2))
        painter.setFont(tick_font)
        transform, length = self.data_transform(), 3*100/72
        for value in self._ticks(options.center_x, self.settings.x):
            x = transform.map(QPointF(value, options.center_y)).x()
            if rect.left()-.01 <= x <= rect.right()+.01:
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.top()-length))
                painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom()+length))
                self.text(painter, f"{value:g}", QRectF(x-40, rect.bottom()+length, 80, 20))
        for value in self._ticks(options.center_y, self.settings.y):
            y = transform.map(QPointF(options.center_x, value)).y()
            if rect.top()-.01 <= y <= rect.bottom()+.01:
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.left()-length, y))
                painter.drawLine(QPointF(rect.right(), y), QPointF(rect.right()+length, y))
                self.text(painter, f"{value:g}", QRectF(rect.left()-56, y-10, 48, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        painter.setFont(self.font(max(6, self.font_size-1)))
        suffix = " (view)" if options.rotation or options.flip else ""
        self.text(painter, self.settings.x+suffix, QRectF(rect.left(), rect.bottom()+24, rect.width(), 22))
        painter.save()
        painter.translate(rect.left()-51, rect.center().y())
        painter.rotate(-90)
        self.text(painter, self.settings.y+suffix, QRectF(-rect.height()/2, -12, rect.height(), 24))
        painter.restore()

    def _prepare_bar(self):
        bar = self.bar_rect
        self.bar_gradient = QLinearGradient(bar.bottomLeft(), bar.topLeft())
        self.bar_gradient.setStops(self.bar_colours)
        # Matplotlib AutoLocator estimates two tick-font heights per Y interval.
        bins = int(np.clip(np.floor(bar.height()*.72/(max(5, self.font_size-2)*2)), 1, 9))
        levels = MaxNLocator(nbins=bins, steps=[1, 2, 2.5, 5, 10]).tick_values(self.low, self.high)
        formatter = ScalarFormatter()
        formatter.create_dummy_axis()
        formatter.axis.set_view_interval(self.low, self.high)
        formatter.set_locs(levels)
        self.bar_ticks = [(value, formatter(value)) for value in levels if self.low <= value <= self.high]
        self.bar_offset = formatter.get_offset()

    def _paint_bar(self, painter):
        bar = self.bar_rect
        painter.fillRect(bar, self.bar_gradient)
        painter.setPen(QPen(QColor("#303030"), .6*100/72))
        painter.drawRect(bar)
        painter.setFont(self.font(max(5, self.font_size-2)))
        for value, label in self.bar_ticks:
            y = bar.bottom() - (value-self.low)/(self.high-self.low)*bar.height()
            painter.drawLine(QPointF(bar.right(), y), QPointF(bar.right()+4, y))
            self.text(painter, label, QRectF(bar.right()+6, y-10, 75, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text(painter, self.source["size_note"], QRectF(bar.center().x()-50, bar.top()-24, 100, 20))
        offset = self.bar_offset
        if offset:
            self.text(painter, offset, QRectF(bar.left()-10, bar.top()-43, 95, 20))


class _PendingWaferLayer(pg.GraphicsObject):
    """Owned unpublished children, detached from the displayed scene."""
    def boundingRect(self):
        return QRectF()

    def paint(self, painter, *args):
        pass


class WaferMapGrid(pg.GraphicsObject):
    """Fixed scientific coordinate frames; the containing view only scrolls."""
    rendered = pyqtSignal(object)
    render_failed = pyqtSignal(str)
    render_progress = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.panels = []
        self.rect = QRectF()
        self.status_callback = None
        self._pending = None
        self._generation = 0
        self.render_stats = {name: 0 for name in ("requests", "published", "panels_created",
                                                "templates_reused", "images_reused", "cancelled", "failed")}
        self._render_timer = QTimer(self, interval=1, singleShot=True)
        self._render_timer.timeout.connect(self._render_batch)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, *args):
        pass

    def clear(self):
        self.cancel_render()
        for panel in self.panels:
            panel.setParentItem(None)
            if panel.scene() is not None:
                panel.scene().removeItem(panel)
        self.panels = []

    @property
    def render_pending(self):
        return self._pending is not None

    def cancel_render(self):
        self._generation += 1
        self._render_timer.stop()
        state, self._pending = self._pending, None
        if state is not None:
            self.render_stats["cancelled"] += 1
            layer = state["layer"]
            layer.setParentItem(None)
            if layer.scene() is not None:
                layer.scene().removeItem(layer)
            layer.deleteLater()

    @staticmethod
    def _layout_boxes(result, rect, font_size):
        rows, columns = result["shape"]
        grow = max(0, font_size-10)
        left, right, top, bottom = 58+9*grow, 78+6*grow, 70+9*grow, 42+9*grow
        wspace, hspace = .42+.02*grow, .28+.055*grow
        width = (rect.width()-left-right)/(columns+(columns-1)*wspace)
        height = (rect.height()-top-bottom)/(rows+(rows-1)*hspace)
        return [QRectF(left+column*width*(1+wspace), top+row*height*(1+hspace), width, height)
                for row, column in (divmod(index, columns) for index in range(len(result["scenes"])))]

    def set_result(self, result, font_size, identity_labels, *, deferred=False, valid=None):
        self.render_stats["requests"] += 1
        self.cancel_render()
        rows, columns = result["shape"]
        rect = QRectF(0, 0, columns*460, rows*420+30)
        layer = _PendingWaferLayer()
        layer.setParent(self)  # QObject ownership without scene invalidation per batch.
        layer.hide()
        templates = {(id(panel.source.get("surface")), id(panel.source.get("layer"))): panel
                     for panel in self.panels if panel.image is not None}
        self._pending = {"generation": self._generation, "result": result, "font": font_size,
                         "identity": dict(identity_labels), "rect": rect,
                         "boxes": self._layout_boxes(result, rect, font_size), "panels": [],
                         "position": 0, "layer": layer, "templates": templates, "valid": valid}
        if not self._is_current(self._pending):
            return
        if deferred and len(result["scenes"]) > 2:
            self._render_timer.start()
        else:
            self._render_batch(len(result["scenes"]), raise_errors=True)

    def _is_current(self, state):
        if (sip.isdeleted(self) or state is not self._pending
                or state["generation"] != self._generation):
            return False
        if state["valid"] is not None and not state["valid"]():
            if not sip.isdeleted(self) and state is self._pending:
                self.cancel_render()
            return False
        return True

    def _render_batch(self, count=2, *, raise_errors=False):
        state = self._pending
        if state is None or not self._is_current(state):
            return
        try:
            for _ in range(count):
                index = state["position"]
                if index == len(state["result"]["scenes"]):
                    break
                scene = state["result"]["scenes"][index]
                template = state["templates"].get((id(scene.get("surface")), id(scene.get("layer"))))
                panel = WaferPanel(scene, state["result"]["settings"], state["layer"], template=template)
                if not self._is_current(state):
                    return
                self.render_stats["panels_created"] += 1
                panel.status_callback = self.status_callback
                panel.identity_labels = state["identity"]
                panel.set_geometry(state["boxes"][index], state["font"], template=template)
                if not self._is_current(state):
                    return
                if (template is not None and panel._geometry_key == template._geometry_key
                        and panel._label_key == template._label_key):
                    self.render_stats["templates_reused"] += 1
                if panel.image is not None:
                    if not self._is_current(state):
                        return
                    # Contours retain the original lazy visible-panel path.
                    # Preparing all offscreen contours here adds work the old
                    # renderer never needed before completing the same viewport.
                    # ImageItem normally materialises its QImage at first paint.
                    # Keep that work in this GUI batch rather than final publication.
                    panel.image.render()
                state["panels"].append(panel)
                state["position"] += 1
                if not self._is_current(state):
                    return
            self.render_progress.emit(state["position"], len(state["result"]["scenes"]))
            if not self._is_current(state):
                return
            if state["position"] == len(state["result"]["scenes"]):
                self._publish(state)
            else:
                self._render_timer.start()
        except Exception as error:
            if self._is_current(state):
                self.render_stats["failed"] += 1
                self.cancel_render()
                self.render_failed.emit(str(error))
                if raise_errors:
                    raise

    def _publish(self, state):
        if not self._is_current(state):
            return
        old = self.panels
        self.prepareGeometryChange()
        self.rect = state["rect"]
        for panel in state["panels"]:
            template = state['templates'].get((id(panel.source.get('surface')), id(panel.source.get('layer'))))
            if template is not None and template.image is not None and panel.image is not None:
                # Only move a published ImageItem after the entire new page is
                # ready. Its old pixels remain untouched throughout preparation.
                image = template.image
                prepared = panel.image
                image.setParentItem(panel)
                image.setImage(prepared.image, autoLevels=False)
                image.setOpacity(prepared.opacity())
                image.setRect(panel.axis_rect)
                image.render()
                prepared.setParentItem(None)
                if prepared.scene() is not None:
                    prepared.scene().removeItem(prepared)
                panel.image = image
                template.image = None
                self.render_stats['images_reused'] += 1
            panel.setParentItem(self)
        self.panels = state["panels"]
        self._pending = None
        self.render_stats["published"] += 1
        for panel in old:
            panel.setParentItem(None)
            if panel.scene() is not None:
                panel.scene().removeItem(panel)
        layer = state["layer"]
        layer.setParentItem(None)
        if layer.scene() is not None:
            layer.scene().removeItem(layer)
        layer.deleteLater()
        self.update()
        self.rendered.emit(state["result"])

    def relayout(self, result, font_size, identity_labels):
        boxes = self._layout_boxes(result, self.rect, font_size)
        for index, panel in enumerate(self.panels):
            panel.identity_labels = identity_labels
            panel.set_geometry(boxes[index], font_size)

    @property
    def valid_count(self):
        return sum(panel.image is not None for panel in self.panels)

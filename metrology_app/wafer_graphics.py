"""Non-interactive pyqtgraph wafer array using the existing prepared surfaces.

No interpolation, sampling, colour limits or source records are changed here.
Qt draws the static annotations in batches; ImageItem owns the colour fields.
The Matplotlib renderer remains the independent vector/raster export backend.
"""
from functools import lru_cache

import numpy as np
import contourpy
import pyqtgraph as pg
from matplotlib.colors import Normalize
from matplotlib.path import Path
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from matplotlib.ticker import MaxNLocator, ScalarFormatter
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTransform
from PyQt6.QtWidgets import QGraphicsView

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

    def __init__(self, scene, settings, parent):
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
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        if not scene.get("skip") and not scene["error"]:
            self.positions = scene["surface"][0]
            self.low, self.high = colour_limits(scene)
            self.values = scene["layer"].value.to_numpy(float)
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

    def set_geometry(self, box, font_size):
        self.prepareGeometryChange()
        self.box, self.font_size = QRectF(box), font_size
        options = self.source.get("options")
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
            self._prepare_labels()
            self._prepare_bar()
        self.update()

    def data_transform(self):
        options, rect = self.source["options"], self.axis_rect
        scale = rect.width() / (options.radius * 2)
        return QTransform(scale, 0, 0, -scale,
                          rect.center().x() - options.center_x * scale,
                          rect.center().y() + options.center_y * scale)

    def _prepare_labels(self):
        labels = self.value_labels
        labels.set_decimals(self.source["options"].point_decimals)
        size = max(4.5, self.font_size * .55)
        if len(self.values) > 100:
            size = max(4.5, size - 1)
        scale = size * 100/72
        gap = max(1.5, scale * .12)
        transform = self.data_transform()
        path, boxes, indices = QPainterPath(), [], []
        for index, (label, position) in enumerate(zip(labels.labels, self.positions)):
            point = transform.map(QPointF(*position))
            width = sum(labels._glyphs[c][1] for c in label) * scale
            # Mirror ValueLabels' baseline and overlap rule into Qt's Y-down space.
            baseline = point.y() + (labels._top + .75) * scale
            box = (point.x()-width/2-gap, baseline-labels._top*scale-gap,
                   point.x()+width/2+gap, baseline+gap)
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in boxes):
                continue
            boxes.append(box)
            indices.append(index)
            cursor = point.x() - width/2
            for character in label:
                glyph, advance = labels._glyphs[character]
                if character not in self._glyph_paths:
                    self._glyph_paths[character] = qt_path(glyph.vertices, glyph.codes)
                path.addPath(QTransform(scale, 0, 0, -scale, cursor, baseline).map(self._glyph_paths[character]))
                cursor += advance * scale
        self.label_path, self.drawn_indices = path, indices

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


class WaferMapGrid(pg.GraphicsObject):
    """Fixed scientific coordinate frames; the containing view only scrolls."""
    def __init__(self):
        super().__init__()
        self.panels = []
        self.rect = QRectF()
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, *args):
        pass

    def clear(self):
        for panel in self.panels:
            panel.setParentItem(None)
            if panel.scene() is not None:
                panel.scene().removeItem(panel)
        self.panels = []

    def set_result(self, result, font_size, identity_labels):
        self.clear()
        self.prepareGeometryChange()
        rows, columns = result["shape"]
        self.rect = QRectF(0, 0, columns*460, rows*420+30)
        self.panels = [WaferPanel(scene, result["settings"], self) for scene in result["scenes"]]
        self.relayout(result, font_size, identity_labels)

    def relayout(self, result, font_size, identity_labels):
        rows, columns = result["shape"]
        grow = max(0, font_size-10)
        left, right, top, bottom = 58+9*grow, 78+6*grow, 70+9*grow, 42+9*grow
        wspace, hspace = .42+.02*grow, .28+.055*grow
        width = (self.rect.width()-left-right)/(columns+(columns-1)*wspace)
        height = (self.rect.height()-top-bottom)/(rows+(rows-1)*hspace)
        for index, panel in enumerate(self.panels):
            row, column = divmod(index, columns)
            panel.identity_labels = identity_labels
            panel.set_geometry(QRectF(left+column*width*(1+wspace), top+row*height*(1+hspace), width, height), font_size)

    @property
    def valid_count(self):
        return sum(panel.image is not None for panel in self.panels)

"""The same nested Mark2 footer for interactive and Matplotlib plots."""
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetricsF

from .mark2 import hierarchy


def visible_labels(spans, limits, width, measure):
    low, high = limits
    scale = width / max(high - low, 1e-12)
    result, right = [], {}
    for span in sorted(spans, key=lambda s: (s["level"], s["start"])):
        if span["end"] <= low or span["start"] >= high or not span["text"]:
            continue
        left, end = max(low, span["start"]), min(high, span["end"])
        center = (left + end) / 2
        # The innermost strip uses vertical, sparse ticks like the reference image.
        needed = 18 if span["level"] == 0 else measure(span["text"]) + 10
        x = (center - low) * scale
        if ((span["level"] == 0 or (end - left) * scale >= needed)
                and x - needed / 2 >= right.get(span["level"], -1e9)):
            result.append((span, center))
            right[span["level"]] = x + needed / 2 + 5
    return result


class HierarchyAxis(pg.AxisItem):
    def __init__(self, columns, values, *, origin=1, font=None):
        super().__init__(orientation="bottom")
        self.columns = tuple(columns)
        self.hierarchy_spans = hierarchy(columns, values, origin=origin)
        self.hierarchy_font = QFont(font) if font is not None else QFont()
        self.setStyle(showValues=False, tickLength=0)
        fm = QFontMetricsF(self.hierarchy_font)
        inner = max((fm.horizontalAdvance(s["text"]) for s in self.hierarchy_spans if s["level"] == 0), default=20)
        self.inner_height = min(110, max(38, inner + 10))
        self.row_height = fm.height() + 10
        self.setHeight(self.inner_height + max(0, len(columns) - 1) * self.row_height + 5)
        self.setToolTip("Mark2: outer → inner: " + " → ".join(columns))

    def drawPicture(self, painter, axisSpec, tickSpecs, textSpecs):
        super().drawPicture(painter, axisSpec, tickSpecs, [])
        _pen, a, b = axisSpec
        left, right = sorted((a.x(), b.x()))
        low, high = self.range
        scale = (right - left) / max(high - low, 1e-12)
        x = lambda value: left + (value - low) * scale
        y = a.y() + 3
        painter.save()
        painter.setFont(self.hierarchy_font)
        painter.setPen(pg.mkPen("#b8b8b8", width=1))
        for level in range(1, len(self.columns)):
            edges = sorted({v for s in self.hierarchy_spans if s["level"] == level for v in (s["start"], s["end"])})
            previous = -1e9
            bottom = y + self.inner_height + level * self.row_height
            for edge in edges:
                if low <= edge <= high and x(edge) - previous >= 4:
                    painter.drawLine(pg.Point(x(edge), y), pg.Point(x(edge), bottom))
                    previous = x(edge)
        painter.setPen(self.textPen())
        fm = QFontMetricsF(self.hierarchy_font)
        for span, center in visible_labels(self.hierarchy_spans, self.range, right - left, fm.horizontalAdvance):
            if span["level"] == 0:
                painter.save()
                painter.translate(x(center), y + 4)
                painter.rotate(90)
                painter.drawText(QRectF(0, -fm.height() / 2, self.inner_height - 6, fm.height()),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, span["text"])
                painter.restore()
            else:
                top = y + self.inner_height + (span["level"] - 1) * self.row_height
                painter.drawText(QRectF(x(center) - 1000, top, 2000, self.row_height),
                                 Qt.AlignmentFlag.AlignCenter, span["text"])
        painter.restore()


def set_hierarchy_axis(plot, columns, values, *, origin=1):
    old = plot.getAxis("bottom")
    signature = (tuple(columns), tuple(tuple(v) for v in values), origin, plot.font().key())
    if isinstance(old, HierarchyAxis) and getattr(plot, "_mark2_axis_signature", None) == signature:
        return old
    axis = HierarchyAxis(columns, values, origin=origin, font=plot.font())
    axis.setPen(old.pen())
    axis.setTextPen(old.textPen())
    plot.setAxisItems({"bottom": axis})
    plot.setLabel("bottom", "")
    plot._mark2_axis_signature = signature
    plot._span_axis_signature = None
    return axis


def draw_hierarchy(axis, columns, values, *, origin=1):
    """Draw ordinal-aligned spans without moving observations to make text fit."""
    from matplotlib.transforms import blended_transform_factory
    from matplotlib.font_manager import FontProperties
    from matplotlib.backends.backend_agg import RendererAgg
    spans = hierarchy(columns, values, origin=origin)
    axis.set_xticks([])
    axis.set_xlabel("")
    renderer = RendererAgg(1, 1, axis.figure.dpi)
    font = FontProperties(size=10)
    measure = lambda value: renderer.get_text_width_height_descent(value, font, False)[0]
    transform = blended_transform_factory(axis.transData, axis.transAxes)
    # Footer positions are in pixels, converted to fractions of the actual plot.
    height = max(1, axis.bbox.height)
    inner = min(110, max(38, max((measure(s["text"]) for s in spans if s["level"] == 0), default=20) + 10))
    row_height = 25 * axis.figure.dpi / 96
    for level in range(1, len(columns)):
        for edge in sorted({v for s in spans if s["level"] == level for v in (s["start"], s["end"])}):
            axis.plot([edge, edge], [-.01, -(inner + level * row_height) / height],
                      color="#b8b8b8", linewidth=.6, transform=transform, clip_on=False)
    for span, center in visible_labels(spans, axis.get_xlim(), axis.bbox.width, measure):
        level = span["level"]
        axis.text(center, -5 / height if level == 0 else -(inner + (level - .5) * row_height) / height,
                  span["text"], rotation=270 if level == 0 else 0,
                  ha="center", va="top" if level == 0 else "center", fontsize=10,
                  transform=transform, clip_on=False)

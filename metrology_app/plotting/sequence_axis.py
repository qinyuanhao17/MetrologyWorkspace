"""Responsive identity labels; fitting never changes plotted observations."""
from bisect import bisect_left, bisect_right
from math import ceil

import numpy as np
import pyqtgraph as pg
from PyQt6.QtGui import QFontMetricsF
from PyQt6.QtWidgets import QApplication


def elide_label(text, available, measure):
    """Middle-elide using the renderer's real font metrics (Qt or export)."""
    if measure(text) <= available:
        return text
    low, high = 0, len(text)
    while low < high:
        count = (low + high + 1) // 2
        left, right = (count + 1) // 2, count // 2
        candidate = text[:left] + "…" + (text[-right:] if right else "")
        if measure(candidate) <= available:
            low = count
        else:
            high = count - 1
    left, right = (low + 1) // 2, low // 2
    return text[:left] + "…" + (text[-right:] if right else "")


def span_label_ticks(spans, limits, width, measure, *, optional_fields=True):
    """Fit labels over visible, ordered, non-overlapping half-edge spans.

    Wafer ID is primary; optional Lot/PAD lines disappear before it is elided.
    Whole group names are thinned when their spans are too narrow to read.
    """
    # Repeated wafer runs reuse the same IDs, metadata and ellipsis. Cache font
    # widths only during this call so resizing/font changes cannot go stale.
    widths = {}
    renderer_measure = measure

    def measure(text):
        if text not in widths:
            widths[text] = renderer_measure(text)
        return widths[text]

    low, high = limits
    scale = width / max(1e-9, high - low)
    ticks, edge = [], -float("inf")
    for start, end, label in spans:
        start, end = max(low, start), min(high, end)
        if end <= start or not label:
            continue
        available = ((end - start) * scale - 8 if optional_fields
                     else max(40, min(width / 2 - 8, (end - start) * scale - 8)))
        values = label.splitlines()
        primary_space = (max(available, min(measure(values[0]), width / 3))
                         if optional_fields else available)
        if primary_space < measure("…"):
            continue
        # At wafer-dense zoom levels thin whole ID labels; never reduce every
        # wafer to the same unreadable ellipsis. Metadata still has to fit its
        # own segment, even when a primary label is thinned this way.
        lines = [elide_label(values[0], primary_space, measure)]
        lines.extend(value for value in values[1:] if measure(value) <= available)
        if not optional_fields:
            lines = [elide_label(value, available, measure) for value in values]
        text = "\n".join(lines)
        position = (start + end) / 2
        pixel = (position - low) * scale
        half = max(map(measure, lines)) / 2
        if pixel - half >= max(0, edge + 8) and pixel + half <= width:
            ticks.append((position, text))
            edge = pixel + half
    return ticks


def fit_tick_labels(ticks, limits, width, measure):
    """Thin visible real Die Seq labels using rendered widths, not digit counts."""
    low, high = limits
    scale = width / max(1e-9, high - low)
    step = max(1, ceil(len(ticks) / max(1, width / 24)))
    kept, edge = [], -float("inf")
    for position, label in ticks[::step]:
        pixel = (position - low) * scale
        half = measure(label) / 2
        if pixel - half >= max(0, edge + 8) and pixel + half <= width:
            kept.append((position, label))
            edge = pixel + half
    return kept


class WaferSpacing:
    """Local caption spacing on an ordinal axis, never measurement X values.

    A short wafer receives its own label allowance, not a scale factor for all
    other wafers. Normalize the display coordinates to the same full extent so
    Auto Range, saved views and linked comparison axes retain their bounds.
    """
    def __init__(self, spans, limits, measure):
        low, high = limits
        spans = [(max(low, start), min(high, end), label)
                 for start, end, label in spans if end > start and end > low and start < high]
        self.source = np.array(sorted({low, high, *(edge for start, end, _ in spans for edge in (start, end))}))
        pixels = np.diff(self.source) * 2
        widths = {}
        for start, end, label in sorted(spans, key=lambda span: span[1] - span[0]):
            for line in label.splitlines():
                if line not in widths:
                    widths[line] = measure(line)
            needed = max((widths[line] for line in label.splitlines()), default=0) + 16
            first, last = np.searchsorted(self.source, [start, end])
            allocated = pixels[first:last].sum()
            if allocated < needed:
                pixels[first:last] *= needed / allocated
        total = pixels.sum()
        self.width = ceil(total)
        self.display = low + np.r_[0., np.cumsum(pixels)] / total * (high - low)
        self.display[-1] = high

    @staticmethod
    def _interpolate(values, source, target):
        # Zoom/pan can extend outside the full span: extrapolate, don't clamp.
        values = np.asarray(values)
        mapped = np.interp(values, source, target)
        for edge, neighbor, outside in ((0, 1, values < source[0]), (-1, -2, values > source[-1])):
            mapped = np.where(outside, target[edge] + (values - source[edge]) *
                              (target[neighbor] - target[edge]) / (source[neighbor] - source[edge]), mapped)
        return mapped

    def forward(self, values):
        return self._interpolate(values, self.source, self.display)

    def inverse(self, values):
        return self._interpolate(values, self.display, self.source)

    def spans(self, spans):
        return [(float(self.forward(start)), float(self.forward(end)), label)
                for start, end, label in spans]


def space_wafer_plot(plot, spacing):
    """Keep curve objects, Y values and source ordinals; space only their display.

    Fresh setData calls invalidate the saved ordinal buffer by identity. This
    lets an already expanded plot accept new rows without applying spacing twice.
    """
    previous = getattr(plot, "_wafer_spacing", None)
    if previous is None and spacing is None:
        return
    view = plot.getViewBox()
    limits = view.viewRange()[0]
    full_range = spacing is not None and np.allclose(limits, spacing.source[[0, -1]], rtol=0, atol=1e-10)
    if previous is not None and not full_range:
        limits = previous.inverse(limits)
    curves = list(plot.listDataItems())
    curves.extend(item for secondary in getattr(plot, "secondary_views", ())
                  for item in secondary.addedItems if isinstance(item, pg.PlotDataItem))
    for curve in curves:
        if curve.xData is None:
            continue
        saved = getattr(curve, "_wafer_ordinals", None)
        source = saved[0] if saved is not None and curve.xData is saved[1] else curve.xData
        positions = spacing.forward(source) if spacing is not None else source
        if not np.array_equal(positions, curve.xData):
            curve.setData(x=positions, y=curve.yData)
        curve._wafer_ordinals = (source, curve.xData)
    plot._wafer_spacing = spacing
    for axis in (plot.getAxis("bottom"), getattr(plot, "_wafer_axis", None)):
        if isinstance(axis, (SpanLabelAxis, DieSequenceAxis)):
            axis.spacing = spacing
            axis.refresh()
    boundaries = getattr(plot, "wafer_boundaries", None)
    if boundaries is not None:
        if not hasattr(boundaries, "_wafer_ordinals"):
            boundaries._wafer_ordinals = boundaries.positions
        boundaries.positions = tuple(spacing.forward(boundaries._wafer_ordinals) if spacing is not None
                                     else boundaries._wafer_ordinals)
        boundaries.update()
    for line in getattr(plot, "_group_boundaries", ()):
        if not hasattr(line, "_wafer_ordinal"):
            line._wafer_ordinal = line.value()
        position = float(spacing.forward(line._wafer_ordinal)) if spacing is not None else line._wafer_ordinal
        line.setValue(position)
        if hasattr(line, "contrast_halo"):
            line.contrast_halo.setValue(position)
    mapped = spacing.forward(limits) if spacing is not None else limits
    if not np.allclose(mapped, view.viewRange()[0], rtol=0, atol=1e-10):
        view.setXRange(*mapped, padding=0)
    if hasattr(plot, "_refresh_group_axis"):
        plot._refresh_group_axis()


class SpanLabelAxis(pg.AxisItem):
    """Linked axis that restores full labels after resizing, zooming or panning."""
    def __init__(self, spans, *, optional_fields=True, font=None, reserve_lines=0):
        self.spans = list(spans)
        self.optional_fields = optional_fields
        self.reserve_lines = reserve_lines
        super().__init__(orientation="bottom")
        self.setStyle(tickLength=0, tickTextOffset=4,
                      tickFont=font or QApplication.font(), autoExpandTextSpace=False)
        self.setToolTip(" · ".join(label for _, _, label in self.spans))

    def linkedViewChanged(self, view, newRange=None):
        super().linkedViewChanged(view, newRange)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self):
        if getattr(self, "_linkedView", None) is None:
            return
        view = self.linkedView()
        if view is None:
            return
        width = max(1, view.sceneBoundingRect().width())
        if width < 8:
            # The plot has not been laid out yet; keep the previous labels
            # instead of clearing them until the first zoom.
            return
        metrics = QFontMetricsF(self.style.get("tickFont") or QApplication.font())
        spacing = getattr(self, "spacing", None)
        spans = spacing.spans(self.spans) if spacing is not None else self.spans
        ticks = span_label_ticks(spans, view.viewRange()[0],
                                 width, metrics.horizontalAdvance,
                                 optional_fields=self.optional_fields)
        if self._tickLevels != [ticks]:
            self.setTicks([ticks])
        lines = max((label.count("\n") + 1 for _, label in ticks), default=1)
        height = max(lines, self.reserve_lines) * metrics.height() + 12
        if self.label.isVisible():
            height += self.label.boundingRect().height() + 5
        if abs(self.height() - height) > .5:
            self.setHeight(height)


class DieSequenceAxis(pg.AxisItem):
    """Sample real Die Seq labels again for the current viewport, not draw time."""
    def __init__(self, ticks, *, font=None):
        self.ticks = list(ticks)
        self.positions = [position for position, _ in self.ticks]
        super().__init__(orientation="bottom")
        self.setStyle(tickFont=font or QApplication.font(), tickTextOffset=0)

    def linkedViewChanged(self, view, newRange=None):
        super().linkedViewChanged(view, newRange)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self):
        if getattr(self, "_linkedView", None) is None:
            return
        view = self.linkedView()
        if view is None:
            return
        low, high = view.viewRange()[0]
        width = max(1, view.sceneBoundingRect().width())
        if width < 8:
            return
        spacing = getattr(self, "spacing", None)
        source_low, source_high = spacing.inverse([low, high]) if spacing is not None else (low, high)
        first, last = bisect_left(self.positions, source_low), bisect_right(self.positions, source_high)
        candidates = self.ticks[first:last]
        if spacing is not None:
            candidates = [(float(spacing.forward(position)), label) for position, label in candidates]
        metrics = QFontMetricsF(self.style.get("tickFont") or QApplication.font())
        ticks = fit_tick_labels(candidates, (low, high), width,
                               metrics.horizontalAdvance)
        self.setTicks([ticks])

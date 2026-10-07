"""Responsive identity labels; fitting never changes plotted observations."""
from bisect import bisect_left, bisect_right
from math import ceil

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
        ticks = span_label_ticks(self.spans, view.viewRange()[0],
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
        first, last = bisect_left(self.positions, low), bisect_right(self.positions, high)
        metrics = QFontMetricsF(self.style.get("tickFont") or QApplication.font())
        ticks = fit_tick_labels(self.ticks[first:last], (low, high), width,
                               metrics.horizontalAdvance)
        self.setTicks([ticks])

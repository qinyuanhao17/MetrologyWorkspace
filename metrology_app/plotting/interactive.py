"""PyQtGraph navigation and frame rules shared by interactive plots."""

from math import ceil

import pyqtgraph as pg
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication


def place_legend_above_frame(plot, *, columns=2):
    """Host this plot's legend in the reserved header row, never over the data.

    PyQtGraph anchors legends inside the ViewBox by default, where they cover
    the curves. Sharing the title row keeps every plot's frame aligned while
    the entries sit above it. Call this before plotting so the entries
    register, and once more after the curves are drawn so the final entry
    widths are in place.
    """
    item = plot.getPlotItem()
    legend = item.legend
    if legend is None:
        legend = item.addLegend(offset=None)
    legend.setColumnCount(max(1, int(columns)))
    if legend.parentItem() is not item:
        legend.setParentItem(item)
    caption = getattr(plot, "title_label", None)
    alignment = (Qt.AlignmentFlag.AlignBottom if caption is not None
                 else Qt.AlignmentFlag.AlignVCenter)
    if getattr(plot, "_legend_in_header", None) is not legend:
        item.layout.addItem(
            legend, 0, 1,
            Qt.AlignmentFlag.AlignLeft | alignment,
        )
        plot._legend_in_header = legend
    if legend.items:
        # Keep the entries side by side: a stretched legend would push the last
        # entry to the far edge, away from the one it belongs to.
        legend.setMaximumWidth(int(legend.preferredSize().width()))
        legend.setMaximumHeight(ceil(legend.preferredSize().height()))
    if caption is not None:
        # Overlay captions and graphics legends need distinct vertical space,
        # especially when a narrow plot cannot separate them horizontally.
        plot._caption_header_height = max(46, ceil(caption.fontMetrics().height() + 4
                                                  + legend.preferredSize().height() + 4))
        item.layout.setRowFixedHeight(0, plot._caption_header_height)
    item.layout.invalidate()
    return legend


class _PlotViewBox(pg.ViewBox):
    """Auto-range Y while keeping an optional, meaningful X extent."""

    def __init__(self, auto_x_range=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fixed_auto_x_range = None
        self.set_auto_x_range(auto_x_range)

    def set_auto_x_range(self, x_range):
        if x_range is None:
            self._fixed_auto_x_range = None
            return
        left, right = map(float, x_range)
        if right <= left:
            raise ValueError("auto X range must increase from left to right")
        self._fixed_auto_x_range = (left, right)
        # PyQtGraph's Auto Scale button enables continuous auto-range instead
        # of calling autoRange() directly. Limits keep that path honest too:
        # Y still fits the data while X cannot grow into empty margins.
        self.setLimits(xMin=left, xMax=right)

    def autoRange(self, padding=None, items=None, item=None):
        """Honor PyQtGraph Auto Range without adding blank X margins."""
        super().autoRange(padding=padding, items=items, item=item)
        if self._fixed_auto_x_range is not None:
            self.setXRange(*self._fixed_auto_x_range, padding=0)

    def enableAutoRange(self, *args, **kwargs):
        super().enableAutoRange(*args, **kwargs)
        # A scrolled-out card may not paint yet; Auto Scale must still take effect.
        if getattr(self, "_autoRangeNeedsUpdate", False) and hasattr(self, "addedItems"):
            self.updateAutoRange()


class InteractivePlotWidget(pg.PlotWidget):
    """A four-sided PyQtGraph plot with predictable Auto Range behavior."""

    def __init__(self, *, auto_x_range=None, frame_tick_length=0, **kwargs):
        view_box = _PlotViewBox(auto_x_range=auto_x_range)
        super().__init__(viewBox=view_box, **kwargs)
        self.secondary_views = []
        self.secondary_axes = []
        # Graphics items are not QWidget parents. Their unparented native menus
        # otherwise outlive a deleted plot through Qt signal connections.
        for menu in (self.getPlotItem().getMenu(), view_box.getMenu(None)):
            if menu is not None:
                menu.setParent(self, menu.windowFlags())
        # AxisItems own the four frame lines. A second ViewBox border would
        # overlap them and make some edges appear heavier than others.
        self.view_box.setBorder(None)
        self._frame_axes(frame_tick_length)

    def add_secondary_axis(self, label, color):
        """Add an X-linked Y view; later axes are placed further right."""
        plot = self.getPlotItem()
        index = len(self.secondary_views)
        if index == 0:
            axis = plot.getAxis("right")
            plot.showAxis("right")
        else:
            axis = pg.AxisItem(orientation="right")
            plot.layout.addItem(axis, 2, 2 + index)
        axis.setStyle(showValues=True, tickLength=-5, autoExpandTextSpace=True)
        axis.setWidth(70)
        axis.setPen(pg.mkPen(color))
        axis.setTextPen(pg.mkPen(color))
        axis.setLabel(label, color=color)
        view = _PlotViewBox(auto_x_range=self.view_box._fixed_auto_x_range)
        menu = view.getMenu(None)
        if menu is not None:
            menu.setParent(self, menu.windowFlags())
        view.setBorder(None)
        plot.scene().addItem(view)
        axis.linkToView(view)
        view.setXLink(self.view_box)
        self.secondary_views.append(view)
        self.secondary_axes.append(axis)

        def sync_geometry():
            view.setGeometry(self.view_box.sceneBoundingRect())
            view.linkedViewChanged(self.view_box, view.XAxis)

        self.view_box.sigResized.connect(sync_geometry)
        sync_geometry()
        return view

    @property
    def view_box(self):
        return self.getPlotItem().getViewBox()

    def set_auto_x_range(self, x_range):
        self.view_box.set_auto_x_range(x_range)

    def wheelEvent(self, event):
        """Leave ordinary wheel navigation to the enclosing page."""
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            parent = self.parentWidget()
            while parent is not None and not isinstance(
                parent, QAbstractScrollArea
            ):
                parent = parent.parentWidget()
            if parent is None:
                event.ignore()
                return
            viewport = parent.viewport()
            local_position = viewport.mapFromGlobal(
                event.globalPosition().toPoint()
            )
            forwarded = QWheelEvent(
                QPointF(local_position), event.globalPosition(),
                event.pixelDelta(), event.angleDelta(), event.buttons(),
                event.modifiers(), event.phase(), event.inverted(),
            )
            QApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
            return
        super().wheelEvent(event)

    def _frame_axes(self, tick_length):
        """Reserve enough layout space for the top and right frame lines."""
        extent = max(1, abs(int(tick_length)) + 1)
        plot = self.getPlotItem()
        for name in ("top", "right"):
            axis = plot.getAxis(name)
            axis.setStyle(showValues=False, tickLength=tick_length,
                          autoExpandTextSpace=False)
            axis.setPen(pg.mkPen("#30343b"))
            axis.setTextPen(pg.mkPen("#30343b"))
            plot.showAxis(name)
            if name == "right":
                axis.setWidth(extent)
            else:
                axis.setHeight(extent)

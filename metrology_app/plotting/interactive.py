"""PyQtGraph navigation and frame rules shared by interactive plots."""

import pyqtgraph as pg


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


class InteractivePlotWidget(pg.PlotWidget):
    """A four-sided PyQtGraph plot with predictable Auto Range behavior."""

    def __init__(self, *, auto_x_range=None, frame_tick_length=0, **kwargs):
        view_box = _PlotViewBox(auto_x_range=auto_x_range)
        super().__init__(viewBox=view_box, **kwargs)
        self.view_box.setBorder(pg.mkPen("#30343b"))
        self._frame_axes(frame_tick_length)

    @property
    def view_box(self):
        return self.getPlotItem().getViewBox()

    def set_auto_x_range(self, x_range):
        self.view_box.set_auto_x_range(x_range)

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

"""Literal coordinate readouts and finite-observation summaries for plots."""
from weakref import ref

import numpy as np
import pyqtgraph as pg


def statistics_text(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return "Mean: N/A · σ: N/A · Min: N/A · Max: N/A"
    sigma = f"{np.std(values, ddof=1):.6g}" if len(values) > 1 else "N/A"
    return (f"Mean: {np.mean(values):.6g} · σ: {sigma} · "
            f"Min: {np.min(values):.6g} · Max: {np.max(values):.6g}")


def series_statistics(series):
    return "\n".join(f"{name}: {statistics_text(values)}" for name, values in series)


def set_plot_statistics(widget, series, enabled=True):
    """Default empty-space tooltip; point readouts always take precedence."""
    widget._statistics_series = tuple(series)
    widget._statistics_text = series_statistics(widget._statistics_series)
    widget._hover_point_tips = {}
    widget.setToolTip(widget._statistics_text)
    for view in [widget.getViewBox(), *widget.secondary_views]:
        view.setToolTip(widget._statistics_text)
    curves = widget.listDataItems() + [item for view in widget.secondary_views
                                     for item in view.addedItems if isinstance(item, pg.PlotDataItem)]
    for item in curves:
        scatter = getattr(item, "scatter", None)
        if scatter is None:
            continue
        if getattr(scatter, "_statistics_hover_hook", False):
            continue
        owner = ref(widget)
        def hovered(scatter, points, event, owner=owner):
            target = owner()
            if target is None:
                return
            tips = target._hover_point_tips
            tips[scatter] = "\n\n".join(point_tip(point.pos().x(), point.pos().y(), point.data())
                                       for point in points[:3])
            text = next((tip for tip in tips.values() if tip), target._statistics_text)
            for view in [target.getViewBox(), *target.secondary_views]:
                view.setToolTip(text)
        scatter.sigHovered.connect(hovered)
        scatter._statistics_hover_hook = True


def point_tip(x, y, data):
    die = data if data not in (None, "") else "N/A"
    return f"Die: {die}\nX: {x:.12g}\nY: {y:.12g}"


def attach_point_hover(item, dies):
    """Keep die labels aligned with the actual full-resolution point arrays."""
    dies = list(dies)
    if item.xData is None and not dies:
        return
    if item.xData is None or len(dies) != len(item.xData):
        raise ValueError("Die labels must match plotted observations.")
    item.opts["data"] = dies
    item.scatter.opts["hoverable"] = True
    item.scatter.opts["tip"] = point_tip
    item.scatter.setPointData(dies)


def value_formatter(value, decimals, *, scientific=False):
    text = f"{value:.{decimals}{'e' if scientific else 'f'}}"
    return text.removeprefix("-") if float(text) == 0 else text


def plain_y_axes(widget, decimals=None):
    for name in ("left", "right"):
        axis = widget.getAxis(name)
        axis.enableAutoSIPrefix(False)
        axis.value_decimals = decimals
    for axis in widget.secondary_axes:
        axis.enableAutoSIPrefix(False)
        axis.value_decimals = decimals


def plain_matplotlib_y(axis, decimals=None):
    if decimals is None:
        axis.ticklabel_format(axis="y", style="plain", useOffset=False)
        return
    from matplotlib.ticker import FuncFormatter

    def format_tick(value, _position):
        locations = axis.yaxis.get_majorticklocs()
        step = abs(locations[1] - locations[0]) if len(locations) > 1 else 0
        return value_formatter(value, decimals, scientific=0 < step < 10 ** -decimals)
    axis.yaxis.set_major_formatter(FuncFormatter(format_tick))

"""Wafer-level Mean and Sigma bar charts for Correlation and Trend."""
from html import escape
from math import ceil

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .appearance import panel_title_label
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .plotting.annotations import plain_matplotlib_y, plain_y_axes, set_plot_statistics
from .plotting.sequence_axis import DieSequenceAxis
from .sequence_page import COMPARE_CONTROL_WIDTH, LINE_COLOR, SequencePage
from .trend import overlay_spec


class WaferStatisticsPage(SequencePage):
    """Wafer Mean/Sigma bar rows plus one pairwise Bias row per comparison."""

    STATISTICS = (("mean", "Wafer Mean"), ("sigma", "Wafer Sigma"))
    BAR_WIDTH = .18
    BAR_STEP = .22
    BIAS_COLOR = "#6b7280"

    def __init__(self):
        super().__init__(defer_initial_input=True)
        self.setObjectName("waferStatisticsPage")
        self.select_button.setToolTip("Select parameters whose wafer statistics should be drawn")
        self.columns.clear()
        self.columns.addItem("2")
        self.columns.setFixedWidth(54)
        self.columns.setEnabled(False)
        self.expand_wafer_ids.setToolTip(
            "Increase horizontal spacing when many wafers produce crowded bar labels."
        )
    def set_identity_labels(self, options):
        if self.identity_labels != options:
            self.identity_labels = dict(options)
            if self.ready:
                self.draw_plot()

    def _panel_specs(self, metrics, groups):
        base = super()._panel_specs(metrics, groups)
        statistics = [
            {**panel, "statistic": statistic, "statistic_label": title}
            for panel in base
            for statistic, title in self.STATISTICS
        ]
        biases = [
            {
                **panel,
                "statistic": statistic,
                "statistic_label": title,
                "plot_kind": "bias",
                "comparison": comparison,
                "comparison_index": comparison_index,
            }
            for panel in base
            for comparison_index, comparison in enumerate(
                panel.get("comparisons", ())
            )
            for statistic, title in self.STATISTICS
        ]
        return statistics + biases

    def _single_curve_geometry(self, *_args):
        return None

    def _numeric_column(self, metric):
        if metric not in self._numeric_columns:
            from .data import number

            self._numeric_columns[metric] = number(self.frame[metric]).to_numpy(float)
        return self._numeric_columns[metric]

    def statistic_values(self, metric, statistic, groups):
        values = []
        numeric = self._numeric_column(metric)
        for group in groups:
            if group is None:
                values.append(np.nan)
                continue
            rows = np.asarray(group["source_positions"], dtype=int)
            sample = numeric[rows]
            sample = sample[np.isfinite(sample)]
            if not len(sample):
                values.append(np.nan)
            elif statistic == "mean":
                values.append(float(sample.mean()))
            else:
                values.append(float(sample.std(ddof=0)))
        return np.asarray(values, dtype=float)

    @staticmethod
    def _groups_by_span(groups):
        result = {}
        for group in groups:
            result.setdefault(group["span_key"], group)
        return result

    @staticmethod
    def _category_label(group):
        return str(group.get("wafer") or group.get("group_label") or group.get("key") or "")

    def _aligned_panel(self, panel, metric, groups):
        """Return category labels plus primary/compare groups aligned by Wafer."""
        primary = self._chosen_groups(panel, groups)
        comparisons = []
        for comparison in panel.get("comparisons", ()):
            source, name = self._comparison_series(panel, comparison)
            comparisons.append((source, name, self._groups_by_span(
                self._series_groups(source, name, groups))))
        primary_by_span = self._groups_by_span(primary)
        keys = list(primary_by_span)
        for _source, _name, mapping in comparisons:
            keys.extend(key for key in mapping if key not in keys)
        labels = []
        primary_groups, comparison_groups = [], [[] for _ in comparisons]
        for key in keys:
            group = primary_by_span.get(key)
            if group is None:
                group = next((mapping[key] for _source, _name, mapping in comparisons if key in mapping), None)
            labels.append(self._category_label(group))
            primary_groups.append(group)
            for target, (_source, _name, mapping) in zip(comparison_groups, comparisons):
                target.append(mapping.get(key))
        return labels, primary_groups, comparison_groups

    @staticmethod
    def _paired_rows(primary, comparison):
        rows = []
        for first, second in zip(primary, comparison):
            members = set()
            if first is not None:
                members.update(np.asarray(
                    first["source_positions"], dtype=int
                ).tolist())
            if second is not None:
                members.update(np.asarray(
                    second["source_positions"], dtype=int
                ).tolist())
            rows.append(tuple(sorted(members)))
        return rows

    def _bar_caption_spans(self, primary, comparisons, x):
        groups = [group or next((values[i] for values in comparisons if values[i] is not None), None)
                  for i, group in enumerate(primary)]
        pairs = [(group, (position - .5, position + .5)) for position, group in zip(x, groups)
                 if group is not None]
        if not self.selection.get("show_group_labels") or not pairs:
            return [], [], []
        bases = []
        for group, (start, end) in pairs:
            label = group["group_label"]
            if bases and bases[-1][1:] == (start, label):
                bases[-1] = (bases[-1][0], end, label)
            else:
                bases.append((start, end, label))
        wafers, combined = self._classification_spans(*zip(*pairs))
        return wafers, bases, combined

    def _append_interactive_panel(self, panel, groups, grid, _label_spans, panel_height, base):
        metric, source, statistic = panel["metric"], panel["source"], panel["statistic"]
        statistic_label = panel["statistic_label"]
        plot_kind = panel.get("plot_kind", "statistic")
        comparisons = tuple(panel.get("comparisons", ()))
        comparison_colours = self._comparison_colours(panel)
        title_name = self._legend_label(source, metric)
        title = f"{title_name} · {statistic_label}"
        labels, primary_groups, comparison_groups = self._aligned_panel(panel, metric, groups)
        compare_source = compare_metric = compare_groups = None
        if plot_kind == "bias":
            comparison_index = panel["comparison_index"]
            compare_source, compare_metric = self._comparison_series(
                panel, panel["comparison"]
            )
            compare_groups = comparison_groups[comparison_index]
            title = (
                f"{statistic_label} Bias · "
                f"{self._legend_label(compare_source, compare_metric)} − "
                f"{title_name}"
            )
        x = np.arange(1, len(labels) + 1, dtype=float)
        widget = InteractivePlotWidget(background="w")
        widget.setMinimumSize(420, 280)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        widget.point_selection.data = getattr(self, "data_point_edits", None)
        scope = ("Wafer Statistics", (source or {}).get("name"), metric, statistic)
        if plot_kind == "bias":
            scope += ("bias", (compare_source or {}).get("name"), compare_metric)
        widget.point_selection.scope = scope
        widget._statistic_category_count = len(labels)
        plot = widget.getPlotItem()
        bottom = DieSequenceAxis(list(zip(x, labels)), font=widget.font())
        bottom.setStyle(tickFont=widget.font(), tickTextOffset=4)
        bottom.setPen(pg.mkPen("#30343b"))
        bottom.setTextPen(pg.mkPen("#30343b"))
        plot.setAxisItems({"bottom": bottom})
        bottom.linkToView(plot.getViewBox())
        plot.setLabel("bottom", "Wafer")
        plot.setLabel("left", title, color="#30343b")
        plot.setTitle(None)
        plot.showGrid(x=False, y=True, alpha=.16)
        heading = panel_title_label(f"<b>{escape(title)}</b>", base + 1)
        if plot_kind == "bias":
            side = QWidget()
            side.setFixedWidth(COMPARE_CONTROL_WIDTH)
        else:
            side = self.build_overlay_control(metric, comparisons, source)
        container = PlotPanel(heading, widget, side_widget=side)
        container.setFixedHeight(panel_height)

        primary_values = self.statistic_values(metric, statistic, primary_groups)
        base_color = (source["color"] if source is not None and self.selection.get("sources")
                      else LINE_COLOR)
        bar_definitions = []
        if plot_kind == "bias":
            compare_values = self.statistic_values(
                compare_metric, statistic, compare_groups
            )
            bar_definitions.append({
                "values": compare_values - primary_values,
                "color": self.BIAS_COLOR,
                "label": f"{statistic_label} Bias",
                "rows": self._paired_rows(primary_groups, compare_groups),
                "specification": None,
            })
        else:
            bar_definitions.append({
                "values": primary_values,
                "color": base_color,
                "label": title_name,
                "rows": [
                    tuple(np.asarray(group["source_positions"], dtype=int))
                    if group is not None else ()
                    for group in primary_groups
                ],
                "specification": None,
            })
            for index, (comparison, selected) in enumerate(
                    zip(comparisons, comparison_groups)):
                compare_source, compare_metric = self._comparison_series(
                    panel, comparison
                )
                values = self.statistic_values(
                    compare_metric, statistic, selected
                )
                bar_definitions.append({
                    "values": values,
                    "color": comparison_colours[index],
                    "label": self._legend_label(
                        compare_source, compare_metric
                    ),
                    "comparison_index": index,
                    "rows": [
                        tuple(np.asarray(group["source_positions"], dtype=int))
                        if group is not None else ()
                        for group in selected
                    ],
                    "specification": overlay_spec(
                        metric, compare_metric, primary_values, values,
                        ratio_limit=self.axis_ratio_limit(),
                        axis_mode=self.axis_mode_value(),
                    ),
                })
        offsets = (
            np.arange(len(bar_definitions))
            - (len(bar_definitions) - 1) / 2
        ) * self.BAR_STEP
        legend = plot.addLegend(
            offset=(8, 6), colCount=min(3, len(bar_definitions))
        )
        all_statistics = []
        secondary_views = []
        for definition, offset in zip(bar_definitions, offsets):
            values = definition["values"]
            color = definition["color"]
            series_label = definition["label"]
            target = plot
            specification = definition["specification"]
            if (specification is not None
                    and specification["kind"] == "second-axis"):
                compare_source, compare_metric = self._comparison_series(
                    panel, comparisons[definition["comparison_index"]]
                )
                target = widget.add_secondary_axis(
                    self._legend_label(
                        compare_source,
                        self._axis_label(
                            compare_metric, specification["secondary_unit"]
                        ),
                    ),
                    color,
                )
                secondary_views.append(target)
            bar = pg.BarGraphItem(
                x=x + offset,
                height=np.nan_to_num(values, nan=0.0),
                width=self.BAR_WIDTH,
                brush=pg.mkBrush(color),
                pen=pg.mkPen(color),
            )
            target.addItem(bar)
            widget.set_point_rows(bar, definition["rows"])
            legend.addItem(bar, series_label)
            all_statistics.append((series_label, values))
            zero = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(
                color, width=1, style=Qt.PenStyle.DotLine))
            target.addItem(zero, ignoreBounds=True)
        plain_y_axes(widget, self.plot_decimals)
        wafers, bases, combined = self._bar_caption_spans(primary_groups, comparison_groups, x)
        widget.group_boundaries = widget.add_vertical_boundaries(
            [start for start, _, _ in bases[1:]], pg.mkPen("#30343b", style=Qt.PenStyle.DashLine))
        widget._statistic_caption_axes = {}
        for row, (kind, spans) in enumerate(zip(("wafer", "base", "combined"), (wafers, bases, combined)), 4):
            if spans:
                widget._statistic_caption_axes[kind] = self._add_caption_axis(widget, spans, row, optional_fields=row == 4)
        left = plot.getAxis("left")
        left_width = QFontMetrics(widget.font()).horizontalAdvance("-0." + "0" * self.plot_decimals + "e-00") + 34
        left.setWidth(left_width)
        set_plot_statistics(widget, all_statistics, True)
        view = plot.getViewBox()
        view.setMouseMode(pg.ViewBox.RectMode)
        view.setXRange(.4, len(labels) + .6, padding=0)
        view.enableAutoRange(axis=pg.ViewBox.YAxis)
        for secondary in secondary_views:
            secondary.setMouseMode(pg.ViewBox.RectMode)
            secondary.setXLink(view)
            secondary.enableAutoRange(axis=pg.ViewBox.YAxis)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        grid.add_panel(container)
        self.plot_widgets.append(widget)
        self.panel_hosts.append(container)

    def expand_layout(self, *_args):
        if self.plot_host is None or not self.plot_widgets:
            return
        count = max((getattr(widget, "_statistic_category_count", 1)
                     for widget in self.plot_widgets), default=1)
        width = max(420, min(1800, 80 * count)) if self.expand_wafer_ids.isChecked() else 0
        for host in self.panel_hosts:
            host.setMinimumWidth(width + COMPARE_CONTROL_WIDTH if width else 0)

    def _finish_interactive(self, grid, previous_scroll, geometry, panels, finished):
        super()._finish_interactive(
            grid, previous_scroll, geometry, panels, finished
        )
        if self.plot_host is not grid:
            return
        right_count = max((len(widget.secondary_axes) for widget in self.plot_widgets), default=0)
        for widget in self.plot_widgets:
            width = QFontMetrics(widget.font()).horizontalAdvance("-0." + "0" * self.plot_decimals + "e-00") + 34
            layout = widget.getPlotItem().layout
            for index in range(right_count):
                layout.setColumnFixedWidth(2 + index, width)
                if index < len(widget.secondary_axes):
                    widget.secondary_axes[index].setWidth(width)
        for splitter in self.plot_host.row_splitters:
            for index in range(splitter.count()):
                splitter.setStretchFactor(index, 1)
            splitter.setSizes([1] * splitter.count())

    def export_plot_data(self):
        from .analysis_export import _series

        plots = []
        groups = self.view_groups or self.groups
        for panel in self.display_panel_specs():
            metric, source, statistic = panel["metric"], panel["source"], panel["statistic"]
            labels, primary_groups, comparison_groups = self._aligned_panel(panel, metric, groups)
            series = []
            plot_kind = panel.get("plot_kind", "statistic")
            if plot_kind == "bias":
                comparison_index = panel["comparison_index"]
                compare_source, compare_metric = self._comparison_series(
                    panel, panel["comparison"]
                )
                compare_groups = comparison_groups[comparison_index]
                primary_values = self.statistic_values(
                    metric, statistic, primary_groups
                )
                compare_values = self.statistic_values(
                    compare_metric, statistic, compare_groups
                )
                title = (
                    f"{panel['statistic_label']} Bias · "
                    f"{self._legend_label(compare_source, compare_metric)} − "
                    f"{self._legend_label(source, metric)}"
                )
                series.append(dict(_series(
                    title, labels, compare_values - primary_values,
                    line=False, markers=False,
                ), color=self.BIAS_COLOR))
                y_column = "Bias"
            else:
                primary_color = (
                    source["color"]
                    if source is not None and self.selection.get("sources")
                    else LINE_COLOR
                )
                candidates = [(
                    source, metric, primary_groups, primary_color
                )]
                colours = self._comparison_colours(panel)
                for index, (comparison, selected) in enumerate(
                        zip(panel.get("comparisons", ()), comparison_groups)):
                    owner, name = self._comparison_series(panel, comparison)
                    candidates.append((
                        owner, name, selected,
                        colours[index],
                    ))
                for owner, name, selected, color in candidates:
                    values = self.statistic_values(name, statistic, selected)
                    series.append(dict(_series(
                        self._legend_label(owner, name), labels, values,
                        line=False, markers=False,
                    ), color=color))
                title = (
                    f"{self._legend_label(source, metric)} · "
                    f"{panel['statistic_label']}"
                )
                y_column = statistic.title()
            plots.append({"sheet": "Wafer Mean and Sigma", "title": title,
                          "kind": "bar", "x": "Wafer", "y": y_column,
                          "series": series})
        return plots

    def build_export_figure(self, panels, groups):
        columns = min(2, len(panels))
        rows = ceil(len(panels) / columns)
        base = int(self.font_size.currentText())
        width, height = self.base_size
        height = max(height, rows * 390 + 30)
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        axes = self.figure.subplots(rows, columns, squeeze=False)
        captions = []
        max_secondary = 0
        for axis, panel in zip(axes.flat, panels):
            metric, source, statistic = panel["metric"], panel["source"], panel["statistic"]
            labels, primary_groups, comparison_groups = self._aligned_panel(panel, metric, groups)
            x = np.arange(len(labels), dtype=float)
            plot_kind = panel.get("plot_kind", "statistic")
            if plot_kind == "bias":
                comparison_index = panel["comparison_index"]
                compare_source, compare_metric = self._comparison_series(
                    panel, panel["comparison"]
                )
                compare_groups = comparison_groups[comparison_index]
                values = (
                    self.statistic_values(
                        compare_metric, statistic, compare_groups
                    )
                    - self.statistic_values(
                        metric, statistic, primary_groups
                    )
                )
                title = (
                    f"{panel['statistic_label']} Bias · "
                    f"{self._legend_label(compare_source, compare_metric)} − "
                    f"{self._legend_label(source, metric)}"
                )
                bars = [(title, values, self.BIAS_COLOR)]
            else:
                primary_color = (
                    source["color"]
                    if source is not None and self.selection.get("sources")
                    else LINE_COLOR
                )
                bars = [(
                    self._legend_label(source, metric),
                    self.statistic_values(metric, statistic, primary_groups),
                    primary_color,
                )]
                colours = self._comparison_colours(panel)
                for index, (comparison, selected) in enumerate(
                        zip(panel.get("comparisons", ()), comparison_groups)):
                    owner, name = self._comparison_series(panel, comparison)
                    bars.append((
                        self._legend_label(owner, name),
                        self.statistic_values(name, statistic, selected),
                        colours[index],
                    ))
                title = (
                    f"{self._legend_label(source, metric)} · "
                    f"{panel['statistic_label']}"
                )
            offsets = (
                np.arange(len(bars)) - (len(bars) - 1) / 2
            ) * self.BAR_STEP
            handles, secondary_axes = [], []
            for index, ((label, values, color), offset) in enumerate(zip(bars, offsets)):
                target = axis
                if index > 0:
                    _source, compare_metric = self._comparison_series(panel, panel["comparisons"][index - 1])
                    spec = overlay_spec(metric, compare_metric, bars[0][1], values,
                                        ratio_limit=self.axis_ratio_limit(), axis_mode=self.axis_mode_value())
                    if spec["kind"] == "second-axis":
                        target = axis.twinx()
                        target.spines.right.set_position(("axes", 1 + .12 * len(secondary_axes)))
                        target.set_ylabel(label, color=color, fontsize=max(7, base - 1))
                        target.tick_params(axis="y", colors=color)
                        secondary_axes.append(target)
                handles.append(target.bar(
                    x + offset, np.nan_to_num(values, nan=0.0),
                    width=self.BAR_WIDTH, color=color, label=label,
                ))
                plain_matplotlib_y(target, self.plot_decimals)
            max_secondary = max(max_secondary, len(secondary_axes))
            axis.set_title(title, fontsize=base + 1, fontweight="semibold")
            axis.set_ylabel(title, fontsize=max(7, base - 1))
            axis.set_xticks(x, labels, fontsize=max(6, base - 2))
            axis.tick_params(axis="x", rotation=35)
            axis.grid(axis="y", color="#d6d8dc", linewidth=.7)
            axis.set_axisbelow(True)
            if len(bars) > 1:
                axis.legend(handles=handles, fontsize=max(6, base - 2), frameon=False,
                            ncol=min(3, len(bars)))
            spans = self._bar_caption_spans(primary_groups, comparison_groups, x)
            captions.append((axis, spans))
            for start, _, _ in spans[1][1:]:
                axis.axvline(start, color="#30343b", linestyle="--", linewidth=.8, zorder=0)
            for spine in axis.spines.values():
                spine.set_color("#c9ccd1")
        for axis in axes.flat[len(panels):]:
            axis.set_axis_off()
        classified = any(bases for _, (_, bases, _) in captions)
        self.figure.subplots_adjust(left=.07, right=.91 if max_secondary else .98,
                                    top=.94, bottom=.21 if classified else .12,
                                    hspace=.52 if classified else .34,
                                    wspace=.36 if max_secondary else .2)
        for axis, layers in captions:
            offset = 3 * base + 10
            for layer, spans in enumerate(layers):
                if spans:
                    self._add_export_caption_row(axis, spans, offset, base, wafer=layer == 0)
                    offset += (base + 3) * max(label.count("\n") + 1 for _, _, label in spans) + 5

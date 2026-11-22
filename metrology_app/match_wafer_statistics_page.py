"""Wafer Mean, Sigma and Bias plots for the Match Workbook result area."""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPalette
from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .plotting import InteractivePlotWidget
from .plotting.annotations import plain_y_axes, set_plot_statistics
from .plotting.parameter_layout import ParameterPlotArea
from .plotting.sequence_axis import DieSequenceAxis, SpanLabelAxis
from .measurements import wafer_identity_labels


class MatchWaferStatisticsPage(QWidget):
    """One Mean/Sigma/Bias row for each checked parameter mapping."""

    layout_changed = pyqtSignal(str, object)

    BAR_WIDTH_PIXELS = 20
    BAR_STEP_PIXELS = 25
    Y_DECIMALS = 3
    REFERENCE_COLOR = "#ed7d31"
    RAW_COLOR = "#5b9bd5"
    BIAS_COLOR = "#6b7280"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.data_point_edits = None
        self.layouts = {}
        self.label_options = {"pad": True, "lot": True}
        self._dirty = True
        self._render_timer = QTimer(self, interval=0, singleShot=True)
        self._render_timer.timeout.connect(self.render)
        self.rendered_parameters = ()
        self.plots_by_parameter = {}
        self.parameter_areas = {}
        self.parameter_cards = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.stack = QStackedWidget()
        self.empty = QLabel("Run the Match Workbook to draw checked parameter statistics.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.scroll)
        layout.addWidget(self.stack)

    def clear(self):
        self.result = None
        self.rendered_parameters = ()
        self.plots_by_parameter = {}
        self.parameter_areas = {}
        self.parameter_cards = {}
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.empty.setText("Run the Match Workbook to draw checked parameter statistics.")
        self.stack.setCurrentWidget(self.empty)
        self._dirty = True

    def set_result(self, result, data_point_edits=None, layouts=None):
        self.result = result
        self.data_point_edits = data_point_edits
        self.layouts = dict(layouts or {})
        self._dirty = True
        if self.isVisible():
            self._render_timer.start()

    def set_label_options(self, options):
        options = {
            "pad": bool(options.get("pad", True)),
            "lot": bool(options.get("lot", True)),
        }
        if options != self.label_options:
            self.label_options = options
            if self.isVisible():
                self._render_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self._render_timer.start()

    def render(self):
        self._dirty = False
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.plots_by_parameter = {}
        self.parameter_areas = {}
        if self.result is None:
            self.stack.setCurrentWidget(self.empty)
            return
        self.rendered_parameters = tuple(self.result.parameter_names)
        if not self.rendered_parameters:
            self.empty.setText("Check at least one Parameter mapping.")
            self.stack.setCurrentWidget(self.empty)
            return
        spans = self.result.group_plan.trend_spans()
        if not spans:
            self.empty.setText("No included measurements are available for Wafer statistics.")
            self.stack.setCurrentWidget(self.empty)
            return
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        stats = self._series_statistics(spans)
        caption_labels = self._caption_labels(spans)
        for parameter in self.rendered_parameters:
            row = self._statistics_for_parameter(parameter, spans, stats)
            plots = {}
            for kind, title, values, series_definitions in (
                ("mean", "Wafer Mean", row["mean"], row["mean_bars"]),
                ("sigma", "Wafer Sigma", row["sigma"], row["sigma_bars"]),
                ("mean_bias", "Wafer Mean Bias", row["mean_bias"], row["mean_bias_bars"]),
                ("sigma_bias", "Wafer Sigma Bias", row["sigma_bias"], row["sigma_bias_bars"]),
            ):
                plot = self._build_plot(
                    parameter, kind, title, spans, values, series_definitions,
                    caption_labels,
                )
                key = f"wafer_{kind}"
                plots[key] = plot
            area = ParameterPlotArea(
                plots,
                plot_height=280,
                titles={
                    "wafer_mean": "Wafer Mean",
                    "wafer_sigma": "Wafer Sigma",
                    "wafer_mean_bias": "Wafer Mean Bias",
                    "wafer_sigma_bias": "Wafer Sigma Bias",
                },
                initial_sizes=(340, 340),
            )
            area.moveDock(
                area.docks["wafer_mean_bias"],
                "bottom",
                area.docks["wafer_mean"],
            )
            area.moveDock(
                area.docks["wafer_sigma_bias"],
                "bottom",
                area.docks["wafer_sigma"],
            )
            if parameter in self.layouts:
                area.restoreState(self.layouts[parameter])
            area.layoutChanged.connect(
                lambda name=parameter, target=area:
                self._layout_changed(name, target)
            )
            card = QFrame(objectName="sheetCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 12)
            handle = QLabel(f"⋮⋮  {parameter}", objectName="parameterDragHandle")
            handle.setToolTip("Parameter row for the draggable Wafer statistics plots.")
            card_layout.addWidget(handle)
            card_layout.addWidget(area)
            card.setFixedHeight(area.height() + handle.sizeHint().height() + 24)
            outer.addWidget(card)
            self.parameter_areas[parameter] = area
            self.parameter_cards[parameter] = card
            self.plots_by_parameter[parameter] = tuple(
                plots[name] for name in (
                    "wafer_mean", "wafer_sigma", "wafer_mean_bias", "wafer_sigma_bias",
                )
            )
        outer.addStretch(1)
        self.scroll.setWidget(content)
        self.stack.setCurrentWidget(self.scroll)

    def _layout_changed(self, parameter, area):
        state = area.saveState()
        self.layouts[parameter] = state
        card = self.parameter_cards.get(parameter)
        if card is not None:
            handle = card.findChild(QLabel, "parameterDragHandle")
            extra = handle.sizeHint().height() if handle is not None else 0
            card.setFixedHeight(area.height() + extra + 24)
        self.layout_changed.emit(parameter, state)

    @staticmethod
    def _caption_label(span, raw=None, options=None):
        group, separator, measurement = str(span.get("label", "")).partition("\n")
        if raw is not None:
            options = options or {"pad": True, "lot": True}
            measurement = wafer_identity_labels(
                raw,
                [span["rows"]],
                show_pad=options.get("pad", True),
                show_lot=options.get("lot", True),
            )[0]
        if separator and measurement:
            return measurement + ("\n" + group if group else "")
        return group

    def _caption_labels(self, spans):
        raw = self.result.group_plan.raw
        if raw is None:
            return [self._caption_label(span) for span in spans]
        measurements = wafer_identity_labels(
            raw,
            [span["rows"] for span in spans],
            show_pad=self.label_options.get("pad", True),
            show_lot=self.label_options.get("lot", True),
        )
        labels = []
        for span, measurement in zip(spans, measurements):
            group, separator, _default = str(span.get("label", "")).partition("\n")
            labels.append(
                measurement + ("\n" + group if group else "")
                if separator and measurement else group
            )
        return labels

    def _series_statistics(self, spans):
        series = {}
        rows = tuple(int(row) for row in self.result.source_rows)
        positions = {row: index for index, row in enumerate(rows)}
        for parameter in self.rendered_parameters:
            frame = self.result.series(parameter)
            values = []
            for span in spans:
                indexes = [positions[row] for row in span["rows"] if row in positions]
                if indexes:
                    selected = frame.iloc[indexes]
                    reference = selected["Reference"].to_numpy(float)
                    raw = selected["Raw"].to_numpy(float)
                else:
                    reference = raw = np.array([], dtype=float)
                reference = reference[np.isfinite(reference)]
                raw = raw[np.isfinite(raw)]
                values.append({
                    "reference": (
                        (float(reference.mean()), float(reference.std(ddof=0)))
                        if len(reference) else (np.nan, np.nan)
                    ),
                    "raw": (
                        (float(raw.mean()), float(raw.std(ddof=0)))
                        if len(raw) else (np.nan, np.nan)
                    ),
                    "rows": tuple(int(row) for row in span["rows"]),
                })
            series[parameter] = values
        return series

    def _statistics_for_parameter(self, parameter, spans, stats):
        values = stats[parameter]
        mean = (
            np.asarray([entry["reference"][0] for entry in values], dtype=float),
            np.asarray([entry["raw"][0] for entry in values], dtype=float),
        )
        sigma = (
            np.asarray([entry["reference"][1] for entry in values], dtype=float),
            np.asarray([entry["raw"][1] for entry in values], dtype=float),
        )
        mean_bias = mean[1] - mean[0]
        sigma_bias = sigma[1] - sigma[0]
        span_rows = [entry["rows"] for entry in values]
        return {
            "mean": mean,
            "sigma": sigma,
            "mean_bias": mean_bias,
            "sigma_bias": sigma_bias,
            "mean_bars": self._reference_raw_bars(mean, span_rows),
            "sigma_bars": self._reference_raw_bars(sigma, span_rows),
            "mean_bias_bars": [(mean_bias, self.BIAS_COLOR, "Raw − Ref", span_rows)],
            "sigma_bias_bars": [(sigma_bias, self.BIAS_COLOR, "Raw − Ref", span_rows)],
        }

    def _reference_raw_bars(self, values, rows):
        return [
            (values[0], self.REFERENCE_COLOR, "Reference", rows),
            (values[1], self.RAW_COLOR, "Raw Data", rows),
        ]

    def _build_plot(self, parameter, kind, statistic, spans, values, definitions,
                    caption_labels=None):
        title = f"{parameter} · {statistic}"
        plot = InteractivePlotWidget(background="w")
        plot.setBackground("w")
        palette = plot.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#20242a"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#20242a"))
        plot.setPalette(palette)
        plot.setMinimumSize(320, 290)
        plot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        plot.point_selection.set_data(
            self.data_point_edits,
            ("Match Workbook", self.result.result_mode.title(), parameter, "wafer-statistics", kind),
        )
        if caption_labels is None:
            caption_labels = self._caption_labels(spans)
        caption_spans = [
            (index - .5, index + .5, label)
            for index, label in enumerate(caption_labels, start=1)
        ]
        bottom = DieSequenceAxis(
            [(float(index), str(index)) for index in range(1, len(spans) + 1)],
            font=plot.font(),
        )
        bottom.setStyle(
            tickTextOffset=2,
            tickLength=0,
            tickFont=plot.font(),
        )
        bottom.setHeight(QFontMetricsF(plot.font()).height() + 8)
        plot.setAxisItems({"bottom": bottom})
        plot.setLabel("bottom", "")
        captions = SpanLabelAxis(
            caption_spans,
            font=plot.font(),
            optional_fields=True,
            show_boundaries=True,
        )
        captions.setStyle(
            tickLength=0,
            tickTextOffset=4,
            tickFont=plot.font(),
        )
        captions.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
        captions.setTextPen(pg.mkPen("#5f6368"))
        plot.getPlotItem().layout.addItem(captions, 4, 1)
        captions.linkToView(plot.getViewBox())
        plot._statistics_caption_axis = captions
        plot.setLabel("left", title, color="#30343b")
        plot.setTitle(title, color="#20242a", size="11pt", bold=True)
        plot.showGrid(x=False, y=True, alpha=.16)
        frame_pen = pg.mkPen("#30343b")
        for axis_name in ("top", "right", "bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(frame_pen)
            axis.setTextPen(frame_pen)
            axis.setStyle(tickLength=0)
        for axis_name in ("top", "right"):
            plot.getAxis(axis_name).setStyle(
                showValues=False, tickLength=0,
            )
        x = np.arange(1, len(spans) + 1, dtype=float)
        legend = plot.addLegend(offset=(8, 6), colCount=min(3, len(definitions)))
        legend.setLabelTextColor("#30343b")
        bars = []
        statistics = []
        offsets = (
            np.arange(len(definitions)) - (len(definitions) - 1) / 2
        ) * (self.BAR_STEP_PIXELS / 24.0)
        for definition, initial_offset in zip(definitions, offsets):
            bar_values, color, label, rows = definition
            bar = pg.BarGraphItem(
                x=x + initial_offset,
                height=np.nan_to_num(bar_values, nan=0.0),
                width=.16,
                brush=pg.mkBrush(color),
                pen=pg.mkPen(color),
            )
            plot.addItem(bar)
            plot.set_point_rows(bar, rows)
            legend.addItem(bar, label)
            bar._statistics_bases = x.copy()
            bar._statistics_offset = len(bars) - (len(definitions) - 1) / 2
            bars.append(bar)
            statistics.append((label, bar_values))
        plot.addItem(pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen("#777777", width=1, style=Qt.PenStyle.DashLine),
        ), ignoreBounds=True)
        group_boundaries = [
            index + .5
            for index, span in enumerate(spans[1:], start=1)
            if span["group"] != spans[index - 1]["group"]
        ]
        plot._statistics_group_boundaries = plot.add_vertical_boundaries(
            group_boundaries,
            pg.mkPen("#000000", width=2, style=Qt.PenStyle.DashLine),
        )
        plain_y_axes(plot, self.Y_DECIMALS)
        for axis_name in ("left", "right"):
            axis = plot.getAxis(axis_name)
            axis.enableAutoSIPrefix(False)
            axis.value_decimals = self.Y_DECIMALS
        for axis in plot.secondary_axes:
            axis.enableAutoSIPrefix(False)
            axis.value_decimals = self.Y_DECIMALS
        set_plot_statistics(plot, statistics, True)
        view = plot.getViewBox()
        view.setMouseMode(pg.ViewBox.RectMode)
        view.setXRange(.4, len(spans) + .6, padding=0)
        if kind in ("mean_bias", "sigma_bias"):
            finite = np.asarray(values, dtype=float)
            finite = finite[np.isfinite(finite)]
            limit = float(np.max(np.abs(finite))) if len(finite) else 1.0
            limit = max(limit, 1.0 if limit == 0 else limit * 1.08)
            view.disableAutoRange(axis=pg.ViewBox.YAxis)
            view.setYRange(-limit, limit, padding=0)
        plot._statistics_bars = bars
        view.sigResized.connect(lambda *_args, target=plot: self._sync_bar_geometry(target))
        view.sigXRangeChanged.connect(lambda *_args, target=plot: self._sync_bar_geometry(target))
        timer = QTimer(plot, interval=0, singleShot=True)
        timer.timeout.connect(lambda target=plot: self._sync_bar_geometry(target))
        timer.start()
        plot._statistics_sync_timer = timer
        return plot

    def _sync_bar_geometry(self, plot):
        view = plot.getViewBox()
        width = float(view.sceneBoundingRect().width())
        low, high = view.viewRange()[0]
        if width <= 1 or high <= low:
            return
        per_unit = width / (high - low)
        width_data = self.BAR_WIDTH_PIXELS / per_unit
        step_data = self.BAR_STEP_PIXELS / per_unit
        for bar in getattr(plot, "_statistics_bars", ()):
            bases = getattr(bar, "_statistics_bases", None)
            if bases is not None:
                bar.setOpts(
                    x=bases + bar._statistics_offset * step_data,
                    width=width_data,
                )

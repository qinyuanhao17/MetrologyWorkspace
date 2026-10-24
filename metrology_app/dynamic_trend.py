"""Cycle-versus-value Trend tab for the Dynamic workspace.

Like the Correlation and Trend tab, every selected parameter gets its own
interactive panel. The difference is the axis meaning: Cycle runs along the
bottom while the panel draws one Die Seq at a time, chosen from the picker to
the right of the plot.
"""

from __future__ import annotations

from html import escape
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings,
                         TREND_LINE_WIDTH, TREND_MARKER_SIZE)
from .appearance import widget_to_qimage
from .dynamic import (changed_dynamic_parameters, cycle_trend,
                      prepare_dynamic_frame, selected_measurement_rows)
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .plotting.annotations import (attach_point_hover, plain_y_axes, plain_matplotlib_y,
                                  set_plot_statistics)
from .settings import get_settings


HOME_PADDING = 0.06
PANEL_WIDTH = 900
PANEL_HEIGHT = 350
DIE_CONTROL_WIDTH = 150
# Die traces need to stay distinguishable up to a full reticle of measurements,
# so this palette is longer than the comparison palettes.
DIE_COLOURS = (
    "#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5",
    "#70AD47", "#264478", "#9E480E", "#636363", "#997300",
    "#255E91", "#43682B", "#698ED0", "#F1975A", "#B7B7B7",
    "#FFCD33", "#7CAFDD", "#8CC168", "#8EA9DB", "#C55A11",
)
class DiePickerComboBox(QComboBox):
    """Switch the plotted Die on vertical wheel input, even without focus."""

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta or not self.count():
            event.ignore()
            return
        step = -1 if delta > 0 else 1
        index = max(0, min(self.currentIndex() + step, self.count() - 1))
        self.setCurrentIndex(index)
        event.accept()


class DynamicTrendPage(QWidget):
    """One Cycle-versus-value panel per parameter, one curve per Die Seq."""

    def __init__(self):
        super().__init__(objectName="dynamicTrendPage")
        settings = get_settings()
        self.frame = pd.DataFrame()
        self.selection = {}
        self.panel_specs = []
        self.plot_widgets = []
        self.panel_hosts = []
        self.panel_widgets = {}
        self.panel_tables = {}
        self.die_pickers = {}
        self.selected_dies = {}
        self.comparisons = {}
        self._compare_render_pending = False
        self.home_views = []
        self.secondary_home_views = []
        self.plot_host = None
        self.ready = False
        self.x_range = (0.5, 1.5)
        self.base_size = (PANEL_WIDTH, PANEL_HEIGHT + 30)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.export_button = QPushButton("Export PNG")
        self.export_button.clicked.connect(self.export_png)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        for control in (self.export_button, self.copy_button):
            toolbar.addWidget(control)
        toolbar.addStretch()
        self.summary = QLabel("0 × 0", objectName="accent")
        toolbar.addWidget(self.summary)
        layout.addLayout(toolbar)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Columns", objectName="muted"))
        self.columns = QComboBox()
        self.columns.addItems(["1", "2"])
        self.columns.setFixedWidth(54)
        self.columns.currentIndexChanged.connect(self.relayout)
        options.addWidget(self.columns)
        self.reset_button = QPushButton("Reset views")
        self.reset_button.setToolTip(
            "Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan.\n"
            "Ordinary scrolling moves the page.\n"
            "Reset returns every curve to its original range."
        )
        self.reset_button.clicked.connect(self.reset_views)
        options.addWidget(self.reset_button)
        options.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentTextChanged.connect(self.restyle)
        options.addWidget(self.font_size)
        options.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(
            max(0, self.resolution.findText(settings.get("resolution", "High")))
        )
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        options.addWidget(self.resolution)
        options.addStretch()
        layout.addLayout(options)

        self.figure = Figure(figsize=(9, 3.8), dpi=100, facecolor="white")
        FigureCanvasAgg(self.figure)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_png)
        self.copy_button.setToolTip(
            "Copy the full panel grid as a PNG. Ctrl+C works while this tab is active."
        )

        self.interactive_scroll = QScrollArea()
        self.interactive_scroll.setWidgetResizable(True)
        self.interactive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.empty = QLabel(objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.interactive_scroll)
        layout.addWidget(self.stack, 1)
        self.status = QLabel(objectName="hint")
        layout.addWidget(self.status)
        self.invalidate()

    def set_input(self, frame, selection):
        changed = changed_dynamic_parameters(self.frame, frame, self.selection, selection)
        self.frame = pd.DataFrame(frame).copy()
        self.selection = dict(selection)
        if changed is not None and self.ready and self._update_parameters(changed):
            return
        self.refresh()

    def _update_parameters(self, changed):
        if not changed:
            return True
        try:
            prepared = prepare_dynamic_frame(selected_measurement_rows(self.frame, self.selection))
            series = {parameter: cycle_trend(prepared, parameter) for parameter in changed}
        except ValueError:
            return False
        if any(not table.index.equals(self.panel_tables[parameter].index)
               or not table.columns.equals(self.panel_tables[parameter].columns)
               for parameter, table in series.items()):
            return False
        self.panel_tables.update(series)
        for widget in self.panel_widgets.values():
            for curve in self.data_curves(widget):
                parameter, die = curve.dynamic_series
                if parameter in changed:
                    table = self.panel_tables[parameter]
                    curve.setData(np.asarray(table.index, dtype=float),
                                  pd.to_numeric(table[die], errors="coerce").to_numpy(float))
                    attach_point_hover(curve, [die] * len(table))
        self.refresh_statistics()
        self.panel_specs = list(self.panel_tables.items())
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        return True

    def refresh(self, *_args):
        parameters = list(self.selection.get("metrics", ()))
        try:
            if not parameters:
                raise ValueError(
                    "Select one measurement set and at least one numeric "
                    "parameter in Data."
                )
            rows = selected_measurement_rows(self.frame, self.selection)
            prepared = prepare_dynamic_frame(
                rows.drop(columns=["Cycle"], errors="ignore")
            )
            series = {
                parameter: cycle_trend(prepared, parameter)
                for parameter in parameters
            }
        except ValueError as error:
            self.invalidate(str(error))
            return
        self.render_interactive(series)

    def invalidate(self, message=None):
        self.ready = False
        self.panel_specs = []
        self.plot_widgets = []
        self.panel_hosts = []
        self.panel_widgets = {}
        self.panel_tables = {}
        self.die_pickers = {}
        self.home_views = []
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.draw_canvas_message(message or "")
        self.clear_interactive(message)
        self.stack.setCurrentWidget(self.empty)
        self.summary.setText("0 × 0")
        if message:
            self.status.setText(message)

    def draw_canvas_message(self, message):
        """Keep the export figure readable when there is nothing to plot yet."""
        size = max(15, int(self.font_size.currentText()) + 3)
        self.figure.text(
            .5, .5, message, ha="center", va="center", color="#746b7e", fontsize=size
        )

    def clear_interactive(self, message=None):
        if self.plot_host is not None:
            self.plot_host.setParent(None)
            self.plot_host.deleteLater()
            self.plot_host = None
        self.plot_widgets = []
        self.panel_hosts = []
        self.home_views = []
        self.panel_widgets = {}
        self.panel_tables = {}
        self.die_pickers = {}
        if message:
            label = QLabel(message, objectName="subtitle")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                f"font-size: {max(15, int(self.font_size.currentText()) + 3)}pt;"
            )
            label.setMinimumSize(600, 360)
            self.plot_host = label
            self.interactive_scroll.setWidget(label)

    @staticmethod
    def cycle_range(series):
        """Shared Cycle axis for every panel; panels may cover different cycles."""
        cycles = [
            float(cycle) for table in series.values() for cycle in table.index
        ]
        if not cycles:
            return (0.5, 1.5)
        return (min(cycles) - 0.5, max(cycles) + 0.5)

    def render_interactive(self, series):
        previous_scroll = self.interactive_scroll.verticalScrollBar().value()
        self.clear_interactive()
        base = int(self.font_size.currentText())
        columns = max(1, min(int(self.columns.currentText()), len(series)))
        rows = ceil(len(series) / columns)
        self.x_range = self.cycle_range(series)
        grid = PanelGrid(columns)
        grid.set_minimum_row_height(rows, PANEL_HEIGHT)
        self.panel_specs = list(series.items())
        self.panel_tables = dict(series)
        self.comparisons = {parameter: [name for name in names if name in series and name != parameter]
                            for parameter, names in self.comparisons.items() if parameter in series}
        for parameter, table in self.panel_specs:
            widget = InteractivePlotWidget(background="w", auto_x_range=self.x_range)
            widget.setMinimumSize(360, 280)
            widget.setToolTip(
                "Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan · "
                "Ordinary scrolling moves the page · "
                "Double-click to fit this curve · Reset views restores all curves"
            )
            plot = widget.getPlotItem()
            plot.setTitle(None)   # the QLabel above the plot owns the heading
            plot.showGrid(x=True, y=True, alpha=.18)
            plot.setLabel(
                "left", str(parameter), color="#30343b",
                size=f"{max(7, base - 1)}pt",
            )
            plot.setLabel(
                "bottom", "Cycle", color="#30343b", size=f"{max(7, base - 1)}pt"
            )
            heading = panel_title_label(f"<b>{escape(str(parameter))}</b>", base + 1)
            plot.getAxis("bottom").setTicks([
                [(float(cycle), str(cycle)) for cycle in table.index]
            ])
            die = self.selected_dies.get(parameter)
            if die not in table.columns:
                die = table.columns[0]
            self.selected_dies[parameter] = die
            self.draw_panel(widget, parameter)
            picker = self.build_die_picker(parameter, table)
            container = PlotPanel(heading, widget, side_widget=picker)
            view = plot.getViewBox()
            view.setMouseMode(pg.ViewBox.RectMode)
            view.setDefaultPadding(HOME_PADDING)
            view.autoRange(padding=HOME_PADDING)
            view.setXRange(*self.x_range, padding=0)
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            grid.add_panel(container)
            self.plot_widgets.append(widget)
            self.panel_hosts.append(container)
            self.panel_widgets[parameter] = widget
            self.panel_tables[parameter] = table
        self.plot_host = grid
        self.base_size = (columns * PANEL_WIDTH, rows * PANEL_HEIGHT + 30)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        # Swapping the grid resets the scroll bar: rebuild with painting off and
        # restore the offset before anything is drawn.
        self.interactive_scroll.setUpdatesEnabled(False)
        try:
            self.interactive_scroll.setWidget(grid)
            self.restore_page_scroll(previous_scroll)
        finally:
            self.interactive_scroll.setUpdatesEnabled(True)
        self.ready = True
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.stack.setCurrentWidget(self.interactive_scroll)
        cycles = sum(len(table.index) for _parameter, table in self.panel_specs)
        dies = max((len(table.columns) for _parameter, table in self.panel_specs),
                   default=0)
        self.summary.setText(f"{len(self.panel_specs)} × {dies}")
        self.status.setText(
            f"{len(self.panel_specs)} parameters · one of {dies} Die Seq per panel · "
            f"{cycles} Cycle points."
        )
        QTimer.singleShot(0, self.remember_home_views)

    def panel_curves(self, parameter):
        die = self.selected_dies[parameter]
        return [(name, die) for name in [parameter, *self.comparisons.get(parameter, ())]
                if die in self.panel_tables[name].columns]

    def panel_statistics(self, parameter):
        return [(f"{name} · Die {die}", self.panel_tables[name][die].to_numpy(float))
                for name, die in self.panel_curves(parameter)]

    def refresh_statistics(self, *_):
        for parameter, widget in self.panel_widgets.items():
            set_plot_statistics(widget, self.panel_statistics(parameter))
        self._export_dirty = True
        self._copy_image = None

    def draw_panel(self, widget, parameter):
        plot = widget.getPlotItem()
        for item in list(widget.listDataItems()):
            plot.removeItem(item)
        for view in widget.secondary_views:
            for item in list(view.addedItems):
                if isinstance(item, pg.PlotDataItem):
                    view.removeItem(item)
        if plot.legend is not None:
            plot.legend.clear()
        curves = self.panel_curves(parameter)
        if len(curves) > 1 and plot.legend is None:
            plot.addLegend(offset=(8, 8), colCount=2)
        targets = getattr(widget, 'dynamic_axes', {})
        for index, (name, die) in enumerate(curves):
            table = self.panel_tables[name]
            if name == parameter:
                target = plot
            elif name not in targets:
                targets[name] = widget.add_secondary_axis(
                    name, DIE_COLOURS[(len(targets) + 5) % len(DIE_COLOURS)])
                targets[name].setDefaultPadding(HOME_PADDING)
                target = targets[name]
            else:
                target = targets[name]
            item = self.plot_die(target, table, die)
            item.dynamic_series = (name, die)
            if index:
                colour = DIE_COLOURS[(index + 4) % len(DIE_COLOURS)]
                item.setPen(pg.mkPen(colour, width=TREND_LINE_WIDTH))
                item.setSymbolBrush(colour)
                item.setSymbolPen(colour)
            if plot.legend is not None:
                plot.legend.addItem(item, f"{name} · Die {die}")
            attach_point_hover(item, [die] * len(table))
        widget.dynamic_axes = targets
        for view in widget.secondary_views:
            view.autoRange(padding=HOME_PADDING)
        plain_y_axes(widget)
        set_plot_statistics(widget, self.panel_statistics(parameter))

    @staticmethod
    def data_curves(widget):
        return widget.listDataItems() + [item for view in widget.secondary_views
            for item in view.addedItems if isinstance(item, pg.PlotDataItem)]

    def add_compare(self, parameter, *, defer=False):
        selected = self.comparisons.setdefault(parameter, [])
        available = [name for name in self.panel_tables if name != parameter and name not in selected]
        if available:
            selected.append(available[0])
            self._queue_compare_render() if defer else self.render_interactive(dict(self.panel_tables))

    def change_compare(self, parameter, index, name, *, defer=False):
        selected = self.comparisons.get(parameter, [])
        if index < len(selected):
            if name is None:
                selected.pop(index)
            else:
                selected[index] = name
            self._queue_compare_render() if defer else self.render_interactive(dict(self.panel_tables))

    def _queue_compare_render(self):
        """Rebuild after the emitting combo/button has returned to Qt."""
        if self._compare_render_pending:
            return
        self._compare_render_pending = True
        QTimer.singleShot(0, self._refresh_compare_panels)

    def _refresh_compare_panels(self):
        self._compare_render_pending = False
        self.render_interactive(dict(self.panel_tables))

    def build_die_picker(self, parameter, table):
        """Right-hand control that keeps one panel on a single Die Seq."""
        control = QFrame(objectName="compareControls")
        control.setFrameShape(QFrame.Shape.StyledPanel)
        control.setFixedWidth(DIE_CONTROL_WIDTH)
        layout = QVBoxLayout(control)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        picker = DiePickerComboBox()
        picker.setObjectName("dynamicDiePicker")
        picker.setToolTip(
            "Choose the Die Seq this panel draws. Scroll up for the previous "
            "Die or down for the next; only this panel refreshes."
        )
        for column in table.columns:
            picker.addItem(f"Die {column}", column)
        index = picker.findData(self.selected_dies.get(parameter))
        picker.setCurrentIndex(index if index >= 0 else 0)
        picker.currentIndexChanged.connect(
            lambda _index, name=parameter, box=picker:
            self.select_die(name, box.currentData())
        )
        layout.addWidget(picker)
        add = QPushButton("Add Compare", objectName="dynamicAddCompare")
        selected = self.comparisons.get(parameter, [])
        add.setEnabled(len(selected) < len(self.panel_tables) - 1)
        add.clicked.connect(lambda _=False, name=parameter:
                            self.add_compare(name, defer=True))
        layout.addWidget(add)
        for index, current in enumerate(selected):
            row = QHBoxLayout()
            box = DiePickerComboBox()
            box.setObjectName("dynamicComparePicker")
            for name in self.panel_tables:
                if name != parameter and (name == current or name not in selected):
                    box.addItem(name, name)
            box.setCurrentIndex(box.findData(current))
            box.currentIndexChanged.connect(lambda _i, p=parameter, i=index, b=box:
                                            self.change_compare(p, i, b.currentData(), defer=True))
            row.addWidget(box)
            remove = QPushButton("×", objectName="compareRemove")
            remove.setAccessibleName("Remove comparison")
            remove.setToolTip("Remove this comparison")
            remove.setFixedSize(25, 25)
            remove.clicked.connect(lambda _=False, p=parameter, i=index:
                                   self.change_compare(p, i, None, defer=True))
            row.addWidget(remove, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(row)
        layout.addStretch(1)
        self.die_pickers[parameter] = picker
        return control

    def select_die(self, parameter, die):
        """Redraw one panel with the Die the engineer picked."""
        widget = self.panel_widgets.get(parameter)
        table = self.panel_tables.get(parameter)
        if widget is None or table is None or die not in table.columns:
            return
        self.selected_dies[parameter] = die
        plot = widget.getPlotItem()
        self.draw_panel(widget, parameter)
        view = plot.getViewBox()
        view.autoRange(padding=HOME_PADDING)
        view.setXRange(*self.x_range, padding=0)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.status.setText(
            f"{parameter} · Die {die} · {len(table.index)} Cycle points."
        )
        QTimer.singleShot(0, self.remember_home_views)

    @staticmethod
    def plot_die(plot, table, die):
        """Draw exactly one Die Seq against the Cycle axis."""
        cycles = np.asarray([float(cycle) for cycle in table.index])
        values = pd.to_numeric(table[die], errors="coerce").to_numpy(float)
        position = list(table.columns).index(die)
        colour = DIE_COLOURS[position % len(DIE_COLOURS)]
        item = pg.PlotDataItem(
            cycles, values, connect="finite",
            pen=pg.mkPen(colour, width=TREND_LINE_WIDTH),
            symbol="o", symbolSize=TREND_MARKER_SIZE,
            symbolPen=pg.mkPen(colour), symbolBrush=pg.mkBrush(colour),
        )
        plot.addItem(item)
        return item

    def restore_page_scroll(self, value):
        """Put the panel list back where the engineer left it."""
        self.interactive_scroll.verticalScrollBar().setValue(int(value))

    def remember_home_views(self):
        """Store the view each panel was drawn with, so Reset views can restore it."""
        self.home_views = [
            widget.getPlotItem().getViewBox().viewRange()
            for widget in self.plot_widgets
        ]
        self.secondary_home_views = [[view.viewRange() for view in widget.secondary_views]
                                     for widget in self.plot_widgets]

    def reset_views(self):
        """Restore every panel to the exact range it was drawn with."""
        if not self.plot_widgets:
            return
        if len(self.home_views) != len(self.plot_widgets):
            for widget in self.plot_widgets:
                widget.getPlotItem().getViewBox().autoRange(padding=HOME_PADDING)
            self.remember_home_views()
        else:
            for widget, home in zip(self.plot_widgets, self.home_views):
                widget.getPlotItem().getViewBox().setRange(
                    xRange=home[0], yRange=home[1], padding=0
                )
            for widget, homes in zip(self.plot_widgets, self.secondary_home_views):
                for view, home in zip(widget.secondary_views, homes):
                    view.setRange(xRange=home[0], yRange=home[1], padding=0)
        self.status.setText(f"Reset {len(self.plot_widgets)} cycle views.")

    def relayout(self, *_args):
        if self.ready:
            self.render_interactive(dict(self.panel_specs))

    def restyle(self, *_args):
        if self.ready:
            base = int(self.font_size.currentText())
            self._export_dirty = True
            self._copy_image = None
            self._copy_dpi = None
            # A font change does not change any curve or its chosen Die/view.
            for container, widget in zip(self.panel_hosts, self.plot_widgets):
                heading = container.findChild(QLabel, "panelTitle")
                if heading is not None:
                    heading.setStyleSheet(f"color: #20242a; font-size: {base + 1}pt;")
                plot = widget.getPlotItem()
                for name in ("left", "bottom"):
                    axis = plot.getAxis(name)
                    options = {key: getattr(axis, attribute) for key, attribute in
                               (("unitPower", "unitPower"), ("siPrefixEnableRanges", "_siPrefixEnableRanges"))
                               if hasattr(axis, attribute)}
                    axis.setLabel(axis.labelText, units=axis.labelUnits, unitPrefix=axis.labelUnitPrefix,
                                  **options,
                                  **{**axis.labelStyle, "size": f"{max(7, base - 1)}pt"})
        elif self.plot_host is None:
            self.draw_canvas_message("")

    def change_resolution(self, *_args):
        if self.ready:
            _scale, dpi = resolution_settings(self.resolution)
            effective = export_dpi(self.figure, dpi, MAX_EXPORT_PIXELS)
            note = (
                f" · capped to {effective} dpi for this {len(self.panel_specs)}-plot size"
                if effective < dpi else ""
            )
            self.status.setText(
                f"PNG output: {dpi} dpi{note}. This setting does not change the "
                "on-screen curves."
            )

    def ensure_export_figure(self):
        """Build the Matplotlib export mirror only when Export / Copy needs it."""
        if self._export_dirty or not self.figure.axes:
            self.build_export_figure()
            self._export_dirty = False

    def build_export_figure(self):
        """Matplotlib mirror of the on-screen grid, used for Export PNG."""
        columns = max(1, min(int(self.columns.currentText()), len(self.panel_specs)))
        rows = ceil(len(self.panel_specs) / columns)
        extra_axes = max((len(self.comparisons.get(parameter, ()))
                          for parameter, _ in self.panel_specs), default=0)
        width, height = self.base_size
        base = int(self.font_size.currentText())
        stats_header = 0
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        if not self.panel_specs:
            self.draw_canvas_message("No cycle trends to export.")
            return
        axes = self.figure.subplots(rows, columns, squeeze=False)
        for ax, (parameter, table) in zip(axes.flat, self.panel_specs):
            cycles = [float(cycle) for cycle in table.index]
            curves = self.panel_curves(parameter)
            targets = {parameter: ax}
            for index, (name, die) in enumerate(curves):
                source = self.panel_tables[name]
                position = list(source.columns).index(die)
                colour = DIE_COLOURS[(position if not index else index + 4) % len(DIE_COLOURS)]
                values = pd.to_numeric(source[die], errors="coerce").to_numpy(float)
                if name not in targets:
                    target = ax.twinx()
                    target.spines['right'].set_position(('outward', 60 * (len(targets) - 1)))
                    target.set_ylabel(name, fontsize=max(7, base - 1))
                    target.tick_params(labelsize=max(6, base - 2))
                    plain_matplotlib_y(target)
                    targets[name] = target
                targets[name].plot([float(cycle) for cycle in source.index], values, color=colour,
                        linestyle="-",
                        marker="o", markersize=TREND_MARKER_SIZE,
                        linewidth=TREND_LINE_WIDTH,
                        label=f"{name} · Die {die}")
            if len(curves) > 1:
                handles, labels = [], []
                for target in targets.values():
                    lines, names = target.get_legend_handles_labels()
                    handles.extend(lines)
                    labels.extend(names)
                ax.legend(handles, labels, fontsize=max(6, base - 2),
                          ncol=min(4, len(curves)))
            title = f"{parameter} · Die {self.selected_dies[parameter]}"
            ax.set_title(
                title, fontsize=base + 1,
                fontweight="semibold", pad=8,
            )
            ax.set_xlabel("Cycle", fontsize=max(7, base - 1))
            ax.set_ylabel(str(parameter), fontsize=max(7, base - 1))
            plain_matplotlib_y(ax)
            ax.set_xlim(*self.x_range)
            ax.set_xticks(cycles)
            ax.tick_params(labelsize=max(6, base - 2))
            for spine in ax.spines.values():
                spine.set_color("#c9ccd1")
        for ax in axes.flat[len(self.panel_specs):]:
            ax.set_axis_off()
        if stats_header:
            plot_height = height / rows - stats_header - 50
            self.figure.subplots_adjust(left=.08, right=.985, top=1 - stats_header / height,
                                        bottom=50 / height, hspace=(stats_header + 50) / plot_height, wspace=.2)
        else:
            self.figure.subplots_adjust(
                left=.08, right=max(.55, .985 - .085 * extra_axes),
                top=.93, bottom=.1,
                hspace=.55, wspace=.2 + .15 * extra_axes
            )

    def export_png(self):
        if not self.ready:
            return
        self.ensure_export_figure()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cycle trends", "cycle_trends.png", "PNG (*.png)"
        )
        if not path:
            return
        path = str(Path(path).with_suffix(".png"))
        _scale, requested = resolution_settings(self.resolution)
        dpi = export_dpi(self.figure, requested, MAX_EXPORT_PIXELS)
        note = f" · capped from {requested} dpi" if dpi < requested else ""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Exporting…")
        QApplication.processEvents()
        try:
            self.figure.savefig(path, dpi=dpi, facecolor="white")
            self.status.setText(f"Exported ({dpi} dpi{note}): {path}")
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()

    def copy_png(self):
        if not self.ready:
            return
        _scale, requested = resolution_settings(self.resolution)
        cache_key = (requested, self.plot_host.width(), self.plot_host.height())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Copying…")
        try:
            if self._copy_image is None or self._copy_dpi != cache_key:
                self._copy_image, scale = widget_to_qimage(
                    self.plot_host, requested / 100, MAX_COPY_PIXELS
                )
                self._copy_dpi = cache_key
            else:
                scale = self._copy_image.width() / max(1, self.plot_host.width())
            image = self._copy_image
            dpi = round(scale * 100)
            note = f" · capped from {requested} dpi" if dpi < requested else ""
            QApplication.clipboard().setImage(image)
            self.status.setText(
                f"Copied Cycle trends ({dpi} dpi{note}) · "
                f"{image.width()} × {image.height()} px"
            )
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()


__all__ = ["DIE_COLOURS", "DynamicTrendPage"]

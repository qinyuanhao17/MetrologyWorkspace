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
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .dynamic import (changed_dynamic_parameters, cycle_trend,
                      prepare_dynamic_frame, selected_measurement_rows)
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .settings import get_settings


HOME_PADDING = 0.06
PANEL_WIDTH = 900
PANEL_HEIGHT = 350
DIE_CONTROL_WIDTH = 150
# Die traces need to stay distinguishable up to a full reticle of measurements,
# so the palette and markers are longer than the comparison palettes.
DIE_COLOURS = (
    "#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5",
    "#70AD47", "#264478", "#9E480E", "#636363", "#997300",
    "#255E91", "#43682B", "#698ED0", "#F1975A", "#B7B7B7",
    "#FFCD33", "#7CAFDD", "#8CC168", "#8EA9DB", "#C55A11",
)
# (pyqtgraph symbol, matplotlib marker). Only symbols both backends know:
# pyqtgraph has no plain "v"/"<"/">" — its triangles are t, t1, t2 and t3.
DIE_SYMBOLS = (
    ("o", "o"), ("s", "s"), ("t", "^"), ("t1", "v"), ("t2", "<"), ("t3", ">"),
    ("d", "D"), ("+", "+"), ("x", "x"), ("star", "*"), ("p", "P"), ("h", "h"),
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
        self.home_views = []
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
        for parameter, table in series.items():
            old = self.panel_tables[parameter]
            self.panel_tables[parameter] = table
            die = self.selected_dies[parameter]
            if not old[die].equals(table[die]):
                # A different Die's edit changes the export table but not this curve.
                curve = self.panel_widgets[parameter].listDataItems()[0]
                curve.setData(np.asarray(table.index, dtype=float),
                              pd.to_numeric(table[die], errors="coerce").to_numpy(float))
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
            self.plot_die(plot, table, die)
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
        for item in list(plot.listDataItems()):
            plot.removeItem(item)
        self.plot_die(plot, table, die)
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
        symbol = DIE_SYMBOLS[position % len(DIE_SYMBOLS)][0]
        item = pg.PlotDataItem(
            cycles, values, connect="finite",
            pen=pg.mkPen(colour, width=1.8),
            symbol=symbol, symbolSize=5,
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
        self.status.setText(f"Reset {len(self.plot_widgets)} cycle views.")

    def relayout(self, *_args):
        if self.ready:
            self.render_interactive(dict(self.panel_specs))

    def restyle(self, *_args):
        if self.ready:
            self.relayout()
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
        width, height = self.base_size
        base = int(self.font_size.currentText())
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        if not self.panel_specs:
            self.draw_canvas_message("No cycle trends to export.")
            return
        axes = self.figure.subplots(rows, columns, squeeze=False)
        for ax, (parameter, table) in zip(axes.flat, self.panel_specs):
            cycles = [float(cycle) for cycle in table.index]
            die = self.selected_dies.get(parameter)
            if die not in table.columns:
                die = table.columns[0]
            position = list(table.columns).index(die)
            colour = DIE_COLOURS[position % len(DIE_COLOURS)]
            marker = DIE_SYMBOLS[position % len(DIE_SYMBOLS)][1]
            values = pd.to_numeric(table[die], errors="coerce").to_numpy(float)
            ax.plot(
                cycles, values, color=colour, linestyle="-",
                marker=marker, markersize=3.8, linewidth=1.5,
            )
            ax.set_title(
                f"{parameter} · Die {die}", fontsize=base + 1,
                fontweight="semibold", pad=8,
            )
            ax.set_xlabel("Cycle", fontsize=max(7, base - 1))
            ax.set_ylabel(str(parameter), fontsize=max(7, base - 1))
            ax.set_xlim(*self.x_range)
            ax.set_xticks(cycles)
            ax.tick_params(labelsize=max(6, base - 2))
            for spine in ax.spines.values():
                spine.set_color("#c9ccd1")
        for ax in axes.flat[len(self.panel_specs):]:
            ax.set_axis_off()
        self.figure.subplots_adjust(
            left=.08, right=.985, top=.93, bottom=.1, hspace=.55, wspace=.2
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


__all__ = ["DIE_COLOURS", "DIE_SYMBOLS", "DynamicTrendPage"]

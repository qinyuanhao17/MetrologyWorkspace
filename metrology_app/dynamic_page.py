"""Qt page for Dynamic cycle tables and per-die 3σ bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHeaderView, QLabel, QScrollArea, QSplitter,
    QTableView, QVBoxLayout, QWidget,
)
from pyqtgraph.graphicsItems.LegendItem import ItemSample, LegendItem

from .dynamic import dynamic_pivot, prepare_dynamic_frame
from .plotting import InteractivePlotWidget
from .settings import get_settings


PLOT_WIDTH = 420
PLOT_HEIGHT = 270
PLOT_SPACING = 14
PLOT_COLUMNS = 3
SERIES_COLOURS = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#000000",
)


class CompactBarLegendSample(ItemSample):
    """Small colour swatch for the combined Dynamic chart legend."""

    SIZE = 10

    def __init__(self, item):
        super().__init__(item)
        self.setFixedWidth(self.SIZE)
        self.setFixedHeight(self.SIZE)

    def boundingRect(self):
        return QRectF(0, 0, self.SIZE, self.SIZE)

    def paint(self, painter, *_args):
        painter.setPen(pg.mkPen(self.item.opts["pen"]))
        painter.setBrush(pg.mkBrush(self.item.opts["brush"]))
        painter.drawRect(QRectF(1, 1, self.SIZE - 2, self.SIZE - 2))


class DynamicPivotModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()

    def set_frame(self, frame):
        self.beginResetModel()
        self.frame = frame.copy()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.frame.iat[index.row(), index.column()]
            if pd.isna(value):
                return ""
            return f"{float(value):.8g}" if isinstance(value, (float, np.floating)) else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if self.frame.index[index.row()] == "3 Sigma":
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            column = self.frame.columns[section]
            if isinstance(column, tuple) and len(column) >= 2:
                return f"{column[0]}\nDie {column[1]}"
            return f"Die {column}"
        return str(self.frame.index[section])


class DynamicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, objectName="dynamicPage")
        self.frame = pd.DataFrame()
        self.selection = {}
        self.parameter_models = {}
        self.parameter_tables = {}
        self.parameter_sections = []
        self.plots = []
        self.bar_items = []
        self.comparison_legend = None
        self.plot = None
        self.pivot_model = None
        self.table = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        self.message = QLabel(
            "Select one measurement set and at least one numeric parameter in Data.",
            objectName="subtitle",
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.content = QFrame(objectName="panel")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)
        dark = get_settings().get("theme") == "dark"
        self._plot_background = "#17121d" if dark else "#f8f7fa"
        self._plot_foreground = "#cfc4d5" if dark else "#5f5965"

        self.results_splitter = QSplitter(Qt.Orientation.Vertical)
        self.results_splitter.setObjectName("dynamicResultsSplitter")
        self.results_splitter.setChildrenCollapsible(False)

        self.table_scroll = QScrollArea(objectName="dynamicTableScroll")
        self.table_scroll.setWidgetResizable(True)
        self.table_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table_host = QWidget(objectName="dynamicTableHost")
        self.table_layout = QVBoxLayout(self.table_host)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.setSpacing(PLOT_SPACING)
        self.table_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.table_scroll.setWidget(self.table_host)

        self.plot_scroll = QScrollArea(objectName="dynamicPlotScroll")
        self.plot_scroll.setWidgetResizable(False)
        self.plot_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_host = QWidget(objectName="dynamicPlotHost")
        self.plot_layout = QGridLayout(self.plot_host)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.setHorizontalSpacing(PLOT_SPACING)
        self.plot_layout.setVerticalSpacing(PLOT_SPACING)
        self.plot_scroll.setWidget(self.plot_host)

        self.results_splitter.addWidget(self.table_scroll)
        self.results_splitter.addWidget(self.plot_scroll)
        self.results_splitter.setStretchFactor(0, 1)
        self.results_splitter.setStretchFactor(1, 1)
        self.results_splitter.setSizes([1, 1])
        content_layout.addWidget(self.results_splitter, 1)
        layout.addWidget(self.content, 1)
        self.content.hide()

    def set_input(self, frame, selection):
        self.frame = pd.DataFrame(frame).copy()
        self.selection = dict(selection)
        self.refresh()

    def _selected_rows(self):
        selected = list(self.selection.get("wafers", ()))
        groups = self.selection.get("groups", {})
        if len(selected) != 1:
            raise ValueError("Select exactly one measurement set in Data.")
        indices = list(groups.get(selected[0], ()))
        if not indices:
            raise ValueError("The selected measurement set has no rows.")
        return self.frame.iloc[indices].reset_index(drop=True)

    def refresh(self, *_args):
        self._clear_results()
        parameters = list(self.selection.get("metrics", ()))
        if not parameters:
            self.content.hide()
            self.message.setText(
                "Select one measurement set and at least one numeric parameter in Data."
            )
            self.message.show()
            return
        try:
            rows = self._selected_rows().drop(columns=["Cycle"], errors="ignore")
            prepared = prepare_dynamic_frame(rows)
            pivots = {
                parameter: dynamic_pivot(prepared, parameter)
                for parameter in parameters
            }
        except ValueError as error:
            self.content.hide()
            self.message.setText(str(error))
            self.message.show()
            return

        if len(parameters) > 1:
            self._add_comparison_plot(parameters, pivots)
        for index, parameter in enumerate(parameters):
            self._add_parameter_section(
                parameter, pivots[parameter]
            )
            self._add_parameter_plot(
                parameter, pivots[parameter],
                SERIES_COLOURS[index % len(SERIES_COLOURS)],
            )
        plot_columns = min(PLOT_COLUMNS, len(self.plots))
        plot_rows = (len(self.plots) + PLOT_COLUMNS - 1) // PLOT_COLUMNS
        plot_width = plot_columns * PLOT_WIDTH
        plot_width += max(0, plot_columns - 1) * PLOT_SPACING
        plot_height = plot_rows * PLOT_HEIGHT
        plot_height += max(0, plot_rows - 1) * PLOT_SPACING
        self.plot_host.setFixedSize(plot_width, plot_height)
        self.plot = self.plots[0]
        self.pivot_model = self.parameter_models[parameters[0]]
        self.table = self.parameter_tables[parameters[0]]
        self.table_scroll.verticalScrollBar().setValue(0)
        self.plot_scroll.horizontalScrollBar().setValue(0)
        self.plot_scroll.verticalScrollBar().setValue(0)
        self.message.hide()
        self.content.show()

    def _clear_results(self):
        self.bar_items = []
        self.comparison_legend = None
        self.plot = None
        self.pivot_model = None
        self.table = None
        while self.table_layout.count():
            item = self.table_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.deleteLater()
        while self.plot_layout.count():
            item = self.plot_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.deleteLater()
        self.parameter_models = {}
        self.parameter_tables = {}
        self.parameter_sections = []
        self.plots = []

    def _new_plot(self, title):
        plot = InteractivePlotWidget(
            background=self._plot_background, frame_tick_length=3
        )
        plot.setFixedSize(PLOT_WIDTH, PLOT_HEIGHT)
        plot.setLabel("bottom", "Die Seq")
        plot.setLabel("left", "3 Sigma (nm)")
        plot.setToolTip(
            "Ctrl+scroll to zoom · Drag to pan · Ordinary scrolling moves the page"
        )
        plot.getAxis("left").enableAutoSIPrefix(False)
        frame_pen = pg.mkPen(self._plot_foreground)
        plot.getPlotItem().getViewBox().setBorder(None)
        for axis_name in ("top", "right", "bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(frame_pen)
            axis.setTextPen(frame_pen)
        plot.showGrid(x=True, y=True, alpha=0.18)
        if title:
            plot.setTitle(title)
            accessible_title = str(title)
        else:
            plot.setTitle(None)
            accessible_title = "selected parameters"
        plot.setAccessibleName(f"Dynamic 3 Sigma — {accessible_title}")
        row, column = divmod(len(self.plots), PLOT_COLUMNS)
        self.plot_layout.addWidget(plot, row, column)
        self.plots.append(plot)
        return plot

    def _add_parameter_section(self, parameter, pivot):
        section = QFrame(objectName="dynamicParameterSection")
        section.setProperty("parameter", parameter)
        section.setAccessibleName(f"Dynamic results — {parameter}")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(10, 10, 10, 10)
        section_layout.setSpacing(10)

        title = QLabel(str(parameter), objectName="sectionTitle")
        section_layout.addWidget(title)

        model = DynamicPivotModel(section)
        model.set_frame(pivot)
        table = QTableView(objectName="dynamicParameterTable")
        table.setAccessibleName(f"Dynamic pivot — {parameter}")
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setMinimumHeight(42)
        table.verticalHeader().setDefaultSectionSize(28)
        table.setFixedHeight(42 + len(pivot) * 28 + 22)
        section_layout.addWidget(table)

        self.parameter_models[parameter] = model
        self.parameter_tables[parameter] = table
        self.parameter_sections.append(section)
        self.table_layout.addWidget(section)

    @staticmethod
    def _set_die_ticks(plot, dies):
        x = np.arange(1, len(dies) + 1, dtype=float)
        plot.getAxis("bottom").setTicks([
            [(float(position), str(label)) for position, label in zip(x, dies)]
        ])
        return x

    def _add_comparison_plot(self, parameters, pivots):
        plot = self._new_plot(None)
        plot_item = plot.getPlotItem()
        plot_item.layout.removeItem(plot_item.titleLabel)
        legend = LegendItem(
            offset=None,
            horSpacing=4,
            verSpacing=0,
            pen=None,
            brush=None,
            frame=False,
            labelTextColor=self._plot_foreground,
            labelTextSize="8pt",
            colCount=len(parameters),
            sampleType=CompactBarLegendSample,
        )
        plot_item.layout.addItem(
            legend, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        plot_item.layout.setRowFixedHeight(0, 22)
        self.comparison_legend = legend
        dies = list(dict.fromkeys(
            die for parameter in parameters for die in pivots[parameter].columns
        ))
        x = self._set_die_ticks(plot, dies)
        group_width = 0.78
        bar_width = group_width / len(parameters)
        for index, parameter in enumerate(parameters):
            colour = SERIES_COLOURS[index % len(SERIES_COLOURS)]
            sigma = pivots[parameter].loc["3 Sigma"].reindex(dies).to_numpy(float)
            finite = np.isfinite(sigma)
            offset = (index - (len(parameters) - 1) / 2.0) * bar_width
            bars = pg.BarGraphItem(
                x=(x + offset)[finite], height=sigma[finite],
                width=bar_width * 0.86, brush=pg.mkBrush(colour),
                pen=pg.mkPen(colour, width=1),
            )
            plot.addItem(bars)
            legend.addItem(bars, parameter)
            self.bar_items.append(bars)

    def _add_parameter_plot(self, parameter, pivot, colour):
        plot = self._new_plot(parameter)
        dies = list(pivot.columns)
        x = self._set_die_ticks(plot, dies)
        sigma = pivot.loc["3 Sigma"].to_numpy(float)
        finite = np.isfinite(sigma)
        bars = pg.BarGraphItem(
            x=x[finite], height=sigma[finite], width=0.72,
            brush=pg.mkBrush(colour), pen=pg.mkPen(colour, width=1),
        )
        plot.addItem(bars)
        self.bar_items.append(bars)


__all__ = ["DynamicPage", "DynamicPivotModel"]

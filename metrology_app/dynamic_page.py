"""Qt page for Dynamic cycle tables and per-die 3σ bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QTableView,
    QVBoxLayout, QWidget,
)

from .appearance import help_title_label
from .dynamic import dynamic_pivot, prepare_dynamic_frame
from .settings import get_settings


PLOT_WIDTH = 510
PLOT_HEIGHT = 330
PLOT_SPACING = 14
SERIES_STYLES = (
    ("#0072B2", "o"),
    ("#D55E00", "s"),
    ("#009E73", "t"),
    ("#CC79A7", "d"),
    ("#000000", "+"),
)


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
            return str(column)
        return str(self.frame.index[section])


class DynamicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, objectName="dynamicPage")
        self.frame = pd.DataFrame()
        self.selection = {}
        self.plots = []
        self.bar_items = []
        self.plot = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.addWidget(help_title_label(
            "Dynamic repeatability",
            "Rows are cycles, columns are Die Seq, and the last row is sample 3σ.",
        ))
        toolbar.addStretch()
        layout.addLayout(toolbar)

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
        self.pivot_model = DynamicPivotModel(self)
        self.table = QTableView()
        self.table.setModel(self.pivot_model)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setMinimumHeight(42)
        self.table.verticalHeader().setDefaultSectionSize(28)
        content_layout.addWidget(self.table, 1)

        dark = get_settings().get("theme") == "dark"
        self._plot_background = "#17121d" if dark else "#f8f7fa"
        self._plot_foreground = "#cfc4d5" if dark else "#5f5965"
        self.plot_scroll = QScrollArea(objectName="dynamicPlotScroll")
        self.plot_scroll.setWidgetResizable(False)
        self.plot_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.plot_scroll.setFixedHeight(PLOT_HEIGHT + 22)
        self.plot_host = QWidget(objectName="dynamicPlotHost")
        self.plot_layout = QHBoxLayout(self.plot_host)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.setSpacing(PLOT_SPACING)
        self.plot_scroll.setWidget(self.plot_host)
        content_layout.addWidget(self.plot_scroll)
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
        self._clear_plots()
        parameters = list(self.selection.get("metrics", ()))
        if not parameters:
            self.pivot_model.set_frame(pd.DataFrame())
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
            self.pivot_model.set_frame(pd.DataFrame())
            self.content.hide()
            self.message.setText(str(error))
            self.message.show()
            return

        combined = pd.concat(pivots, axis=1)
        self.pivot_model.set_frame(combined)
        if len(parameters) > 1:
            self._add_comparison_plot(parameters, pivots)
        for index, parameter in enumerate(parameters):
            self._add_parameter_plot(
                parameter, pivots[parameter], SERIES_STYLES[index % len(SERIES_STYLES)]
            )
        self.plot = self.plots[0]
        width = len(self.plots) * PLOT_WIDTH
        width += max(0, len(self.plots) - 1) * PLOT_SPACING
        self.plot_host.setFixedSize(width, PLOT_HEIGHT)
        self.plot_scroll.horizontalScrollBar().setValue(0)
        self.message.hide()
        self.content.show()

    def _clear_plots(self):
        self.bar_items = []
        self.plot = None
        while self.plot_layout.count():
            item = self.plot_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.deleteLater()
        self.plots = []

    def _new_plot(self, title):
        plot = pg.PlotWidget(background=self._plot_background)
        plot.setFixedSize(PLOT_WIDTH, PLOT_HEIGHT)
        plot.setLabel("bottom", "Die Seq")
        plot.setLabel("left", "3 Sigma (nm)")
        plot.getAxis("left").enableAutoSIPrefix(False)
        for axis_name in ("bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(self._plot_foreground))
            axis.setTextPen(pg.mkPen(self._plot_foreground))
        plot.showGrid(x=True, y=True, alpha=0.18)
        plot.setTitle(title)
        plot.setAccessibleName(f"Dynamic 3 Sigma — {title}")
        self.plot_layout.addWidget(plot)
        self.plots.append(plot)
        return plot

    @staticmethod
    def _set_die_ticks(plot, dies):
        x = np.arange(1, len(dies) + 1, dtype=float)
        plot.getAxis("bottom").setTicks([
            [(float(position), str(label)) for position, label in zip(x, dies)]
        ])
        return x

    def _add_comparison_plot(self, parameters, pivots):
        plot = self._new_plot(" + ".join(parameters))
        plot.addLegend(offset=(10, 8))
        dies = list(dict.fromkeys(
            die for parameter in parameters for die in pivots[parameter].columns
        ))
        x = self._set_die_ticks(plot, dies)
        group_width = 0.78
        bar_width = group_width / len(parameters)
        for index, parameter in enumerate(parameters):
            colour, symbol = SERIES_STYLES[index % len(SERIES_STYLES)]
            sigma = pivots[parameter].loc["3 Sigma"].reindex(dies).to_numpy(float)
            finite = np.isfinite(sigma)
            offset = (index - (len(parameters) - 1) / 2.0) * bar_width
            positions = x + offset
            bars = pg.BarGraphItem(
                x=positions[finite], height=sigma[finite], width=bar_width * 0.86,
                brush=pg.mkBrush(colour), pen=pg.mkPen(colour, width=1),
            )
            plot.addItem(bars)
            self.bar_items.append(bars)
            plot.plot(
                positions[finite], sigma[finite], pen=None, symbol=symbol,
                symbolSize=7, symbolBrush=colour,
                symbolPen=pg.mkPen(self._plot_foreground, width=1), name=parameter,
            )

    def _add_parameter_plot(self, parameter, pivot, style):
        colour, symbol = style
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
        plot.plot(
            x[finite], sigma[finite], pen=None, symbol=symbol, symbolSize=7,
            symbolBrush=colour, symbolPen=pg.mkPen(self._plot_foreground, width=1),
        )


__all__ = ["DynamicPage", "DynamicPivotModel"]

"""Qt page for Dynamic cycle tables and per-die 3σ bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QTableView, QVBoxLayout,
    QWidget,
)

from .appearance import help_title_label
from .dynamic import dynamic_pivot, prepare_dynamic_frame
from .settings import get_settings


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
            return str(self.frame.columns[section])
        return str(self.frame.index[section])


class DynamicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, objectName="dynamicPage")
        self.frame = pd.DataFrame()
        self.selection = {}
        self.bars = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.addWidget(help_title_label(
            "Dynamic repeatability",
            "Rows are cycles, columns are Die Seq, and the last row is sample 3σ.",
        ))
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Parameter"))
        self.parameter = QComboBox(objectName="dynamicParameter")
        self.parameter.currentTextChanged.connect(self.refresh)
        toolbar.addWidget(self.parameter)
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(28)
        content_layout.addWidget(self.table, 1)
        dark = get_settings().get("theme") == "dark"
        background = "#17121d" if dark else "#f8f7fa"
        foreground = "#cfc4d5" if dark else "#5f5965"
        self.plot = pg.PlotWidget(background=background)
        self.plot.setMinimumHeight(280)
        self.plot.setLabel("bottom", "Die Seq")
        self.plot.setLabel("left", "3 Sigma (nm)")
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(foreground))
            axis.setTextPen(pg.mkPen(foreground))
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        content_layout.addWidget(self.plot, 1)
        layout.addWidget(self.content, 1)
        self.content.hide()

    def set_input(self, frame, selection):
        self.frame = pd.DataFrame(frame).copy()
        self.selection = dict(selection)
        metrics = list(selection.get("metrics", ()))
        current = self.parameter.currentText()
        self.parameter.blockSignals(True)
        self.parameter.clear()
        self.parameter.addItems(metrics)
        if current in metrics:
            self.parameter.setCurrentText(current)
        self.parameter.blockSignals(False)
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
        self.plot.clear()
        self.bars = None
        parameter = self.parameter.currentText()
        if not parameter:
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
            pivot = dynamic_pivot(prepared, parameter)
        except ValueError as error:
            self.pivot_model.set_frame(pd.DataFrame())
            self.content.hide()
            self.message.setText(str(error))
            self.message.show()
            return
        self.pivot_model.set_frame(pivot)
        sigma = pivot.loc["3 Sigma"].to_numpy(float)
        x = np.arange(1, len(sigma) + 1, dtype=float)
        finite = np.isfinite(sigma)
        self.bars = pg.BarGraphItem(
            x=x[finite], height=sigma[finite], width=0.72,
            brush=pg.mkBrush("#5b9bd5"), pen=pg.mkPen("#3f78ad", width=1),
        )
        self.plot.addItem(self.bars)
        self.plot.getAxis("bottom").setTicks([
            [(float(position), str(label))
             for position, label in zip(x, pivot.columns)]
        ])
        self.plot.setTitle(parameter)
        self.message.hide()
        self.content.show()


__all__ = ["DynamicPage", "DynamicPivotModel"]

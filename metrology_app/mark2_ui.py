"""Mark2 label selection: checked fields ordered from outer to inner."""
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                             QLabel, QListWidget, QListWidgetItem, QVBoxLayout)

from .mark2 import MAX_METRIC_FIELDS, config


class _HierarchyFields(QListWidget):
    def __init__(self, options, selected):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for key in [*selected, *(key for key in options if key not in selected)]:
            item = QListWidgetItem(options[key], self)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)

    def selection(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())
                if self.item(i).checkState() == Qt.CheckState.Checked]


class Mark2Dialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage groups Mark2")
        self.resize(470, 480)
        self.state = config(state)
        layout = QVBoxLayout(self)
        note = QLabel("Check one or more label fields. Drag to set the hierarchy,\n"
                      "from outermost (top) to innermost (bottom).")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.fields = _HierarchyFields({name: name for name in self.state["columns"]}, self.state["selected"])
        layout.addWidget(self.fields, 1)
        layout.addWidget(QLabel("Plot order"))
        self.order = QComboBox()
        self.order.addItem("Source Raw table order", "source")
        self.order.addItem("Selected hierarchy order", "hierarchy")
        self.order.setCurrentIndex(self.order.findData(self.state["order_mode"]))
        self.order.setToolTip("Hierarchy order sorts by checked labels from top to bottom; equal labels retain source order.")
        layout.addWidget(self.order)
        self.status = QLabel("Click OK to apply these settings and refresh all plots.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.fields.itemChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.selection()))

    def selection(self):
        return self.fields.selection()

    def settings(self):
        return {**self.state, "selected": self.selection(), "order_mode": self.order.currentData()}


class MetricsClassificationDialog(QDialog):
    def __init__(self, columns, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom classification")
        self.resize(470, 420)
        options = {None: "Wafer", **{name: f"Mark2 · {name}" for name in columns}}
        selected = [field for field in selected if field in options] or [None]
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.fields = _HierarchyFields(options, selected)
        layout.addWidget(self.fields, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.fields.itemChanged.connect(self._validate)
        self._validate()

    def _validate(self, item=None):
        selected = self.fields.selection()
        limit = MAX_METRIC_FIELDS
        if len(selected) > limit:
            with QSignalBlocker(self.fields):
                item.setCheckState(Qt.CheckState.Unchecked)
            self.status.setText(f"Up to {limit} fields. Uncheck a field before selecting another.")
        else:
            self.status.setText(f"Check up to {limit} fields and drag them from outermost (top) to innermost (bottom).")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(selected))

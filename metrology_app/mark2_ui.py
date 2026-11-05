"""Mark2 label selection: checked fields ordered from outer to inner."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                             QLabel, QListWidget, QListWidgetItem, QVBoxLayout)

from .mark2 import config


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
        self.fields = QListWidget()
        self.fields.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        selected = self.state["selected"]
        for name in selected + [c for c in self.state["columns"] if c not in selected]:
            item = QListWidgetItem(name, self.fields)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked)
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
        return [self.fields.item(i).text() for i in range(self.fields.count())
                if self.fields.item(i).checkState() == Qt.CheckState.Checked]

    def settings(self):
        return {**self.state, "selected": self.selection(), "order_mode": self.order.currentData()}

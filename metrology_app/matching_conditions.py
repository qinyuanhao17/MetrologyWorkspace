"""Two ordered, checkable source-field lists for Type2 composite IDs."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                            QListWidget, QListWidgetItem, QVBoxLayout, QWidget)


class MatchingConditions(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.lists = {}
        for side, title in (("reference", "Reference matching fields"), ("raw", "Raw Data matching fields")):
            card = QFrame(objectName="card")
            column = QVBoxLayout(card)
            column.addWidget(QLabel(title))
            fields = QListWidget()
            fields.setAccessibleName(title)
            fields.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            fields.setDefaultDropAction(Qt.DropAction.MoveAction)
            fields.setMinimumHeight(100)
            fields.setMaximumHeight(150)
            fields.setToolTip("Check ID fields; drag rows up/down. Checked fields pair left-to-right in displayed order.")
            fields.itemChanged.connect(self._changed)
            fields.model().rowsMoved.connect(self._changed)
            column.addWidget(fields)
            row.addWidget(card, 1)
            self.lists[side] = fields
        layout.addLayout(row)
        self.status = QLabel("Choose corresponding fields in the same order on both sides.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _changed(self, *_):
        if not self._updating:
            self.changed.emit()

    def selection(self):
        return {side: [fields.item(i).data(Qt.ItemDataRole.UserRole) for i in range(fields.count())
                       if fields.item(i).checkState() == Qt.CheckState.Checked]
                for side, fields in self.lists.items()}

    def set_fields(self, reference, raw, selected):
        self._updating = True
        try:
            for side, columns in (("reference", reference), ("raw", raw)):
                fields = self.lists[side]
                previous = [fields.item(i).data(Qt.ItemDataRole.UserRole) for i in range(fields.count())]
                chosen = selected[side]
                # Selected order is authoritative after a restore; keep other rows stable on edits.
                order = list(dict.fromkeys([*chosen, *previous, *map(str, columns)]))
                order = [name for name in order if name in columns or name in chosen]
                fields.clear()
                for name in order:
                    item = QListWidgetItem(name if name in columns else name + " (missing)")
                    item.setData(Qt.ItemDataRole.UserRole, name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                    item.setCheckState(Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked)
                    fields.addItem(item)
        finally:
            self._updating = False

"""Paste and preview wafer-level aliases before applying them."""
from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .sheet import clipboard_rows
from .wafer_id_mapping import parse_wafer_id_list


_HEADERS = ("Original Wafer ID", "New Wafer ID")


def _configure_table(table):
    table.setHorizontalHeaderLabels(_HEADERS)
    table.horizontalHeader().setStretchLastSection(True)
    table.setColumnWidth(0, 136)
    table.setAlternatingRowColors(True)


class _WaferIdListTable(QTableWidget):
    paste_error = pyqtSignal(str)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_list(QApplication.clipboard().text())
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            with QSignalBlocker(self):
                for item in self.selectedItems():
                    item.setText("")
            self.cellChanged.emit(self.currentRow(), self.currentColumn())
        else:
            super().keyPressEvent(event)

    def paste_list(self, text):
        rows = clipboard_rows(text)
        while rows and not any(cell.strip() for cell in rows[-1]):
            rows.pop()
        if not rows:
            return
        if any(len(row) > 2 for row in rows):
            self.paste_error.emit("Copy only the two Wafer ID columns and paste again.")
            return
        if tuple(cell.strip().casefold() for cell in rows[0]) == tuple(h.casefold() for h in _HEADERS):
            rows.pop(0)
        with QSignalBlocker(self):
            self.clearContents()
            self.setRowCount(max(12, len(rows)))
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    self.setItem(row, column, QTableWidgetItem(value))
        self.cellChanged.emit(0, 0)

    def values(self):
        return [(self.item(row, 0).text() if self.item(row, 0) is not None else "",
                 self.item(row, 1).text() if self.item(row, 1) is not None else "")
                for row in range(self.rowCount())]


class WaferIdListDialog(QDialog):
    def __init__(self, source_ids, apply_aliases, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste Wafer ID List")
        self.resize(760, 450)
        self._source_ids = source_ids
        self._apply_aliases = apply_aliases

        layout = QVBoxLayout(self)
        panels = QHBoxLayout()
        layout.addLayout(panels, 1)
        example_panel = QVBoxLayout()
        panels.addLayout(example_panel, 1)
        example_panel.addWidget(QLabel("Example"))
        example = QTableWidget(2, 2)
        _configure_table(example)
        example.setMinimumWidth(280)
        example.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        example.verticalHeader().hide()
        for row, pair in enumerate((("XFP11558.03", "X1U483#03"), ("X1K860#01", "X1K860#01"))):
            for column, value in enumerate(pair):
                example.setItem(row, column, QTableWidgetItem(value))
        example.ensurePolished()
        example.resizeRowsToContents()
        example.setFixedHeight(example.horizontalHeader().sizeHint().height()
                               + example.verticalHeader().length() + 2 * example.frameWidth() + 30)
        example_panel.addWidget(example)
        note = QLabel("Copy two columns from Excel and press Ctrl+V in the table, with or without the headers shown above. "
                      "Apply replaces the current mapping. Raw wafers missing from the list keep their original IDs.")
        note.setWordWrap(True)
        example_panel.addWidget(note)
        example_panel.addStretch()

        input_panel = QVBoxLayout()
        panels.addLayout(input_panel, 2)
        input_panel.addWidget(QLabel("Wafer ID List"))
        self.table = _WaferIdListTable(12, 2)
        _configure_table(self.table)
        input_panel.addWidget(self.table)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.cellChanged.connect(self._validate)
        self.table.paste_error.connect(self._invalid)
        self.table.setCurrentCell(0, 0)
        self.table.setFocus()
        self._validate()

    def _invalid(self, message):
        self.status.setText(message)
        self.apply_button.setEnabled(False)

    def _validate(self):
        try:
            self._aliases = parse_wafer_id_list(self.table.values())
        except ValueError as error:
            self._invalid(str(error))
            return
        if not self._aliases:
            self._invalid("Paste a Wafer ID list to preview the mapping.")
            return
        matched = self._source_ids.intersection(self._aliases)
        changed = sum(self._aliases[old] != old for old in matched)
        missing = len(self._aliases) - len(matched)
        self.status.setText(f"{changed:,} wafers will be renamed · "
                            f"{len(self._source_ids) - changed:,} will keep their original ID · "
                            f"{missing:,} list entries were not found in Raw Data")
        self.apply_button.setEnabled(True)

    def _apply(self):
        self._validate()
        if not self.apply_button.isEnabled():
            return
        try:
            self._apply_aliases(self._aliases)
        except ValueError as error:
            self._invalid(str(error))
            return
        self.accept()

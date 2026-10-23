"""Choose visible report sheets; calculation dependencies remain hidden."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                            QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)


class ExportSheetDialog(QDialog):
    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Select output sheets')
        self.resize(540, 480)
        layout = QVBoxLayout(self)
        note = QLabel('Choose visible output sheets. Required formula source sheets are kept hidden.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.sheets = QListWidget()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.sheets.addItem(item)
        layout.addWidget(self.sheets)
        tools = QHBoxLayout()
        for text, state in (('All', Qt.CheckState.Checked), ('None', Qt.CheckState.Unchecked)):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, value=state: self.set_all(value))
            tools.addWidget(button)
        tools.addStretch()
        layout.addLayout(tools)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.sheets.itemChanged.connect(self.update_accept)
        layout.addWidget(self.buttons)
        self.update_accept()

    def selected_sheets(self):
        return [self.sheets.item(i).text() for i in range(self.sheets.count())
                if self.sheets.item(i).checkState() == Qt.CheckState.Checked]

    def set_all(self, state):
        for i in range(self.sheets.count()):
            self.sheets.item(i).setCheckState(state)

    def update_accept(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.selected_sheets()))


def choose_export_sheets(parent, names):
    dialog = ExportSheetDialog(names, parent)
    try:
        return dialog.selected_sheets() if dialog.exec() == QDialog.DialogCode.Accepted else None
    finally:
        dialog.deleteLater()

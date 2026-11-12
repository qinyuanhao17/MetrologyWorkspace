"""Compact classification editor shared by analytical windows."""
import re
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QTableView,
                            QVBoxLayout, QHBoxLayout, QSizePolicy, QHeaderView)

from .appearance import fit_window_to_screen
from .match_groups import normalized


class GroupDetailsModel(QAbstractTableModel):
    headers = ('Wafer ID','Lot ID','PAD Name','Die Seq','TestFlag','Head','Mark','Group')

    def __init__(self, controls, sources, parent=None):
        super().__init__(parent)
        self.controls = controls
        columns = {normalized(c):c for c in sources}
        self.identities = [[str(row.get(columns.get(c),'')) for c in ('waferid','lotid','padname','dieseq')]
                           for row in sources.to_dict('records')]
        controls.order_model.dataChanged.connect(self.refresh)
        controls.order_model.modelReset.connect(self.refresh)

    def refresh(self, *_):
        if self.identities:
            self.dataChanged.emit(self.index(0,4),self.index(len(self.identities)-1,7))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.identities)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section] if orientation == Qt.Orientation.Horizontal else str(section+1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if index.column() < 4:
            return self.identities[index.row()][index.column()] if role in (
                Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.EditRole,Qt.ItemDataRole.ToolTipRole) else None
        model = self.controls.order_model
        return model.data(model.index(index.row()+1,index.column()-4),role)

    def flags(self, index):
        value = super().flags(index)
        return value | Qt.ItemFlag.ItemIsEditable if index.column() == 4 else value

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 4 and role == Qt.ItemDataRole.EditRole:
            text = str(value).strip()
            if not re.fullmatch(r'[+-]?\d+',text):
                return False
            model = self.controls.order_model
            return model.setData(model.index(index.row()+1,0),str(int(text)),role)
        return False


class GroupSettingsDialog(QDialog):
    def __init__(self, owner, controls, title, *, trend=True, hint='TestFlag is editable; Head / Mark / Group are calculated.'):
        super().__init__(owner)
        self.setWindowTitle(title)
        self.setSizeGripEnabled(True)
        self.controls = controls
        layout = QVBoxLayout(self)
        form = controls.layout().itemAt(0).layout()
        if not trend:
            form.setRowVisible(controls.order,False)
            form.setRowVisible(controls.group_order_button,False)
        form.takeRow(0)
        form.takeRow(0)
        classification = QHBoxLayout()
        for widget in (controls.enabled,controls.names_button,controls.mark_enabled,controls.new_button):
            classification.addWidget(widget)
        classification.addStretch(1)
        controls.layout().insertLayout(0,classification)
        controls.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        controls.layout().removeWidget(controls.status)
        layout.addWidget(controls)
        note = QLabel(hint,objectName='hint')
        layout.addWidget(note)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table,1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(controls.apply_button,QDialogButtonBox.ButtonRole.ApplyRole)
        buttons.rejected.connect(self.close)
        footer = QHBoxLayout()
        footer.addWidget(controls.status,1)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        fit_window_to_screen(self,(1000,640),minimum=(650,380))

    def set_rows(self, sources):
        previous = self.table.model()
        model = GroupDetailsModel(self.controls,sources,self.table)
        self.table.setModel(model)
        if previous is not None:
            previous.deleteLater()
        for column,width in enumerate((150,140,130,70,80,110,110)):
            self.table.setColumnWidth(column,width)
        return model

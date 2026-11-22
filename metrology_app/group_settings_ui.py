"""Compact classification editor shared by analytical windows."""
import re
from functools import partial
from types import SimpleNamespace

from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, QTimer, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel,
                            QVBoxLayout, QHBoxLayout, QSizePolicy, QHeaderView, QLineEdit,
                            QListWidget, QListWidgetItem, QMessageBox, QPushButton, QToolButton)

from .appearance import fit_window_to_screen
from .match_groups import flag_value, normalized
from .sheet import clipboard_rows
from .table_clipboard import attach_copy_feedback
from .table_selection import RangeSelectionTableView


def _natural(value):
    return tuple(int(part) if part.isdigit() else part.casefold()
                 for part in re.split(r"(\d+)", str(value)))


class ColumnValueFilterDialog(QDialog):
    """Excel-style multi-value filter for one identity column."""
    def __init__(self, parent, title, values, selected=None):
        super().__init__(parent)
        self.setWindowTitle(f"Filter {title}")
        self.resize(330, 470)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(placeholderText=f"Search {title}…")
        layout.addWidget(self.search)
        self.values = QListWidget()
        selected = set(values) if selected is None else set(selected)
        for value in values:
            item = QListWidgetItem(value or "(Blank)")
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked)
            self.values.addItem(item)
        layout.addWidget(self.values, 1)
        controls = QHBoxLayout()
        all_button = QPushButton("Select All")
        none_button = QPushButton("Clear")
        all_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        none_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        controls.addWidget(all_button)
        controls.addWidget(none_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._filter_items)

    def _filter_items(self, text):
        query = text.strip().casefold()
        for row in range(self.values.count()):
            item = self.values.item(row)
            item.setHidden(query not in item.text().casefold())

    def _set_all(self, state):
        for row in range(self.values.count()):
            if not self.values.item(row).isHidden():
                self.values.item(row).setCheckState(state)

    def selected_values(self):
        return tuple(self.values.item(row).data(Qt.ItemDataRole.UserRole)
                     for row in range(self.values.count())
                     if self.values.item(row).checkState() == Qt.CheckState.Checked)


class ExcelHeaderFilters(QObject):
    """Place compact filter arrows on selected table columns."""
    def __init__(self, table, columns, parent=None):
        super().__init__(parent or table)
        self.table = table
        self.header = table.horizontalHeader()
        self.columns = tuple(columns)
        self.buttons = {}
        for column in self.columns:
            button = QToolButton(self.header.viewport())
            button.setText("▾")
            button.setAutoRaise(True)
            button.setFixedSize(18, 18)
            button.setToolTip("Filter by value")
            button.clicked.connect(partial(self.open_filter, column))
            self.buttons[column] = button
        self.header.sectionResized.connect(self.position_buttons)
        self.header.sectionMoved.connect(self.position_buttons)
        self.header.installEventFilter(self)
        table.horizontalScrollBar().valueChanged.connect(self.position_buttons)
        table.model().modelReset.connect(self.position_buttons)
        QTimer.singleShot(0, self.position_buttons)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show) and watched is getattr(self, "header", None):
            self.position_buttons()
        return False

    def position_buttons(self, *_):
        count = self.table.model().columnCount() if self.table.model() is not None else 0
        for column, button in self.buttons.items():
            visible = column < count and not self.header.isSectionHidden(column)
            button.setVisible(visible)
            if visible:
                x = self.header.sectionViewportPosition(column) + self.header.sectionSize(column) - 20
                button.move(max(self.header.sectionViewportPosition(column) + 2, x), 2)
        self._mark_active()

    def _mark_active(self):
        model = self.table.model()
        for column, button in self.buttons.items():
            active = hasattr(model, "filter_for") and model.filter_for(column) is not None
            button.setStyleSheet("color:#1665c0;font-weight:700;" if active else "")

    def open_filter(self, column):
        model = self.table.model()
        if not hasattr(model, "set_column_filter"):
            return
        dialog = ColumnValueFilterDialog(self.table.window(), model.headers[column],
                                         model.distinct_values(column), model.filter_for(column))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selected_values()
            available = set(model.distinct_values(column))
            model.set_column_filter(column, None if set(selected) == available else selected)


class _MatchFlagAdapter:
    """Expose selected Match rows through TestFlagDialog's generic interface."""
    def __init__(self, controls, rows):
        frame = controls.raw
        columns = {normalized(column): index for index, column in enumerate(frame.columns)}
        names = (("waferid", "wafer", "waferno"), ("lotid", "lot", "lotno"),
                 ("padname", "pad", "slot"), ("dieseq", "diesequence"))
        positions = [next((columns[name] for name in aliases if name in columns), None)
                     for aliases in names]
        flags = controls.flags_frame()
        records = []
        self.test_flags = {}
        for row in rows:
            if not 0 <= row < len(frame):
                continue
            values = ["" if column is None else str(frame.iat[row, column])
                      for column in positions]
            identity = SimpleNamespace(wafer=values[0], lot=values[1], tool_sn="",
                                       pad=values[2], die_seq=values[3])
            records.append(SimpleNamespace(key=row, identity=identity))
            self.test_flags[row] = (int(flag_value(flags.iat[row, 0]))
                                    if row < len(flags) else 0)
        self.catalog = SimpleNamespace(spectra=tuple(records))
        self.records = tuple(records)
        self.test_flag_values = [int(value) for value in controls.test_flag_values()]
        self.test_flag_grouping = ["wafer", "lot", "pad"]


class GroupDetailsModel(QAbstractTableModel):
    headers = ('Wafer ID','Lot ID','PAD Name','Die Seq','TestFlag','Head','Mark','Group')
    uniform_selection_flags = True

    def __init__(self, controls, sources, parent=None, *, number_source_rows=True):
        super().__init__(parent)
        self.controls = controls
        self.number_source_rows = number_source_rows
        self.sources = None
        self.rows = ()
        self._source_rows = ()
        self.filters = {}
        self.identities = []
        self.set_rows(sources)
        controls.order_model.dataChanged.connect(self.refresh)
        controls.order_model.modelReset.connect(self.refresh)

    def set_rows(self, sources, rows=None):
        rows = range(len(sources)) if rows is None else rows if isinstance(rows, range) else tuple(rows)
        rows = tuple(rows)
        if self.sources is sources and self._source_rows == rows:
            return
        self.beginResetModel()
        if self.sources is not sources:
            self.sources = sources
            columns = {normalized(column): index for index, column in enumerate(sources.columns)}
            fields = (('waferid', 'wafer', 'waferno'), ('lotid', 'lot', 'lotno'),
                      ('padname', 'pad', 'slot'), ('dieseq', 'diesequence'))
            headers = [next((columns[name] for name in aliases if name in columns), None) for aliases in fields]
            self.identities = [None if column is None else sources.iloc[:, column].fillna("").astype(str).to_numpy()
                               for column in headers]
        self._source_rows = rows
        self.rows = self._filtered_rows()
        self.endResetModel()

    def _filtered_rows(self):
        rows = self._source_rows
        for column, allowed in self.filters.items():
            rows = tuple(row for row in rows
                         if str(self._value(row, column, Qt.ItemDataRole.DisplayRole)) in allowed)
        return rows

    def distinct_values(self, column):
        if not 0 <= column < len(self.headers):
            return ()
        return tuple(sorted({str(self._value(row, column, Qt.ItemDataRole.DisplayRole))
                             for row in self._source_rows},
                            key=_natural))

    def filter_for(self, column):
        return self.filters.get(column)

    def set_column_filter(self, column, values):
        self.beginResetModel()
        if values is None:
            self.filters.pop(column, None)
        else:
            self.filters[column] = frozenset(str(value) for value in values)
        self.rows = self._filtered_rows()
        self.endResetModel()

    def clear_filters(self):
        if not self.filters:
            return
        self.beginResetModel()
        self.filters.clear()
        self.rows = self._filtered_rows()
        self.endResetModel()

    def source_row(self, row):
        return self.rows[row]

    def refresh(self, *_):
        if self.filters:
            rows = self._filtered_rows()
            if rows != self.rows:
                self.beginResetModel()
                self.rows = rows
                self.endResetModel()
            elif self.rows:
                self.dataChanged.emit(self.index(0, 4), self.index(len(self.rows) - 1, 7))
        elif self.rows:
            self.dataChanged.emit(self.index(0,4),self.index(len(self.rows)-1,7))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.headers[section]
            return str((self.source_row(section) if self.number_source_rows else section) + 1)

    def _value(self, row, column, role=Qt.ItemDataRole.DisplayRole):
        if column < 4:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
                values = self.identities[column]
                return "" if values is None or row >= len(values) else values[row]
            return None
        model = self.controls.order_model
        return model.data(model.index(row + 1, column - 4), role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        return self._value(self.source_row(index.row()), index.column(), role)

    def flags(self, index):
        value = super().flags(index)
        return value | Qt.ItemFlag.ItemIsEditable if index.column() == 4 else value

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 4 and role == Qt.ItemDataRole.EditRole:
            try:
                text = flag_value(value)
            except ValueError:
                return False
            if text not in self.controls.test_flag_values():
                return False
            model = self.controls.order_model
            return model.setData(model.index(self.source_row(index.row())+1,0),text,role)
        return False


class _GroupDetailsView(RangeSelectionTableView):
    @staticmethod
    def _flag_rows(view):
        rows = set()
        for selected in view.selectionModel().selection():
            if selected.left() <= 4 <= selected.right():
                rows.update(range(selected.top(), selected.bottom() + 1))
        index = view.currentIndex()
        if not rows and index.isValid() and index.column() == 4:
            rows.add(index.row())
        return sorted(rows)

    def keyPressEvent(self, event):
        rows = self._flag_rows(self)
        if rows and event.matches(QKeySequence.StandardKey.Paste):
            model = self.model()
            clip = clipboard_rows(QApplication.clipboard().text())
            allowed = set(model.controls.test_flag_values())
            try:
                values = [flag_value(row[0]) for row in clip if row]
                invalid = [value for value in values if value not in allowed]
                if invalid:
                    raise ValueError("Choose an existing Test Flag: " + ", ".join(sorted(allowed)))
                changes = {(model.source_row(row) + 1, 0): value
                           for row, value in zip(rows, values)}
            except ValueError as error:
                QMessageBox.warning(self, "Cannot paste Test Flags", str(error))
            else:
                if changes:
                    model.controls.order_model.edit(changes)
            event.accept()
            return
        text = event.text().strip()
        if rows and re.fullmatch(r"[+-]?\d+", text):
            value = flag_value(text)
            if value not in self.model().controls.test_flag_values():
                QMessageBox.warning(
                    self, "Cannot set Test Flag",
                    "Choose an existing Test Flag: "
                    + ", ".join(self.model().controls.test_flag_values()))
            else:
                source_rows = [self.model().source_row(row) for row in rows]
                self.model().controls.set_test_flags(source_rows, value)
            event.accept()
            return
        super().keyPressEvent(event)


class GroupSettingsDialog(QDialog):
    def __init__(self, owner, controls, title, *, trend=True, number_source_rows=True,
                 hint='TestFlag is editable; Head / Mark / Group are calculated.', **kwargs):
        super().__init__(owner, **kwargs)
        self.setWindowTitle(title)
        self.setSizeGripEnabled(True)
        self.controls = controls
        self.number_source_rows = number_source_rows
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
        self.set_flags_button = QPushButton('Set Test Flag…')
        flag_editor = getattr(owner, 'open_test_flags', None)
        if callable(flag_editor) and getattr(owner, 'workspace_type', None) == 'spectra_viewer':
            # Spectra Viewer owns flag definitions and assignments globally;
            # Match Workbook uses the selected rows in this dialog instead.
            self.flag_menu = None
            self.set_flags_button.clicked.connect(flag_editor)
        elif (callable(getattr(controls, 'test_flag_values', None))
                and callable(getattr(controls, 'set_test_flags', None))):
            self.flag_menu = None
            self.set_flags_button.clicked.connect(self.choose_test_flag)
        else:
            self.flag_menu = None
            self.set_flags_button.setEnabled(False)
        classification.addWidget(self.set_flags_button)
        classification.addStretch(1)
        controls.layout().insertLayout(0,classification)
        controls.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        controls.layout().removeWidget(controls.status)
        layout.addWidget(controls)
        note = QLabel(hint,objectName='hint')
        layout.addWidget(note)
        self.table = _GroupDetailsView()
        self.table.copy_headers_for_full_columns = True
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(self.table.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionsClickable(True)
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
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        fit_window_to_screen(self,(1000,640),minimum=(650,380))

    def selected_source_rows(self):
        model = self.table.model()
        if model is None:
            return set()
        return {model.source_row(row)
                for selected in self.table.selectionModel().selection()
                for row in range(selected.top(), selected.bottom() + 1)}

    def choose_test_flag(self):
        if not len(self.controls.raw):
            QMessageBox.information(self, "Set Test Flag", "There are no measurement sets to assign.")
            return
        from .spectra_info_ui import TestFlagDialog
        adapter = _MatchFlagAdapter(self.controls, range(len(self.controls.raw)))
        dialog = TestFlagDialog(adapter, parent=self, records=adapter.records)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controls.set_test_flag_assignments(dialog.assignments)

    def apply_test_flag(self, value):
        rows = self.selected_source_rows()
        if rows and str(value) in self.controls.test_flag_values():
            self.controls.set_test_flags(rows, value)

    def set_rows(self, sources, rows=None):
        model = self.table.model()
        if model is None:
            model = GroupDetailsModel(self.controls, sources, self.table, number_source_rows=self.number_source_rows)
            self.table.setModel(model)
            self.header_filters = ExcelHeaderFilters(self.table, range(len(GroupDetailsModel.headers)))
            attach_copy_feedback(self.table)
            for column,width in enumerate((150,140,130,70,80,110,110)):
                self.table.setColumnWidth(column,width)
        model.set_rows(sources, rows)
        return model

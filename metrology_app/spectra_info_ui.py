"""Spectra Info tables and local Test Flag assignment."""
from collections import defaultdict
import re

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                            QHeaderView, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem,
                            QMainWindow, QMessageBox, QMenu, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
                            QVBoxLayout, QWidget)

from .appearance import fit_window_to_screen
from .settings import apply_theme
from .spectra_info import INFO_COLUMNS, REQUIRED_REPORT_COLUMNS
from .table_clipboard import attach_copy_feedback
from .table_selection import RangeSelectionTableView
from .widgets import CheckableListWidget, ScrollSafeComboBox


class SpectraInfoWindow(QMainWindow):
    def __init__(self, viewer):
        super().__init__(viewer, Qt.WindowType.Window)
        from .matching_window import DataFrameModel
        owner = self

        class InfoModel(DataFrameModel):
            def flags(self, index):
                flags = super().flags(index)
                if index.isValid() and self.frame.columns[index.column()] == "Test Flag":
                    flags |= Qt.ItemFlag.ItemIsEditable
                return flags

            def data(self, index, role=Qt.ItemDataRole.DisplayRole):
                if role == Qt.ItemDataRole.EditRole and index.isValid():
                    return str(self.frame.iat[index.row(), index.column()])
                return super().data(index, role)

            def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
                if (role != Qt.ItemDataRole.EditRole or not index.isValid()
                        or not self.flags(index) & Qt.ItemFlag.ItemIsEditable):
                    return False
                if not owner.edit_flag(index.row(), value):
                    return False
                self.frame["Test Flag"] = self.frame["Test Flag"].astype(object)
                self.frame.iat[index.row(), index.column()] = int(str(value).strip())
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
                return True
        self.viewer = viewer
        viewer.add_edit_history_actions(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Spectra Info")
        fit_window_to_screen(self, (1250, 730), minimum=(750, 450))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        tools = QHBoxLayout()
        self.status = QLabel()
        tools.addWidget(self.status, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        tools.addWidget(refresh)
        self.columns_button = QPushButton("Choose Columns…", objectName="spectraInfoChooseColumns")
        self.columns_button.clicked.connect(self.open_column_picker)
        tools.addWidget(self.columns_button)
        self.copy_button = QPushButton("Copy Table")
        self.export_button = QPushButton("Export CSV…", objectName="primary")
        self.copy_button.clicked.connect(self.copy_table)
        self.export_button.clicked.connect(self.choose_export)
        tools.addWidget(self.copy_button)
        tools.addWidget(self.export_button)
        layout.addLayout(tools)
        self.tabs = QTabWidget()
        self.models, self.tables = [], []
        self.column_picker = None
        for tab, title in enumerate(("Spectra Info", "With Test Flag", "XY")):
            table = RangeSelectionTableView()
            table.copy_headers_for_full_columns = True
            model = InfoModel(parent=self)
            table.setModel(model)
            table.setAlternatingRowColors(True)
            table.setSortingEnabled(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().setDefaultSectionSize(135)
            header = table.horizontalHeader()
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(
                lambda point, i=tab, h=header: self.build_column_menu(
                    i, h.logicalIndexAt(point), header=True).exec(h.mapToGlobal(point)))
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(
                lambda point, i=tab, t=table: self.build_column_menu(i, t.indexAt(point).column()).exec(t.viewport().mapToGlobal(point)))
            attach_copy_feedback(table)
            self.models.append(model)
            self.tables.append(table)
            self.tabs.addTab(table, title)
        layout.addWidget(self.tabs, 1)
        self.issues = QTreeWidget()
        self.issues.setHeaderLabels(["Matching issues — export/copy blocked until resolved"])
        self.issues.setMaximumHeight(170)
        self.issues.setRootIsDecorated(False)
        layout.addWidget(self.issues)
        apply_theme(self)
        self.refresh()

    def refresh(self):
        try:
            self.result = self.viewer.spectra_info()
            frames = (self.result.without_flags, self.result.with_flags, self.result.xy)
            problems = self.result.issues
        except ValueError as error:
            import pandas as pd
            self.result = None
            frames, problems = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame()), (str(error),)
        self.source_columns = [tuple(frame.columns) for frame in frames]
        if self.result is not None:
            self.source_columns[0] = (*INFO_COLUMNS, *self.result.available_reference_columns)
        for tab, (model, table, frame) in enumerate(zip(self.models, self.tables, frames)):
            frame = frame.drop(columns=list(self.viewer.info_deleted_columns[tab]), errors="ignore")
            if not model.frame.equals(frame):
                model.set_frame(frame)
            signature = "|".join(frame.columns)
            if table.property("spectraInfoColumns") != signature:
                widths = {"Time": 185, "Die Seq": 70, "Tool SN": 90, "Type": 90,
                          "Relative Column": 110, "Relative Row": 110, "Test Flag": 80,
                          "FIELD X": 90, "FIELD Y": 90, "X(mm)": 110, "Y(mm)": 110}
                for column, name in enumerate(frame.columns):
                    table.setColumnWidth(column, widths.get(name, 135))
                table.setProperty("spectraInfoColumns", signature)
            # Invalid pairings must not be copied through Ctrl+C either.
            table.setEnabled(not problems)
        self.problems = problems
        self.issues.clear()
        for issue in problems:
            self.issues.addTopLevelItem(QTreeWidgetItem([issue]))
        self.issues.setVisible(bool(problems))
        self.copy_button.setEnabled(not problems)
        self.export_button.setEnabled(not problems)
        order = ("original Raw Data order" if self.result is not None and self.result.raw_order
                 else "natural Wafer / Lot / PAD / Die / Time order")
        self.status.setText(f"{len(frames[0]):,} visible rows · {order}"
                            + (f" · {len(problems)} matching issues" if problems else ""))

    def build_column_menu(self, tab, column, *, header=False):
        menu = QMenu(self)
        frame = self.models[tab].frame
        if 0 <= column < len(frame.columns):
            selected = [index.column() for index in self.tables[tab].selectionModel().selectedColumns()]
            columns = sorted(selected) if column in selected else [column]
            names = [frame.columns[i] for i in columns if frame.columns[i] not in REQUIRED_REPORT_COLUMNS]
            if names:
                menu.addAction("Delete Column" if len(names) == 1 else "Delete Columns",
                               lambda: self.viewer.delete_info_columns(tab, names))
            if header:
                copy = menu.addAction("Copy Column" if len(columns) == 1 else "Copy Columns",
                                      lambda: self._copy_frame(frame.iloc[:, columns]))
                copy.setEnabled(not self.problems)
        hidden = self.viewer.info_deleted_columns[tab]
        if hidden:
            restore = menu.addMenu("Restore Columns")
            restore.addAction("Restore All Columns", lambda: self.viewer.restore_info_columns(tab, hidden))
            restore.addSeparator()
            for name in sorted(hidden, key=str.casefold):
                restore.addAction(name, lambda _checked=False, column=name: self.viewer.restore_info_columns(tab, (column,)))
        menu.addAction("Choose Columns…", self.open_column_picker)
        menu.addSeparator()
        menu.addAction(self.undo_action)
        menu.addAction(self.redo_action)
        return menu

    def open_column_picker(self):
        if self.column_picker is not None:
            self.column_picker.raise_()
            return self.column_picker
        dialog = self.column_picker = QDialog(self, objectName="spectraInfoColumnPicker")
        dialog.setWindowTitle("Choose Spectra Info columns")
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        lists = {}
        visible = {tab: set(self.models[tab].frame.columns) for tab in (0, 2)}
        for tab in (0, 2):
            choices = CheckableListWidget()
            for name in dict.fromkeys(self.source_columns[tab]):
                item = QListWidgetItem(name)
                if name in REQUIRED_REPORT_COLUMNS:
                    item.setCheckState(Qt.CheckState.Checked)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip("Required column")
                else:
                    item.setCheckState(Qt.CheckState.Checked if name in visible[tab] else Qt.CheckState.Unchecked)
                choices.addItem(item)
            tabs.addTab(choices, self.tabs.tabText(tab))
            lists[tab] = choices
        tabs.setCurrentIndex(int(self.tabs.currentIndex() == 2))
        layout.addWidget(tabs, 1)

        def set_column_checks(state):
            choices = tabs.currentWidget()
            with QSignalBlocker(choices):
                for row in range(choices.count()):
                    item = choices.item(row)
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        item.setCheckState(state)

        actions = QHBoxLayout()
        for label, state, tip in (
            ("All", Qt.CheckState.Checked, "Select all columns on this tab"),
            ("None", Qt.CheckState.Unchecked, "Keep only the required columns on this tab"),
        ):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked, state=state: set_column_checks(state))
            actions.addWidget(button)
        actions.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)

        def finished(code):
            self.column_picker = None
            if code == QDialog.DialogCode.Accepted:
                hidden = [set(names) for names in self.viewer.info_deleted_columns]
                included = set(self.viewer.info_included_columns)
                for tab, choices in lists.items():
                    for row in range(choices.count()):
                        item = choices.item(row)
                        name = item.text()
                        checked = item.checkState() == Qt.CheckState.Checked
                        if checked == (name in visible[tab]):
                            continue
                        if checked:
                            hidden[tab].discard(name)
                            if tab == 0:
                                included.add(name)
                        else:
                            hidden[tab].add(name)
                self.viewer.set_info_columns(hidden, included=included)
            if not self.viewer.info_columns_configured:
                self.viewer.info_columns_configured = True
                self.viewer.stateChanged.emit()
            dialog.deleteLater()

        dialog.finished.connect(finished)
        fit_window_to_screen(dialog, (540, 495), minimum=(350, 300))
        dialog.open()
        return dialog

    def edit_flag(self, row, value):
        if self.problems or self.result is None or not 0 <= row < len(self.result.spectrum_keys):
            return False
        if not re.fullmatch(r"[+-]?\d+", str(value).strip()):
            self.status.setText("Test Flag must be an integer.")
            return False
        try:
            value = int(str(value).strip())
        except ValueError:
            self.status.setText("Test Flag must be an integer.")
            return False
        self.viewer.set_test_flags({self.result.spectrum_keys[row]: value})
        return True

    def table_frame(self):
        self.refresh()
        if self.problems:
            raise ValueError("Resolve the Spectra Info matching issues before exporting or copying.")
        return self.models[self.tabs.currentIndex()].frame.copy()

    def copy_table(self):
        self._copy_frame(self.table_frame())

    @staticmethod
    def _copy_frame(frame):
        QApplication.clipboard().setText(frame.to_csv(sep="\t", index=False, lineterminator="\n"))

    def export_csv(self, path):
        frame = self.table_frame()
        # The supplied company CSV protects the 17-digit time with a leading tab.
        if "Time" in frame:
            frame["Time"] = frame["Time"].map(lambda value: "\t" + str(value) if value else "")
        frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")

    def choose_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Spectra Info", "Spectra_Info.csv", "CSV (*.csv)")
        if path:
            try:
                self.export_csv(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Spectra Info export failed", str(error))


class TestFlagDialog(QDialog):
    """Marks-style per-measurement-set assignment, independent of participation."""
    def __init__(self, viewer, *, parent=None, records=None):
        super().__init__(parent or viewer)
        self.setWindowTitle("Set Test Flag")
        self.resize(760, 700)
        self.viewer = viewer
        self.records = tuple(viewer.catalog.spectra if records is None else records)
        self.assignments = dict(viewer.test_flags)
        layout = QVBoxLayout(self)
        from .spectra_plots import SpectrumViewMenu
        self.group_picker = QPushButton()
        self.group_menu = SpectrumViewMenu(self.group_picker)
        self.group_picker.setMenu(self.group_menu)
        self.group_columns = (("wafer", "Wafer ID"), ("lot", "Lot ID"), ("tool_sn", "Tool SN"), ("pad", "PAD Name"))
        for field, title in self.group_columns:
            action = self.group_menu.addAction(title)
            action.setData(field)
            action.setCheckable(True)
            action.setChecked(field in viewer.test_flag_grouping)
            action.toggled.connect(self.rebuild_assignments)
        layout.addWidget(self.group_picker)
        self.search = QLineEdit(placeholderText="Find Wafer / Lot / PAD…")
        layout.addWidget(self.search)
        self.values = QTreeWidget()
        self.values.setHeaderLabels(["Test Flag", "Fallback"])
        self.values.setRootIsDecorated(False)
        self.values.setMaximumHeight(150)
        self.values.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked | QTreeWidget.EditTrigger.EditKeyPressed)
        for value in dict.fromkeys((*viewer.test_flag_values, *self.assignments.values())):
            self.add_value(value)
        layout.addWidget(self.values)
        value_bar = QHBoxLayout()
        self.add_flag_button = QPushButton("Add Flag")
        self.delete_flag_button = QPushButton("Delete Flag")
        self.add_flag_button.clicked.connect(self.add_flag)
        self.delete_flag_button.clicked.connect(self.delete_flag)
        value_bar.addWidget(self.add_flag_button)
        value_bar.addWidget(self.delete_flag_button)
        value_bar.addStretch()
        layout.addLayout(value_bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Measurement set", "Test Flag"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)
        batch = QHBoxLayout()
        self.batch_value = self.make_combo()
        assign = QPushButton("Assign Visible")
        assign.clicked.connect(self.assign_visible)
        batch.addWidget(self.batch_value)
        batch.addWidget(assign)
        batch.addStretch()
        layout.addLayout(batch)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter_sets)
        self.values.itemChanged.connect(self.rename_flag)
        self.tree.itemPressed.connect(self.assign_range)
        self.rebuild_assignments()
        apply_theme(self)

    def flag_values(self):
        return [self.values.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.values.topLevelItemCount())]

    def group_fields(self):
        return [action.data() for action in self.group_menu.actions() if action.isChecked()]

    def make_combo(self):
        combo = ScrollSafeComboBox()
        for value in self.flag_values():
            combo.addItem("0 (Fallback)" if value == 0 else str(value), value)
        return combo

    def add_value(self, value):
        item = QTreeWidgetItem([str(value), "✓" if value == 0 else ""])
        item.setData(0, Qt.ItemDataRole.UserRole, value)
        if value != 0:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.values.addTopLevelItem(item)
        return item

    def add_flag(self):
        value = 1
        while value in self.flag_values():
            value += 1
        self.values.setCurrentItem(self.add_value(value))
        self.refresh_values()

    def delete_flag(self):
        item = self.values.currentItem()
        if item is None or item.data(0, Qt.ItemDataRole.UserRole) == 0:
            return
        old = item.data(0, Qt.ItemDataRole.UserRole)
        self.values.takeTopLevelItem(self.values.indexOfTopLevelItem(item))
        self.assignments = {key: 0 if value == old else value for key, value in self.assignments.items()}
        self.refresh_values()

    def rename_flag(self, item, column):
        if column != 0:
            return
        old = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            value = int(item.text(0).strip())
            if (old == 0 and value != 0) or (value != old and value in self.flag_values()):
                raise ValueError()
        except ValueError:
            blocker = QSignalBlocker(self.values)
            item.setText(0, str(old))
            del blocker
            QMessageBox.warning(self, "Test Flag", "Use unique integer Test Flags. 0 remains the fallback.")
            return
        blocker = QSignalBlocker(self.values)
        item.setData(0, Qt.ItemDataRole.UserRole, value)
        item.setText(0, str(value))
        del blocker
        self.assignments = {key: value if current == old else current for key, current in self.assignments.items()}
        self.refresh_values()

    def refresh_values(self):
        current = self.batch_value.currentData()
        self.batch_value.clear()
        for value in self.flag_values():
            self.batch_value.addItem("0 (Fallback)" if value == 0 else str(value), value)
        self.batch_value.setCurrentIndex(max(0, self.batch_value.findData(current)))
        self.rebuild_assignments()

    def rebuild_assignments(self):
        if not hasattr(self, "tree"):
            return
        fields = self.group_fields()
        self.group_picker.setText(" / ".join(a.text() for a in self.group_menu.actions() if a.isChecked()) or "All spectra")
        groups = defaultdict(list)
        for source in self.records:
            groups[tuple(str(getattr(source.identity, field)) for field in fields)].append(source.key)
        self.tree.clear()
        self.combos, self.anchor = [], None
        for identity, keys in groups.items():
            item = QTreeWidgetItem([" / ".join(identity) or "All spectra", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, tuple(keys))
            self.tree.addTopLevelItem(item)
            combo = self.make_combo()
            values = {self.assignments.get(key, 0) for key in keys}
            if len(values) == 1:
                combo.setCurrentIndex(combo.findData(next(iter(values))))
            else:
                combo.insertItem(0, "Mixed", None)
                combo.setCurrentIndex(0)
            combo.currentIndexChanged.connect(lambda _index, keys=tuple(keys), combo=combo: self.assign(keys, combo.currentData()))
            self.tree.setItemWidget(item, 1, combo)
            self.combos.append((item, combo))
        self.filter_sets()

    def assign(self, keys, value):
        if value is not None:
            self.assignments.update({key: value for key in keys})

    def filter_sets(self):
        query = self.search.text().casefold()
        for item, _combo in self.combos:
            item.setHidden(query not in item.text(0).casefold())

    def assign_visible(self):
        for item, combo in self.combos:
            if not item.isHidden():
                combo.setCurrentIndex(combo.findData(self.batch_value.currentData()))

    def assign_range(self, item, column):
        if column != 0:
            return
        if self.anchor is not None and QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            combo = self.tree.itemWidget(self.anchor, 1)
            value = combo.currentData()
            if value is not None:
                first, last = sorted((self.tree.indexOfTopLevelItem(self.anchor), self.tree.indexOfTopLevelItem(item)))
                for index in range(first, last + 1):
                    target = self.tree.topLevelItem(index)
                    if not target.isHidden():
                        self.tree.itemWidget(target, 1).setCurrentIndex(self.tree.itemWidget(target, 1).findData(value))
        else:
            self.anchor = item

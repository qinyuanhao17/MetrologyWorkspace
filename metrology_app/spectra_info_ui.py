"""Spectra Info tables and local Test Flag assignment."""
from collections import defaultdict

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                            QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                            QPushButton, QTabWidget, QTableView, QTreeWidget, QTreeWidgetItem,
                            QVBoxLayout, QWidget)

from .appearance import fit_window_to_screen
from .settings import apply_theme
from .table_clipboard import attach_copy_feedback
from .widgets import ScrollSafeComboBox


class SpectraInfoWindow(QMainWindow):
    def __init__(self, viewer):
        super().__init__(viewer, Qt.WindowType.Window)
        from .matching_window import DataFrameModel
        self.viewer = viewer
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
        self.copy_button = QPushButton("Copy Table")
        self.export_button = QPushButton("Export CSV…", objectName="primary")
        self.copy_button.clicked.connect(self.copy_table)
        self.export_button.clicked.connect(self.choose_export)
        tools.addWidget(self.copy_button)
        tools.addWidget(self.export_button)
        layout.addLayout(tools)
        self.tabs = QTabWidget()
        self.models, self.tables = [], []
        for title in ("Spectra Info", "With Test Flag"):
            table = QTableView()
            model = DataFrameModel()
            table.setModel(model)
            table.setAlternatingRowColors(True)
            table.setSortingEnabled(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().setDefaultSectionSize(135)
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
            frames = (self.result.without_flags, self.result.with_flags)
            problems = self.result.issues
        except ValueError as error:
            import pandas as pd
            self.result = None
            frames, problems = (pd.DataFrame(), pd.DataFrame()), (str(error),)
        for model, table, frame in zip(self.models, self.tables, frames):
            model.set_frame(frame)
            signature = "|".join(frame.columns)
            if table.property("spectraInfoColumns") != signature:
                widths = {"Time": 185, "Die Seq": 70, "Tool SN": 90, "Type": 90,
                          "Relative Column": 110, "Relative Row": 110, "Test Flag": 80}
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
        self.status.setText(f"{len(frames[0]):,} visible rows · original Raw Data order"
                            + (f" · {len(problems)} matching issues" if problems else ""))

    def table_frame(self):
        self.refresh()
        if self.problems:
            raise ValueError("Resolve the Spectra Info matching issues before exporting or copying.")
        return self.models[self.tabs.currentIndex()].frame.copy()

    def copy_table(self):
        frame = self.table_frame()
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
    def __init__(self, viewer):
        super().__init__(viewer)
        self.setWindowTitle("Set Test Flag")
        self.resize(760, 700)
        self.viewer = viewer
        self.assignments = dict(viewer.test_flags)
        layout = QVBoxLayout(self)
        from .spectra_viewer import _ViewMenu
        self.group_picker = QPushButton()
        self.group_menu = _ViewMenu(self.group_picker)
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
        for source in self.viewer.catalog.spectra:
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

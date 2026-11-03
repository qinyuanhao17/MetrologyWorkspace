"""A full-source table with explicit, source-stable analysis participation."""
from copy import deepcopy

import numpy as np
import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QApplication, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QTableView, QToolButton,
    QVBoxLayout, QWidget,
)

from .match_groups import participation_ids, participation_source_keys, row_ids, filter_mask
from .match_group_ui import ColumnFilterDialog
from .table_clipboard import attach_copy_feedback
from .table_selection import RangeSelectionTableView
from .selection_script import context_frame, export_script, import_script, selection_view


_PARTICIPATION_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
_USE_FLAGS = _PARTICIPATION_FLAGS | Qt.ItemFlag.ItemIsUserCheckable


class ParticipationModel(QAbstractTableModel):
    changed = pyqtSignal()

    @property
    def uniform_selection_flags(self):
        return (type(self).flags is ParticipationModel.flags
                and type(self).headerData is ParticipationModel.headerData)

    def __init__(self, frame, record_ids, checked, parent=None):
        super().__init__(parent)
        self.frame, self.ids = frame, tuple(record_ids)
        self.checked = set(checked)
        self.headers = ["Use", "Source row"] + list(frame.columns)
        self.rows = list(range(len(frame)))
        self.sort_column, self.sort_order = 1, Qt.SortOrder.AscendingOrder

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = self.rows[index.row()], index.column()
        if column == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if self.ids[row] in self.checked else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if column == 0:
                return "Participates" if role == Qt.ItemDataRole.ToolTipRole and self.ids[row] in self.checked else ""
            if column == 1:
                return str(row + 1)
            value = self.frame.iat[row, column - 2]
            return "" if pd.isna(value) else str(value)

    def flags(self, index):
        return _USE_FLAGS if index.column() == 0 else _PARTICIPATION_FLAGS

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        return self.set_checked_range(index.row(), index.row(), value)

    def set_checked_range(self, first, last, value):
        """Change inclusive visible rows once, preserving hidden source IDs."""
        if not 0 <= first <= last < len(self.rows):
            return False
        keys = (self.ids[row] for row in self.rows[first:last + 1])
        if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
            self.checked.update(keys)
        else:
            self.checked.difference_update(keys)
        self.dataChanged.emit(self.index(first, 0), self.index(last, 0), [Qt.ItemDataRole.CheckStateRole])
        self.changed.emit()
        return True

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self._sort()
        self.endResetModel()

    def _sort(self):
        if self.sort_column == 0:
            values = pd.Series([key in self.checked for key in self.ids])
        elif self.sort_column == 1:
            values = pd.Series(range(len(self.frame)))
        else:
            values = self.frame.iloc[:, self.sort_column - 2].fillna("").astype(str)
            numeric = pd.to_numeric(values, errors="coerce")
            if numeric.notna().sum() == values.str.strip().ne("").sum():
                values = numeric
        self.rows = values.iloc[self.rows].sort_values(
            ascending=self.sort_order == Qt.SortOrder.AscendingOrder, kind="stable", na_position="last").index.tolist()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sort_column, self.sort_order = column, order
        self.set_rows(self.rows)


class ParticipationView(RangeSelectionTableView):
    """Click anywhere on a row; Shift applies the anchor's state to visible rows."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.anchor = None

    def mouseReleaseEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or not index.isValid():
            super().mouseReleaseEvent(event)
            return
        model, row = self.model(), index.row()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.anchor is not None:
            state = model.data(model.index(self.anchor, 0), Qt.ItemDataRole.CheckStateRole)
            start, end = sorted((self.anchor, row))
            model.set_checked_range(start, end, state)
        else:
            state = model.data(model.index(row, 0), Qt.ItemDataRole.CheckStateRole)
            model.setData(model.index(row, 0), Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
            self.anchor = row
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
            row = self.currentIndex().row()
            state = self.model().data(self.model().index(row, 0), Qt.ItemDataRole.CheckStateRole)
            self.model().setData(self.model().index(row, 0), Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
            event.accept()
            return
        super().keyPressEvent(event)


class SelectionDialog(QDialog):
    """Shared row/column selection body over one displayed table."""
    selectionChanged = pyqtSignal()

    def __init__(self, frame, record_ids, checked, groups, parent=None, *,
                 object_name="dataSelectionDialog",
                 title="Data selection — analysis participation",
                 row_bools=None, group_bools=None, show="all", search="", hide_excluded=False, context=None):
        super().__init__(parent, objectName=object_name)
        self.setWindowTitle(title)
        self.resize(1100, 650)
        self._base_frame = frame
        self._selection_context = deepcopy(context or [])
        frame = context_frame(frame, {"filters": groups or [], "context": self._selection_context})
        self.model = ParticipationModel(frame, record_ids, checked, self)
        self.filter_groups = [[dict(spec) for spec in group] for group in groups]
        self.filter_row_bools = [list(bools) for bools in (row_bools or [])]
        self.filter_group_bools = [str(value).lower() for value in (group_bools or [])]
        self.filter_row_widgets = []
        self.filter_bool_combos = []
        self.filter_group_combos = []
        layout = QVBoxLayout(self)
        conditions = QHBoxLayout()
        # Boolean matrix: a row combines its own conditions first, then the
        # rows are combined by the connectors between them.
        self.filter_menu = QMenu(self)
        for column in frame.columns:
            action = self.filter_menu.addAction(column)
            action.triggered.connect(
                lambda _checked=False, name=column:
                QTimer.singleShot(0, lambda: self.add_row(name))
            )
        self.add_row_button = QToolButton(objectName="addFilterRow")
        self.add_row_button.setText("Add row")
        self.add_row_button.setMinimumWidth(96)
        self.add_row_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_row_button.setMenu(self.filter_menu)
        conditions.addWidget(self.add_row_button)
        clear = QPushButton("Clear filters")
        conditions.addWidget(clear)
        conditions.addStretch(1)
        self.script_dialog = None
        self.selection_script_button = QPushButton("Selection Script…", objectName="selectionScript")
        self.selection_script_button.clicked.connect(self.open_selection_script)
        conditions.addWidget(self.selection_script_button)
        layout.addLayout(conditions)
        self.filter_rows = QVBoxLayout()
        self.filter_rows.setContentsMargins(0, 0, 0, 0)
        self.filter_rows.setSpacing(4)
        layout.addLayout(self.filter_rows)
        tools = QHBoxLayout()
        self.search = QLineEdit(objectName="dataSelectionSearch")
        self.search.setPlaceholderText("Find across Order, Reference and Raw Data…")
        self.search.setText(search)
        self.show_rows = QComboBox(objectName="dataSelectionShow")
        for label, key in (("All rows", "all"), ("Filtered rows", "filtered"),
                           ("Checked rows", "checked"), ("Unchecked rows", "unchecked")):
            self.show_rows.addItem(label, key)
        self.show_rows.setCurrentIndex(max(0, self.show_rows.findData(show)))
        self.show_rows.setToolTip(
            "Only Filtered rows applies filter conditions. Checked rows / Unchecked rows show current "
            "participation across the source data. Search refines every view; "
            "Check Visible / Uncheck Visible act on exactly the displayed rows.")
        tools.addWidget(self.search, 1)
        tools.addWidget(self.show_rows)
        for title, checked_value in (("Check Visible", True), ("Uncheck Visible", False)):
            button = QPushButton(title)
            button.clicked.connect(lambda _=False, value=checked_value: self.check_visible(value))
            tools.addWidget(button)
        layout.addLayout(tools)
        self.table = ParticipationView()
        self.table.setModel(self.model)
        attach_copy_feedback(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 86)
        for i in range(2, self.model.columnCount()):
            self.table.setColumnWidth(i, 160)
        layout.addWidget(self.table, 1)
        self.status = QLabel(objectName="hint")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.hide_excluded = QCheckBox("Hide excluded rows in tables", objectName="hideExcludedRows")
        self.hide_excluded.setChecked(hide_excluded)
        self.hide_excluded.setToolTip("Hide unchecked records in this window's tables. Source data is retained.")
        footer = QHBoxLayout()
        footer.addWidget(self.hide_excluded)
        footer.addStretch(1)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        clear.clicked.connect(self.clear_filters)
        self.search.textChanged.connect(self.refresh_rows)
        self.show_rows.currentIndexChanged.connect(self.refresh_rows)
        self.model.changed.connect(self.update_status)
        self.model.changed.connect(self.selectionChanged.emit)
        self.hide_excluded.toggled.connect(self.selectionChanged.emit)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_rows)
        self.model.changed.connect(self._schedule_refresh)
        self.model.modelReset.connect(lambda: setattr(self.table, "anchor", None))
        self._rebuild_filter_rows()
        self.refresh_rows()

    def view_state(self):
        view = {"filters": deepcopy(self.filter_groups),
                "row_bools": [self._normalized_row_bools(i) for i in range(len(self.filter_groups))],
                "group_bools": self._normalized_group_bools(),
                "show": self.show_rows.currentData(), "search": self.search.text(),
                "hide_excluded": self.hide_excluded.isChecked()}
        if self._selection_context:
            view["context"] = deepcopy(self._selection_context)
        return view

    def selection_script(self):
        state = {"checked": [i for i, key in enumerate(self.model.ids) if key in self.model.checked], **self.view_state()}
        return export_script(self.model.frame, state)

    def apply_selection_script(self, text, *, allow_partial=False):
        state = import_script(self._base_frame, text, allow_partial=allow_partial,
                              current_checked=[i for i, key in enumerate(self.model.ids) if key in self.model.checked])
        frame = context_frame(self._base_frame, state)
        self._selection_context = deepcopy(state.get("context", []))
        self.model.beginResetModel()
        self.model.frame = frame
        self.model.headers = ["Use", "Source row"] + list(frame.columns)
        if self.model.sort_column >= len(self.model.headers):
            self.model.sort_column = 1
        self.model.endResetModel()
        self.filter_menu.clear()
        for column in frame.columns:
            action = self.filter_menu.addAction(column)
            action.triggered.connect(lambda _=False, name=column: QTimer.singleShot(0, lambda: self.add_row(name)))
        self.filter_groups = state["filters"]
        self.filter_row_bools, self.filter_group_bools = state["row_bools"], state["group_bools"]
        self.model.checked = {self.model.ids[i] for i in state["checked"]}
        blockers = [QSignalBlocker(widget) for widget in (self.search, self.show_rows, self.hide_excluded)]
        self.search.setText(state["search"])
        self.show_rows.setCurrentIndex(self.show_rows.findData(state["show"]))
        self.hide_excluded.setChecked(state["hide_excluded"])
        del blockers
        self._rebuild_filter_rows()
        self.refresh_rows()
        return state

    def open_selection_script(self):
        if self.script_dialog is None:
            self.script_dialog = SelectionScriptDialog(self)
        self.script_dialog.show()
        self.script_dialog.refresh_script()
        self.script_dialog.raise_()

    def update_status(self):
        text = (f"{len(self.model.frame):,} rows × {len(self.model.frame.columns)} columns · "
                f"{len(self.model.rows):,} visible · "
                f"{len(self.model.checked):,} participating · "
                f"{len(self.model.ids) - len(self.model.checked):,} excluded")
        if any(self.filter_groups):
            expression, emitted = [], False
            for row_index, row in enumerate(self.filter_groups):
                if not row:
                    continue
                if emitted:
                    connector = self._normalized_group_bools()[row_index - 1]
                    expression.append("OR" if connector == "or" else "AND")
                pieces = [row[0]["column"]]
                bools = self._normalized_row_bools(row_index)
                for position, spec in enumerate(row[1:], start=1):
                    pieces.append("OR" if bools[position - 1] == "or" else "AND")
                    pieces.append(spec["column"])
                body = " ".join(pieces)
                expression.append(f"({body})" if len(row) > 1 else body)
                emitted = True
            text += " · Filters: " + " ".join(expression)
        self.status.setText(text)

    def _schedule_refresh(self):
        # Keep the visible row indices stable throughout one Shift-click range.
        if self.show_rows.currentData() != "all" or self.model.sort_column == 0:
            self._refresh_timer.start(0)

    @staticmethod
    def _combine_masks(parts, bools):
        """SQL precedence: AND binds tighter than OR inside one level."""
        combined, segment = None, None
        for index, part in enumerate(parts):
            connector = bools[index - 1] if index and index - 1 < len(bools) else "and"
            if index and connector == "or":
                combined = segment if combined is None else (combined | segment)
                segment = part
            else:
                segment = part if segment is None else (segment & part)
        return segment if combined is None else (combined | segment)

    def refresh_rows(self):
        self._prune_filters()
        mask = np.ones(len(self.model.frame), dtype=bool)
        show = self.show_rows.currentData() or "all"
        if show == "filtered" and any(self.filter_groups):
            row_masks = []
            for row_index, row in enumerate(self.filter_groups):
                parts = [filter_mask(self.model.frame[spec["column"]], spec) for spec in row]
                row_masks.append(self._combine_masks(parts, self._normalized_row_bools(row_index)))
            mask &= self._combine_masks(row_masks, self._normalized_group_bools())
        query = self.search.text().strip()
        if query:
            found = np.zeros(len(mask), dtype=bool)
            for column in self.model.frame:
                found |= self.model.frame[column].fillna("").astype(str).str.contains(query, case=False, regex=False).to_numpy()
            mask &= found
        if show in ("checked", "unchecked"):
            checked = np.array([key in self.model.checked for key in self.model.ids], dtype=bool)
            mask &= checked if show == "checked" else ~checked
        self.model.set_rows(np.flatnonzero(mask))
        self.update_status()
        self.selectionChanged.emit()

    def check_visible(self, checked):
        keys = {self.model.ids[row] for row in self.model.rows}
        self.model.checked = self.model.checked | keys if checked else self.model.checked - keys
        self.refresh_rows()

    def clear_filters(self):
        self.filter_groups = []
        self.filter_row_bools = []
        self.filter_group_bools = []
        self.search.clear()
        self._rebuild_filter_rows()
        self.refresh_rows()

    @staticmethod
    def _filter_detail(spec):
        parts = []
        if spec.get("values") is not None:
            values = [str(value) for value in spec["values"]]
            parts.append(", ".join(values[:3]) + ("…" if len(values) > 3 else ""))
        if spec.get("query"):
            parts.append(f"contains {spec['query']}")
        if spec.get("minimum") not in (None, ""):
            parts.append(f"≥ {spec['minimum']}")
        if spec.get("maximum") not in (None, ""):
            parts.append(f"≤ {spec['maximum']}")
        return " · ".join(parts)

    def _normalized_row_bools(self, row_index):
        count = len(self.filter_groups[row_index])
        bools = list(self.filter_row_bools[row_index]) if row_index < len(self.filter_row_bools) else []
        bools = bools[: max(0, count - 1)]
        while len(bools) < max(0, count - 1):
            bools.append("and")
        return [value if value in ("and", "or") else "and" for value in bools]

    def _normalized_group_bools(self):
        count = len(self.filter_groups)
        bools = list(self.filter_group_bools)[: max(0, count - 1)]
        while len(bools) < max(0, count - 1):
            bools.append("and")
        return [value if value in ("and", "or") else "and" for value in bools]

    def _prune_filters(self):
        group_source = self._normalized_group_bools()
        kept_groups, kept_row_bools, kept_group_bools = [], [], []
        for row_index, row in enumerate(self.filter_groups):
            bools = self._normalized_row_bools(row_index)
            kept, kept_bools = [], []
            for position, spec in enumerate(row):
                if spec["column"] not in self.model.frame:
                    continue
                if kept:
                    kept_bools.append(bools[position - 1] if position - 1 < len(bools) else "and")
                kept.append(spec)
            if not kept:
                continue
            if kept_groups:
                kept_group_bools.append(group_source[row_index - 1] if row_index - 1 < len(group_source) else "and")
            kept_groups.append(kept)
            kept_row_bools.append(kept_bools)
        self.filter_groups, self.filter_row_bools, self.filter_group_bools = (
            kept_groups, kept_row_bools, kept_group_bools)

    def _set_filter_bool(self, row_index, position, value):
        bools = self._normalized_row_bools(row_index)
        if position < len(bools):
            bools[position] = value if value in ("and", "or") else "and"
        while len(self.filter_row_bools) <= row_index:
            self.filter_row_bools.append([])
        self.filter_row_bools[row_index] = bools
        self.refresh_rows()

    def _set_group_bool(self, index, value):
        bools = self._normalized_group_bools()
        if index < len(bools):
            bools[index] = value if value in ("and", "or") else "and"
        self.filter_group_bools = bools
        self.refresh_rows()

    @staticmethod
    def _bool_combo(value):
        combo = QComboBox(objectName="filterBoolean")
        combo.setMinimumWidth(64)
        combo.addItem("AND", "and")
        combo.addItem("OR", "or")
        combo.setCurrentIndex(combo.findData(value))
        return combo

    def _rebuild_filter_rows(self):
        self.filter_row_bools = [self._normalized_row_bools(index)
                                 for index in range(len(self.filter_groups))]
        self.filter_group_bools = self._normalized_group_bools()
        while self.filter_rows.count():
            item = self.filter_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.filter_row_widgets = []
        self.filter_bool_combos = []
        self.filter_group_combos = []
        for row_index, row in enumerate(self.filter_groups):
            if row_index:
                connector = self._bool_combo(self.filter_group_bools[row_index - 1])
                connector.currentIndexChanged.connect(
                    lambda _index, position=row_index - 1, combo=connector:
                    self._set_group_bool(position, combo.currentData()))
                holder = QFrame(objectName="filterJoin")
                holder_layout = QHBoxLayout(holder)
                holder_layout.setContentsMargins(18, 0, 0, 0)
                holder_layout.addWidget(connector)
                holder_layout.addStretch(1)
                self.filter_rows.addWidget(holder)
                self.filter_group_combos.append(connector)
            frame_row = QFrame(objectName="filterRow")
            row_layout = QHBoxLayout(frame_row)
            row_layout.setContentsMargins(10, 4, 10, 4)
            row_layout.setSpacing(8)
            for position, spec in enumerate(row):
                if position:
                    connector = self._bool_combo(self.filter_row_bools[row_index][position - 1])
                    connector.currentIndexChanged.connect(
                        lambda _index, target=row_index, spot=position - 1, combo=connector:
                        self._set_filter_bool(target, spot, combo.currentData()))
                    row_layout.addWidget(connector)
                    self.filter_bool_combos.append(connector)
                chip = QFrame(objectName="filterChip")
                chip_layout = QHBoxLayout(chip)
                chip_layout.setContentsMargins(8, 1, 4, 1)
                chip_layout.setSpacing(6)
                chip_layout.addWidget(QLabel(spec["column"], objectName="filterColumn"))
                chip_layout.addWidget(
                    QLabel(self._filter_detail(spec) or "(no condition)", objectName="hint"))
                edit = QPushButton("Edit", objectName="filterChipEdit")
                edit.clicked.connect(
                    lambda _checked=False, target=row_index, spot=position:
                    self._edit_condition(target, spot))
                remove = QPushButton("×", objectName="filterChipRemove")
                remove.setToolTip("Remove this condition")
                remove.clicked.connect(
                    lambda _checked=False, target=row_index, spot=position:
                    self._remove_condition(target, spot))
                chip_layout.addWidget(edit)
                chip_layout.addWidget(remove)
                row_layout.addWidget(chip)
            row_layout.addStretch(1)
            add = QPushButton("+ condition", objectName="link")
            add.setToolTip("Add a condition to this row")
            add.clicked.connect(
                lambda _checked=False, target=row_index, button=add:
                self._choose_condition_column(target, button))
            row_layout.addWidget(add)
            self.filter_rows.addWidget(frame_row)
            self.filter_row_widgets.append(frame_row)

    def _condition_index(self, column):
        for row_index, row in enumerate(self.filter_groups):
            for position, spec in enumerate(row):
                if spec["column"] == column:
                    return row_index, position
        return None

    def _condition_dialog(self, column, spec):
        dialog = ColumnFilterDialog(column, self.model.frame[column], spec, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        removed, new_spec = dialog.removed, None
        if accepted and not removed:
            try:
                new_spec = {"column": column, **dialog.specification()}
            except ValueError as error:
                self.status.setText(str(error))
        dialog.deleteLater()
        return removed, new_spec

    def _edit_condition(self, row_index, position):
        spec = self.filter_groups[row_index][position]
        removed, new_spec = self._condition_dialog(spec["column"], spec)
        if removed:
            self._remove_condition(row_index, position)
            return
        if new_spec is not None:
            self.filter_groups[row_index][position] = new_spec
            self._show_filtered_rows()
        self._rebuild_filter_rows()
        self.refresh_rows()

    def add_condition(self, row_index, column):
        removed, new_spec = self._condition_dialog(column, {})
        if removed or new_spec is None:
            self._prune_filters()
        else:
            self.filter_groups[row_index].append(new_spec)
            self._show_filtered_rows()
        self._rebuild_filter_rows()
        self.refresh_rows()

    def add_filter(self, column):
        """Append a condition to the last row (creating the first row if needed)."""
        if not self.filter_groups:
            self.filter_groups.append([])
        self.add_condition(len(self.filter_groups) - 1, column)

    def _show_filtered_rows(self):
        """Jump the Show combo to Filtered rows once a condition exists."""
        index = self.show_rows.findData("filtered")
        if index >= 0 and self.show_rows.currentData() != "filtered":
            self.show_rows.setCurrentIndex(index)

    def add_row(self, column):
        """Start a new boolean row with this first condition."""
        self.filter_groups.append([])
        self.add_condition(len(self.filter_groups) - 1, column)

    def _choose_condition_column(self, row_index, button):
        menu = QMenu(self)
        for column in self.model.frame.columns:
            action = menu.addAction(column)
            action.triggered.connect(
                lambda _checked=False, name=column, target=row_index:
                QTimer.singleShot(0, lambda: self.add_condition(target, name)))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _remove_condition(self, row_index, position):
        self.filter_groups[row_index].pop(position)
        bools = self._normalized_row_bools(row_index)
        if bools:
            if position < len(bools):
                bools.pop(position)
            elif position:
                bools.pop(position - 1)
        while len(self.filter_row_bools) <= row_index:
            self.filter_row_bools.append([])
        self.filter_row_bools[row_index] = bools
        self._prune_filters()
        self._rebuild_filter_rows()
        self.refresh_rows()

    def edit_filter(self, column):
        found = self._condition_index(column)
        if found is None:
            self.add_filter(column)
        else:
            self._edit_condition(*found)

    def remove_filter(self, column):
        found = self._condition_index(column)
        if found is not None:
            self._remove_condition(*found)

class SelectionScriptDialog(QDialog):
    """A live, copyable recipe; imports edit the surrounding selection draft."""
    def __init__(self, selection):
        super().__init__(selection, objectName="selectionScriptDialog")
        self.selection = selection
        self.setWindowTitle("Selection Script")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Copy this selection to another window, or paste a script and apply it here."))
        self.editor = QPlainTextEdit(objectName="selectionScriptText")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.editor, 1)
        self.message = QLabel(objectName="hint")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy Selection Script")
        self.copy_button.clicked.connect(self.copy_script)
        buttons.addWidget(self.copy_button)
        self.paste_button = QPushButton("Paste from Clipboard")
        self.paste_button.clicked.connect(lambda: self.editor.setPlainText(QApplication.clipboard().text()))
        buttons.addWidget(self.paste_button)
        buttons.addStretch(1)
        self.apply_button = QPushButton("Apply Script", objectName="primary")
        self.apply_button.clicked.connect(self.apply_script)
        buttons.addWidget(self.apply_button)
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        selection.selectionChanged.connect(self.refresh_script)

    def refresh_script(self):
        if self.isVisible():
            try:
                text = self.selection.selection_script()
            except ValueError as error:
                self.editor.clear()
                self.message.setText(str(error))
                self.copy_button.setEnabled(False)
                return False
            self.editor.setPlainText(text)
            self.copy_button.setEnabled(True)
            self.message.clear()
            return True

    def copy_script(self):
        if not self.refresh_script():
            return
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.message.setText("Selection script copied.")

    def apply_script(self):
        try:
            self.selection.apply_selection_script(self.editor.toPlainText())
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.message.setText("Script applied to this selection. Use Apply in Data selection to accept it.")


def selection_frame(plan):
    frames = [("Order", plan.order_frame), ("Reference", plan.reference), ("Raw Data", plan.raw)]
    return pd.concat([data.reset_index(drop=True).rename(columns=lambda c: f"{name} / {c}")
                      for name, data in frames], axis=1)


class DataSelectionDialog(SelectionDialog):
    """The Match Workbook's Order / Reference / Raw participation dialog."""

    def __init__(self, plan, parent=None):
        self.plan = plan
        self.selection = deepcopy(plan.state["data_selection"])
        frame = selection_frame(plan)
        ids = participation_ids(plan.raw, self.selection)
        checked = [ids[row] for row in plan.included_rows]
        view = selection_view(self.selection)
        super().__init__(frame, ids, checked, view["filters"], parent,
                         row_bools=view["row_bools"], group_bools=view["group_bools"],
                         show=view["show"], search=view["search"], hide_excluded=view["hide_excluded"])
        self.hide_excluded.setToolTip("Apply hides unchecked records in Order, Reference, Raw Data and linked Match-selection views. Uncheck and Apply to restore them; source data is never deleted.")

    def accept(self):
        self.selection = {"records": [{"key": key, "id": identifier} for key, identifier in zip(row_ids(self.plan.raw), self.model.ids)],
                          "excluded": [key for key in self.model.ids if key not in self.model.checked],
                          "view_filter_groups": deepcopy([list(row) for row in self.filter_groups]),
                          "view_filter_row_bools": [list(bools) for bools in self.filter_row_bools],
                          "view_filter_group_bools": list(self.filter_group_bools),
                          "view_show": self.show_rows.currentData(),
                          "view_search": self.search.text(),
                          "hide_excluded": self.hide_excluded.isChecked()}
        super().accept()


class FrameSelectionDialog(SelectionDialog):
    """One workspace table (Wafer Map / Correlation) and its own row selection."""

    def __init__(self, frame, excluded=(), parent=None, extra_frames=None, *,
                 filters=None, row_bools=None, group_bools=None, show="all", search="", hide_excluded=False,
                 prefix_raw=False, context=None):
        self.excluded = []
        self.saved_filters = deepcopy([list(row) for row in (filters or [])])
        self.saved_row_bools = [list(bools) for bools in (row_bools or [])]
        self.saved_group_bools = list(group_bools or [])
        self.saved_show = show
        frame = frame.reset_index(drop=True)
        keys = participation_source_keys(frame)
        skipped = set(excluded)
        checked = [key for key in keys if key not in skipped]
        display = frame
        extras = [(name, extra.reset_index(drop=True))
                  for name, extra in (extra_frames or [])
                  if extra is not None and len(extra) == len(frame)]
        if extras or prefix_raw:
            columns = [extra.rename(columns=lambda column, prefix=name: f"{prefix} / {column}")
                       for name, extra in extras]
            columns.append(frame.rename(columns=lambda column: f"Raw Data / {column}"))
            display = pd.concat(columns, axis=1)
        super().__init__(display, keys, checked, self.saved_filters, parent,
                         object_name="frameSelectionDialog",
                         title="Data selection — rows used by this window",
                         row_bools=self.saved_row_bools, group_bools=self.saved_group_bools,
                         show=self.saved_show, search=search, hide_excluded=hide_excluded, context=context)

    def accept(self):
        self.excluded = [key for key in self.model.ids if key not in self.model.checked]
        self.saved_filters = deepcopy([list(row) for row in self.filter_groups])
        self.saved_row_bools = [list(bools) for bools in self.filter_row_bools]
        self.saved_group_bools = list(self.filter_group_bools)
        self.saved_show = self.show_rows.currentData()
        super().accept()

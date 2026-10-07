"""Workbook group controls and source-mapped editable sheet projections."""
from copy import deepcopy
from math import ceil
import json
from uuid import uuid4

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QAbstractProxyModel, QEvent, QModelIndex, QPointF, QRectF, QSignalBlocker, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .appearance import fit_window_to_screen, widget_to_qimage
from .match_groups import GroupPlan, applied_state, flag_order, flag_value, group_state, normalized, participation_ids, row_ids
from .plotting import InteractivePlotWidget, place_legend_above_frame
from .sheet import SheetModel, clipboard_rows


class _ViewCells:
    def __init__(self, proxy):
        self.proxy = proxy

    def __bool__(self):
        return bool(self.proxy.sourceModel().cells)

    def get(self, key, default=""):
        row, column = key
        return self.proxy.sourceModel().cells.get((self.proxy.source_row(row), column), default)


class ProjectedSheetModel(QAbstractProxyModel):
    """Keep the editable header and map every cell operation to its source row."""
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.rows = None
        self.setSourceModel(source)
        self.cells = _ViewCells(self)
        self.undo = source.undo
        source.changed.connect(self.refresh)

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def set_rows(self, rows):
        rows = None if rows is None else tuple(int(row) + 1 for row in rows)
        if rows != self.rows:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()

    def source_row(self, row):
        return row if self.rows is None or row == 0 else self.rows[row - 1]

    def mapToSource(self, index):
        if not index.isValid():
            return QModelIndex()
        return self.sourceModel().index(self.source_row(index.row()), index.column())

    def mapFromSource(self, index):
        if not index.isValid():
            return QModelIndex()
        if self.rows is None or index.row() == 0:
            row = index.row()
        else:
            try:
                row = self.rows.index(index.row()) + 1
            except ValueError:
                return QModelIndex()
        return self.index(row, index.column())

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else (len(self.rows) + 1 if self.rows is not None else self.sourceModel().rowCount())

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.sourceModel().columnCount()

    def index(self, row, column, parent=QModelIndex()):
        return self.createIndex(row, column) if not parent.isValid() and 0 <= row < self.rowCount() and 0 <= column < self.columnCount() else QModelIndex()

    def parent(self, index):
        return QModelIndex()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        return self.sourceModel().data(self.mapToSource(index), role)

    def flags(self, index):
        return self.sourceModel().flags(self.mapToSource(index))

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(self.source_row(section) + 1)
        return self.sourceModel().headerData(section, orientation, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        return self.sourceModel().setData(self.mapToSource(index), value, role)

    def edit(self, changes):
        if self.rows is not None and any(r > len(self.rows) for r, _ in changes):
            raise ValueError("Paste fits only within displayed rows. Clear filters/sort before appending records.")
        self.sourceModel().edit({(self.source_row(r), c): value for (r, c), value in changes.items()})

    def replace_matrix(self, matrix):
        self.sourceModel().replace_matrix(matrix)


class OrderModel(SheetModel):
    def __init__(self):
        super().__init__()
        self.plan = None
        self.load(pd.DataFrame(columns=["TestFlag"]))

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else max(self.height, len(self.plan.raw) + 1 if self.plan is not None else 2)

    @staticmethod
    def _row_count(cells, plan):
        return max(2, max((r + 1 for (r, c), value in cells.items() if c == 0 and str(value).strip()), default=1),
                   len(plan.raw) + 1 if plan is not None else 1)

    def restore(self, state, emit_changed=True):
        cells, _, _ = state
        super().restore((cells, self._row_count(cells, None), 4), emit_changed)

    def apply(self, changes):
        cells = dict(self.cells)
        for key, value in changes.items():
            if key[1] == 0:
                if value:
                    cells[key] = value
                else:
                    cells.pop(key, None)
        reset = self._row_count(cells, self.plan) != self.rowCount()
        if reset:
            self.beginResetModel()
        self.cells = cells
        self.height = self._row_count(cells, None)
        if reset:
            self.endResetModel()
        else:
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 3))
        self.changed.emit()

    def set_plan(self, plan):
        reset = self._row_count(self.cells, plan) != self.rowCount()
        if reset:
            self.beginResetModel()
        self.plan = plan
        if reset:
            self.endResetModel()
        else:
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 3))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.row() > 0 and index.column() == 0:
            try:
                flag_value(self.cells.get((index.row(), 0), ""))
            except ValueError as error:
                if role == Qt.ItemDataRole.BackgroundRole:
                    return QColor("#fff0f1")
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor("#a3132b")
                if role == Qt.ItemDataRole.ToolTipRole:
                    return str(error)
        if index.isValid() and index.column() > 0:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
                if index.row() == 0:
                    return ("TestFlag", "Head", "Mark", "Group")[index.column()]
                if self.plan is not None and index.row() <= len(self.plan.raw):
                    row = index.row() - 1
                    # Without a TestFlag the Mark is the whole Group, so the
                    # Mark-only plan must show it in the Group column too.
                    if (not self.plan.flags[row]
                            and not (index.column() == 2 and self.plan.mark_enabled)
                            and not (index.column() == 3 and self.plan.mark_only)):
                        return ""
                    return str(self.plan.order_frame.iat[row, index.column()])
                return ""
        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        return flags & ~Qt.ItemFlag.ItemIsEditable if index.column() else flags

    def edit(self, changes):
        super().edit({key: value for key, value in changes.items() if key[1] == 0})

    def flags_frame(self, count=0):
        # Order has only paired rows (or explicitly entered flags), not the
        # empty final-row marker used by ordinary source-table snapshots.
        extent = max(count, max((r for (r, c), value in self.cells.items()
                                 if c == 0 and str(value).strip()), default=0))
        return pd.DataFrame({"TestFlag": [self.cells.get((r, 0), "") for r in range(1, extent + 1)]})


class ColumnFilterDialog(QDialog):
    def __init__(self, name, series, spec, parent):
        super().__init__(parent)
        self.setWindowTitle(f"Filter · {name}")
        self.resize(400, 510)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.query = QLineEdit(str(spec.get("query", "")))
        self.minimum = QLineEdit(str(spec.get("minimum", "")))
        self.maximum = QLineEdit(str(spec.get("maximum", "")))
        for label, field in (("Contains", self.query), ("Minimum", self.minimum), ("Maximum", self.maximum)):
            form.addRow(label, field)
        layout.addLayout(form)
        self.search = QLineEdit(placeholderText="Find a value…")
        layout.addWidget(self.search)
        actions = QHBoxLayout()
        self.all_button, self.none_button = QPushButton("All"), QPushButton("None")
        actions.addWidget(self.all_button)
        actions.addWidget(self.none_button)
        layout.addLayout(actions)
        self.values = QListWidget()
        unique = list(dict.fromkeys(series.fillna("").astype(str).str.strip()))
        selected = spec.get("values")
        for value in unique:
            item = QListWidgetItem(value or "(blank)")
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if selected is None or value in selected else Qt.CheckState.Unchecked)
            self.values.addItem(item)
        layout.addWidget(self.values)
        self.search.textChanged.connect(lambda text: [self.values.item(i).setHidden(text.lower() not in self.values.item(i).text().lower()) for i in range(self.values.count())])
        self.all_button.clicked.connect(lambda: self.check_visible(True))
        self.none_button.clicked.connect(lambda: self.check_visible(False))
        self.removed = False
        if spec:
            remove = QPushButton("Remove filter", objectName="removeColumnFilter")
            remove.clicked.connect(self._remove)
            layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _remove(self):
        self.removed = True
        self.accept()

    def check_visible(self, checked):
        for i in range(self.values.count()):
            item = self.values.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def specification(self):
        selected = [self.values.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.values.count())
                    if self.values.item(i).checkState() == Qt.CheckState.Checked]
        output = {"query": self.query.text().strip(), "values": None if len(selected) == self.values.count() else selected}
        for key, field in (("minimum", self.minimum), ("maximum", self.maximum)):
            if field.text().strip():
                value = float(field.text())
                if not np.isfinite(value):
                    raise ValueError("Filter bounds must be finite numbers.")
                output[key] = value
        return output


class GroupControls(QWidget):
    changed = pyqtSignal()
    apply_requested = pyqtSignal()
    combined_imported = pyqtSignal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = group_state()
        self.state["data_selection"] = {"records": [], "excluded": []}
        self.state["applied"] = deepcopy(self.state)
        self.reference, self.raw = pd.DataFrame(), pd.DataFrame()
        self.plan = None
        self.order_model = OrderModel()
        self._loading = False
        self._header_tables = {}
        self.order_model.changed.connect(self.flags_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setSpacing(10)
        self.enabled = QCheckBox("Head groups")
        self.mark_enabled = QCheckBox("Mark")
        self.mark_enabled.setToolTip("Optional per-wafer classification; disabling it groups by head only and retains every Mark.")
        self.names_button = QPushButton("Head names…")
        self.names_button.setEnabled(False)
        self.new_button = QPushButton("Marks…")
        self.order = QComboBox()
        for label, value in (("Group → wafer → Die Seq", "groups"), ("Original row order", "original")):
            self.order.addItem(label, value)
        for index, tip in enumerate(("Arrange by Group, wafer and Die Seq.",
                                    "Keep the original input row order, ignoring table sorting.")):
            self.order.setItemData(index, tip, Qt.ItemDataRole.ToolTipRole)
        self.order.setToolTip("Original row order keeps the input order and marks each wafer\n"
                             "boundary with a thin grey dashed line; only Die Seq is labelled.")
        self.group_order_button = QPushButton("Group order…")
        self.card = QCheckBox("Use group Card")
        self.card.setToolTip(
            "Group Match / Trend only: calibrate each head (and optional Mark) group with its own Card.\n"
            "All parameter plots always uses the overall Match Card when Card is checked."
        )
        self.apply_button = QPushButton("Apply", objectName="primary")
        form.addRow(self.enabled, self.names_button)
        form.addRow(self.mark_enabled, self.new_button)
        form.addRow("Trend order", self.order)
        form.addRow("Group sequence", self.group_order_button)
        layout.addLayout(form)
        self.card.hide()  # Reparented onto Group plots by the Workbook.
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.enabled.toggled.connect(lambda value: self.change("enabled", value))
        self.mark_enabled.toggled.connect(lambda value: self.change("mark_enabled", value))
        self.order.currentIndexChanged.connect(lambda: self.change("trend_order", self.order.currentData()))
        self.names_button.clicked.connect(self.edit_names)
        self.new_button.clicked.connect(self.mark_new)
        self.group_order_button.clicked.connect(self.edit_group_order)
        self.apply_button.clicked.connect(self.apply_requested)

    @property
    def pending(self):
        current = {key: value for key, value in self.state.items() if key != "applied"}
        applied = {key: value for key, value in self.state.get("applied", {}).items() if key != "flags"}
        return current != applied

    def change(self, key, value):
        if self._loading:
            return
        self.state[key] = value
        self.refresh()
        self.changed.emit()

    def flags_changed(self):
        if self._loading:
            return
        self.state["flag_revision"] = self.state.get("flag_revision", 0) + 1
        self.refresh()
        self.changed.emit()

    def set_sources(self, reference, raw):
        if self.reference is reference and self.raw is raw:
            return
        self.reference, self.raw = reference, raw
        if len(raw) and len(raw) == len(reference):
            ids = participation_ids(raw, self.state.get("data_selection"))
            for config in (self.state, self.state.get("applied", {})):
                selection = config.get("data_selection")
                if selection is not None and not selection["records"]:
                    selection["records"] = [{"key": key, "id": identifier} for key, identifier in zip(row_ids(raw), ids)]
        self.refresh()

    def refresh(self):
        try:
            self.plan = GroupPlan(self.raw, self.order_model.flags_frame(len(self.raw)),
                                  {key: value for key, value in self.state.items() if key != "applied"}, self.reference)
            detail = "; ".join(f"{spec['table']} / {spec['column']}" for spec in self.state["filters"])
            self.status.setText(f"{len(self.plan.included_rows):,} / {len(self.raw):,} paired rows · "
                                f"{len(self.plan.measurements)} measurement sets"
                                + (f" · Filters: {detail}" if detail else "")
                                + (" · Settings pending: click Apply" if self.pending else ""))
            self.apply_button.setEnabled(True)
        except (ValueError, IndexError) as error:
            self.plan = None
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)
        self.order_model.set_plan(self.plan)
        self.names_button.setEnabled(bool(self.entered_flags()))
        self.card.setEnabled(self.plan is not None and self.plan.enabled)
        self.new_button.setEnabled(self.state["mark_enabled"] and self.plan is not None)

    def flags_frame(self):
        return self.order_model.flags_frame(max(len(self.raw), len(self.reference)))

    def restore(self, state, flags=None):
        self._loading = True
        try:
            self.state = group_state(state)
            self.state.setdefault("applied", deepcopy({k: v for k, v in self.state.items() if k != "applied"}))
            self.order_model.load(flags if flags is not None else pd.DataFrame(columns=["TestFlag"]))
            self.enabled.setChecked(self.state["enabled"])
            self.mark_enabled.setChecked(self.state["mark_enabled"])
            self.card.setChecked(self.state["use_group_card"])
            self.order.setCurrentIndex(max(0, self.order.findData(self.state["trend_order"])))
        finally:
            self._loading = False
        self.refresh()

    def accept_changes(self):
        self.state["applied"] = deepcopy({k: v for k, v in self.state.items() if k != "applied"})
        self.state["applied"]["flags"] = self.flags_frame().iloc[:, 0].tolist()
        self.refresh()

    def clear_filters(self):
        self.state["sort"] = []
        self.change("filters", [])

    def attach_header(self, view, table):
        header = view.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Qt's own customContextMenuRequested delivery crashes on Windows when
        # the slot asks the header for the clicked column, so the menu is opened
        # from an event filter instead of from that signal.
        self._header_tables[header] = (view, table)
        header.installEventFilter(self)
        header.setToolTip("Right-click a column to filter or sort all three paired tables.")

    def eventFilter(self, watched, event):
        target = self._header_tables.get(watched)
        if target is not None and event.type() == QEvent.Type.ContextMenu:
            view, table = target
            point = event.pos()
            self.column_menu(view, table, watched.logicalIndexAt(point), watched.mapToGlobal(point))
            return True
        return super().eventFilter(watched, event)

    def column_menu(self, view, table, column, point):
        if column < 0 or self.plan is None:
            return
        frame = {"order": self.plan.order_frame, "reference": self.reference, "raw": self.raw}[table]
        if column >= len(frame.columns):
            return
        name = str(frame.columns[column])
        menu = QMenu(self)
        asc, desc = menu.addAction(f"Sort {name} ascending"), menu.addAction(f"Sort {name} descending")
        filter_action = menu.addAction(f"Filter {name}…")
        remove = menu.addAction(f"Clear filter for {name}")
        action = menu.exec(point)
        if action is None:
            return
        if action in (asc, desc):
            request = ("sort", action == desc)
        elif action == remove:
            request = ("clear", False)
        elif action == filter_action:
            request = ("filter", False)
        else:
            return
        # The header is still dispatching its own context-menu signal here.
        # Replacing the paired-table models inside it crashes Qt on Windows, so
        # the chosen action is applied once the menu handler has returned.
        QTimer.singleShot(
            0, lambda: self.apply_column_request(table, name, frame, request)
        )

    def apply_column_request(self, table, name, frame, request):
        kind, descending = request
        if kind == "sort":
            specs = [s for s in self.state["sort"] if (s["table"], s["column"]) != (table, name)]
            specs.append({"table": table, "column": name, "descending": descending})
            self.change("sort", specs)
        elif kind == "clear":
            self.change("filters", [s for s in self.state["filters"] if (s["table"], s["column"]) != (table, name)])
        elif kind == "filter":
            specs = [s for s in self.state["filters"] if (s["table"], s["column"]) != (table, name)]
            current = next((s for s in self.state["filters"] if (s["table"], s["column"]) == (table, name)), {})
            dialog = ColumnFilterDialog(name, frame[name], current, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.removed:
                    self.change("filters", specs)
                    return
                try:
                    specs.append({"table": table, "column": name, **dialog.specification()})
                    self.change("filters", specs)
                except ValueError as error:
                    QMessageBox.warning(self, "Invalid filter", str(error))

    def entered_flags(self):
        values = []
        for (row, column), value in sorted(self.order_model.cells.items()):
            if row > 0 and column == 0:
                try:
                    values.append(flag_value(value))
                except ValueError:
                    pass  # Invalid cells still block Apply, but not correction of head names.
        return [flag for flag in flag_order(values) if flag]

    def edit_names(self):
        flags = self.entered_flags()
        if not flags:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("TestFlag → head names")
        layout = QFormLayout(dialog)
        fields = {flag: QLineEdit(self.state["head_names"].get(flag, f"TestFlag {flag}")) for flag in flags}
        for flag, field in fields.items():
            layout.addRow(f"TestFlag {flag}", field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            names = {flag: field.text().strip() for flag, field in fields.items()}
            if not all(names.values()) or len(set(names.values())) != len(names):
                QMessageBox.warning(self, "Head names", "Use a distinct, non-empty name for each TestFlag.")
                return
            self.change("head_names", {**self.state["head_names"], **names})

    def edit_group_order(self):
        if self.plan is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Trend group order")
        layout = QVBoxLayout(dialog)
        values = QListWidget()
        values.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        for key in self.plan.group_keys:
            item = QListWidgetItem(self.plan.label(key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            values.addItem(item)
        layout.addWidget(values)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            ordered = [values.item(i).data(Qt.ItemDataRole.UserRole) for i in range(values.count())]
            self.change("group_order", ordered + [key for key in self.state["group_order"] if key not in ordered])

    def mark_new(self):
        if self.plan is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Marks")
        dialog.resize(760, 700)
        layout = QVBoxLayout(dialog)
        picker = QPushButton(" / ".join(self.plan.identity_columns) or "Select grouping columns")
        menu = QMenu(picker)
        columns = [c for c in self.raw if normalized(c) not in {"dieseq", "fieldx", "fieldy", "xmm", "ymm", "testflag"}
                   and "path" not in str(c).lower()
                   and (pd.to_numeric(self.raw[c], errors="coerce").isna().any()
                        or any(word in normalized(c) for word in ("wafer", "lot", "pad", "run", "batch", "tool", "recipe")))]
        for column in columns:
            action = menu.addAction(str(column))
            action.setCheckable(True)
            action.setChecked(column in self.plan.identity_columns)
        picker.setMenu(menu)
        layout.addWidget(picker)
        search = QLineEdit(placeholderText="Find wafer / lot / PAD…", objectName="markSearch")
        layout.addWidget(search)
        # The first Mark also catches wafers without an explicit assignment, so a
        # two-name vocabulary is still a binary classification.
        marks = QTreeWidget(objectName="markValues")
        marks.setColumnCount(2)
        marks.setHeaderLabels(["Mark", "Fallback"])
        marks.setToolTip("One Mark per wafer. The ✓ row also catches wafers without an explicit "
                         "assignment; rename it to label that bucket.")
        marks.setRootIsDecorated(False)
        marks.setUniformRowHeights(True)
        marks.setMaximumHeight(170)
        marks.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        for spec in self.state["mark_values"]:
            item = QTreeWidgetItem([spec["name"], ""])
            item.setData(0, Qt.ItemDataRole.UserRole, spec["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            marks.addTopLevelItem(item)
        layout.addWidget(marks)
        mark_bar = QHBoxLayout()
        add_mark = QPushButton("Add Mark", objectName="addMark")
        delete_mark = QPushButton("Delete Mark", objectName="deleteMark")
        mark_bar.addWidget(add_mark)
        mark_bar.addWidget(delete_mark)
        mark_bar.addStretch()
        layout.addLayout(mark_bar)

        assignments = QTreeWidget(objectName="markAssignments")
        assignments.setColumnCount(2)
        assignments.setHeaderLabels(["Measurement set", "Mark"])
        assignments.setRootIsDecorated(False)
        assignments.setUniformRowHeights(True)
        assignments.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(assignments, 1)
        batch = QHBoxLayout()
        batch_mark = QComboBox(objectName="markVisible")
        batch_mark.setEditable(True)
        apply_visible = QPushButton("Assign Visible", objectName="assignVisibleMark")
        batch.addWidget(batch_mark, 1)
        batch.addWidget(apply_visible)
        layout.addLayout(batch)
        chosen = list(self.plan.identity_columns)
        original = {self.plan.ids[i]: self.plan.marks[i] for i in range(len(self.raw))}
        edited = set()
        draft_names = {}
        name_lookup = {}
        combos = []
        anchor = [None]
        rebuilding = False

        def mark_specs():
            return [{"id": marks.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole),
                     "name": marks.topLevelItem(i).text(0).strip()}
                    for i in range(marks.topLevelItemCount())]

        def names_by_id():
            return {spec["id"]: spec["name"] for spec in mark_specs() if spec["name"]}

        def refresh_visible_columns():
            nonlocal name_lookup
            fallback_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            blocker = QSignalBlocker(marks)
            for i in range(marks.topLevelItemCount()):
                item = marks.topLevelItem(i)
                item.setIcon(1, fallback_icon if i == 0 else QIcon())
                item.setToolTip(1, "Wafers without an explicit assignment fall into this Mark."
                                if i == 0 else "")
            del blocker
            by_id = names_by_id()
            names = list(by_id.values())
            fallback = names[0] if names else ""
            for _item, combo in combos:
                text = combo.currentText().strip()
                previous_id = name_lookup.get(text.casefold())
                target = by_id.get(previous_id) if previous_id else None
                if target is None:
                    target = text if text in names else fallback
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(target)
                combo.blockSignals(False)
            name_lookup = {name.casefold(): spec_id for spec_id, name in by_id.items()}
            text = batch_mark.currentText().strip()
            batch_mark.blockSignals(True)
            batch_mark.clear()
            batch_mark.addItems(names)
            batch_mark.setCurrentText(text if text in names else (names[-1] if names else ""))
            batch_mark.blockSignals(False)

        def apply_search():
            needle = search.text().lower()
            for i in range(assignments.topLevelItemCount()):
                item = assignments.topLevelItem(i)
                item.setHidden(needle not in item.text(0).lower())

        def touched(ids, text):
            if rebuilding:
                return
            for identifier in ids:
                edited.add(identifier)
                draft_names[identifier] = str(text).strip()

        def rebuild():
            nonlocal chosen, rebuilding
            rebuilding = True
            chosen = [action.text() for action in menu.actions() if action.isChecked()]
            state = {**self.state, "identity_columns": chosen}
            state.pop("applied", None)
            plan = GroupPlan(self.raw, self.flags_frame(), state, self.reference)
            names = names_by_id()
            fallback = next(iter(names), "")
            assignments.clear()
            combos.clear()
            for measurement in plan.measurements:
                ids = [plan.ids[row] for row in measurement.rows]
                current = draft_names.get(ids[0]) if ids else None
                if current not in names:
                    current = next(
                        (names[original[identifier]] for identifier in ids if original.get(identifier) in names),
                        fallback,
                    )
                label = measurement.label.replace("\n", " / ")
                flags = ", ".join(dict.fromkeys(plan.head(plan.flags[row]) for row in measurement.rows))
                item = QTreeWidgetItem([label, ""])
                item.setData(0, Qt.ItemDataRole.UserRole, ids)
                item.setToolTip(0, f"{label}\n{len(ids):,} records · {flags}")
                assignments.addTopLevelItem(item)
                combo = QComboBox()
                combo.setEditable(True)
                combo.addItems([spec["name"] for spec in mark_specs() if spec["name"]])
                combo.setCurrentText(current if current else fallback)
                combo.currentTextChanged.connect(
                    lambda text, ids=ids: touched(ids, text))
                assignments.setItemWidget(item, 1, combo)
                combos.append((item, combo))
            picker.setText(" / ".join(chosen) or "Select grouping columns")
            apply_search()
            rebuilding = False

        def add_mark_value():
            used = {spec["id"] for spec in mark_specs()}
            index = 1
            while f"m{index}" in used:
                index += 1
            item = QTreeWidgetItem([f"Mark {index}", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, f"m{index}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            marks.addTopLevelItem(item)
            marks.setCurrentItem(item)
            marks.editItem(item, 0)
            refresh_visible_columns()

        def delete_mark_value():
            item = marks.currentItem()
            if item is None or marks.topLevelItemCount() <= 1:
                return
            marks.takeTopLevelItem(marks.indexOfTopLevelItem(item))
            refresh_visible_columns()

        def assign_visible():
            name = batch_mark.currentText().strip()
            names = [spec["name"] for spec in mark_specs() if spec["name"]]
            if not name or name not in names:
                return
            for item, combo in combos:
                if item.isHidden():
                    continue
                touched(item.data(0, Qt.ItemDataRole.UserRole), name)
                combo.setCurrentText(name)

        def row_pressed(item, column):
            if column != 0 or item is None:
                return
            previous = anchor[0]
            if (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
                    and previous is not None and previous is not item):
                source = next((combo for candidate, combo in combos if candidate is previous), None)
                if source is not None:
                    value = source.currentText().strip()
                    first, last = sorted((assignments.indexOfTopLevelItem(previous),
                                          assignments.indexOfTopLevelItem(item)))
                    for index in range(first, last + 1):
                        target = assignments.topLevelItem(index)
                        target_combo = assignments.itemWidget(target, 1)
                        if target.isHidden() or target_combo is None:
                            continue
                        touched(target.data(0, Qt.ItemDataRole.UserRole), value)
                        target_combo.setCurrentText(value)
            else:
                anchor[0] = item

        def validate():
            specs = mark_specs()
            names = [spec["name"] for spec in specs]
            if not specs or not all(names) or len({name.casefold() for name in names}) != len(names):
                QMessageBox.warning(dialog, "Marks", "Use one or more unique, non-empty Mark names.")
                return False
            return True

        def confirm():
            if validate():
                dialog.accept()

        marks.itemChanged.connect(lambda *_: refresh_visible_columns())
        add_mark.clicked.connect(add_mark_value)
        delete_mark.clicked.connect(delete_mark_value)
        apply_visible.clicked.connect(assign_visible)
        assignments.itemPressed.connect(row_pressed)
        search.textChanged.connect(apply_search)
        for action in menu.actions():
            action.toggled.connect(rebuild)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(confirm)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        refresh_visible_columns()
        rebuild()
        dialog.exec()
        if dialog.result() != QDialog.DialogCode.Accepted:
            return
        specs = mark_specs()
        fallback = specs[0]["id"]
        known = {spec["id"] for spec in specs}
        by_name = {spec["name"].casefold(): spec["id"] for spec in specs}
        generated = {}
        final = {}
        for item, combo in combos:
            ids = item.data(0, Qt.ItemDataRole.UserRole)
            text = combo.currentText().strip()
            key = text.casefold()
            mark_id = by_name.get(key)
            if mark_id is None and text:
                if key not in generated:
                    used = {spec["id"] for spec in specs} | set(generated.values())
                    index = len(specs) + 1
                    while f"m{index}" in used:
                        index += 1
                    generated[key] = f"m{index}"
                    specs.append({"id": generated[key], "name": text})
                mark_id = generated[key]
                by_name[key] = mark_id
            for identifier in ids:
                if mark_id is not None and identifier in edited:
                    final[identifier] = mark_id
                elif identifier in original:
                    previous = original[identifier]
                    final[identifier] = previous if previous in known else fallback
        rows = {}
        for identifier, mark_id in final.items():
            if mark_id != fallback:
                rows.setdefault(mark_id, []).append(identifier)
        old_names = {spec["id"]: spec["name"] for spec in self.state["mark_values"]}
        new_names = {spec["id"]: spec["name"] for spec in specs}
        renamed_marks = {old: new_names[key] for key, old in old_names.items() if key in new_names}
        renamed_groups = {}
        for key, old in old_names.items():
            new = new_names.get(key)
            if new is None or new == old:
                continue
            renamed_groups[old] = new
            for flag in dict.fromkeys(self.plan.flags):
                renamed_groups[f"{old} {self.plan.head(flag)}"] = f"{new} {self.plan.head(flag)}"
        for spec in self.state["filters"]:
            if spec.get("table") == "order" and spec.get("values") is not None:
                renames = {"Mark": renamed_marks, "Group": renamed_groups}.get(spec.get("column"), {})
                spec["values"] = [renames.get(value, value) for value in spec["values"]]
        self.state["identity_columns"] = chosen
        self.change("mark_values", [dict(spec) for spec in specs])
        self.change("mark_rows", {key: sorted(value) for key, value in rows.items()})

    def import_combined(self):
        matrix = clipboard_rows(QApplication.clipboard().text())
        if len(matrix) < 2:
            QMessageBox.warning(self, "Import combined", "Copy a table including its header first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Assign combined-table columns")
        dialog.resize(640, 600)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(matrix[0]), 2)
        table.setHorizontalHeaderLabels(["Source column", "Destination"])
        pickers = []
        for i, name in enumerate(matrix[0]):
            table.setItem(i, 0, QTableWidgetItem(f"{i + 1}: {name or '(blank)'}"))
            picker = QComboBox()
            picker.addItems(["Ignore", "TestFlag", "Reference", "Raw Data"])
            picker.setCurrentText("TestFlag" if normalized(name) == "testflag" else "Raw Data" if name.strip() else "Ignore")
            pickers.append(picker)
            table.setCellWidget(i, 1, picker)
        table.setColumnWidth(0, 380)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                frames = split_combined_table(matrix, [picker.currentText() for picker in pickers])
                self.combined_imported.emit(*frames)
            except ValueError as error:
                QMessageBox.warning(self, "Import combined", str(error))


def split_combined_table(matrix, destinations):
    output = []
    for role in ("Reference", "Raw Data", "TestFlag"):
        indices = [i for i, destination in enumerate(destinations) if destination == role]
        if not indices or (role == "TestFlag" and len(indices) != 1):
            raise ValueError("Choose Reference and Raw Data columns, and exactly one TestFlag column.")
        names = [str(matrix[0][i]).strip() for i in indices]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate names in {role}; assign the Reference column separately.")
        frame = pd.DataFrame([[row[i] if i < len(row) else "" for i in indices] for row in matrix[1:]], columns=names)
        if role == "TestFlag":
            frame.columns = ["TestFlag"]
            for value in frame["TestFlag"]:
                flag_value(value)
        output.append(frame)
    return tuple(output)


class GroupLabelAxis(pg.AxisItem):
    """Solid boundaries extend through the separate group-label strip."""
    def __init__(self, *, boundary_width=2):
        super().__init__(orientation="bottom")
        self.boundaries = []
        self.boundary_width = boundary_width

    def paint(self, painter, *args):
        super().paint(painter, *args)
        view = self.linkedView()
        if view is None:
            return
        low, high = view.viewRange()[0]
        for position in self.boundaries:
            if low <= position <= high:
                x = self.mapFromScene(view.mapViewToScene(QPointF(position, 0))).x()
                if self.boundary_width == 2 and QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 128:
                    painter.setPen(pg.mkPen("#eeeeee", width=4))
                    painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
                # Align in device pixels too: fractional Windows display scales
                # otherwise give identical pens alternating one/two-pixel edges.
                transform = painter.deviceTransform()
                inverse, invertible = transform.inverted()
                if not invertible:
                    continue
                device_x = transform.map(QPointF(x, 0)).x()
                left = np.ceil(transform.map(QPointF(self.boundingRect().left(), 0)).x())
                right = np.floor(transform.map(QPointF(self.boundingRect().right(), 0)).x()) - self.boundary_width
                device_x = min(max(round(device_x - self.boundary_width / 2), left), right)
                top = transform.map(QPointF(0, 0)).y()
                bottom = transform.map(QPointF(0, self.height())).y()
                painter.fillRect(QRectF(inverse.map(QPointF(device_x, top)),
                                        inverse.map(QPointF(device_x + self.boundary_width, bottom))),
                                 QColor("#000000" if self.boundary_width == 2 else "#929292"))


def _group_boundary(plot, position):
    line = pg.InfiniteLine(position, angle=90, pen=pg.mkPen("#000000", width=2, style=Qt.PenStyle.DashLine))
    if plot.palette().color(QPalette.ColorRole.Base).lightness() < 128:
        halo = pg.InfiniteLine(position, angle=90, pen=pg.mkPen("#eeeeee", width=4, style=Qt.PenStyle.DashLine))
        halo.setZValue(5)
        plot.addItem(halo, ignoreBounds=True)
        line.contrast_halo = halo
    line.setZValue(6)
    line.setToolTip("Group boundary")
    plot.addItem(line, ignoreBounds=True)
    return line


def set_group_axes(plot, result, data, *, show_wafers=False):
    """Sparse Die Seq; Group labels only for Group order, with optional wafer detail."""
    plan = result.group_plan
    row_order = plan.state["trend_order"] == "original"
    rows = data["Source row"].tolist()
    groups = data["Group"].tolist()
    starts = [0] + [i for i in range(1, len(groups)) if groups[i] != groups[i - 1]] + [len(groups)]
    spans = [(start + .5, end + .5, plan.label(groups[start], multiline=True))
             for start, end in zip(starts, starts[1:]) if start < end]
    wafer_spans, wafer_tooltips = [], []
    if row_order:
        spans = []
    elif show_wafers:
        offset = 0
        names = {normalized(column): column for column in plan.raw}
        fields = [(label, next((names[key] for key in aliases if key in names), None))
                  for label, aliases in (("Wafer ID", ("waferid", "wafer", "waferno")),
                                         ("Lot ID", ("lotid", "lot", "lotno")),
                                         ("PAD Name", ("padname", "pad")))]
        for span in plan.trend_spans():
            end = offset + len(span["rows"])
            labels, detail = [], []
            for label, column in fields:
                if column is not None:
                    values = plan.raw.iloc[span["rows"]][column].fillna("").astype(str).str.strip()
                    text = ", ".join(dict.fromkeys(value or "(blank)" for value in values))
                    labels.append(text)
                    detail.append(f"{label}: {text}")
            wafer_spans.append((offset + .5, end + .5, "\n".join(labels)))
            wafer_tooltips.append("\n".join(detail))
            offset = end
    die_column = next((c for c in plan.raw if normalized(c) == "dieseq"), None)
    # Only this column is needed. Reading heterogeneous DataFrame rows here
    # rebuilds a Series for every plotted point, repeated across all panels.
    die_values = plan.raw[die_column].to_numpy() if die_column else None
    die = [str(die_values[row]) if die_values is not None else str(row + 1) for row in rows]
    plot._group_tick_data = (die, spans, wafer_spans)
    for line in getattr(plot, "_group_boundaries", []):
        plot.removeItem(line)
        if hasattr(line, "contrast_halo"):
            plot.removeItem(line.contrast_halo)
    plot._group_boundaries = []
    if row_order:
        # Rows keep their input order, so the dashed lines must mark where the
        # wafer itself changes: a Lot or PAD change inside one wafer is not a
        # boundary the engineer can act on.
        wafers = {row: measurement.wafer for measurement in plan.measurements for row in measurement.rows}
        wafer_starts = [i + .5 for i in range(1, len(rows))
                        if wafers.get(rows[i]) != wafers.get(rows[i - 1])]
    else:
        wafer_starts = sorted({start for start, _, _ in spans[1:] + wafer_spans[1:]})
    for start in wafer_starts:
        boundary = int(start - .5)
        if row_order or (show_wafers and groups[boundary] == groups[boundary - 1]):
            line = pg.InfiniteLine(start, angle=90, pen=pg.mkPen("#929292", width=1, style=Qt.PenStyle.DashLine))
            line.setToolTip("Wafer boundary")
            plot.addItem(line, ignoreBounds=True)
        else:
            line = _group_boundary(plot, start)
        plot._group_boundaries.append(line)
    bottom = plot.getAxis("bottom")
    bottom.setHeight(40)
    plot.setLabel("bottom", "Die Seq")
    if not hasattr(plot, "_group_axis"):
        plot._group_axis = GroupLabelAxis()
        plot._group_axis.linkToView(plot.getViewBox())
        plot.getPlotItem().layout.addItem(plot._group_axis, 4, 1)
    if not hasattr(plot, "_wafer_axis"):
        plot._wafer_axis = GroupLabelAxis(boundary_width=1)
        plot._wafer_axis.linkToView(plot.getViewBox())
        layout = plot.getPlotItem().layout
        layout.removeItem(plot._group_axis)
        layout.addItem(plot._wafer_axis, 4, 1)
        layout.addItem(plot._group_axis, 5, 1)
    wafer_axis = plot._wafer_axis
    wafer_axis.setVisible(bool(wafer_spans))
    wafer_axis.boundaries = sorted({value for start, end, _ in wafer_spans for value in (start, end)})
    wafer_axis.update()
    wafer_axis.setStyle(tickLength=0, tickFont=plot.font(), tickTextOffset=3)
    wafer_axis.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
    wafer_axis.setTextPen(bottom.textPen())
    wafer_axis.setToolTip(" · ".join(wafer_tooltips))
    axis = plot._group_axis
    axis.setVisible(not row_order)
    axis.boundaries = sorted({value for start, end, _ in spans for value in (start, end)})
    axis.update()
    axis.setStyle(tickLength=0, tickFont=plot.font(), tickTextOffset=3)
    axis.setHeight(0 if row_order else max((label.count("\n") + 1 for _, _, label in spans), default=2) * QFontMetrics(plot.font()).height() + 8)
    axis.setToolTip("" if row_order else "Groups: " + " · ".join(label for _, _, label in spans))
    axis.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
    axis.setTextPen(bottom.textPen())
    if not hasattr(plot, "_refresh_group_axis"):
        def refresh(*_):
            die, spans, wafer_spans = plot._group_tick_data
            low, high = plot.getViewBox().viewRange()[0]
            width = max(1., plot.getViewBox().sceneBoundingRect().width())
            scale = width / max(1e-9, high - low)
            metrics = QFontMetrics(plot.font())
            def sparse(candidates):
                kept, edge = [], -float("inf")
                for position, label in candidates:
                    pixel = (position - low) * scale
                    half = max((metrics.horizontalAdvance(line) for line in label.splitlines()), default=0) / 2
                    if label and pixel - half >= max(0, edge + 8) and pixel + half <= width:
                        kept.append((position, label))
                        edge = pixel + half
                return kept
            first, last = max(0, ceil(low) - 1), min(len(die) - 1, int(high) - 1)
            count = min(max(0, last - first + 1), max(2, int(width / 45)))
            indices = np.unique(np.linspace(first, last, count, dtype=int)) if count else []
            ticks = sparse([(int(i) + 1, die[i]) for i in indices])
            if count and not ticks:
                middle = (first + last) // 2
                ticks = sparse([(middle + 1, die[middle])])
            bottom.setTicks([ticks])
            labels = []
            for start, end, label in spans:
                start, end = max(low, start), min(high, end)
                if end > start:
                    # Thin whole Group labels at narrow widths instead of
                    # reducing every group to an indistinguishable ellipsis.
                    available = max(40, int(width / 2 - 8))
                    text = "\n".join(metrics.elidedText(line, Qt.TextElideMode.ElideMiddle, available)
                                     for line in label.splitlines())
                    labels.append(((start + end) / 2, text))
            plot._group_axis.setTicks([sparse(labels)])
            wafer_labels = []
            for start, end, label in wafer_spans:
                start, end = max(low, start), min(high, end)
                available = int((end - start) * scale - 8)
                if available < 16 or not label:
                    continue
                values = label.splitlines()
                # Each identity stays inside its own wafer segment. Secondary
                # metadata is optional at narrow widths, never overlapped.
                text = [metrics.elidedText(values[0], Qt.TextElideMode.ElideMiddle, available)]
                text.extend(value for value in values[1:] if metrics.horizontalAdvance(value) <= available)
                wafer_labels.append(((start + end) / 2, "\n".join(text)))
            ticks = sparse(wafer_labels)
            plot._wafer_axis.setTicks([ticks])
            lines = max((text.count("\n") + 1 for _, text in ticks), default=0)
            plot._wafer_axis.setHeight(lines * metrics.height() + 8 if lines else 0)
        plot._refresh_group_axis = refresh
        plot.getViewBox().sigResized.connect(refresh)
        plot.getViewBox().sigRangeChanged.connect(refresh)
    plot._refresh_group_axis()


def draw_group_trend(plot, result, parameter, key="all", card_mode="raw", *, group_only=False):
    """Append measurement spans; keep NaN gaps and the shared Trend chrome."""
    plot.clear()
    legend = place_legend_above_frame(plot)
    legend.clear()
    legend.setZValue(10)
    data = result.group_series(parameter, key, trend=True, card_mode=card_mode)
    plan = result.group_plan
    x = np.arange(1, len(data) + 1, dtype=float)
    reference = plot.plot(x, data["Reference"].to_numpy(float), pen=pg.mkPen("#ed7d31", width=1.5),
              symbol="o", symbolSize=4, symbolBrush="#ed7d31", symbolPen=None,
              name=str(result.match_type), connect="finite")
    reference.setZValue(5)  # Reference stays visible above overlapping Raw/Card curves.
    # Boundaries annotate the ordinal sequence; only missing observations break it.
    groups = data["Group"].tolist()
    starts = [0] + [i for i in range(1, len(groups)) if groups[i] != groups[i - 1]] + [len(groups)]
    plot.plot(x, data["Trend value"].to_numpy(float),
              pen=pg.mkPen("#5b9bd5", width=1.5, style=Qt.PenStyle.DashLine),
              symbol="s", symbolSize=4, symbolBrush="#5b9bd5", symbolPen=None,
              name="PMISH", connect="finite")
    place_legend_above_frame(plot)
    offset, labels, boundaries, previous_group = 0, [], [], None
    for span in plan.trend_spans(key):
        if offset:
            is_group_boundary = groups[offset] != previous_group
            if is_group_boundary:
                line = _group_boundary(plot, offset + .5)
            else:
                line = pg.InfiniteLine(offset + .5, angle=90, pen=pg.mkPen("#929292", style=Qt.PenStyle.DashLine))
                plot.addItem(line, ignoreBounds=True)
            boundaries.append(line)
        labels.append((offset + (len(span["rows"]) + 1) / 2, span["label"]))
        offset += len(span["rows"])
        previous_group = groups[offset - 1]
    plot._group_boundaries = boundaries
    die_column = next((c for c in plan.raw if normalized(c) == "dieseq"), None)
    rows = data["Source row"].tolist()
    die_values = plan.raw[die_column].to_numpy() if die_column else None
    die = [str(die_values[row]) if die_values is not None else str(row + 1) for row in rows]
    positions = np.unique(np.linspace(0, max(0, len(rows) - 1), min(24, len(rows)), dtype=int)) if rows else []
    # Keep long wafer labels sparse at realistic screen widths.
    major = [labels[i] for i in np.unique(np.linspace(0, len(labels) - 1, min(5, len(labels)), dtype=int))] if labels else []
    plot.getAxis("bottom").setTicks([[(int(i) + 1, die[i]) for i in positions]])
    plot.getAxis("bottom").setHeight(30)
    item = plot.getPlotItem()
    group_axis = getattr(plot, "_group_axis", None)
    if group_axis is None:
        group_axis = GroupLabelAxis()
        group_axis.linkToView(plot.getViewBox())
        group_axis.setStyle(tickLength=0)
        item.layout.addItem(group_axis, 4, 1)
        plot._group_axis = group_axis
    group_axis.setTicks([major])
    group_axis.boundaries = [float(i) + .5 for i in starts]
    group_axis.setHeight(52)
    pen = plot.getAxis("bottom").textPen()
    group_axis.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
    group_axis.setTextPen(pen)
    plot.setLabel("bottom", "Measurement order · Die Seq")
    # The Trend title is the Raw Data column and the Y axis never carries a
    # label; the block heading and the status row already name the scope.
    plot.setLabel("left", "")
    unavailable = data["Trend value"].isna().sum() if card_mode == "group" else 0
    title = result.raw_column(parameter) + (f" · {unavailable} unavailable/missing" if unavailable else "")
    if hasattr(plot, "set_scope_title"):
        plot.set_scope_title(title)
    else:
        plot.setTitle(title)
    if len(data):
        plot.set_auto_x_range((.5, len(data) + .5))
        plot.setXRange(.5, len(data) + .5, padding=0)
    if group_only or plan.state["trend_order"] == "original":
        set_group_axes(plot, result, data)
    elif getattr(plan, "scope_label", ""):
        set_group_axes(plot, result, data, show_wafers=True)
    return data


class _GroupTree(QTreeWidget):
    """Separate native check columns; names retain double-click editing."""
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.setHeaderLabels(["Group", "Show wafer"])
        self.setRootIsDecorated(False)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setItemDelegate(_GroupNameDelegate(self))
        self._clear_anchor()
        self.model().modelReset.connect(self._clear_anchor)
        self.model().rowsRemoved.connect(self._clear_anchor)

    def _clear_anchor(self):
        self._anchor = self._pressed = None

    def mousePressEvent(self, event):
        self._pressed = self.itemAt(event.position().toPoint()) if event.button() == Qt.MouseButton.LeftButton else None
        self._column = self.columnAt(int(event.position().x()))
        self._before = self._pressed.data(self._column, Qt.ItemDataRole.CheckStateRole) if self._pressed else None
        self._shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._pressed and self._shift and self._before is not None:
            self.setCurrentItem(self._pressed, self._column)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or item is None or item is not self._pressed or self._before is None:
            super().mouseReleaseEvent(event)
            return
        column = self._column
        if self._shift and self._anchor is not None and self._anchor[1] == column:
            anchor = self.topLevelItem(self._anchor[0])
            state = anchor.checkState(column)
            first, last = sorted((self._anchor[0], self.indexOfTopLevelItem(item)))
            for row in range(first, last + 1):
                self.topLevelItem(row).setCheckState(column, state)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            if item.data(column, Qt.ItemDataRole.CheckStateRole) == self._before:
                item.setCheckState(column, Qt.CheckState.Unchecked if item.checkState(column) == Qt.CheckState.Checked else Qt.CheckState.Checked)
            self._anchor = (self.indexOfTopLevelItem(item), column)
        self._pressed = None


class _GroupNameDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return super().createEditor(parent, option, index) if index.column() == 0 else None


class CombinedGroupDialog(QDialog):
    """Edit combined Group rows against fixed base Groups, committing on Apply."""
    def __init__(self, plan, parent=None):
        super().__init__(parent, objectName="combinedGroupEditor")
        self.setWindowTitle("Manage combined Groups")
        fit_window_to_screen(self, (720, 620), minimum=(520, 460))
        self.plan = plan
        self.groups = deepcopy(plan.state["combined_groups"])
        self.show_wafer_groups = set(plan.state["show_wafer_groups"])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Base Groups (fixed)", objectName="panelTitle"))
        self.members = _GroupTree(objectName="combinedGroupMembers")
        self.members.setMinimumHeight(100)
        self.members.setMaximumHeight(240)
        keys = list(plan.group_keys)
        for spec in self.groups:
            keys.extend(key for key in spec["members"] if key not in keys)
        for key in keys:
            item = QTreeWidgetItem([plan.label(key) + (" · inactive" if not plan.rows(key) else ""), ""])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self._set_wafer_checkbox(item, key)
            item.setSizeHint(0, QSize(0, 30))
            self.members.addTopLevelItem(item)
        self.members.setMinimumHeight(min(240, self.members.topLevelItemCount() * 36 + 44))
        layout.addWidget(self.members, 1)
        row_header = QHBoxLayout()
        row_header.addWidget(QLabel("Combined Groups", objectName="panelTitle"))
        row_header.addStretch()
        add = QPushButton("Add", objectName="addCombinedGroup")
        add.clicked.connect(self.add_group)
        row_header.addWidget(add)
        self.delete_button = QPushButton("Delete Group")
        self.delete_button.clicked.connect(self.delete_group)
        row_header.addWidget(self.delete_button)
        layout.addLayout(row_header)
        self.combined_list = _GroupTree(objectName="combinedGroupsList")
        self.combined_list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        for spec in self.groups:
            self._add_group_row(spec)
        layout.addWidget(self.combined_list, 2)
        self.error = QLabel("", objectName="hint")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.combined_list.currentItemChanged.connect(self.load_group)
        self.combined_list.itemChanged.connect(self.edit_group)
        self.members.itemChanged.connect(self.update_members)
        if self.groups:
            self.combined_list.setCurrentItem(self.combined_list.topLevelItem(0))
        else:
            self.load_group()

    def _add_group_row(self, spec):
        item = QTreeWidgetItem([spec["name"], ""])
        item.setData(0, Qt.ItemDataRole.UserRole, spec["id"])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setSizeHint(0, QSize(0, 34))
        self._set_wafer_checkbox(item, spec["id"])
        self.combined_list.addTopLevelItem(item)
        return item

    def _set_wafer_checkbox(self, item, key):
        item.setCheckState(1, Qt.CheckState.Checked if key in self.show_wafer_groups else Qt.CheckState.Unchecked)
        item.setToolTip(1, "Show Wafer ID, Lot ID and PAD Name in this Group's Trend and Bias plots. Apply to update.")

    def _update_wafer_checkbox(self, item):
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if item.checkState(1) == Qt.CheckState.Checked:
            self.show_wafer_groups.add(key)
        else:
            self.show_wafer_groups.discard(key)

    def _current_group(self):
        item = self.combined_list.currentItem()
        return next((s for s in self.groups if item is not None and s["id"] == item.data(0, Qt.ItemDataRole.UserRole)), None)

    def add_group(self):
        names = {self.plan.label(k).casefold() for k in self.plan.group_keys}
        names.update(s["name"].strip().casefold() for s in self.groups)
        number = 1
        while f"combined group {number}" in names:
            number += 1
        spec = {"id": "combined:" + uuid4().hex, "name": f"Combined Group {number}", "members": []}
        self.groups.append(spec)
        self.combined_list.setCurrentItem(self._add_group_row(spec))
        self.error.clear()

    def load_group(self, *_):
        spec = self._current_group()
        self.delete_button.setEnabled(spec is not None)
        self.members._clear_anchor()
        with QSignalBlocker(self.members):
            for row in range(self.members.topLevelItemCount()):
                item = self.members.topLevelItem(row)
                if spec is None:
                    item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
                else:
                    item.setCheckState(0, Qt.CheckState.Checked if item.data(0, Qt.ItemDataRole.UserRole) in spec["members"] else Qt.CheckState.Unchecked)

    def edit_group(self, item, column):
        if column == 1:
            self._update_wafer_checkbox(item)
        else:
            spec = next(s for s in self.groups if s["id"] == item.data(0, Qt.ItemDataRole.UserRole))
            spec["name"] = item.text(0)
        self.error.clear()

    def update_members(self, item, column):
        if column == 1:
            self._update_wafer_checkbox(item)
            return
        spec = self._current_group()
        if spec is not None:
            spec["members"] = [self.members.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.members.topLevelItemCount())
                               if self.members.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
            self.error.clear()

    def delete_group(self):
        item = self.combined_list.currentItem()
        if item is not None:
            self.show_wafer_groups.discard(item.data(0, Qt.ItemDataRole.UserRole))
            self.groups = [spec for spec in self.groups if spec["id"] != item.data(0, Qt.ItemDataRole.UserRole)]
            self.combined_list.takeTopLevelItem(self.combined_list.indexOfTopLevelItem(item))
            self.error.clear()

    def accept(self):
        names = {self.plan.label(k).casefold() for k in self.plan.group_keys}
        for row, spec in enumerate(self.groups):
            name = spec["name"].strip()
            if not name or name.casefold() in names or len(set(spec["members"])) < 2:
                self.combined_list.setCurrentItem(self.combined_list.topLevelItem(row))
                self.error.setText("Use a unique, non-empty name and check at least two base Groups for each row.")
                return
            names.add(name.casefold())
        for spec in self.groups:
            spec["name"] = spec["name"].strip()
        super().accept()


class GroupPlotPage(QWidget):
    """Group scopes rendered through shared parameter blocks in one scroll area."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workbook_window = parent
        self.result = None
        self._panels = {}
        self.plot_groups = {}
        self.parameter_sections = {}
        self.scopes = {}
        self.block_order = []
        self._restored = None
        self._render_pending = False
        layout = QVBoxLayout(self)
        self.card = QCheckBox("Apply Card to Trend")
        self.card.setChecked(True)
        self.use_group_card = parent.group_controls.card
        self.use_group_card.setParent(self)
        self.use_group_card.show()
        self.use_group_card.setToolTip("Checked: this Group's Card (a combined Group fits its own Card).\nUnchecked: the corresponding All parameter plots Card. Data scope never changes.")
        self.use_group_card.toggled.connect(self.card_source_changed)
        self.status = QLabel(objectName="hint")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status.setWordWrap(True)
        options = QHBoxLayout()
        for widget in (self.card, self.use_group_card):
            options.addWidget(widget)
        options.addWidget(self.status, 1)
        layout.addLayout(options)
        self.canvas = QWidget()
        self.plots = QVBoxLayout(self.canvas)
        self.plots.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        self.scroll.hide()
        layout.addWidget(self.scroll, 1)
        self.card.toggled.connect(self.trend_card_changed)

    def set_result(self, result):
        previous = self.result
        if self._restored is None and (self.result is None or self.result.result_mode != result.result_mode):
            self.card.blockSignals(True)
            self.card.setChecked(result.result_mode == "preview")
            self.card.blockSignals(False)
        self.result = result
        plan = result.group_plan
        keys = list(plan.plot_group_keys) if plan.enabled else []
        structure_changed = (previous is None or previous.result_mode != result.result_mode
                             or previous.match_type != result.match_type
                             or previous.parameter_names != result.parameter_names
                             or set(self.scopes) != set(keys))
        self.scopes = {key: (plan.label(key), plan.rows(key)) for key in keys}
        self._restored = None
        if self._panels and not structure_changed and self.workbook_window.isVisible() and not self.isVisible():
            # Keep the latest result, not a queue of obsolete hidden redraws.
            # All scopes are still drawn on show/export; source analysis itself
            # remains current while the engineer edits another results tab.
            self._render_pending = True
            owner = self.workbook_window
            for key in self.scopes:
                for parameter in result.parameter_names:
                    owner._trend_card_state.setdefault(
                        (result.result_mode, f"group-plots:{key}:{parameter}"), self.card.isChecked())
            self._update_status()
            return
        self.render()

    def showEvent(self, event):
        super().showEvent(event)
        if self._render_pending:
            self.render()

    def _update_status(self):
        mode = "group" if self.use_group_card.isChecked() else "global"
        count = len(self.scopes) * len(self.result.parameter_names)
        self.status.setText(f"{count} plot blocks · Calibration: {mode} Card · Match fits only the displayed Group.")

    def card_source_changed(self, checked):
        controls = self.workbook_window.group_controls
        if controls._loading:
            return
        controls.state["use_group_card"] = bool(checked)
        controls.state.setdefault("applied", {})["use_group_card"] = bool(checked)
        self.render()
        self.changed.emit()

    def scope_label(self, key):
        return self.scopes[key][0]

    def render(self):
        if self.result is None:
            return
        self._render_pending = False
        scroll = self.scroll.verticalScrollBar().value()
        owner = self.workbook_window
        parameters = owner._reconciled_parameter_order(self.result.parameter_names)
        cells = [(key, parameter) for parameter in parameters for key in self.scopes]
        cells.sort(key=lambda cell: (parameters.index(cell[1]),
                                    self.block_order.index(cell) if cell in self.block_order else len(self.block_order)))
        mode = "group" if self.use_group_card.isChecked() else "global"
        visible = cells
        for cell in tuple(self._panels):
            if cell not in visible:
                panel = self._panels.pop(cell)[0]
                self.plot_groups.pop(cell, None)
                panel.parentWidget().layout().removeWidget(panel)
                panel.deleteLater()
        for parameter in tuple(self.parameter_sections):
            if parameter not in parameters or not self.scopes:
                section = self.parameter_sections.pop(parameter)
                self.plots.removeWidget(section)
                section.deleteLater()
        for parameter in parameters:
            if self.scopes and parameter not in self.parameter_sections:
                self.parameter_sections[parameter] = owner._create_parameter_section(parameter)
                self.plots.addWidget(self.parameter_sections[parameter])
        # A scope fits every mapped parameter. Prepare it once per Group for
        # this render, not once per Group × parameter; discard it next render
        # so edited sources/Card mode cannot reuse stale coefficients.
        scopes = {}
        for key, parameter in visible:
            section_layout = self.parameter_sections[parameter].layout()
            position = 1 + [cell for cell in visible if cell[1] == parameter].index((key, parameter))
            label, rows = self.scopes[key]
            show_wafers = key in self.result.group_plan.state["show_wafer_groups"]
            if key not in scopes:
                scopes[key] = self.result.plot_scope(rows, local_card=mode == "group", label=label)
                scopes[key].group_plan.card_source_label = "Group Card" if mode == "group" else "All parameter plots Card"
            scoped = scopes[key]
            data = scoped.group_series(parameter, trend=True, card_mode="global")
            owner = self.workbook_window
            card_key = (self.result.result_mode, f"group-plots:{key}:{parameter}")
            trend_card = owner._trend_card_state.get(card_key, self.card.isChecked())
            signature = (label, mode, trend_card, show_wafers, scoped.group_plan.state["trend_order"], scoped.group_plan.trend_spans(),
                         owner._selected_bias_views(), owner.workbook.mappings, self.result.result_mode, self.result.match_type)
            previous = self._panels.get((key, parameter))
            if previous is not None and previous[1].equals(data) and previous[2] == signature:
                section_layout.insertWidget(position, previous[0])
                continue
            block = self.plot_groups.get((key, parameter))
            if block is not None and (block["trend_card_key"][0] != self.result.result_mode
                    or block["workbook"].match_type != owner.workbook.match_type or tuple(block["plots"]) != tuple(
                    ["match", "trend"] + (["bias"] if owner.absolute_bias.isChecked() else [])
                    + (["bias-percent"] if owner.percent_bias.isChecked() else []))):
                section_layout.removeWidget(block["card"])
                block["card"].deleteLater()
                block = None
            if block is None:
                block = owner._create_plot_group(parameter, detail_key=f"group-plots:{key}:{parameter}")
                self.plot_groups[(key, parameter)] = block
                block["card"].workspace = self
                block["plot_area"].layoutChanged.connect(
                    lambda target=block: target["card"].setFixedHeight(54 + target["plot_area"].height()))
                checkbox = block["plots"]["trend"].card_checkbox
                checkbox.toggled.connect(lambda checked, target=block, name=parameter:
                    self.block_card_changed(name, target, checked))
            panel = block["card"]
            heading = panel.layout().itemAt(0).layout().itemAt(0).widget()
            heading.setText(f"⋮⋮  {label}")
            block.update(result=scoped, workbook=owner.workbook, group_scope=True,
                         fit_card=scoped.plot_fits[parameter], show_wafers=show_wafers)
            for plot in block["plots"].values():
                plot.clear()
            checkbox = block["plots"]["trend"].card_checkbox
            checkbox.blockSignals(True)
            checkbox.setChecked(trend_card)
            owner._trend_card_state[card_key] = trend_card
            checkbox.setToolTip(f"Apply the {'Group' if mode == 'group' else 'All parameter plots'} Card to Trend.")
            checkbox.blockSignals(False)
            owner._draw_parameter_group(parameter, block)
            wafers = [measurement.label.replace("\n", " / ") for measurement in scoped.group_plan.measurements
                      if set(measurement.rows) & set(scoped.source_rows)]
            block["note"].setText(f"{len(data):,} rows · {len(wafers)} wafers · {mode} Card")
            if not np.isfinite(block["fit_card"].slope):
                block["note"].setText(block["note"].text() + " · Fit unavailable")
            block["note"].setToolTip("\n".join(wafers))
            panel.setFixedHeight(54 + block["plot_area"].height())
            section_layout.insertWidget(position, panel)
            self._panels[(key, parameter)] = (panel, data.copy(), deepcopy(signature))
        self.apply_parameter_order()
        self._update_status()
        self.scroll.show()
        self.scroll.verticalScrollBar().setValue(scroll)

    def block_card_changed(self, parameter, block, checked):
        self.workbook_window._trend_card_state[block["trend_card_key"]] = bool(checked)
        self.workbook_window._draw_trend_plot(parameter, block)
        self.changed.emit()

    def trend_card_changed(self, checked):
        if self.result is not None:
            for key in self.scopes:
                for parameter in self.result.parameter_names:
                    self.workbook_window._trend_card_state[(self.result.result_mode, f"group-plots:{key}:{parameter}")] = bool(checked)
        self.render()
        self.changed.emit()

    def selection_state(self):
        return {"card": self.card.isChecked(),
                "block_order": [list(cell) for cell in self.block_order]}

    def clear_parameter_drop_previews(self):
        for section in self.parameter_sections.values():
            section._show_drop_position(None)
        for block in self.plot_groups.values():
            block["card"]._show_drop_position(None)

    def apply_parameter_order(self):
        for parameter in self.workbook_window._reconciled_parameter_order(self.parameter_sections):
            section = self.parameter_sections[parameter]
            self.plots.removeWidget(section)
            self.plots.addWidget(section)

    def move_parameter(self, source, target, *, before=True):
        lookup = {block["storage_key"]: cell for cell, block in self.plot_groups.items()}
        if source not in lookup or target not in lookup or source == target:
            return
        if lookup[source][1] != lookup[target][1]:
            return  # Group blocks stay inside their parameter section.
        cells = [(key, parameter) for parameter in self.result.parameter_names for key in self.scopes]
        ordered = [cell for cell in self.block_order if cell in cells] + [cell for cell in cells if cell not in self.block_order]
        cell, target_cell = lookup[source], lookup[target]
        ordered.remove(cell)
        ordered.insert(ordered.index(target_cell) + (not before), cell)
        self.block_order = ordered
        self.render()
        self.changed.emit()

    def restore_state(self, state):
        if not state:
            self._restored = None
            self.block_order = []
            return
        self._restored = deepcopy(state or {})
        self.block_order = [tuple(cell) for cell in self._restored.get("block_order", [])]
        self.card.blockSignals(True)
        self.card.setChecked(self._restored.get("card", True))
        self.card.blockSignals(False)

    def page_image(self):
        if self._render_pending:
            self.render()
        image, scale = widget_to_qimage(self.canvas, 2)
        return image.copy(0, 0, image.width(), min(image.height(), round(self.plots.sizeHint().height() * scale)))

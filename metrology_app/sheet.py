"""Small spreadsheet model: editable cells, range clipboard and undo/redo."""
import csv
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from io import StringIO
from types import MappingProxyType

import pandas as pd
from PyQt6.QtCore import (
    QAbstractProxyModel, QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QFont, QKeySequence, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QStyle, QStyleOptionHeader, QTableView, QToolButton,
)

from .settings import get_settings
from .table_clipboard import ClipboardRangeOutline, copy_selection, selection_bounds


HEADER_COLOURS = {"dark": ("#201629", "#d6b9f5"), "light": ("#f0f0f2", "#18181b")}
CELL_FLAGS = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
              | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemNeverHasChildren)


def header_colours():
    return HEADER_COLOURS.get(get_settings()["theme"], HEADER_COLOURS["dark"])


def column_letter(index):
    result = ""
    while index >= 0:
        result = chr(65 + index % 26) + result
        index = index // 26 - 1
    return result


def clipboard_rows(text):
    if not text:
        return []
    try:
        delimiter = "\t" if "\t" in text else csv.Sniffer().sniff(text, delimiters=",;").delimiter
    except csv.Error:
        delimiter = "\t"
    return list(csv.reader(StringIO(text), delimiter=delimiter))


@dataclass(frozen=True)
class PasteReport:
    """Last clipboard transaction, in source coordinates; never document state."""

    changes: Mapping[tuple[int, int], tuple[str, str]]
    columns: tuple[tuple[int, str, int], ...]
    rows_added: int = 0
    rows_removed: int = 0
    bounds: tuple[int, int, int, int] | None = None

    @property
    def summary(self):
        if not self.changes and not (self.rows_added or self.rows_removed):
            return "No changes — pasted values match the existing table."
        count = len(self.changes)
        parts = [f"Paste complete — {count:,} {'cell' if count == 1 else 'cells'} changed"]
        rows = len({row for row, _ in self.changes if row > 0})
        if rows:
            parts.append(f"{rows:,} data {'row' if rows == 1 else 'rows'}")
        headers = sum(row == 0 for row, _ in self.changes)
        if headers:
            parts.append(f"{headers:,} {'header' if headers == 1 else 'headers'} changed")
        if self.rows_added:
            parts.append(f"{self.rows_added:,} {'row' if self.rows_added == 1 else 'rows'} added")
        if self.rows_removed:
            parts.append(f"{self.rows_removed:,} {'row' if self.rows_removed == 1 else 'rows'} removed")
        names = [f"{name} ({count:,})" for _, name, count in self.columns[:3]]
        if len(self.columns) > 3:
            names.append(f"+{len(self.columns) - 3} more columns")
        if names:
            parts.append(", ".join(names))
        return " · ".join(parts)


class CellEdit(QUndoCommand):
    def __init__(self, model, changes):
        super().__init__("Edit cells")
        self.model = model
        self.before = {cell: model.cells.get(cell, "") for cell in changes}
        self.after = changes
        self.before_rows = model._document_rows
        self.after_rows = max(self.before_rows, max((row for (row, _), value in changes.items() if value), default=0))

    def redo(self):
        self.model._document_rows = self.after_rows
        self.model.apply(self.after)

    def undo(self):
        self.model._document_rows = self.before_rows
        self.model.apply(self.before)


class TableReplace(QUndoCommand):
    """Undoable whole-table replacement behind the Ctrl+Shift+V paste."""

    def __init__(self, model, matrix):
        super().__init__("Replace table")
        self.model = model
        self.before = model.snapshot()
        self.after = model.state_from_matrix(matrix)

    def redo(self):
        self.model.restore(self.after)

    def undo(self):
        self.model.restore(self.before)


class SheetModel(QAbstractTableModel):
    changed = pyqtSignal()
    paste_report_changed = pyqtSignal()
    metadata_locks_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.cells = {}
        self._document_rows = 0
        self._preserves_record_positions = False
        self._frames = {}
        self._extent = None
        self._selection_extent = None
        self._frame_change = None
        self.paste_report = None
        self.clipboard_locks = frozenset()
        self.changed.connect(self._invalidate_frames)
        self.changed.connect(self.clear_paste_report)
        self.height, self.width = 100, 26
        self.undo = QUndoStack(self)
        self._revision = 0

    @property
    def revision(self):
        """Monotonic edit counter; analysis reuse is keyed on it, never on values."""
        return self._revision

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.height

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.width

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return column_letter(section) if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.cells.get((index.row(), index.column()), "")
        change = (self.paste_report.changes.get((index.row(), index.column()))
                  if self.paste_report is not None else None)
        if change is not None:
            if role == Qt.ItemDataRole.ToolTipRole:
                before, after = (escape(text) if text else "(blank)" for text in change)
                return f"<b>Pasted update</b><br>Before: {before}<br>After: {after}"
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            return value
        if index.row() == 0:
            background, foreground = header_colours()
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor(background)
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(foreground)
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setWeight(QFont.Weight.DemiBold)
                return font

    def flags(self, index):
        if index.isValid() and self.cells.get((0, index.column()), "") in self.clipboard_locks:
            return CELL_FLAGS & ~Qt.ItemFlag.ItemIsEditable
        return CELL_FLAGS if index.isValid() else Qt.ItemFlag.ItemIsEditable

    def set_clipboard_locks(self, names):
        """Lock named metadata without modifying source values or row identity."""
        headers = set(self.source_headers())
        names = frozenset(name for name in names if name in headers)
        if names != self.clipboard_locks:
            self.clipboard_locks = names
            self.metadata_locks_changed.emit()

    def range_editable(self, bounds):
        _top, left, _bottom, right = bounds
        return not any(self.cells.get((0, column), "") in self.clipboard_locks
                       for column in range(left, right + 1))

    def merge_clipboard_frame(self, frame):
        """Preserve locked source strings by row position, never infer a join.

        A different row count or ambiguous headers cannot safely carry coordinates
        forward. Reject before changing the source, its Undo history or UI state.
        Explicit file/workbook loads do not use this clipboard-only contract.
        """
        if not self.clipboard_locks:
            return frame
        self.validate_clipboard_frame(frame)
        current = self.document_frame()
        merged = frame.reset_index(drop=True).copy()
        for column in current.columns:
            if column in self.clipboard_locks:
                merged[column] = current[column].to_numpy(copy=True)
        return merged

    def validate_clipboard_frame(self, frame):
        if self.clipboard_locks:
            if len(frame) != self._document_rows:
                raise ValueError("Unlock metadata before pasting a different number of rows.")
            headers = self.source_headers()
            if not frame.columns.is_unique or len(set(headers)) != len(headers):
                raise ValueError("Unlock metadata or fix duplicate column names before pasting.")

    def _merge_clipboard_matrix(self, matrix):
        if not self.clipboard_locks:
            return matrix
        width = max((len(row) for row in matrix), default=0)
        padded = [list(row) + [""] * (width - len(row)) for row in matrix]
        frame = pd.DataFrame(padded[1:], columns=padded[0]) if padded else pd.DataFrame()
        frame = self.merge_clipboard_frame(frame)
        return [list(frame.columns), *frame.values.tolist()]

    @property
    def uniform_selectable(self):
        return type(self).flags is SheetModel.flags and type(self).headerData is SheetModel.headerData

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if not self.flags(index) & Qt.ItemFlag.ItemIsEditable:
            return False
        self.edit({(index.row(), index.column()): str(value)})
        return True

    def edit(self, changes):
        changes = {key: value for key, value in changes.items()
                   if self.cells.get((0, key[1]), "") not in self.clipboard_locks
                   and self.cells.get(key, "") != value}
        if changes:
            self.undo.push(CellEdit(self, changes))

    def paste_cells(self, changes, *, bounds=None):
        """Paste over a range and report actual edits, not the clipboard size."""
        if self.clipboard_locks:
            if any(row > self._document_rows for row, _ in changes):
                raise ValueError("Unlock metadata before pasting additional rows.")
            changes = {key: value for key, value in changes.items()
                       if self.cells.get((0, key[1]), "") not in self.clipboard_locks}
        before = {key: self.cells.get(key, "") for key, value in changes.items()
                  if self.cells.get(key, "") != value}
        rows = self._document_rows
        headers = {column: self.cells.get((0, column), "") for _, column in before}
        self.edit({key: changes[key] for key in before})
        if bounds is None and changes:
            bounds = (min(r for r, _ in changes), min(c for _, c in changes),
                      max(r for r, _ in changes), max(c for _, c in changes))
        self._report_paste(before, rows, headers, bounds)

    def clear_paste_report(self):
        if self.paste_report is not None:
            self.paste_report = None
            self.paste_report_changed.emit()

    def _replacement_paste_before(self, state):
        cells, _, _ = state
        before = {key: self.cells.get(key, "") for key, value in cells.items()
                  if self.cells.get(key, "") != value}
        before.update((key, value) for key, value in self.cells.items()
                      if value and key not in cells)
        headers = {column: self.cells.get((0, column), "") for _, column in before}
        return before, self._document_rows, headers

    def _report_paste(self, before, rows, headers, bounds=None):
        changes = {key: (value, self.cells.get(key, "")) for key, value in before.items()
                   if value != self.cells.get(key, "")}
        counts = Counter(column for _, column in changes)
        columns = tuple((column, self.cells.get((0, column), "") or headers[column]
                         or f"Column {column_letter(column)}", counts[column])
                        for column in sorted(counts))
        self.paste_report = PasteReport(
            MappingProxyType(changes), columns,
            max(0, self._document_rows - rows), max(0, rows - self._document_rows), bounds)
        # Presentation only: do not increment revisions, invalidate analysis,
        # mark dirty or persist the receipt in WKB/recovery snapshots.
        self.paste_report_changed.emit()

    @property
    def preserves_record_positions(self):
        """Cell edits keep record positions; explicit table replacement may reorder."""
        return self._preserves_record_positions

    def apply(self, changes):
        previous = self._frame_change
        self._frame_change = changes
        try:
            self._apply_cells(changes)
        finally:
            self._frame_change = previous

    @property
    def changed_cells(self):
        """Read-only edit context during a cell-change notification, else None.

        Replacement/load and untracked notifications use the full refresh path.
        Receivers must consume this on the GUI thread, not retain it in a worker.
        """
        return MappingProxyType(self._frame_change) if self._frame_change is not None else None

    def _apply_cells(self, changes):
        self._invalidate_frames()
        self._revision += 1
        self._preserves_record_positions = True
        rows = max(self.height, max(r for r, _ in changes) + 21)
        cols = max(self.width, max(c for _, c in changes) + 4)
        if rows > self.height:
            self.beginInsertRows(QModelIndex(), self.height, rows - 1)
            self.height = rows
            self.endInsertRows()
        if cols > self.width:
            self.beginInsertColumns(QModelIndex(), self.width, cols - 1)
            self.width = cols
            self.endInsertColumns()
        for key, value in changes.items():
            if value:
                self.cells[key] = value
            else:
                self.cells.pop(key, None)
        self._document_rows = max(self._document_rows,
                                  max((row for (row, _), value in changes.items() if value), default=0))
        first = self.index(min(r for r, _ in changes), min(c for _, c in changes))
        last = self.index(max(r for r, _ in changes), max(c for _, c in changes))
        self.dataChanged.emit(first, last)
        self.changed.emit()

    def load(self, frame, *, report_paste=False):
        matrix = [list(frame.columns)] + frame.fillna("").astype(str).values.tolist() if len(frame.columns) else []
        self.load_matrix(matrix, report_paste=report_paste)

    def load_matrix(self, matrix, *, report_paste=False):
        """Replace every cell with a rectangular clipboard matrix."""
        if report_paste:
            matrix = self._merge_clipboard_matrix(matrix)
        state = self.state_from_matrix(matrix)
        before = self._replacement_paste_before(state) if report_paste else None
        self.restore(state, emit_changed=False)
        self.undo.clear()
        self.undo.setClean()
        self.changed.emit()
        if before is not None:
            self._report_paste(*before, self._matrix_bounds(matrix))

    def replace_matrix(self, matrix, *, report_paste=False):
        """Replace the table as one user-visible, undoable operation."""
        if report_paste:
            matrix = self._merge_clipboard_matrix(matrix)
        command = TableReplace(self, matrix)
        before = self._replacement_paste_before(command.after) if report_paste else None
        if command.before != command.after:
            self.undo.push(command)
        if before is not None:
            self._report_paste(*before, self._matrix_bounds(matrix))

    @staticmethod
    def _matrix_bounds(matrix):
        width = max((len(row) for row in matrix), default=0)
        return (0, 0, len(matrix) - 1, width - 1) if matrix and width else None

    def snapshot(self):
        cells = dict(self.cells)
        if self._document_rows:
            # An empty final-row marker retains the three-field snapshot shape.
            # It is document extent, not a value/extra scientific observation.
            cells.setdefault((self._document_rows, 0), "")
        return cells, self.height, self.width

    @staticmethod
    def state_from_matrix(matrix):
        matrix = [list(row) for row in matrix]
        if matrix:
            width = max(len(row) for row in matrix)
            matrix = [row + [""] * (width - len(row)) for row in matrix]
        width = max((len(row) for row in matrix), default=0)
        cells = {
            (r, c): str(value)
            for r, row in enumerate(matrix)
            for c, value in enumerate(row)
            if str(value)
        }
        if len(matrix) > 1:
            cells.setdefault((len(matrix) - 1, 0), "")
        return cells, max(100, len(matrix) + 20), max(26, width + 3)

    def restore(self, state, emit_changed=True):
        self._frame_change = None
        self.clear_paste_report()
        self._invalidate_frames()
        self._revision += 1
        cells, height, width = state
        self._preserves_record_positions = False
        self.beginResetModel()
        self.cells = dict(cells)
        self._document_rows = max((row for row, _ in cells), default=0)
        self.height = height
        self.width = width
        self.endResetModel()
        if self.clipboard_locks:
            # New/Open may remove fields entirely. Do not leave hidden locks
            # that make an empty table impossible to paste into or unlock.
            self.set_clipboard_locks(self.clipboard_locks)
        if emit_changed:
            self.changed.emit()

    def frame(self):
        if "analysis" in self._frames:
            return self._frames["analysis"].copy()
        if not self.cells:
            return pd.DataFrame()
        rows, columns = self._cell_extent()
        headers = self.headers(columns)
        if len(set(headers)) != len(headers):
            raise ValueError("Duplicate column names in row 1. Rename them to continue.")
        matrix = [[self.cells.get((r, c), "") for c in range(columns)] for r in range(1, rows)]
        frame = pd.DataFrame([row for row in matrix if any(v.strip() for v in row)], columns=headers)
        self._frames["analysis"] = frame
        return frame.copy()

    def _invalidate_frames(self):
        changes = self._frame_change
        if (changes and self._extent is not None
                and all(row > 0 and isinstance(value, str) and value.strip() and (row, column) in self.cells
                        for (row, column), value in changes.items())):
            # Existing nonblank data cells cannot change headers, row inclusion
            # or extent. Patch only module-owned string frames; public reads
            # still return detached copies, including accepted Save snapshots.
            width = self._extent[1]
            columns = {}
            for (row, column), value in changes.items():
                columns.setdefault(column, []).append((row - 1, value))
            for kind, frame in list(self._frames.items()):
                if (len(frame) == self._document_rows and len(frame.columns) == width
                        and all(dtype == object for dtype in frame.dtypes)):
                    for column, updates in columns.items():
                        if len(updates) == 1:
                            row, value = updates[0]
                            frame.iat[row, column] = value
                        else:
                            frame.iloc[[row for row, _ in updates], column] = [value for _, value in updates]
                else:
                    # Analysis frames with omitted blank rows have a different
                    # positional map. Keep their original full rebuild behavior.
                    del self._frames[kind]
            return
        # Headers, blanks, growth, replacement and unknown notifications retain
        # full invalidation. No change summary is inferred from an old revision.
        self._frames.clear()
        self._extent = None
        self._selection_extent = None

    def _cell_extent(self):
        if self._extent is None:
            self._extent = (max((row for row, _ in self.cells), default=-1) + 1,
                            max((column for _, column in self.cells), default=-1) + 1)
        return self._extent

    def selection_extent(self):
        """Occupied rectangle, excluding reserved cells and empty tail markers."""
        if self._selection_extent is None:
            rows = columns = 0
            for (row, column), value in self.cells.items():
                if value:
                    rows, columns = max(rows, row + 1), max(columns, column + 1)
            self._selection_extent = rows, columns
        return self._selection_extent

    def document_frame(self):
        """Save a draft exactly, including duplicate headers and empty rows."""
        if "document" in self._frames:
            return self._frames["document"].copy()
        if not self.cells:
            return pd.DataFrame()
        height, width = self._cell_extent()
        height = max(self._document_rows + 1, height)
        headers = [self.cells.get((0, c), "") for c in range(width)]
        frame = pd.DataFrame([[self.cells.get((r, c), "") for c in range(width)]
                             for r in range(1, height)], columns=headers)
        self._frames["document"] = frame
        return frame.copy()

    def headers(self, columns=None):
        """Row-1 header text, falling back to the column letter when it is blank."""
        if columns is None:
            columns = self._cell_extent()[1]
        return [self.cells.get((0, c), "").strip() or f"Column {column_letter(c)}"
                for c in range(columns)]

    def source_headers(self):
        """Literal document names for clipboard protection, not analysis aliases."""
        return [self.cells.get((0, column), "") for column in range(self._cell_extent()[1])]

    def duplicate_header_count(self):
        """How many row-1 names repeat (0 when every header is unique)."""
        headers = self.headers()
        return len(headers) - len(set(headers))

    def rename_duplicate_headers(self):
        """Number repeated row-1 headers by column order and return the renames.

        The first column of each name keeps it; later repeats become ``name_1``,
        ``name_2`` … (skipping any suffix already used elsewhere), so the table
        can be read again without touching any other cell. Renames go through the
        undo stack.
        """
        headers = self.headers()
        used = set(headers)
        seen, changes = {}, {}
        for column, name in enumerate(headers):
            seen[name] = seen.get(name, 0) + 1
            if seen[name] == 1:
                continue
            suffix = seen[name] - 1
            candidate = f"{name}_{suffix}"
            while candidate in used:
                suffix += 1
                candidate = f"{name}_{suffix}"
            used.add(candidate)
            changes[(0, column)] = candidate
        if changes:
            self.edit(changes)
        return {column: (headers[column], value) for (_, column), value in changes.items()}


class DuplicateHeaderBanner(QFrame):
    """Shared, self-updating repair action for editable spreadsheet headers."""

    renamed = pyqtSignal(dict)

    def __init__(self, model=None, parent=None):
        super().__init__(parent, objectName="warningBanner")
        self._model = None
        self.setMinimumHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        self.message = QLabel(
            "Duplicate column names in row 1. Rename them to continue.",
            objectName="warningText",
        )
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)
        self.button = QPushButton("Auto rename", objectName="warningAction")
        self.button.setToolTip(
            "Append 2, 3 … to repeated row-1 column names, in column order."
        )
        self.button.clicked.connect(self.rename_duplicates)
        layout.addWidget(self.button)
        self.set_model(model)

    def set_model(self, model):
        if self._model is model:
            self.refresh()
            return
        if self._model is not None:
            try:
                self._model.changed.disconnect(self.refresh)
            except TypeError:
                pass
        self._model = model
        if model is not None:
            model.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        duplicated = bool(
            self._model is not None and self._model.duplicate_header_count()
        )
        self.message.setVisible(duplicated)
        self.button.setVisible(duplicated)
        self.setVisible(duplicated)

    def rename_duplicates(self):
        renames = self._model.rename_duplicate_headers() if self._model else {}
        self.refresh()
        if renames:
            self.renamed.emit(renames)
        return renames


class _SheetHeader(QHeaderView):
    """Native header styling with range-based selection for uniform sheets.

    Qt's header asks isColumnSelected for each painted column, which calls
    Python model.flags for every record. A rectangular sheet selection already
    contains that information. Custom/disabled-cell models keep Qt's path.
    """

    def initStyleOptionForIndex(self, option, section):
        model = self.model()
        if not getattr(model, "uniform_selectable", False):
            return super().initStyleOptionForIndex(option, section)
        self.initStyleOption(option)
        horizontal = self.orientation() == Qt.Orientation.Horizontal
        count = model.rowCount() if horizontal else model.columnCount()
        ranges = self.selectionModel().selection()

        def selected(index):
            spans = sorted((r.top(), r.bottom()) if horizontal else (r.left(), r.right())
                           for r in ranges if (r.left() <= index <= r.right() if horizontal
                                               else r.top() <= index <= r.bottom()))
            end = -1
            for low, high in spans:
                if low > end + 1:
                    break
                end = max(end, high)
            return bool(spans), end >= count - 1 and count > 0

        intersects, full = selected(section)
        if self.sectionsClickable():
            if self.underMouse() and self.logicalIndexAt(self.mapFromGlobal(QCursor.pos())) == section:
                option.state |= QStyle.StateFlag.State_MouseOver
            if self.highlightSections():
                if intersects:
                    option.state |= QStyle.StateFlag.State_On
                if full:
                    option.state |= QStyle.StateFlag.State_Sunken
        option.section = section
        option.text = str(model.headerData(section, self.orientation(), Qt.ItemDataRole.DisplayRole) or "")
        alignment = model.headerData(section, self.orientation(), Qt.ItemDataRole.TextAlignmentRole)
        option.textAlignment = alignment if alignment is not None else self.defaultAlignment()
        visual = self.visualIndex(section)
        option.position = (QStyleOptionHeader.SectionPosition.OnlyOneSection if self.count() == 1
                           else QStyleOptionHeader.SectionPosition.Beginning if visual == 0
                           else QStyleOptionHeader.SectionPosition.End if visual == self.count() - 1
                           else QStyleOptionHeader.SectionPosition.Middle)
        before, after = selected(self.logicalIndex(visual - 1))[1], selected(self.logicalIndex(visual + 1))[1]
        option.selectedPosition = (QStyleOptionHeader.SelectedPosition.NextAndPreviousAreSelected if before and after
                                   else QStyleOptionHeader.SelectedPosition.PreviousIsSelected if before
                                   else QStyleOptionHeader.SelectedPosition.NextIsSelected if after
                                   else QStyleOptionHeader.SelectedPosition.NotAdjacent)
        if self.isSortIndicatorShown() and self.sortIndicatorSection() == section:
            option.sortIndicator = (QStyleOptionHeader.SortIndicator.SortDown
                                    if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
                                    else QStyleOptionHeader.SortIndicator.SortUp)


class SheetView(QTableView):
    table_pasted = pyqtSignal()
    paste_report_changed = pyqtSignal()

    def __init__(self, model):
        super().__init__()
        self._paste_source = None
        self.keyboard_editing = False
        self.clipboard_outline = ClipboardRangeOutline(self)
        self.setHorizontalHeader(_SheetHeader(Qt.Orientation.Horizontal, self))
        self.setVerticalHeader(_SheetHeader(Qt.Orientation.Vertical, self))
        for header in (self.horizontalHeader(), self.verticalHeader()):
            header.setSectionsClickable(True)
            header.setHighlightSections(True)
        self.setModel(model)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(self.SelectionMode.ContiguousSelection)
        self.setHorizontalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(29)
        self.horizontalHeader().setDefaultSectionSize(118)
        self.horizontalHeader().setMinimumSectionSize(48)
        self.verticalHeader().setMinimumWidth(44)

    @staticmethod
    def source_cell(index):
        model = index.model()
        while isinstance(model, QAbstractProxyModel):
            index = model.mapToSource(index)
            model = model.sourceModel()
        return model, (index.row(), index.column())

    def setModel(self, model):
        previous_model = self.model()
        if previous_model is not None:
            previous_model.modelReset.disconnect(self.clipboard_outline.clear)
            previous_model.dataChanged.disconnect(self.clipboard_outline.clear)
        self.clipboard_outline.clear()
        previous = getattr(self, "_paste_source", None)
        source = model
        while isinstance(source, QAbstractProxyModel):
            source = source.sourceModel()
        if previous is not source and previous is not None:
            previous.paste_report_changed.disconnect(self._paste_feedback_changed)
        super().setModel(model)
        model.modelReset.connect(self.clipboard_outline.clear)
        model.dataChanged.connect(self.clipboard_outline.clear)
        self._paste_source = source if isinstance(source, SheetModel) else None
        if self._paste_source is not None and previous is not source:
            source.paste_report_changed.connect(self._paste_feedback_changed)
        self._paste_feedback_changed()

    @property
    def paste_report(self):
        return getattr(self._paste_source, "paste_report", None)

    def _paste_feedback_changed(self):
        self.viewport().update()
        self.paste_report_changed.emit()

    def clear_paste_report(self):
        if self._paste_source is not None:
            self._paste_source.clear_paste_report()

    def selectAll(self):
        """Select in one batched change so Qt does not repaint in stages."""
        model = self.model()
        rows, columns = model.selection_extent()
        if rows <= 0 or columns <= 0:
            self.clearSelection()
            return
        selection = QItemSelection(model.index(0, 0), model.index(rows - 1, columns - 1))
        self.setUpdatesEnabled(False)
        try:
            self.selectionModel().select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        finally:
            self.setUpdatesEnabled(True)
        self.viewport().update()

    @staticmethod
    def _data_size(model):
        """(columns, data rows) currently holding values, ignoring trailing blanks."""
        if not model.cells:
            return 0, 0
        columns = max(c for _, c in model.cells) + 1
        last_row = max(r for r, _ in model.cells)
        rows = sum(1 for r in range(1, last_row + 1)
                   if any(model.cells.get((r, c), "").strip() for c in range(columns)))
        return columns, rows

    def mismatched_paste_choice(self, pasted, current):
        """Ask before an A1 paste leaves existing cells outside the pasted range.

        ``pasted`` and ``current`` are (columns, data rows). Returns
        ``"keep"``, ``"replace"`` or ``"cancel"``.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Paste size differs")
        box.setText(f"Pasted data: {pasted[0]} columns × {pasted[1]} rows. "
                    f"Current table: {current[0]} columns × {current[1]} rows.")
        box.setInformativeText("Cells outside the pasted range keep their current values. "
                               "Choose “Clear table and paste” to replace everything "
                               "(Ctrl+Shift+V).")
        keep = box.addButton("Paste over range", QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton("Clear table and paste", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace:
            return "replace"
        if clicked is keep:
            return "keep"
        return "cancel"

    def paste(self, replace=False):
        model = self.model()
        was_empty = not model.cells
        matrix = clipboard_rows(QApplication.clipboard().text())
        if not matrix:
            return
        index = self.currentIndex()
        row, column = (index.row(), index.column()) if index.isValid() else (0, 0)
        if not replace and (row, column) == (0, 0) and not was_empty and len(matrix) > 1:
            pasted = (max(len(line) for line in matrix), len(matrix) - 1)
            # Document bounds are an upper bound on occupied data rows. An
            # equal/larger rectangle cannot leave old cells outside it; only
            # potentially smaller pastes need the exact nonblank-row scan.
            covers_document = (isinstance(model, SheetModel)
                               and pasted[0] >= model._cell_extent()[1]
                               and pasted[1] >= model._document_rows)
            if not covers_document:
                current = self._data_size(model)
                if pasted[0] < current[0] or pasted[1] < current[1]:
                    choice = self.mismatched_paste_choice(pasted, current)
                    if choice == "cancel":
                        return
                    replace = choice == "replace"
        if replace:
            # Explicit Ctrl+Shift+V replacement: clear the rest of the table so
            # no stale cells from a previously pasted file survive.
            model.replace_matrix(matrix, report_paste=True)
        else:
            model.paste_cells(
                {(row + r, column + c): v for r, line in enumerate(matrix) for c, v in enumerate(line)},
                bounds=(row, column, row + len(matrix) - 1, column + max(map(len, matrix)) - 1))
        top, left = (0, 0) if replace else (row, column)
        self.mark_pasted_range((top, left, top + len(matrix) - 1,
                                left + max(map(len, matrix)) - 1))
        if matrix and (was_empty or replace):
            # The first paste into an empty sheet replaces the table, so the
            # window should re-run automatic wafer/parameter identification.
            self.table_pasted.emit()

    def mark_pasted_range(self, bounds):
        self.clipboard_outline.clear()
        top, left, bottom, right = bounds
        model = self.model()
        self.selectionModel().select(
            QItemSelection(model.index(top, left), model.index(bottom, right)),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def copy(self):
        return copy_selection(self, Qt.ItemDataRole.EditRole)

    def cut(self):
        bounds = selection_bounds(self)
        if bounds is None:
            return False
        top, left, bottom, right = bounds
        model = self.model()
        if hasattr(model, "range_editable") and not model.range_editable(bounds):
            return False
        if not getattr(model, "uniform_selectable", False) and any(
                not model.flags(model.index(row, column)) & Qt.ItemFlag.ItemIsEditable
                for row in range(top, bottom + 1) for column in range(left, right + 1)):
            return False
        if not self.copy():
            return False
        # Copy succeeded first. One normal edit owns the clear and Undo; no
        # pending move can later delete a different source or hidden record.
        changes = {(row, column): "" for row, column in model.cells
                   if top <= row <= bottom and left <= column <= right}
        model.edit(changes)
        self.clipboard_outline.show_range(bounds, "copy")
        return True

    def keyPressEvent(self, event):
        # The owning workbook can coalesce rapid keyboard paste/Undo analysis,
        # while the Qt model, Undo stack and table values still update now.
        self.keyboard_editing = True
        try:
            self._handle_key_press(event)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to paste", str(error))
        finally:
            self.keyboard_editing = False

    def _handle_key_press(self, event):
        if (event.key() == Qt.Key.Key_V
                and event.modifiers() == (Qt.KeyboardModifier.ControlModifier
                                          | Qt.KeyboardModifier.ShiftModifier)):
            self.paste(replace=True)
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif event.matches(QKeySequence.StandardKey.Cut):
            self.cut()
        elif event.key() == Qt.Key.Key_Escape:
            self.clipboard_outline.clear()
            super().keyPressEvent(event)
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.model().undo.undo()
        elif event.matches(QKeySequence.StandardKey.Redo):
            self.model().undo.redo()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            model = self.model()
            if getattr(model, 'uniform_selectable', False):
                # Uniform selectable flags: ranges describe the same selection
                # without constructing a QModelIndex for every trailing blank.
                bounds = [(r.top(), r.bottom(), r.left(), r.right())
                          for r in self.selectionModel().selection()]
                changes = {(row, column): "" for row, column in model.cells
                           if any(top <= row <= bottom and left <= column <= right
                                  for top, bottom, left, right in bounds)}
            else:
                # Projections and models with custom disabled cells retain Qt's
                # own selectable-index semantics and source-row translation.
                changes = {(i.row(), i.column()): "" for i in self.selectedIndexes()}
            model.edit(changes)
        else:
            super().keyPressEvent(event)


class PasteFeedbackBar(QFrame):
    """Small, non-modal receipt for the view's current source/stage."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)
        self.clear_button = QToolButton()
        self.clear_button.setText("×")
        self.clear_button.setAccessibleName("Clear paste feedback")
        self.clear_button.setToolTip("Dismiss the receipt; keep the pasted data.")
        self.clear_button.clicked.connect(view.clear_paste_report)
        layout.addWidget(self.clear_button)
        view.paste_report_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        report = self.view.paste_report
        self.setVisible(report is not None)
        if report is None:
            self.message.clear()
            return
        self.message.setText(report.summary)
        columns = "\n".join(f"{column_letter(column)} — {name}: {count:,} changed cells"
                            for column, name, count in report.columns)
        self.message.setToolTip(
            f"{escape(columns).replace(chr(10), '<br>')}<br>Only pasted values are reported, not analysis completion."
            "<br>Feedback clears on the next edit, Undo, table reload, or ×.")

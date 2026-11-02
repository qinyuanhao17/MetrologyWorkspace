"""Small spreadsheet model: editable cells, range clipboard and undo/redo."""
import csv
from copy import deepcopy
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from io import StringIO
from itertools import chain, product
from types import MappingProxyType

import pandas as pd
from PyQt6.QtCore import (
    QAbstractProxyModel, QAbstractTableModel, QEvent, QItemSelection, QItemSelectionModel, QModelIndex, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QFont, QKeySequence, QPainter, QPen, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QAbstractItemDelegate, QApplication, QFrame, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QStyle, QStyleOptionHeader, QTableView, QToolButton, QToolTip,
)

from .settings import get_settings
from .metadata_locks import ColumnLockDelegate, is_metadata_column
from .table_clipboard import ClipboardRangeOutline, copy_selection, selection_bounds
from .table_selection import RangeSelectionHeader, RangeSelectionTableView
from .sheet_batch import ColumnChanges, prepare_column_paste
from .table_version import LiteralTableVersion, LiteralFrameSource
from .version_cells import TrackedCells, VersionCells


HEADER_COLOURS = {"dark": ("#201629", "#d6b9f5"), "light": ("#f0f0f2", "#18181b")}
CELL_FLAGS = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
              | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemNeverHasChildren)


def header_colours():
    return HEADER_COLOURS.get(get_settings()["theme"], HEADER_COLOURS["dark"])


def _hidden_row_colour():
    return QColor("#e6b54a" if get_settings()["theme"] == "dark" else "#b87200")


def column_letter(index):
    result = ""
    while index >= 0:
        result = chr(65 + index % 26) + result
        index = index // 26 - 1
    return result


def table_size_text(rows, columns, *, visible_rows=None):
    """Describe source data, not the sheet's reserved editing cells or row labels."""
    size = f"{rows:,} rows × {columns} columns"
    if visible_rows is not None and visible_rows != rows:
        return f"{visible_rows:,} visible / {size}"
    return size


def clipboard_rows(text):
    if not text:
        return []
    try:
        delimiter = ("\t" if "\t" in text or not any(separator in text for separator in ",;")
                     else csv.Sniffer().sniff(text, delimiters=",;").delimiter)
    except csv.Error:
        delimiter = "\t"
    return list(csv.reader(StringIO(text), delimiter=delimiter))


def nonempty_cell_bounds(items, row_positions=None):
    """Inclusive visible content bounds; internal gaps remain in the rectangle."""
    top = left = float("inf")
    bottom = right = -1
    for (row, column), value in items:
        if row_positions is not None and row:
            row = row_positions.get(row)
            if row is None:
                continue
        if value is None or not str(value).strip():
            continue
        if row < top:
            top = row
        if row > bottom:
            bottom = row
        if column < left:
            left = column
        if column > right:
            right = column
    return (top, left, bottom, right) if bottom >= 0 else None


def rectangular_cell_bounds(cells, rows, columns):
    """Find dense-table edges without visiting interior cells (including blanks)."""
    def occupied(row, column):
        value = cells.get((rows[row], column), "")
        return value is not None and bool(str(value).strip())

    top = next((row for row in range(len(rows))
                if any(occupied(row, column) for column in range(columns))), None)
    if top is None:
        return None
    bottom = next(row for row in range(len(rows) - 1, top - 1, -1)
                  if any(occupied(row, column) for column in range(columns)))
    left = next(column for column in range(columns)
                if any(occupied(row, column) for row in range(top, bottom + 1)))
    right = next(column for column in range(columns - 1, left - 1, -1)
                 if any(occupied(row, column) for row in range(top, bottom + 1)))
    return top, left, bottom, right


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
        rows = (self.changes.data_row_count if isinstance(self.changes, ColumnChanges)
                else len({row for row, _ in self.changes if row > 0}))
        if rows:
            parts.append(f"{rows:,} data {'row' if rows == 1 else 'rows'}")
        headers = (0 if isinstance(self.changes, ColumnChanges)
                   else sum(row == 0 for row, _ in self.changes))
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
    def __init__(self, model, changes, *, document_rows=None):
        super().__init__("Edit cells")
        self.model = model
        self._before_cells = {cell: model.cells.get(cell, "") for cell in changes}
        self._after_cells = changes
        self.before = MappingProxyType(self._before_cells)
        self.after = MappingProxyType(changes)
        self.before_mode = self._value_mode(self.before)
        self.after_mode = self._value_mode(self.after)
        self.before_rows = model._document_rows
        self.after_rows = max(self.before_rows if document_rows is None else document_rows,
                              max((row for (row, _), value in changes.items() if value), default=0))
        # Command-owned immutable keys have the same bounds for Undo and Redo.
        self.bounds = (min(r for r, _ in changes), min(c for _, c in changes),
                       max(r for r, _ in changes), max(c for _, c in changes))
        self.before_extent = max(self.before_rows,
                                 max((r for (r, _), value in self.before.items() if value), default=0))

    @staticmethod
    def _value_mode(changes):
        # Immutable command values: C-level update/clear are exact only for
        # uniformly populated/blank edits. Mixed edits keep the ordinary loop.
        return True if all(changes.values()) else False if not any(changes.values()) else None

    def redo(self):
        self.model._document_rows = self.after_rows
        if type(self.model).apply is SheetModel.apply:
            self.model._apply_changes(self._after_cells, bounds=self.bounds, document_rows=self.after_rows,
                                      value_mode=self.after_mode)
        else:
            self.model.apply(self.after)

    def undo(self):
        self.model._document_rows = self.before_rows
        if type(self.model).apply is SheetModel.apply:
            self.model._apply_changes(self._before_cells, bounds=self.bounds, document_rows=self.before_extent,
                                      value_mode=self.before_mode)
        else:
            self.model.apply(self.before)


class ColumnEdit(QUndoCommand):
    """One ordinary Undo step over an owned immutable set of column vectors."""

    def __init__(self, model, parts, data_rows):
        super().__init__("Edit cells")
        self.model = model
        self.before = ColumnChanges(parts, 'before', data_rows)
        self.after = ColumnChanges(parts, 'after', data_rows)
        self.rows = model._document_rows
        self.before_version = model._column_version()
        self.after_version = None
        if self.before_version is not None:
            columns = {}
            for part in parts:
                if part.rows == range(1, self.before_version.row_count + 1):
                    columns[part.column] = part.after
                else:
                    values = list(self.before_version.columns[part.column])
                    for row, value in zip(part.rows, part.after):
                        values[row - 1] = value
                    columns[part.column] = values
            self.after_version = self.before_version.replace_columns(columns)

    def _apply(self, changes, expected, target):
        current = self.model.cells
        version = (target if isinstance(current, VersionCells)
                   and current.version is expected else None)
        self.model._apply_changes(changes, bounds=changes.bounds,
                                  document_rows=self.rows, value_mode=True,
                                  table_version=version)

    def redo(self):
        self.model._document_rows = self.rows
        self._apply(self.after, self.before_version, self.after_version)

    def undo(self):
        self.model._document_rows = self.rows
        self._apply(self.before, self.after_version, self.before_version)


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
        self._writing_cells = False
        self.cells = TrackedCells(changed=self._direct_cells_changed) if type(self) is SheetModel else {}
        self._document_rows = 0
        self._preserves_record_positions = False
        self._frames = {}
        self._borrowed_frames = False
        self._extent = None
        self._selection_extent = None
        self._selection_bounds = None
        self._frame_change = None
        self._prepared_load = False
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

    @property
    def literal_version(self):
        """Internal immutable source read; public frames remain detached copies."""
        return self.cells.version if isinstance(self.cells, VersionCells) else None

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
        """Preserve locked names and strings at their current column/row positions.

        A different row count or ambiguous headers cannot safely carry coordinates
        forward. Reject before changing the source, its Undo history or UI state.
        Clipboard paste and explicit Workbook copy share this merge. File/Open
        loads still replace the document rather than merging its old values.
        """
        if not self.clipboard_locks:
            return frame
        self.validate_clipboard_frame(frame)
        current = self.document_frame()
        merged = frame.reset_index(drop=True).copy()
        headers = list(merged.columns)
        for column, name in enumerate(current.columns):
            if name in self.clipboard_locks:
                merged[merged.columns[column]] = current.iloc[:, column].to_numpy(copy=True)
                headers[column] = name
        merged.columns = headers
        if not merged.columns.is_unique:
            raise ValueError("Unlock metadata or fix duplicate column names before pasting.")
        return merged

    def validate_clipboard_frame(self, frame):
        if self.clipboard_locks:
            if len(frame) != self._document_rows:
                raise ValueError("Unlock metadata before pasting a different number of rows.")
            headers = self.source_headers()
            named_headers = [name for name in headers if str(name).strip()]
            if not frame.columns.is_unique or len(set(named_headers)) != len(named_headers):
                raise ValueError("Unlock metadata or fix duplicate column names before pasting.")
            if any(column >= len(frame.columns) for column, name in enumerate(headers)
                   if name in self.clipboard_locks):
                raise ValueError("Unlock metadata before pasting a table missing a locked column position.")

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

    @property
    def uniform_selection_flags(self):
        return (type(self).flags is SheetModel.flags
                and type(self).headerData is SheetModel.headerData)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if not self.flags(index) & Qt.ItemFlag.ItemIsEditable:
            return False
        self.edit({(index.row(), index.column()): str(value)})
        return True

    def edit(self, changes, *, document_rows=None):
        """Apply one undoable edit and return read-only original values.

        Paste feedback reuses the Undo capture; callers cannot modify it.
        Locked and unchanged cells are absent from the returned mapping.
        """
        if self.clipboard_locks:
            changes = {key: value for key, value in changes.items()
                       if self.cells.get((0, key[1]), "") not in self.clipboard_locks}
        changes = {key: value for key, value in changes.items()
                   if self.cells.get(key, "") != value}
        if changes:
            command = CellEdit(self, changes, document_rows=document_rows)
            before = MappingProxyType(command.before)
            self.undo.push(command)
            return before
        return MappingProxyType({})

    def paste_cells(self, changes, *, bounds=None):
        """Paste over a range and report actual edits, not the clipboard size."""
        if self.clipboard_locks:
            if any(row > self._document_rows for row, _ in changes):
                raise ValueError("Unlock metadata before pasting additional rows.")
            changes = {key: value for key, value in changes.items()
                       if self.cells.get((0, key[1]), "") not in self.clipboard_locks}
        rows = self._document_rows
        headers = {column: self.cells.get((0, column), "") for column in {c for _, c in changes}}
        before = self.edit(changes)
        if bounds is None and changes:
            bounds = (min(r for r, _ in changes), min(c for _, c in changes),
                      max(r for r, _ in changes), max(c for _, c in changes))
        self._report_paste(before, rows, headers, bounds)

    def _paste_value_matrix(self, matrix, row, column):
        if type(self) is not SheetModel or self.clipboard_locks:
            return False
        document = self._frames.get('document')
        if document is None and isinstance(self.cells, VersionCells) and self.cells.version is not None:
            self.document_frame()
            document = self._frames.get('document')
        if (document is None or len(document) != self._document_rows
                or self._extent != (self._document_rows + 1, len(document.columns))):
            return False
        prepared = prepare_column_paste(document, matrix, row, column)
        if prepared is None:
            return False
        parts, data_rows = prepared
        bounds = row, column, row + len(matrix) - 1, column + len(matrix[0]) - 1
        if parts:
            command = ColumnEdit(self, parts, data_rows)
            revision = self.revision
            self.undo.push(command)
            if self.revision != revision + 1:
                # Reentrant edits can change the pasted values before push
                # returns; the receipt must capture those actual final strings.
                headers = {p.column: str(document.columns[p.column]) for p in parts}
                self._report_paste(command.before, self._document_rows, headers, bounds)
                return True
            changes = ColumnChanges(parts, 'pairs', data_rows)
            columns = tuple((p.column, str(document.columns[p.column]), len(p.rows)) for p in parts)
        else:
            changes, columns = MappingProxyType({}), ()
        self.paste_report = PasteReport(changes, columns, bounds=bounds)
        self.paste_report_changed.emit()
        return True

    def _column_version(self):
        """Adopt only tracked, normalized dense source cells, without changing data."""
        if isinstance(self.cells, VersionCells):
            return self.cells.version
        document = self._frames.get('document')
        if type(self.cells) is not TrackedCells or document is None:
            return None
        try:
            version = LiteralTableVersion.from_frame(document)
        except (TypeError, ValueError):
            return None
        if (not version.dense or self._document_rows != version.row_count
                or self._extent != (version.row_count + 1, len(version.headers))
                or len(self.cells) != (version.row_count + 1) * len(version.headers)):
            return None
        self.cells = VersionCells(version, changed=self._direct_cells_changed)
        return version

    def _direct_cells_changed(self):
        # Public cells remain writable. Unknown writes cannot leave a materialized
        # frame (or an immutable version) claiming to represent the new values.
        if not self._writing_cells:
            self._frames.clear()
            self._borrowed_frames = False
            self._extent = self._selection_extent = self._selection_bounds = None

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
        self._apply_changes(changes)

    def _apply_changes(self, changes, *, bounds=None, document_rows=None, value_mode=None,
                       prepared_frames=None, table_version=None):
        previous = self._frame_change
        self._frame_change = changes
        try:
            self._apply_cells(changes, bounds=bounds, document_rows=document_rows,
                              value_mode=value_mode, prepared_frames=prepared_frames,
                              table_version=table_version)
        finally:
            self._frame_change = previous

    @property
    def changed_cells(self):
        """Read-only edit context during a cell-change notification, else None.

        Replacement/load and untracked notifications use the full refresh path.
        Receivers must consume this on the GUI thread, not retain it in a worker.
        """
        return MappingProxyType(self._frame_change) if self._frame_change is not None else None

    @property
    def changed_cell_bounds(self):
        """Known bounds of a compact batch notification, without visiting cells."""
        return self._frame_change.bounds if isinstance(self._frame_change, ColumnChanges) else None

    def _apply_cells(self, changes, *, bounds=None, document_rows=None, value_mode=None,
                     prepared_frames=None, table_version=None):
        if self._borrowed_frames:
            if table_version is None:
                # An older internal snapshot may still read these buffers.
                # General edits patch owned writable replacements instead.
                self._frames = {name: frame.copy(deep=True) for name, frame in self._frames.items()}
            self._borrowed_frames = False
        if table_version is None and isinstance(self.cells, VersionCells):
            # General/unknown/structural edits keep the ordinary dictionary path.
            self.cells = TrackedCells(self.cells.copy(), changed=self._direct_cells_changed)
        if bounds is None:
            bounds = (min(r for r, _ in changes), min(c for _, c in changes),
                      max(r for r, _ in changes), max(c for _, c in changes))
        top, left, bottom, right = bounds
        renamed_locks = {}
        if self.clipboard_locks and top <= 0 <= bottom:
            headers = ((0, c) for c in range(left, right + 1)) if right-left < len(changes) else (key for key in changes if key[0] == 0)
            if any(key in changes and self.cells.get(key, "") in self.clipboard_locks for key in headers):
                # Duplicate locked draft headers keep the original last-write
                # rule, which follows command insertion order, not column order.
                renamed_locks = {self.cells.get((0, c), ""): value if is_metadata_column(value) else ""
                                 for (r, c), value in changes.items()
                                 if r == 0 and self.cells.get((0, c), "") in self.clipboard_locks}
        if table_version is not None:
            self._frames.clear()
            frames_patched = True
        elif prepared_frames is None:
            frames_patched = self._invalidate_frames()
        else:
            self._frames = {name: frame.copy(deep=True) for name, frame in prepared_frames.items()}
            frames_patched = True
        self._revision += 1
        self._preserves_record_positions = True
        rows = max(self.height, bottom + 21)
        cols = max(self.width, right + 4)
        if rows > self.height:
            self.beginInsertRows(QModelIndex(), self.height, rows - 1)
            self.height = rows
            self.endInsertRows()
        if cols > self.width:
            self.beginInsertColumns(QModelIndex(), self.width, cols - 1)
            self.width = cols
            self.endInsertColumns()
        self._writing_cells = True
        try:
            if table_version is not None:
                self.cells = VersionCells(table_version, changed=self._direct_cells_changed)
                self._frames.clear()
            elif isinstance(changes, ColumnChanges):
                changes.update_cells(self.cells)
            elif value_mode is True:
                self.cells.update(changes)
            elif value_mode is False and self.cells.keys() <= changes.keys():
                self.cells.clear()
            else:
                for key, value in changes.items():
                    if value:
                        self.cells[key] = value
                    else:
                        self.cells.pop(key, None)
        finally:
            self._writing_cells = False
        if renamed_locks:
            # Undo/Redo can restore an earlier header name despite the lock.
            # Keep metadata protected on its slot; absent/nonmetadata headers
            # must not leave invisible locks or lock every reserved blank cell.
            self.set_clipboard_locks({renamed_locks.get(name, name) for name in self.clipboard_locks} - {""})
        if document_rows is None:
            document_rows = max((row for (row, _), value in changes.items() if value), default=0)
        self._document_rows = max(self._document_rows, document_rows)
        if not frames_patched:
            # Structural notifications may have rebuilt the old frames while
            # rows/columns were being inserted. Discard them before observers
            # capture the completed edit.
            context, self._frame_change = self._frame_change, None
            try:
                self._invalidate_frames()
            finally:
                self._frame_change = context
        first = self.index(top, left)
        last = self.index(bottom, right)
        self.dataChanged.emit(first, last)
        # Consume this known notification once: these frames are current.
        # Reentrant edits and unknown changed.emit() still invalidate normally.
        self._prepared_load = True
        try:
            self.changed.emit()
        finally:
            self._prepared_load = False

    def apply_linked_values(self, prepared, frame):
        """Commit a proved source delta; independent drafts are checked by the owner."""
        if (type(self) is not SheetModel or self.clipboard_locks
                or prepared.get('base_revision') != self.revision
                or not prepared['document'].equals(frame)
                or not self.document_frame().equals(prepared['base_document'])):
            return False
        changes = prepared['value_changes']
        self._apply_changes(changes, bounds=changes.bounds,
                            document_rows=self._document_rows, value_mode=True,
                            prepared_frames={name: prepared[name] for name in ('document', 'analysis')})
        # Following a Workbook source is a load, not a new child edit command.
        self.undo.clear()
        self.undo.setClean()
        return True

    def load(self, frame, *, report_paste=False):
        prepared = getattr(self, "_linked_prepared_load", None)
        self._linked_prepared_load = None
        if (not report_paste and prepared is not None
                and (self._prepared_source_matches(prepared, frame) or prepared["document"].equals(frame)
                     or prepared["document"].equals(frame.fillna("").astype(str).reset_index(drop=True)))):
            self._load_prepared_frame(prepared)
            return
        document = frame.fillna("").astype(str).reset_index(drop=True)
        document.columns = [str(name) for name in document.columns]
        matrix = [list(document.columns)] + document.values.tolist() if len(document.columns) else []
        self._load_matrix(matrix, report_paste=report_paste,
                          document=None if report_paste else document)

    def _load_prepared_frame(self, prepared):
        """Transfer an owned, data-only load result on the GUI thread."""
        document = prepared["document"]
        if type(self).restore is not SheetModel.restore:
            self.load(document)  # Subclass restore hooks retain the general seam.
            return
        version = prepared.get('version')
        cells = (VersionCells(version, changed=self._direct_cells_changed) if version is not None
                 else prepared.pop('cells'))
        self._restore_owned(cells, prepared["height"], prepared["width"],
                            prepared["rows"], emit_changed=False)
        if prepared["exact_extent"]:
            self._extent = (prepared["rows"] + 1, len(document.columns))
        if self.cells:
            readonly = version is not None and not document.to_numpy(copy=False).flags.writeable
            self._frames["document"] = document.iloc[:, :self._cell_extent()[1]].copy(deep=not readonly)
            if prepared.get("analysis") is not None:
                self._frames["analysis"] = prepared["analysis"].copy(deep=not readonly)
            self._borrowed_frames = readonly
        self.undo.clear()
        self.undo.setClean()
        self._prepared_load = True
        try:
            self.changed.emit()
        finally:
            self._prepared_load = False

    def update_headers(self, frame):
        """Refresh linked aliases only when every literal data cell is unchanged."""
        prepared = getattr(self, "_linked_prepared_load", None)
        comparison = self._prepared_comparison(prepared, frame)
        if comparison is not None and not comparison[2]:
            return False
        if (self.literal_version is not None and prepared is not None
                and self._prepared_source_matches(prepared, frame)):
            old, new = self.literal_version, prepared['version']
            if len(old.headers) != len(new.headers) or old.row_count != new.row_count or old.columns != new.columns:
                return False
            changes = {(0, column): name for column, name in enumerate(new.headers)
                       if old.headers[column] != name}
            if changes:
                self.apply(changes)
            self.undo.clear()
            self.undo.setClean()
            return True
        current = self._document_view()
        incoming = (prepared["document"] if prepared is not None and prepared["document"].equals(frame)
                    else frame.fillna("").astype(str).reset_index(drop=True))
        if comparison is None and (current.shape != incoming.shape or not current.set_axis(incoming.columns, axis=1, copy=False).equals(incoming)):
            return False
        changes = {(0, column): str(name) for column, name in enumerate(incoming.columns)
                   if current.columns[column] != str(name)}
        if changes:
            self.apply(changes)
        # Like load(), a new linked source is not an undoable user edit.
        self.undo.clear()
        self.undo.setClean()
        return True

    @staticmethod
    def _prepared_source_matches(prepared, frame):
        version = prepared.get('version')
        return any(isinstance(source, LiteralFrameSource) and source.matches(frame, version)
                   for source in (prepared.get('input_source'), prepared.get('document_source')))

    def matches_document(self, frame):
        """Compare literal sources, reusing a proved incoming immutable version."""
        prepared = getattr(self, '_linked_prepared_load', None)
        comparison = self._prepared_comparison(prepared, frame)
        if comparison is not None:
            return comparison[1]
        if (self.literal_version is not None and prepared is not None
                and self._prepared_source_matches(prepared, frame)):
            old, new = self.literal_version, prepared['version']
            return old.headers == new.headers and old.row_count == new.row_count and old.columns == new.columns
        return self._document_view().equals(frame)

    def _prepared_comparison(self, prepared, frame):
        comparison = prepared.get('comparison') if prepared is not None else None
        if (comparison is not None and comparison[0] == self.revision
                and self._prepared_source_matches(prepared, frame)):
            return comparison
        return None

    def matches_analysis(self, frame):
        """Recognize the current readonly source without rescanning its literals."""
        if self._literal_source(frame) is not None:
            return True
        return self._analysis_view().equals(frame)

    def load_matrix(self, matrix, *, report_paste=False):
        """Replace every cell with a rectangular clipboard matrix."""
        self._load_matrix(matrix, report_paste=report_paste)

    def _load_matrix(self, matrix, *, report_paste=False, document=None):
        if report_paste:
            matrix = self._merge_clipboard_matrix(matrix)
        if document is not None and matrix and all(chain.from_iterable(matrix)):
            # load() already produced a rectangular matrix of literal strings.
            # The dense case needs neither padding nor another Python str()
            # call per cell. Sparse/clipboard matrices keep the general path.
            columns = len(matrix[0])
            cells = dict(zip(product(range(len(matrix)), range(columns)), chain.from_iterable(matrix)))
            state = cells, max(100, len(matrix) + 20), max(26, columns + 3)
        else:
            state = self.state_from_matrix(matrix)
        before = self._replacement_paste_before(state) if report_paste else None
        if type(self).restore is SheetModel.restore:
            # The loader alone owns this new dictionary and knows its final
            # row marker. Undo snapshots/public restore must remain detached;
            # subclasses keep their own restore hooks (e.g. calculated Order).
            self._restore_owned(*state, max(0, len(matrix) - 1), emit_changed=False)
        else:
            self.restore(state, emit_changed=False)
        width = max((len(row) for row in matrix), default=0)
        if matrix and width and len(matrix[0]) == width and str(matrix[0][-1]):
            # A populated final header proves the exact column extent. The
            # retained final-row marker proves the height, even for blank rows.
            self._extent = (len(matrix), width)
        if document is not None and self.cells:
            # Publish the already converted strings before observers read the
            # new sheet, not after they have reconstructed the same large table.
            self._frames["document"] = document.iloc[:, :self._cell_extent()[1]].copy()
            literal = self._frames["document"]
            headers = self.headers(len(literal.columns))
            if (len(literal) and len(set(headers)) == len(headers)
                    and literal.iloc[:, 0].str.strip().ne("").all()):
                # A nonblank first cell proves every source row survives the
                # analysis view. Keep its exact strings and normalized headers;
                # ambiguous headers/blank rows retain frame()'s general path.
                self._frames["analysis"] = literal.set_axis(headers, axis=1)
        self.undo.clear()
        self.undo.setClean()
        self._prepared_load = True
        try:
            self.changed.emit()
        finally:
            self._prepared_load = False
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
        cells = self.cells.copy() if isinstance(self.cells, VersionCells) else dict(self.cells)
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
            (r, c): text
            for r, row in enumerate(matrix)
            for c, value in enumerate(row)
            if (text := str(value))
        }
        if len(matrix) > 1:
            cells.setdefault((len(matrix) - 1, 0), "")
        return cells, max(100, len(matrix) + 20), max(26, width + 3)

    def restore(self, state, emit_changed=True):
        cells, height, width = state
        self._restore_owned(dict(cells), height, width,
                            max((row for row, _ in cells), default=0), emit_changed)

    def _restore_owned(self, cells, height, width, document_rows, emit_changed=True):
        self._frame_change = None
        self.clear_paste_report()
        self._invalidate_frames()
        self._revision += 1
        self._preserves_record_positions = False
        self.beginResetModel()
        self.cells = (TrackedCells(cells, changed=self._direct_cells_changed)
                      if type(self) is SheetModel and not isinstance(cells, VersionCells) else cells)
        self._document_rows = document_rows
        self.height = height
        self.width = width
        # About-to-reset observers may have materialized the old source again.
        # End-of-reset observers must see the complete replacement, while old
        # borrowed buffers remain alive independently of this cache.
        self._frames.clear()
        self._borrowed_frames = False
        self._extent = self._selection_extent = self._selection_bounds = None
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
        if isinstance(self.cells, VersionCells) and self.cells.version is not None:
            document = self.document_frame()
            if document.iloc[:, 0].str.strip().ne('').all():
                self._frames['analysis'] = document.set_axis(headers, axis=1)
                return self._frames['analysis'].copy()
        matrix = (self._frames["document"].values.tolist() if "document" in self._frames
                  else [[self.cells.get((r, c), "") for c in range(columns)] for r in range(1, rows)])
        frame = pd.DataFrame([row for row in matrix if any(v.strip() for v in row)], columns=headers)
        self._frames["analysis"] = frame
        return frame.copy()

    def _invalidate_frames(self):
        if self._prepared_load:
            # restore() already invalidated the previous sheet. Consume once
            # so a reentrant edit/unknown notification still invalidates fully.
            self._prepared_load = False
            return
        changes = self._frame_change
        columns = {}
        if isinstance(changes, ColumnChanges) and self._extent is not None:
            columns = changes.frame_updates(self._frames.get('document')) or {}
        elif isinstance(changes, ColumnChanges):
            pass  # Unknown structural state retains complete invalidation.
        elif changes and self._extent is not None:
            for (row, column), value in changes.items():
                previous = self.cells.get((row, column), "")
                if (row <= 0 or not isinstance(value, str) or not value or value.isspace()
                        or not previous or previous.isspace()):
                    columns.clear()
                    break
                updates = columns.get(column)
                if updates is None:
                    updates = columns[column] = ([], [])
                updates[0].append(row - 1)
                updates[1].append(value)
        if columns:
            # Existing nonblank data cells cannot change headers, row inclusion
            # or extent. Public reads remain detached from these owned frames.
            width = self._extent[1]
            for kind, frame in list(self._frames.items()):
                if (len(frame) == self._document_rows and len(frame.columns) == width
                        and all(dtype == object for dtype in frame.dtypes)):
                    if isinstance(changes, ColumnChanges):
                        # Keep a single owned object block. Replacing each
                        # column separately fragments the table and makes
                        # every observer's detached copy consolidate it again.
                        values = frame.to_numpy(copy=True)
                        for column, (rows, replacements) in columns.items():
                            values[rows, column] = replacements
                        updated = pd.DataFrame(values, index=frame.index.copy(),
                                               columns=frame.columns.copy(), copy=False)
                        updated.attrs = deepcopy(frame.attrs)
                        self._frames[kind] = updated
                        continue
                    for column, (rows, replacements) in columns.items():
                        if len(rows) == 1:
                            frame.iat[rows[0], column] = replacements[0]
                        else:
                            # Replace one owned object column in a single batch.
                            # Unlike mutating to_numpy(copy=False), this is also
                            # correct for fragmented blocks and copy-on-write.
                            values = frame.iloc[:, column].to_numpy(copy=True)
                            values[rows] = replacements
                            frame.isetitem(column, values)
                else:
                    # Analysis frames with omitted blank rows have a different
                    # positional map. Keep their original full rebuild behavior.
                    del self._frames[kind]
            return True
        # Headers, blanks, growth, replacement and unknown notifications retain
        # full invalidation. No change summary is inferred from an old revision.
        self._frames.clear()
        self._borrowed_frames = False
        self._extent = None
        self._selection_extent = None
        self._selection_bounds = None

    def _cell_extent(self):
        if self._extent is None:
            self._extent = (max((row for row, _ in self.cells), default=-1) + 1,
                            max((column for _, column in self.cells), default=-1) + 1)
        return self._extent

    def selection_extent(self):
        """Occupied rectangle, excluding reserved cells and empty tail markers."""
        if self._selection_extent is None:
            bounds = self.selection_bounds()
            self._selection_extent = (bounds[2] + 1, bounds[3] + 1) if bounds else (0, 0)
        return self._selection_extent

    def selection_bounds(self):
        if self._selection_bounds is None:
            height, width = self._cell_extent()
            self._selection_bounds = (rectangular_cell_bounds(self.cells, range(height), width)
                                      if height * width <= 4 * len(self.cells)
                                      else nonempty_cell_bounds(self.cells.items()))
        return self._selection_bounds

    def document_shape(self):
        """Document dimensions excluding row-1 headers and reserved blank cells."""
        if not self.cells:
            return 0, 0
        height, width = self._cell_extent()
        return max(self._document_rows, height - 1), width

    def document_frame(self):
        """Save a draft exactly, including duplicate headers and empty rows."""
        if "document" in self._frames:
            return self._frames["document"].copy()
        if not self.cells:
            return pd.DataFrame()
        if isinstance(self.cells, VersionCells) and self.cells.version is not None:
            frame = self.cells.version.to_frame()
            self._frames['document'] = frame
            return frame.copy()
        height, width = self._cell_extent()
        height = max(self._document_rows + 1, height)
        headers = [self.cells.get((0, c), "") for c in range(width)]
        frame = pd.DataFrame([[self.cells.get((r, c), "") for c in range(width)]
                             for r in range(1, height)], columns=headers)
        self._frames["document"] = frame
        return frame.copy()

    def _document_view(self):
        """Internal borrowed read of immutable data; public reads stay detached."""
        return self._read_frame_view('document')

    def _literal_source(self, frame=None):
        """Prove a request shares this current version's readonly document region."""
        version = self.literal_version
        if version is None or not version.dense:
            return None
        try:
            source = LiteralFrameSource(version, self._document_view())
        except (TypeError, ValueError):
            return None  # Unknown cache metadata/layout retains full validation.
        return source if frame is None or source.matches(frame, version) else None

    def _analysis_view(self):
        return self._read_frame_view('analysis')

    def _read_frame_view(self, kind):
        reader = self.document_frame if kind == 'document' else self.frame
        version = self.literal_version
        if version is None:
            return reader()
        frame = self._frames.get(kind)
        if frame is None:
            if kind == 'document':
                frame = self._frames[kind] = version.to_frame()
            else:
                reader()
                frame = self._frames.get(kind)
        if frame is None:
            return reader()
        # A readonly buffer export also prevents callers from reenabling array
        # writes. Fresh pandas metadata wrappers never share mutable attrs.
        self._borrowed_frames = True
        return _readonly_frame(frame)

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


class _SheetHeader(RangeSelectionHeader):
    """Native header styling with range-based selection for uniform sheets.

    Qt's header asks isColumnSelected for each painted column, which calls
    Python model.flags for every record. A rectangular sheet selection already
    contains that information. Custom/disabled-cell models keep Qt's path.
    """

    def paintSection(self, painter, rect, section):
        super().paintSection(painter, rect, section)
        gap = getattr(self.model(), "hidden_rows_before", None)
        if self.orientation() != Qt.Orientation.Vertical or gap is None or gap(section) is None:
            return
        painter.save()
        colour = _hidden_row_colour()
        painter.setPen(QPen(colour, 2, Qt.PenStyle.DashLine))
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        # A small fold mark also identifies the boundary without relying on colour.
        painter.setPen(QPen(colour, 1.5))
        x, y = rect.right() - 7, rect.top() + 3
        painter.drawLine(x - 3, y, x, y + 3)
        painter.drawLine(x, y + 3, x + 3, y)
        painter.restore()

class SheetView(RangeSelectionTableView):
    table_pasted = pyqtSignal()
    paste_report_changed = pyqtSignal()

    def __init__(self, model, *, metadata_locks=False):
        super().__init__()
        self._paste_source = None
        self.keyboard_editing = False
        self.clipboard_outline = ClipboardRangeOutline(self)
        self.metadata_locks_enabled = bool(metadata_locks)
        if self.metadata_locks_enabled:
            self.setItemDelegate(ColumnLockDelegate(self))
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
            previous.metadata_locks_changed.disconnect(self.viewport().update)
        super().setModel(model)
        model.modelReset.connect(self.clipboard_outline.clear)
        model.dataChanged.connect(self.clipboard_outline.clear)
        self._paste_source = source if isinstance(source, SheetModel) else None
        if self._paste_source is not None and previous is not source:
            source.paste_report_changed.connect(self._paste_feedback_changed)
            source.metadata_locks_changed.connect(self.viewport().update)
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

    def paintEvent(self, event):
        super().paintEvent(event)
        model = self.model()
        gap = getattr(model, "hidden_rows_before", None)
        first = self.rowAt(0)
        if gap is None or first < 0:
            return
        last = self.rowAt(self.viewport().height() - 1)
        if last < 0:
            last = model.rowCount() - 1
        positions = [self.rowViewportPosition(row) for row in range(max(1, first), last + 1)
                     if gap(row) is not None]
        if not positions:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QPen(_hidden_row_colour(), 2, Qt.PenStyle.DashLine))
        for y in positions:
            if 0 <= y < self.viewport().height():
                painter.drawLine(0, y, self.viewport().width() - 1, y)
        painter.end()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            row = self.rowAt(event.pos().y())
            gap = getattr(self.model(), "hidden_rows_before", None)
            if (row >= 1 and gap is not None and gap(row) is not None
                    and 0 <= event.pos().y() - self.rowViewportPosition(row) <= 4):
                tip = self.model().headerData(row, Qt.Orientation.Vertical, Qt.ItemDataRole.ToolTipRole)
                QToolTip.showText(event.globalPos(), tip, self.viewport())
                return True
        return super().viewportEvent(event)

    def toggle_column_lock(self, index=None):
        if not self.metadata_locks_enabled:
            return False
        index = self.currentIndex() if index is None else index
        if not index.isValid():
            return False
        if self.state() == self.State.EditingState:
            editor = QApplication.focusWidget()
            if editor is not None and self.isAncestorOf(editor):
                self.commitData(editor)
                self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        model, (_row, column) = self.source_cell(index)
        if not hasattr(model, "set_clipboard_locks"):
            return False
        name = model.data(model.index(0, column), Qt.ItemDataRole.EditRole)
        if not is_metadata_column(name):
            return False
        model.set_clipboard_locks(set(model.clipboard_locks) ^ {name})
        return True

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        delegate = self.itemDelegateForIndex(index)
        if (event.button() == Qt.MouseButton.LeftButton and isinstance(delegate, ColumnLockDelegate)
                and delegate.lock_state(index) is not None
                and delegate.lock_rect(self.visualRect(index)).contains(event.position().toPoint())):
            self.toggle_column_lock(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def selectAll(self):
        """Select in one batched change so Qt does not repaint in stages."""
        model = self.model()
        bounds = model.selection_bounds()
        if bounds is None:
            self.clearSelection()
            return
        top, left, bottom, right = bounds
        selection = QItemSelection(model.index(top, left), model.index(bottom, right))
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
        projected = getattr(model, "rows", None) is not None
        if projected and row + len(matrix) > model.rowCount():
            raise ValueError(f"Paste fits only within displayed rows. Pasted {len(matrix):,} rows but only {max(0, model.rowCount() - row):,} remain. Hidden rows will not be changed.")
        if not projected and not replace and (row, column) == (0, 0) and not was_empty and len(matrix) > 1:
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
        elif type(model) is not SheetModel or not model._paste_value_matrix(matrix, row, column):
            cells = model.cells if type(model) is SheetModel else None
            changes = {(row + r, column + c): value for r, line in enumerate(matrix)
                       for c, value in enumerate(line)
                       if cells is None or cells.get((row + r, column + c), "") != value}
            model.paste_cells(changes,
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
        if not getattr(model, "uniform_selectable", False) and any(
                not model.flags(model.index(row, column)) & Qt.ItemFlag.ItemIsEditable
                for row in range(top, bottom + 1) for column in range(left, right + 1)):
            return False
        if not self.copy():
            return False
        # Copy succeeded first. One normal edit owns the clear and Undo; no
        # pending move can later delete a different source or hidden record.
        # A plain sheet's edit already skips locked columns: copy the whole
        # rectangle, but clear only its unlocked cells in the same Undo step.
        changes = {(row, column): "" for row, column in model.cells
                   if top <= row <= bottom and left <= column <= right}
        report = getattr(model, "paste_report", None)
        if isinstance(model, SheetModel) and report is not None and report.bounds == bounds and report.rows_added:
            # Cutting the entire just-pasted range also removes its newly added
            # empty tail. Keep every pre-existing source row, including blanks;
            # the edit command restores both extent and values on Undo.
            model.edit(changes, document_rows=model._document_rows - report.rows_added)
        else:
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
        if event.key() == Qt.Key.Key_L and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.toggle_column_lock()
        elif (event.key() == Qt.Key.Key_V
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
                if len(bounds) == 1:
                    top, bottom, left, right = bounds[0]
                    changes = {(row, column): "" for row, column in model.cells
                               if top <= row <= bottom and left <= column <= right}
                else:
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


def _readonly_frame(frame):
    import numpy as np
    values = np.asarray(memoryview(frame.to_numpy(copy=False)).toreadonly())
    result = pd.DataFrame(values, index=frame.index.copy(deep=True),
                          columns=frame.columns.copy(deep=True), copy=False)
    result.attrs = deepcopy(frame.attrs)
    return result


def prepare_sheet_version(frame, version, *, source=None):
    """Reuse a proved immutable source, while keeping mutable GUI frames owned."""
    if not isinstance(version, LiteralTableVersion) or not version.dense:
        return None
    proved = isinstance(source, LiteralFrameSource) and source.matches(frame, version)
    if not proved and not version.matches_frame(frame):
        return None
    document = _readonly_frame(version.to_frame())
    headers = [name.strip() or f'Column {column_letter(column)}'
               for column, name in enumerate(version.headers)]
    analysis = None
    if len(set(headers)) == len(headers):
        if document.iloc[:, 0].str.strip().ne('').all():
            analysis = document.set_axis(headers, axis=1, copy=False)
        else:
            analysis = document.loc[document.apply(lambda col: col.str.strip().ne('')).any(axis=1)]
            analysis = analysis.set_axis(headers, axis=1).reset_index(drop=True)
            analysis = _readonly_frame(analysis)
    return {'document': document, 'analysis': analysis, 'version': version,
            'document_source': LiteralFrameSource(version, document),
            'input_source': source if proved else None,
            'height': max(100, version.row_count + 21), 'width': max(26, len(headers) + 3),
            'rows': version.row_count, 'exact_extent': True}


def prepare_sheet_frame(frame):
    """Build detached literal-cell storage without constructing a Qt object.

    Kept equivalent to load/_load_matrix, including blank trailing row markers.
    Only a GUI-thread load may consume the resulting owned cell dictionary.
    """
    document = frame.fillna("").astype(str).reset_index(drop=True)
    document.columns = [str(name) for name in document.columns]
    matrix = [list(document.columns)] + document.values.tolist() if len(document.columns) else []
    if matrix and all(chain.from_iterable(matrix)):
        cells = dict(zip(product(range(len(matrix)), range(len(matrix[0]))), chain.from_iterable(matrix)))
        height, width = max(100, len(matrix) + 20), max(26, len(matrix[0]) + 3)
    else:
        cells, height, width = SheetModel.state_from_matrix(matrix)
    headers = [name.strip() or f"Column {column_letter(column)}"
               for column, name in enumerate(document.columns)]
    analysis = None
    if len(set(headers)) == len(headers):
        if len(document.columns) and document.iloc[:, 0].str.strip().ne("").all():
            analysis = document.set_axis(headers, axis=1)
        else:
            analysis = pd.DataFrame([row for row in matrix[1:] if any(value.strip() for value in row)],
                                    columns=headers)
    return {"document": document, "analysis": analysis, "cells": cells, "height": height, "width": width,
            "rows": max(0, len(matrix) - 1),
            "exact_extent": bool(matrix and len(matrix[0]) and str(matrix[0][-1]))}

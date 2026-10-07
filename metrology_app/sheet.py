"""Small spreadsheet model: editable cells, range clipboard and undo/redo."""
import csv
from io import StringIO

import pandas as pd
from PyQt6.QtCore import (
    QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QFont, QKeySequence, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QStyle, QStyleOptionHeader, QTableView,
)

from .settings import get_settings


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

    def __init__(self):
        super().__init__()
        self.cells = {}
        self._document_rows = 0
        self._preserves_record_positions = False
        self._frames = {}
        self._extent = None
        self.changed.connect(self._invalidate_frames)
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
        return CELL_FLAGS if index.isValid() else Qt.ItemFlag.ItemIsEditable

    @property
    def uniform_selectable(self):
        return type(self).flags is SheetModel.flags and type(self).headerData is SheetModel.headerData

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        self.edit({(index.row(), index.column()): str(value)})
        return True

    def edit(self, changes):
        changes = {key: value for key, value in changes.items() if self.cells.get(key, "") != value}
        if changes:
            self.undo.push(CellEdit(self, changes))

    @property
    def preserves_record_positions(self):
        """Cell edits keep record positions; explicit table replacement may reorder."""
        return self._preserves_record_positions

    def apply(self, changes):
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

    def load(self, frame):
        matrix = [list(frame.columns)] + frame.fillna("").astype(str).values.tolist() if len(frame.columns) else []
        self.load_matrix(matrix)

    def load_matrix(self, matrix):
        """Replace every cell with a rectangular clipboard matrix."""
        self.restore(self.state_from_matrix(matrix), emit_changed=False)
        self.undo.clear()
        self.undo.setClean()
        self.changed.emit()

    def replace_matrix(self, matrix):
        """Replace the table as one user-visible, undoable operation."""
        command = TableReplace(self, matrix)
        if command.before != command.after:
            self.undo.push(command)

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
        # Model edits, replacement and Undo invalidate together. Returned
        # frames remain detached: callers cannot change a later Save snapshot.
        self._frames.clear()
        self._extent = None

    def _cell_extent(self):
        if self._extent is None:
            self._extent = (max((row for row, _ in self.cells), default=-1) + 1,
                            max((column for _, column in self.cells), default=-1) + 1)
        return self._extent

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

    def __init__(self, model):
        super().__init__()
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

    def selectAll(self):
        """Select in one batched change so Qt does not repaint in stages."""
        model = self.model()
        rows, columns = model.rowCount(), model.columnCount()
        if rows <= 0 or columns <= 0:
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
            current = self._data_size(model)
            if pasted[0] < current[0] or pasted[1] < current[1]:
                choice = self.mismatched_paste_choice(pasted, current)
                if choice == "cancel":
                    return
                replace = choice == "replace"
        if replace:
            # Explicit Ctrl+Shift+V replacement: clear the rest of the table so
            # no stale cells from a previously pasted file survive.
            model.replace_matrix(matrix)
        else:
            model.edit({(row + r, column + c): v for r, line in enumerate(matrix) for c, v in enumerate(line)})
        if matrix and (was_empty or replace):
            # The first paste into an empty sheet replaces the table, so the
            # window should re-run automatic wafer/parameter identification.
            self.table_pasted.emit()

    def copy(self):
        if getattr(self.model(), 'uniform_selectable', False):
            ranges = self.selectionModel().selection()
            if not ranges:
                return
            rows = range(min(r.top() for r in ranges), max(r.bottom() for r in ranges) + 1)
            columns = range(min(r.left() for r in ranges), max(r.right() for r in ranges) + 1)
        else:
            indexes = self.selectedIndexes()
            if not indexes:
                return
            rows = range(min(i.row() for i in indexes), max(i.row() for i in indexes) + 1)
            columns = range(min(i.column() for i in indexes), max(i.column() for i in indexes) + 1)
        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow([self.model().cells.get((row, c), "") for c in columns])
        QApplication.clipboard().setText(output.getvalue())

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_V
                and event.modifiers() == (Qt.KeyboardModifier.ControlModifier
                                          | Qt.KeyboardModifier.ShiftModifier)):
            self.paste(replace=True)
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
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

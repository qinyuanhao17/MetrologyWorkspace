"""Range-based Qt notifications for models whose valid cells are all selectable."""
from PyQt6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QPersistentModelIndex, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QApplication, QAbstractItemView, QComboBox, QHeaderView,
                            QStyle, QStyleOptionHeader, QTableView, QTableWidget)


class RangeSelectionHeader(QHeaderView):
    """Preserve native header states without expanding uniform selected ranges."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._native_header_press = False

    def mousePressEvent(self, event):
        self._native_header_press = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._native_header_press = False

    def initStyleOptionForIndex(self, option, section):
        model = self.model()
        if (not getattr(model, "uniform_selection_flags", False)
                or (self._native_header_press and QApplication.mouseButtons() != Qt.MouseButton.NoButton)):
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
        if self.window().isActiveWindow():
            option.state |= QStyle.StateFlag.State_Active
        if self.sectionsClickable():
            if self.underMouse() and self.logicalIndexAt(self.mapFromGlobal(QCursor.pos())) == section:
                option.state |= QStyle.StateFlag.State_MouseOver
            if self.highlightSections():
                if intersects:
                    option.state |= QStyle.StateFlag.State_On
                if full:
                    option.state |= QStyle.StateFlag.State_Sunken
        option.section = section
        text = model.headerData(section, self.orientation(), Qt.ItemDataRole.DisplayRole)
        option.text = "" if text is None else str(text)
        alignment = model.headerData(section, self.orientation(), Qt.ItemDataRole.TextAlignmentRole)
        option.textAlignment = alignment if alignment is not None else self.defaultAlignment()
        option.iconAlignment = Qt.AlignmentFlag.AlignVCenter
        option.orientation = self.orientation()
        if hasattr(option, "textElideMode"):
            option.textElideMode = self.textElideMode()
        visual = self.visualIndex(section)
        position = self.sectionPosition(section)
        first = position == 0
        last = position + self.sectionSize(section) == self.length()
        reverse = horizontal and self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        option.position = (QStyleOptionHeader.SectionPosition.OnlyOneSection if first and last
                           else (QStyleOptionHeader.SectionPosition.End if reverse else QStyleOptionHeader.SectionPosition.Beginning) if first
                           else (QStyleOptionHeader.SectionPosition.Beginning if reverse else QStyleOptionHeader.SectionPosition.End) if last
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


_DIRECTIONS = {Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0),
               Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1)}


class _ExcelRangeKeys:
    """Extend rectangular selections to data boundaries with Ctrl+Shift+Arrow."""

    def mousePressEvent(self, event):
        self._excel_range = None
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        direction = _DIRECTIONS.get(event.key())
        if modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and direction:
            if self._extend_excel_range(*direction):
                event.accept()
                return
        if event.key() not in (Qt.Key.Key_Control, Qt.Key.Key_Shift):
            self._excel_range = None
        super().keyPressEvent(event)

    def _populated_cell(self, index):
        if not index.flags() & Qt.ItemFlag.ItemIsSelectable:
            return False
        widget = self.indexWidget(index)
        if isinstance(widget, QComboBox):
            return widget.currentText() != ""
        value = index.data(Qt.ItemDataRole.DisplayRole)
        return ((value is not None and value != "")
                or index.data(Qt.ItemDataRole.CheckStateRole) is not None)

    def _extend_excel_range(self, row_step, column_step):
        index = self.currentIndex()
        if not index.isValid() or self.selectionMode() == QAbstractItemView.SelectionMode.NoSelection:
            return False
        model = self.model()
        parent = index.parent()
        row, column = index.row(), index.column()
        vertical = bool(row_step)
        step = row_step or column_step
        start = row if vertical else column
        count = model.rowCount(parent) if vertical else model.columnCount(parent)
        hidden = self.isRowHidden if vertical else self.isColumnHidden
        positions = range(start + step, count if step > 0 else -1, step)
        cells = (model.index(position if vertical else row, column if vertical else position, parent)
                 for position in positions if not hidden(position))
        first = next(cells, None)
        if first is None:
            return True
        target = first
        if self._populated_cell(index) and self._populated_cell(first):
            for cell in cells:
                if not self._populated_cell(cell):
                    break
                target = cell
        elif not self._populated_cell(first):
            for cell in cells:
                target = cell
                if self._populated_cell(cell):
                    break

        previous = getattr(self, "_excel_range", None)
        anchor = previous[0] if previous is not None and previous[1] == index and previous[0].isValid() else index
        top, bottom = sorted((anchor.row(), target.row()))
        left, right = sorted((anchor.column(), target.column()))
        selection = QItemSelection(model.index(top, left, parent), model.index(bottom, right, parent))
        self.selectionModel().setCurrentIndex(target, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self._excel_range = QPersistentModelIndex(anchor), QPersistentModelIndex(target)
        self.scrollTo(target)
        return True


class RangeSelectionTableWidget(_ExcelRangeKeys, QTableWidget):
    """QTableWidget with the same data-boundary navigation as model-based tables."""


class RangeSelectionTableView(_ExcelRangeKeys, QTableView):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        for orientation in (Qt.Orientation.Horizontal, Qt.Orientation.Vertical):
            header = RangeSelectionHeader(orientation, self)
            header.setSectionsClickable(True)
            header.setHighlightSections(True)
            if orientation == Qt.Orientation.Horizontal:
                self.setHorizontalHeader(header)
            else:
                self.setVerticalHeader(header)

    def selectionChanged(self, selected, deselected):
        model = self.model()
        if (not getattr(model, "uniform_selection_flags", False)
                or any(r.isValid() and r.model() is not model for r in (*selected, *deselected))):
            return QTableView.selectionChanged(self, selected, deselected)

        def first_cell(ranges):
            for span in ranges:
                if span.isValid():
                    first = QModelIndex(span.topLeft())
                    return QItemSelection(first, first)
            return QItemSelection()

        # Qt 6.11 QTableView emits Add/Remove for only the first index, but
        # obtains it by expanding every cell. Keep those SAME native events;
        # the real selection model and its signals still contain full ranges.
        QTableView.selectionChanged(self, first_cell(selected), first_cell(deselected))
        QAbstractItemView.selectionChanged(self, selected, deselected)

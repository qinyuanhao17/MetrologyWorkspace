"""Selectable wafer × parameter boxes, using native spreadsheet selection."""
from PyQt6.QtCore import QItemSelection, QItemSelectionModel, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from .table_clipboard import attach_copy_feedback


class MapSelector(QTableWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__(objectName="mapSelector")
        attach_copy_feedback(self)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setShowGrid(False)
        self.setWordWrap(True)
        self.setAutoScroll(True)
        self.itemSelectionChanged.connect(self._selection_changed)
        self.wafers, self.metrics = [], []
        self.labels = {}
        self.enabled_cells = None
        self.pending_draw = False
        self._selected_cells = None
        self.selectionModel().selectionChanged.connect(self._invalidate_selected_cells)
        for signal in (self.model().dataChanged, self.model().modelReset,
                       self.model().rowsInserted, self.model().rowsRemoved,
                       self.model().columnsInserted, self.model().columnsRemoved):
            signal.connect(self._invalidate_selected_cells)

    def _invalidate_selected_cells(self, *_):
        self._selected_cells = None

    def _selection_changed(self):
        """A user selection needs an explicit Draw, even if changed back."""
        self.pending_draw = True
        self.changed.emit()

    def selected_cells(self):
        if self._selected_cells is None:
            self._selected_cells = frozenset((self.wafers[index.row()], self.metrics[index.column()])
                                            for index in self.selectedIndexes())
        return set(self._selected_cells)

    def set_selected_cells(self, cells, *, notify=True):
        """Select an exact set of wafer/metric boxes after an array rebuild."""
        cells = set(cells)
        self.blockSignals(True)
        self._select_cells(cells)
        self.blockSignals(False)
        if notify:
            self._selection_changed()

    def _select_cells(self, cells):
        # Qt stores selections as rectangles. Apply them together instead of
        # repeatedly merging one more selected cell into a growing selection.
        selection = QItemSelection()
        active = {}
        for row in range(len(self.wafers) + 1):
            runs, start = set(), None
            for column in range(len(self.metrics) + 1):
                cell = ((self.wafers[row], self.metrics[column])
                        if row < len(self.wafers) and column < len(self.metrics) else None)
                chosen = cell in cells and (self.enabled_cells is None or cell in self.enabled_cells)
                if chosen and start is None:
                    start = column
                elif not chosen and start is not None:
                    runs.add((start, column - 1))
                    start = None
            for bounds in tuple(active):
                if bounds not in runs:
                    first_row = active.pop(bounds)
                    selection.select(self.model().index(first_row, bounds[0]),
                                     self.model().index(row - 1, bounds[1]))
            for bounds in runs:
                active.setdefault(bounds, row)
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def reconciled_cells(self, previous):
        """Keep exact boxes when possible, otherwise carry metrics to new wafers."""
        previous = set(previous)
        available = {
            (wafer, metric)
            for wafer in self.wafers
            for metric in self.metrics
        }
        exact = previous & available
        if exact:
            return exact
        metrics = {
            metric for _wafer, metric in previous if metric in self.metrics
        }
        return {
            (wafer, metric)
            for wafer in self.wafers
            for metric in metrics
        }

    def set_array(self, wafers, metrics, labels=None, enabled_cells=None):
        labels = labels or {}
        enabled_cells = None if enabled_cells is None else set(enabled_cells)
        if (wafers == self.wafers and metrics == self.metrics
                and labels == self.labels and enabled_cells == self.enabled_cells):
            return
        parameters_changed = (list(metrics) != self.metrics
                              or enabled_cells != self.enabled_cells)
        if list(wafers) != self.wafers or parameters_changed:
            self.pending_draw = True
        previous = self.selected_cells()
        old_cells = (
            {(w, m) for w in self.wafers for m in self.metrics}
            if self.enabled_cells is None else set(self.enabled_cells)
        )
        self.blockSignals(True)
        reused = self._reuse_cells(wafers, metrics, labels)
        self.wafers, self.metrics = list(wafers), list(metrics)
        self.labels = labels.copy()
        self.enabled_cells = enabled_cells
        if not reused:
            self.clear()
            self.setRowCount(len(wafers))
            self.setColumnCount(len(metrics))
        self.setVerticalHeaderLabels([labels.get(w, w) for w in wafers])
        self.setHorizontalHeaderLabels(metrics)
        chosen_cells = set()
        for row, wafer in enumerate(wafers):
            for col, metric in enumerate(metrics):
                name = labels.get(wafer, wafer)
                item = self.item(row, col) if reused else None
                new_item = item is None
                if new_item:
                    item = QTableWidgetItem(f"{metric}\n{name}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                enabled = (
                    enabled_cells is None or (wafer, metric) in enabled_cells
                )
                if enabled and (new_item or (wafer, metric) not in old_cells):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    item.setToolTip(
                        f"{name} / {metric}\n"
                        "Drag to select; Ctrl adds or removes boxes."
                    )
                elif not enabled and (new_item or (wafer, metric) in old_cells):
                    item.setFlags(
                        item.flags()
                        & ~Qt.ItemFlag.ItemIsEnabled
                        & ~Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setToolTip(
                        f"{metric} is not selected for this data source."
                    )
                if new_item:
                    self.setItem(row, col, item)
                if enabled and (
                    parameters_changed or (wafer, metric) in previous
                    or (wafer, metric) not in old_cells
                ):
                    chosen_cells.add((wafer, metric))
        for header, count, size, minimum in ((self.horizontalHeader(), len(metrics), 260, 170),
                                             (self.verticalHeader(), len(wafers), 190, 110)):
            header.setMinimumSectionSize(minimum)
            header.setDefaultSectionSize(size)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch if count <= 4 else QHeaderView.ResizeMode.Interactive)
        self._select_cells(chosen_cells)
        self.blockSignals(False)
        self.changed.emit()

    def _reuse_cells(self, wafers, metrics, labels):
        """Keep unchanged boxes when a few wafer or parameter choices change."""
        old, new = set(self.wafers), set(wafers)
        shared = old & new
        old_metrics, new_metrics = set(self.metrics), set(metrics)
        shared_metrics = old_metrics & new_metrics
        if (len(old) != len(self.wafers) or len(new) != len(wafers)
                or len(old_metrics) != len(self.metrics) or len(new_metrics) != len(metrics)
                or len(old ^ new) > 8 or len(old_metrics ^ new_metrics) > 8
                or [key for key in self.wafers if key in shared] != [key for key in wafers if key in shared]
                or [name for name in self.metrics if name in shared_metrics] != [name for name in metrics if name in shared_metrics]
                or any(self.labels.get(key, key) != labels.get(key, key) for key in shared)):
            return False
        for row in range(len(self.wafers) - 1, -1, -1):
            if self.wafers[row] not in new:
                self.removeRow(row)
        for row, wafer in enumerate(wafers):
            if wafer not in old:
                self.insertRow(row)
        for column in range(len(self.metrics) - 1, -1, -1):
            if self.metrics[column] not in new_metrics:
                self.removeColumn(column)
        for column, metric in enumerate(metrics):
            if metric not in old_metrics:
                self.insertColumn(column)
        return True

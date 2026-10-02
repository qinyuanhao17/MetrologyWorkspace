"""Selectable wafer × parameter boxes, using native spreadsheet selection."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem


class MapSelector(QTableWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__(objectName="mapSelector")
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

    def _selection_changed(self):
        """A user selection needs an explicit Draw, even if changed back."""
        self.pending_draw = True
        self.changed.emit()

    def selected_cells(self):
        return {(self.wafers[index.row()], self.metrics[index.column()]) for index in self.selectedIndexes()}

    def set_selected_cells(self, cells, *, notify=True):
        """Select an exact set of wafer/metric boxes after an array rebuild."""
        cells = set(cells)
        self.blockSignals(True)
        self.clearSelection()
        for row, wafer in enumerate(self.wafers):
            for column, metric in enumerate(self.metrics):
                if (wafer, metric) in cells:
                    self.item(row, column).setSelected(True)
        self.blockSignals(False)
        if notify:
            self._selection_changed()

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
        self.wafers, self.metrics = list(wafers), list(metrics)
        self.labels = labels.copy()
        self.enabled_cells = enabled_cells
        self.clear()
        self.setRowCount(len(wafers))
        self.setColumnCount(len(metrics))
        self.setVerticalHeaderLabels([labels.get(w, w) for w in wafers])
        self.setHorizontalHeaderLabels(metrics)
        for row, wafer in enumerate(wafers):
            for col, metric in enumerate(metrics):
                name = labels.get(wafer, wafer)
                item = QTableWidgetItem(f"{metric}\n{name}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                enabled = (
                    enabled_cells is None or (wafer, metric) in enabled_cells
                )
                if enabled:
                    item.setToolTip(
                        f"{name} / {metric}\n"
                        "Drag to select; Ctrl adds or removes boxes."
                    )
                else:
                    item.setFlags(
                        item.flags()
                        & ~Qt.ItemFlag.ItemIsEnabled
                        & ~Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setToolTip(
                        f"{metric} is not selected for this data source."
                    )
                self.setItem(row, col, item)
                item.setSelected(enabled and (
                    parameters_changed or (wafer, metric) in previous
                    or (wafer, metric) not in old_cells
                ))
        for header, count, size, minimum in ((self.horizontalHeader(), len(metrics), 260, 170),
                                             (self.verticalHeader(), len(wafers), 190, 110)):
            header.setMinimumSectionSize(minimum)
            header.setDefaultSectionSize(size)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch if count <= 4 else QHeaderView.ResizeMode.Interactive)
        self.blockSignals(False)
        self.changed.emit()

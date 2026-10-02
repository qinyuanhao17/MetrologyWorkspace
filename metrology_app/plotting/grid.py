"""Resizable panel grid shared by the PyQtGraph workspace pages."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QHBoxLayout, QSizePolicy, QSplitter, QSplitterHandle, QVBoxLayout, QWidget,
)


class PlotPanel(QWidget):
    """Keep a light title area and plot together as one resizable panel.

    ``side_widget`` is optional and, when given, sits in a narrow column to the
    right of the plot. The Trend page uses it for its compare / unlink control
    so a primary action is visible instead of hidden behind a right click.
    """

    def __init__(self, heading, plot_widget, parent=None, side_widget=None):
        super().__init__(parent)
        self.setObjectName("plotPanel")
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#20242a"))
        self.setPalette(palette)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(0)
        heading.setMinimumWidth(0)
        heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.side_widget = side_widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(heading)
        if side_widget is None:
            layout.addWidget(plot_widget, 1)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(plot_widget, 1)
            side = QWidget()
            side.setObjectName("plotSide")
            side_layout = QVBoxLayout(side)
            side_layout.setContentsMargins(0, 0, 0, 0)
            side_layout.setSpacing(4)
            # The control column matches the plot's height; the control's own
            # layout keeps its buttons at the top instead of stretching them.
            side_layout.addWidget(side_widget, 1)
            row.addWidget(side)
            layout.addLayout(row, 1)


class _Handle(QSplitterHandle):
    """Restore the default panel layout on double-click."""

    def mouseDoubleClickEvent(self, event):
        grid = getattr(self.splitter(), "grid", None)
        if grid is not None:
            grid.reset_layout()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _Splitter(QSplitter):
    def __init__(self, orientation, grid):
        super().__init__(orientation)
        self.grid = grid

    def createHandle(self):
        return _Handle(self.orientation(), self)


class PanelGrid(_Splitter):
    """Lay out resizable panels while keeping column widths aligned."""

    def __init__(self, columns=1, parent=None):
        super().__init__(Qt.Orientation.Vertical, self)
        self.setObjectName("panelGrid")
        if parent is not None:
            self.setParent(parent)
        self.setChildrenCollapsible(True)
        self.setHandleWidth(6)
        self.columns = max(1, int(columns))
        self.panels = []
        self.placeholders = []
        self.row_splitters = []
        self._fixed_row_height = None
        self._height_placeholder = None

    def set_minimum_row_height(self, rows, panel_height):
        """Reserve full rows but let their columns share the viewport width."""
        rows = max(1, int(rows))
        height = rows * int(panel_height) + max(0, rows - 1) * self.handleWidth()
        self.setMinimumSize(0, height)

    def set_fixed_row_height(self, rows, panel_height):
        """Keep sparse result pages from stretching their remaining rows."""
        rows = max(1, int(rows))
        self._fixed_row_height = int(panel_height)
        height = rows * self._fixed_row_height + max(0, rows - 1) * self.handleWidth()
        self.setMinimumSize(0, height)

    def add_panel(self, widget):
        index = len(self.panels)
        row = index // self.columns
        while len(self.row_splitters) <= row:
            splitter = _Splitter(Qt.Orientation.Horizontal, self)
            splitter.setObjectName("panelRow")
            splitter.setChildrenCollapsible(True)
            splitter.setHandleWidth(6)
            if self._fixed_row_height is not None:
                splitter.setFixedHeight(self._fixed_row_height)
            splitter.splitterMoved.connect(
                lambda _position, _index, source=splitter: self.sync_columns(source))
            self.row_splitters.append(splitter)
            self.addWidget(splitter)
        self.row_splitters[row].addWidget(widget)
        self.panels.append(widget)

    def complete_last_row(self, minimum_width=0):
        """Reserve missing columns so a partial row keeps normal panel widths."""
        if not self.row_splitters:
            return
        row = self.row_splitters[-1]
        while row.count() < self.columns:
            placeholder = QWidget(objectName="plotPlaceholder")
            placeholder.setEnabled(False)
            placeholder.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            placeholder.setMinimumWidth(max(0, int(minimum_width)))
            row.addWidget(placeholder)
            self.placeholders.append(placeholder)
        for index in range(row.count()):
            row.setStretchFactor(index, 1)
        row.setSizes([1] * row.count())
        self.sync_columns(row)
        if self._fixed_row_height is not None and self._height_placeholder is None:
            filler = QWidget(objectName="plotHeightPlaceholder")
            filler.setEnabled(False)
            filler.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._height_placeholder = filler
            self.addWidget(filler)
            for index in range(len(self.row_splitters)):
                self.setStretchFactor(index, 0)
            self.setStretchFactor(self.count() - 1, 1)
            self.setSizes(
                [self._fixed_row_height] * len(self.row_splitters) + [1_000_000]
            )

    def reset_layout(self):
        for splitter in (self, *self.row_splitters):
            if splitter.count():
                splitter.setSizes([1] * splitter.count())
        self.sync_columns(self.row_splitters[0] if self.row_splitters else self)

    def sync_columns(self, source):
        sizes = source.sizes()
        for splitter in self.row_splitters:
            if splitter is not source and splitter.count() == source.count():
                splitter.setSizes(sizes)

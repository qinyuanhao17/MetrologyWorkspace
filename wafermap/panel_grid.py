"""Resizable panel area for the PyQtGraph workspace pages.

Rows are stacked in an outer splitter and every row is an inner splitter, so the
boundaries between plots can be dragged to give one panel more room (or to push
it out of the way completely and drag it back). Column widths stay in step
across rows, which keeps the array aligned like a grid, and double-clicking any
boundary restores the default layout.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QSplitterHandle


class _Handle(QSplitterHandle):
    """Splitter handle: a double click restores the default panel layout."""

    def mouseDoubleClickEvent(self, event):
        grid = getattr(self.splitter(), "grid", None)
        if grid is not None:
            grid.reset_layout()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _Splitter(QSplitter):
    """Splitter that reports double clicks on its handles back to the grid."""

    def __init__(self, orientation, grid):
        super().__init__(orientation)
        self.grid = grid

    def createHandle(self):
        return _Handle(self.orientation(), self)


class PanelGrid(_Splitter):
    """A rows x columns panel area with draggable boundaries."""

    def __init__(self, columns=1, parent=None):
        super().__init__(Qt.Orientation.Vertical, self)
        self.setObjectName("panelGrid")
        if parent is not None:
            self.setParent(parent)
        # A boundary may be dragged past its neighbour, which hides that panel
        # completely; dragging back shows it again and a double click resets.
        self.setChildrenCollapsible(True)
        self.setHandleWidth(6)
        self.columns = max(1, int(columns))
        self.panels = []
        self.row_splitters = []

    def add_panel(self, widget):
        """Append a panel in reading order, opening a new row when needed."""
        index = len(self.panels)
        row = index // self.columns
        while len(self.row_splitters) <= row:
            splitter = _Splitter(Qt.Orientation.Horizontal, self)
            splitter.setObjectName("panelRow")
            splitter.setChildrenCollapsible(True)
            splitter.setHandleWidth(6)
            splitter.splitterMoved.connect(
                lambda _position, _index, source=splitter: self.sync_columns(source))
            self.row_splitters.append(splitter)
            self.addWidget(splitter)
        self.row_splitters[row].addWidget(widget)
        self.panels.append(widget)

    def reset_layout(self):
        """Restore the default layout: equal rows and equal columns."""
        for splitter in (self, *self.row_splitters):
            if splitter.count():
                splitter.setSizes([1] * splitter.count())
        self.sync_columns(self.row_splitters[0] if self.row_splitters else self)

    def sync_columns(self, source):
        """Mirror a dragged row's column widths onto every other row."""
        sizes = source.sizes()
        for splitter in self.row_splitters:
            if splitter is not source and splitter.count() == source.count():
                splitter.setSizes(sizes)

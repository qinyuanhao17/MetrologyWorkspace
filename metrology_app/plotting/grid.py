"""Resizable panel grid shared by the PyQtGraph workspace pages."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QHBoxLayout, QSizePolicy, QSplitter, QSplitterHandle, QVBoxLayout, QWidget,
)


class PlotPanel(QWidget):
    """Keep a light title area and plot together as one resizable panel."""

    def __init__(self, heading, plot_widget, parent=None, heading_extra=None):
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        if heading_extra is None:
            layout.addWidget(heading)
        else:
            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(6)
            header_layout.addWidget(heading, 1)
            header_layout.addWidget(heading_extra)
            layout.addWidget(header)
        layout.addWidget(plot_widget, 1)


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
        self.row_splitters = []

    def set_minimum_row_height(self, rows, panel_height):
        """Reserve full rows but let their columns share the viewport width."""
        rows = max(1, int(rows))
        height = rows * int(panel_height) + max(0, rows - 1) * self.handleWidth()
        self.setMinimumSize(0, height)

    def add_panel(self, widget):
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
        for splitter in (self, *self.row_splitters):
            if splitter.count():
                splitter.setSizes([1] * splitter.count())
        self.sync_columns(self.row_splitters[0] if self.row_splitters else self)

    def sync_columns(self, source):
        sizes = source.sizes()
        for splitter in self.row_splitters:
            if splitter is not source and splitter.count() == source.count():
                splitter.setSizes(sizes)

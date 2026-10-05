"""Local, non-floating plot docking inside one movable parameter card."""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QSplitter, QSizePolicy
from pyqtgraph.dockarea import Dock, DockArea
from pyqtgraph.dockarea.Dock import DockLabel


def normalize_plot_layouts(layouts):
    """Validate JSON-only UI state before handing a WKB tree to Qt docking."""
    if layouts is None:
        return {}
    if not isinstance(layouts, dict) or set(layouts) - {"preview", "final"}:
        raise ValueError("Invalid parameter plot layout stages.")
    result = {}
    variants = {"match|trend", "match|trend|bias", "match|trend|bias-percent",
                "match|trend|bias|bias-percent"}
    for stage, parameters in layouts.items():
        if not isinstance(parameters, dict):
            raise ValueError("Invalid parameter plot layouts.")
        result[stage] = {}
        for parameter, states in parameters.items():
            if not isinstance(parameter, str) or not parameter.strip() or not isinstance(states, dict):
                raise ValueError("Invalid parameter plot layout name.")
            result[stage][parameter] = {}
            for variant, state in states.items():
                if variant not in variants or not isinstance(state, dict) or set(state) != {"main", "float"} or state["float"] != []:
                    raise ValueError("Invalid parameter plot layout; floating plots are not supported.")
                seen = set()

                def tree(node, depth=0):
                    if depth > 7 or not isinstance(node, (tuple, list)) or len(node) != 3:
                        raise ValueError("Invalid parameter plot layout tree.")
                    kind, children, options = node
                    if kind == "dock":
                        if not isinstance(children, str) or children not in variant.split("|") or children in seen or options != {}:
                            raise ValueError("Invalid or repeated parameter plot.")
                        seen.add(children)
                        return [kind, children, {}]
                    if kind not in ("horizontal", "vertical") or not isinstance(children, (tuple, list)) or not 1 <= len(children) <= 4:
                        raise ValueError("Invalid parameter plot container.")
                    if not isinstance(options, dict) or set(options) != {"sizes"}:
                        raise ValueError("Invalid parameter plot sizes.")
                    sizes = options["sizes"]
                    if (not isinstance(sizes, (tuple, list)) or len(sizes) != len(children)
                            or any(type(size) is not int or size < 0 for size in sizes) or sum(sizes) <= 0):
                        raise ValueError("Invalid parameter plot sizes.")
                    return [kind, [tree(child, depth + 1) for child in children], {"sizes": list(sizes)}]

                main = tree(state["main"])
                if seen != set(variant.split("|")):
                    raise ValueError("Parameter plot layout is incomplete.")
                result[stage][parameter][variant] = {"main": main, "float": []}
    return result


class _PlotLabel(DockLabel):
    def updateStyle(self):
        self.setObjectName("plotDragHandle")
        self.setStyleSheet("")  # Use the workspace's light/dark theme.


def _local_drop(target, event):
    source = event.source()
    if isinstance(source, _PlotDock) and source.area is target.area:
        return True
    target.dockdrop.dragLeaveEvent(event)
    event.ignore()
    return False


class _PlotDock(Dock):
    def updateStyle(self):
        self.widgetArea.setStyleSheet("")

    def dragEnterEvent(self, event):
        if _local_drop(self, event):
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if _local_drop(self, event):
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if _local_drop(self, event):
            super().dropEvent(event)


class ParameterPlotArea(DockArea):
    """Keep existing plot widgets; only rearrange their local Qt containers."""

    layoutChanged = pyqtSignal()
    LABEL_HEIGHT = 24

    def __init__(self, plots, *, plot_height=330, parent=None):
        super().__init__(parent=parent)
        self.plot_height = plot_height
        self._variant = "|".join(plots)
        self._building = True
        self._default_sizes_pending = True
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        titles = {"match": "Match", "trend": "Trend", "bias": "Bias", "bias-percent": "Bias %"}
        for name, plot in plots.items():
            label = _PlotLabel("::  " + titles[name])
            label.setFixedHeight(self.LABEL_HEIGHT)
            label.setCursor(Qt.CursorShape.OpenHandCursor)
            label.setToolTip("Drag to a plot's left/right edge to reorder, or top/bottom edge to stack.\n"
                             "Plots stay inside this parameter. Drag the gaps to resize.")
            label.setAccessibleName(f"Move {titles[name]} plot")
            label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            label.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
            for position, text in (("left", "Move to left edge"), ("right", "Move to right edge"),
                                   ("top", "Move to top row"), ("bottom", "Move to bottom row")):
                action = QAction(text, label)
                action.triggered.connect(lambda _checked=False, p=position, l=label:
                                         l.dock.area.moveDock(l.dock, p, None))
                label.addAction(action)
            dock = _PlotDock(name, label=label, autoOrientation=False,
                             size=(340 if name == "match" else 500, plot_height))
            dock.setObjectName("parameterPlotDock")
            # The destination overlay is enough feedback; a drag border would
            # change container minimum sizes while capturing the new layout.
            dock.dragStyle = ""
            dock.setMinimumHeight(plot_height + self.LABEL_HEIGHT)
            dock.setMinimumWidth(120)
            dock.dockdrop.removeAllowedArea("center")  # Never hide plots in tabs.
            plot.setMinimumWidth(0)
            plot.setMaximumWidth(16777215)
            plot.setFixedHeight(plot_height)
            plot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            dock.addWidget(plot)
            dock.layout.setAlignment(plot, Qt.AlignmentFlag.AlignTop)
            self.addDock(dock, "right")
        self._building = False
        self._sync_height()

    def makeContainer(self, typ):
        container = super().makeContainer(typ)
        if isinstance(container, QSplitter):
            container.setObjectName("parameterPlotSplitter")
            container.setHandleWidth(6)
            container.setChildrenCollapsible(False)
            container.splitterMoved.connect(self._splitter_changed)
        return container

    def _splitter_changed(self, *_args):
        if not self._building:
            self._default_sizes_pending = False
            self.layoutChanged.emit()

    def moveDock(self, dock, position, neighbor):
        if (dock.area is not self or neighbor is dock or position not in ("left", "right", "top", "bottom")
                or (neighbor is not None and neighbor is not self and neighbor.area is not self)):
            return
        super().moveDock(dock, position, neighbor)
        self._default_sizes_pending = False
        self._sync_height()
        if not self._building:
            self.layoutChanged.emit()

    def floatDock(self, dock):
        # Double-clicking a drag label must not detach a workbook-owned plot.
        return

    def _sync_height(self):
        def height(node):
            if isinstance(node, Dock):
                return self.plot_height + self.LABEL_HEIGHT
            children = [height(node.widget(i)) for i in range(node.count())]
            if node.type() == "vertical":
                return sum(children) + node.handleWidth() * (len(children) - 1)
            return max(children, default=0)
        if self.topContainer is not None:
            self.setFixedHeight(height(self.topContainer))

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_default_sizes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_default_sizes_pending", False):
            self._apply_default_sizes()
            QTimer.singleShot(0, self._apply_default_sizes)

    def _apply_default_sizes(self):
        if self._default_sizes_pending and isinstance(self.topContainer, QSplitter):
            count = self.topContainer.count()
            total = self.width() - self.topContainer.handleWidth() * (count - 1)
            match_width = min(340, max(1, total - 180 * (count - 1)))
            other = max(1, (total - match_width) // max(1, count - 1))
            self.topContainer.setSizes([match_width] + [other] * (count - 1))
            for index in range(count):
                self.topContainer.setStretchFactor(index, 0 if index == 0 else 1)

    def restoreState(self, state):
        state = normalize_plot_layouts({"preview": {"parameter": {self._variant: state}}})["preview"]["parameter"][self._variant]
        self._building = True
        try:
            super().restoreState(state)
            self._default_sizes_pending = False
            self._sync_height()
        finally:
            self._building = False

    def dragEnterEvent(self, event):
        if _local_drop(self, event):
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if _local_drop(self, event):
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if _local_drop(self, event):
            super().dropEvent(event)

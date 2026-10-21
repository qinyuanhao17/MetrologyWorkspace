"""Direct parameter navigation; never changes the source/drawn cell selection."""
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QWidget


class _ParameterFlowLayout(QLayout):
    """Let Qt negotiate the button rows' height from the available width."""
    def __init__(self, parent):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def __del__(self):
        for item in self._items:
            if not sip.isdeleted(item):
                sip.delete(item)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), measure=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, *, measure=False):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            size = item.sizeHint()
            if row_height and x + size.width() > rect.x() + rect.width():
                x, y, row_height = rect.x(), y + row_height + self.spacing(), 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()


class ParameterFilterBar(QWidget):
    changed = pyqtSignal(object)

    def __init__(self, parent=None, *, pair_selection=False):
        super().__init__(parent)
        self._parameters = frozenset()
        self._pair_selection = pair_selection
        self._pair_mode = False
        self._source_mode = False
        self.names = ()
        self.source_groups = ()
        self._choices = ()
        self.buttons = {}
        self.flow = QGridLayout(self)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_parameters(())

    @property
    def parameter(self):
        """JSON-safe state; old single/union choices keep their original shape."""
        if self._source_mode:
            return {"mode": "source-pair" if self._pair_mode else "source",
                    "parameters": [list(key) for key in self._choices if key in self._parameters]}
        selected = [name for name in self.names if name in self._parameters]
        if self._pair_mode:
            return {"mode": "pair", "parameters": selected}
        return selected[0] if len(selected) == 1 else selected or None

    def matches(self, names):
        """Pair mode keeps pairs inside the chosen set; Ctrl alone is a union."""
        if not self._source_mode:
            names = tuple(key[1] if isinstance(key, tuple) else key for key in names)
        if self._pair_mode and len(self._parameters) >= 2:
            return self._parameters.issuperset(names)
        return not self._parameters or not self._parameters.isdisjoint(names)

    def set_selection(self, parameters):
        """Restore or choose a selection without depending on held Ctrl keys."""
        source_mode = isinstance(parameters, dict) and parameters.get("mode") in ("source", "source-pair")
        pair = (self._pair_selection and isinstance(parameters, dict)
                and parameters.get("mode") in ("pair", "source-pair"))
        if isinstance(parameters, dict):
            parameters = parameters.get("parameters", ()) if pair or source_mode else ()
        if not isinstance(parameters, (list, tuple, set, frozenset)):
            parameters = (parameters,)
        if source_mode:
            choices = [tuple(key) for key in parameters if isinstance(key, (list, tuple)) and len(key) == 2
                       and all(isinstance(value, str) for value in key)]
            selected = frozenset(key for key in self._choices if key in choices)
        else:
            selected = frozenset(name for name in self.names if name in parameters)
        source_mode = bool(source_mode and selected)
        pair = bool(pair and selected)
        changed = selected != self._parameters or pair != self._pair_mode or source_mode != self._source_mode
        self._parameters = selected
        self._pair_mode = pair
        self._source_mode = source_mode
        for name, button in self.buttons.items():
            active = (name is None and not selected) or name in selected or (
                not source_mode and isinstance(name, tuple) and name[1] in selected)
            button.setChecked(active)
            button.setObjectName("primary" if active else "subtle")
            button.style().unpolish(button)
            button.style().polish(button)
        if changed:
            self.changed.emit(self.parameter)

    def set_parameters(self, names, *, sources=()):
        names = tuple(dict.fromkeys(names))
        sources = tuple((source, tuple(dict.fromkeys(name for name in parameters if name in names)))
                        for source, parameters in sources)
        sources = tuple((source, parameters) for source, parameters in sources if parameters)
        if names == self.names and sources == self.source_groups:
            self.setVisible(bool(names))
            return
        self.names = names
        self.source_groups = sources
        self._choices = tuple((source, name) for source, parameters in sources for name in parameters) if sources else names
        self._parameters = self._parameters.intersection(self._choices if self._source_mode else names)
        self._source_mode = self._source_mode and bool(self._parameters)
        self._pair_mode = self._pair_mode and bool(self._parameters)
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget()
            widget.hide()
            widget.deleteLater()
            sip.delete(item)
        for button in self.buttons.values():
            self.group.removeButton(button)
        self.buttons = {}
        self.flow.setVerticalSpacing(10 if sources else 6)
        self.flow.setHorizontalSpacing(10 if sources else 6)
        self.flow.setColumnStretch(1, 1 if sources else 0)
        self.flow.setColumnStretch(2, 0)
        if sources:
            for index, (source, parameters) in enumerate(sources):
                panel = QFrame(objectName="parameterSourceGroup")
                panel.setAccessibleName(f"{source} parameters")
                role = {"Reference": "reference", "Raw Data": "raw"}.get(source, "other")
                panel.setProperty("sourceRole", role)
                panel_layout = QHBoxLayout(panel)
                panel_layout.setContentsMargins(12, 10, 12, 10)
                panel_layout.setSpacing(12)
                label = QLabel({"Reference": "REF", "Raw Data": "RAW"}.get(source, source),
                               objectName="parameterSourceBadge")
                label.setProperty("sourceRole", role)
                label.setAccessibleName(source)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setMinimumWidth(56)
                label.setFixedHeight(30)
                panel_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
                row = QWidget()
                row_flow = _ParameterFlowLayout(row)
                for name in parameters:
                    row_flow.addWidget(self._make_button((source, name)))
                panel_layout.addWidget(row, 1)
                self.flow.addWidget(panel, index, 1, 1, 2)
            self.flow.addWidget(self._make_button(None), 0, 0, len(sources), 1, Qt.AlignmentFlag.AlignTop)
        elif names:
            row = QWidget()
            row_flow = _ParameterFlowLayout(row)
            self.flow.addWidget(row, 0, 0, 1, 3)
            for parameter in (None, *names):
                row_flow.addWidget(self._make_button(parameter))
        self.flow.invalidate()
        self.updateGeometry()
        self.setVisible(bool(names))

    def _make_button(self, parameter):
        name = parameter[1] if isinstance(parameter, tuple) else parameter
        caption = f"{parameter[0]} · {name}" if isinstance(parameter, tuple) else str(name)
        button = QPushButton("ALL" if parameter is None else str(name))
        active = (parameter is None and not self._parameters) or parameter in self._parameters or (
            not self._source_mode and name in self._parameters)
        button.setObjectName("primary" if active else "subtle")
        button.setCheckable(True)
        button.setChecked(active)
        button.setToolTip("Show all drawn plots" if parameter is None else
                          f"Show plots containing {caption} · Ctrl+click to add or remove"
                          + (" · Ctrl+Alt+click to show pairwise correlations among selected parameters"
                             if self._pair_selection else ""))
        button.clicked.connect(lambda _checked, name=parameter: self._choose(name))
        self.group.addButton(button)
        self.buttons[parameter] = button
        if isinstance(parameter, tuple):
            button.setAccessibleName(f"{parameter[0]} · {name}")
        return button

    def _choose(self, parameter):
        if parameter not in self.buttons:
            return
        modifiers = QApplication.keyboardModifiers()
        if isinstance(parameter, tuple):
            selected = self._parameters if self._source_mode else frozenset(
                key for key in self._choices if key[1] in self._parameters)
            pair = (self._pair_selection and modifiers & Qt.KeyboardModifier.ControlModifier
                    and modifiers & Qt.KeyboardModifier.AltModifier)
            if pair and len(selected) >= 2 and not self._pair_mode:
                selected = frozenset()
            selected = (selected.symmetric_difference((parameter,)) if modifiers & Qt.KeyboardModifier.ControlModifier
                        else frozenset((parameter,)))
            self.set_selection({"mode": "source-pair" if pair else "source", "parameters": list(selected)})
            return
        if (parameter is not None and self._pair_selection
                and modifiers & Qt.KeyboardModifier.ControlModifier
                and modifiers & Qt.KeyboardModifier.AltModifier):
            selected = self._parameters
            if len(selected) >= 2 and not self._pair_mode:
                selected = frozenset()  # Start pairwise selection from an existing Ctrl union.
            selected = selected.symmetric_difference((parameter,))
            self.set_selection({"mode": "pair", "parameters": list(selected)})
        elif parameter is not None and modifiers & Qt.KeyboardModifier.ControlModifier:
            self.set_selection(self._parameters.symmetric_difference((parameter,)))
        else:
            self.set_selection(parameter)

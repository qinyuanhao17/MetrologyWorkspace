"""Direct parameter navigation; never changes the source/drawn cell selection."""
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QButtonGroup, QLayout, QPushButton, QSizePolicy, QWidget


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
        self.names = ()
        self.buttons = {}
        self.flow = _ParameterFlowLayout(self)
        self.group = QButtonGroup(self)
        self.group.setExclusive(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_parameters(())

    @property
    def parameter(self):
        """JSON-safe state; old single/union choices keep their original shape."""
        selected = [name for name in self.names if name in self._parameters]
        if self._pair_mode:
            return {"mode": "pair", "parameters": selected}
        return selected[0] if len(selected) == 1 else selected or None

    def matches(self, names):
        """Pair mode requires both names; ordinary multi-selection is a union."""
        if self._pair_mode and len(self._parameters) == 2:
            return self._parameters.issubset(names)
        return not self._parameters or not self._parameters.isdisjoint(names)

    def set_selection(self, parameters):
        """Restore or choose a selection without depending on held Ctrl keys."""
        pair = (self._pair_selection and isinstance(parameters, dict)
                and parameters.get("mode") == "pair")
        if isinstance(parameters, dict):
            parameters = parameters.get("parameters", ()) if pair else ()
        if not isinstance(parameters, (list, tuple, set, frozenset)):
            parameters = (parameters,)
        selected = frozenset(name for name in self.names if name in parameters)
        pair = bool(pair and 0 < len(selected) <= 2)
        changed = selected != self._parameters or pair != self._pair_mode
        self._parameters = selected
        self._pair_mode = pair
        for name, button in self.buttons.items():
            active = (name is None and not selected) or name in selected
            button.setChecked(active)
            button.setObjectName("primary" if active else "subtle")
            button.style().unpolish(button)
            button.style().polish(button)
        if changed:
            self.changed.emit(self.parameter)

    def set_parameters(self, names):
        names = tuple(dict.fromkeys(names))
        if names == self.names:
            self.setVisible(bool(names))
            return
        self.names = names
        self._parameters = self._parameters.intersection(names)
        self._pair_mode = self._pair_mode and bool(self._parameters)
        while self.flow.count():
            item = self.flow.takeAt(0)
            button = item.widget()
            button.hide()
            self.group.removeButton(button)
            button.deleteLater()
            sip.delete(item)
        self.buttons = {}
        for parameter in ((None, *names) if names else ()):
            button = QPushButton("ALL" if parameter is None else str(parameter))
            active = (parameter is None and not self._parameters) or parameter in self._parameters
            button.setObjectName("primary" if active else "subtle")
            button.setCheckable(True)
            button.setChecked(active)
            button.setToolTip("Show all drawn plots" if parameter is None else
                              f"Show plots containing {parameter} · Ctrl+click to add or remove"
                              + (" · Ctrl+Alt+click two parameters to show only their correlation"
                                 if self._pair_selection else ""))
            button.clicked.connect(lambda _checked, name=parameter: self._choose(name))
            self.group.addButton(button)
            self.flow.addWidget(button)
            self.buttons[parameter] = button
        self.flow.invalidate()
        self.updateGeometry()
        self.setVisible(bool(names))

    def _choose(self, parameter):
        if parameter not in self.buttons:
            return
        modifiers = QApplication.keyboardModifiers()
        if (parameter is not None and self._pair_selection
                and modifiers & Qt.KeyboardModifier.ControlModifier
                and modifiers & Qt.KeyboardModifier.AltModifier):
            selected = self._parameters
            if len(selected) >= 2 and (not self._pair_mode or parameter not in selected):
                selected = frozenset()  # Start another pair, never grow a pair to three names.
            selected = selected.symmetric_difference((parameter,))
            self.set_selection({"mode": "pair", "parameters": list(selected)})
        elif parameter is not None and modifiers & Qt.KeyboardModifier.ControlModifier:
            self.set_selection(self._parameters.symmetric_difference((parameter,)))
        else:
            self.set_selection(parameter)

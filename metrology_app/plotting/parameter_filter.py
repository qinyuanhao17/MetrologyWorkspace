"""Direct parameter navigation; never changes the source/drawn cell selection."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QScrollArea, QWidget


class ParameterFilterBar(QScrollArea):
    changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parameter = None
        self.names = ()
        self.buttons = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(46)
        self.set_parameters(())

    def set_parameters(self, names):
        names = tuple(dict.fromkeys(names))
        if self.buttons and names == self.names:
            self.setVisible(bool(names))
            return
        self.names = names
        if self.parameter not in names:
            self.parameter = None
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(body)
        self.buttons = {}
        for parameter in (None, *names):
            button = QPushButton("ALL" if parameter is None else str(parameter))
            button.setObjectName("primary" if parameter == self.parameter else "subtle")
            button.setCheckable(True)
            button.setChecked(parameter == self.parameter)
            button.setToolTip("Show all drawn plots" if parameter is None else f"Show plots containing {parameter}")
            button.clicked.connect(lambda _checked, name=parameter: self._choose(name))
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[parameter] = button
        layout.addStretch()
        self.setWidget(body)
        self.setVisible(bool(names))

    def _choose(self, parameter):
        if parameter != self.parameter:
            self.parameter = parameter
            for name, button in self.buttons.items():
                button.setObjectName("primary" if name == parameter else "subtle")
                button.style().unpolish(button)
                button.style().polish(button)
            self.changed.emit(parameter)

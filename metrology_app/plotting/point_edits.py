"""Undo history for exclusions made directly on a plot."""
from weakref import ref

from PyQt6.QtGui import QUndoCommand


class PointRemoval(QUndoCommand):
    def __init__(self, apply, before, after, widget=None, row=None):
        super().__init__("point removal")
        self._apply = apply
        self._before = before
        self._after = after
        self._widget = ref(widget) if widget is not None and not isinstance(widget, tuple) else lambda: widget
        self._row = row

    def undo(self):
        self._apply(self._before, self._widget(), self._row, False)

    def redo(self):
        self._apply(self._after, self._widget(), self._row, True)


def add_point_edit_actions(menu, history):
    menu.addSeparator()
    undo = menu.addAction("Undo point removal", history.undo)
    redo = menu.addAction("Redo point removal", history.redo)
    reset = menu.addAction("Restore all removed points", lambda: history.setIndex(0))
    undo.setEnabled(history.canUndo())
    redo.setEnabled(history.canRedo())
    reset.setEnabled(history.canUndo())
    history.canUndoChanged.connect(undo.setEnabled)
    history.canRedoChanged.connect(redo.setEnabled)
    history.canUndoChanged.connect(reset.setEnabled)

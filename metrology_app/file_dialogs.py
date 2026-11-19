"""Shared file and folder pickers for import workflows."""
from pathlib import Path
import sys

from PyQt6.QtCore import QDir
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMessageBox, QTreeView, QVBoxLayout,
)

from .appearance import fit_window_to_screen


def choose_files(parent, title, name_filter, *, directory=None):
    paths, _ = QFileDialog.getOpenFileNames(parent, title, str(directory or ""), name_filter)
    return tuple(map(Path, paths))


def choose_folders(parent, title, *, directory=None):
    if sys.platform == "win32":
        from .windows_folder_dialog import choose_windows_folders
        try:
            return choose_windows_folders(int(parent.window().winId()), title, directory)
        except OSError as error:
            QMessageBox.warning(parent, title, str(error))
            return ()
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Select folders with Ctrl or Shift. Subfolders are included."))
    tree = QTreeView(dialog)
    model = QFileSystemModel(tree)
    model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
    model.setRootPath("")
    tree.setModel(model)
    tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    for column in range(1, model.columnCount()):
        tree.hideColumn(column)
    initial = model.index(str(directory or Path.home()))
    ancestor = initial.parent()
    while ancestor.isValid():
        tree.expand(ancestor)
        ancestor = ancestor.parent()
    if initial.isValid():
        tree.scrollTo(initial)
    layout.addWidget(tree)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    load = buttons.addButton("Load folders", QDialogButtonBox.ButtonRole.AcceptRole)
    selection = tree.selectionModel()
    load.setEnabled(False)
    selection.selectionChanged.connect(lambda: load.setEnabled(bool(selection.selectedRows())))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    fit_window_to_screen(dialog, (690, 500), minimum=(460, 340))
    paths = ()
    if dialog.exec() == QDialog.DialogCode.Accepted:
        paths = tuple(Path(model.filePath(index)) for index in selection.selectedRows())
    dialog.deleteLater()
    return paths

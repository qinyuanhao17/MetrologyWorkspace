"""AutoWeighting Writer: local screenshot input, candidate review and two tables."""
import base64
import hashlib
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import (QAbstractTableModel, QBuffer, QIODevice, QModelIndex,
                         QThread, Qt, pyqtSignal)
from PyQt6.QtGui import QAction, QColor, QImage, QKeySequence, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .auto_weighting import Cell, WriterDocument, export_excel
from .workspace_document import WkbDocument, commit_editors, recovery_decision
from .workspace_store import WorkspaceSnapshot, file_revision, load_workspace
from .table_selection import RangeSelectionTableView


class WriterTableModel(QAbstractTableModel):
    changed = pyqtSignal()

    @property
    def uniform_selection_flags(self):
        return (type(self).flags is WriterTableModel.flags
                and type(self).headerData is WriterTableModel.headerData)

    def __init__(self, window, kind):
        super().__init__(window)
        self.window, self.kind = window, kind

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.window.writer.tables[self.kind])

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.window.writer.columns[self.kind])

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.window.writer.columns[self.kind][section] if orientation == Qt.Orientation.Horizontal else str(section+1)

    def flags(self, index):
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable) if index.isValid() else Qt.ItemFlag.NoItemFlags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell = self.window.writer.tables[self.kind][index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return cell.text
        issues = self.window.writer.issues(self.kind, index.row(), index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            return '\n'.join(issues + [f'Collection: {cell.status}', f'Original OCR: {cell.raw}',
                f'Source: {cell.source}', 'Click to inspect the source crop and conflicting candidates.'])
        if role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole):
            strong = any(not message.startswith('Unreviewed') for message in issues) and cell.collected
            if issues:
                if role == Qt.ItemDataRole.BackgroundRole:
                    return QColor('#f4d6d6' if strong else '#fff0c2' if cell.collected else '#e1e1e1')
                return QColor('#4d1717' if strong else '#493600' if cell.collected else '#444444')
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or self.window.worker is not None:
            return False
        self.window._remember()
        self.window.writer.edit(self.kind, index.row(), index.column(), str(value))
        self.window._repaint()
        self.changed.emit()
        return True


class RecognitionWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, inputs, kind, parent, recognize=None):
        super().__init__(parent)
        self.inputs, self.kind, self.recognize = inputs, kind, recognize

    def run(self):
        try:
            from .auto_weighting_ocr import LocalRecognizer, recognize_screenshot
            recognize = self.recognize or recognize_screenshot
            engine = None if self.recognize else LocalRecognizer()
            results = []
            for index, (source, png) in enumerate(self.inputs):
                if self.isInterruptionRequested():
                    return
                self.progress.emit(f'Image {index+1}/{len(self.inputs)}: local CPU recognition…')
                results.append(recognize(png, source, self.kind, recognizer=engine,
                    cancelled=self.isInterruptionRequested, progress=self.progress.emit))
            if not self.isInterruptionRequested():
                self.result_ready.emit(results)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class CandidateDialog(QDialog):
    """Review before importing, including duplicate/misread Names; no data loss."""
    def __init__(self, results, window):
        super().__init__(window)
        self.results, self.window = results, window
        self.setWindowTitle('Review local OCR candidates — nothing has been merged yet')
        self.resize(1180, 740)
        layout = QVBoxLayout(self)
        label = QLabel('OCR can miss minus signs, underscores and formula characters even with high confidence. '
                       'Correct candidates here, then Import. Blank Fix values stay blank. Conflicts keep both versions.')
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(label)
        split = QSplitter()
        tabs = QTabWidget()
        self.crop = QLabel('Select a cell to view its source crop.')
        self.crop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop.setMinimumWidth(220)
        self.crop.setWordWrap(True)
        split.addWidget(tabs)
        split.addWidget(self.crop)
        split.setSizes([850, 300])
        layout.addWidget(split, 1)
        for index, result in enumerate(results):
            table = QTableWidget(len(result.rows), len(result.columns))
            table.setHorizontalHeaderLabels(result.columns)
            for row, cells in enumerate(result.rows):
                for col, cell in enumerate(cells):
                    item = QTableWidgetItem(cell.text)
                    item.setToolTip(f'OCR: {cell.raw}\nConfidence: {cell.confidence:.1%}')
                    table.setItem(row, col, item)
            for col in range(len(result.columns)):
                table.setColumnWidth(col, 190 if col == 0 else 110 if result.kind == 'parameters' or col % 2 else 190)
            table.currentCellChanged.connect(lambda row, col, _r, _c, data=result: self.show_crop(data, row, col))
            table.itemChanged.connect(lambda item, data=result: self.change(data, item))
            tabs.addTab(table, f'Image {index+1} · {result.kind} ({len(result.rows)} rows)')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Import / merge candidates')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_crop(self, result, row, col):
        if row >= 0 and col >= 0:
            self.window.show_cell_image(result.rows[row][col], self.crop)

    def change(self, result, item):
        cell = result.rows[item.row()][item.column()]
        cell.text, cell.reviewed = item.text(), True

    def accept(self):
        try:
            candidate = WriterDocument.from_dict(self.window.writer.to_dict())
            for result in self.results:
                candidate.merge(result)
        except ValueError as error:
            QMessageBox.warning(self, 'Correct candidates before import', str(error))
            return
        super().accept()


class AutoWeightingWindow(QMainWindow):
    workspace_type = 'auto_weighting'

    def __init__(self, *, recognize=None):
        super().__init__()
        self.writer = WriterDocument()
        self.worker = None
        self.recognize_function = recognize
        self._undo, self._redo = [], []
        self._pending_results, self._worker_error = None, ''
        self._close_requested = False
        self.resize(1450, 850)
        self.setAcceptDrops(True)
        self._build_ui()
        self.document = WkbDocument(self)
        self.document.mark_clean()

    def action(self, bar, title, callback, shortcut=None):
        action = QAction(title, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        bar.addAction(action)
        return action

    def _build_ui(self):
        filebar = QToolBar('Workspace and screenshots', self)
        self.addToolBar(filebar)
        self.action(filebar, 'Open project…', self.open_project, 'Ctrl+O')
        self.action(filebar, 'Save', self.save_wkb, 'Ctrl+S')
        self.action(filebar, 'Save As…', self.save_as, 'Ctrl+Shift+S')
        self.action(filebar, 'Recover draft…', self.recover_draft)
        filebar.addSeparator()
        self.action(filebar, 'Open images…', self.open_images)
        self.action(filebar, 'Paste screenshot', self.paste_screenshot, 'Ctrl+Shift+V')
        self.action(filebar, 'Copy screenshot', self.copy_screenshot)
        filebar.addSeparator()
        self.action(filebar, 'Export Excel…', self.export_dialog)
        self.addToolBarBreak()
        tools = QToolBar('Review and editing', self)
        self.addToolBar(tools)
        self.kind = QComboBox()
        for label, value in [('Auto table type', 'auto'), ('Base Parameters', 'parameters'), ('Multiple Step', 'steps')]:
            self.kind.addItem(label, value)
        tools.addWidget(self.kind)
        self.recognize_action = self.action(tools, 'Recognize selected images', self.start_recognition)
        self.cancel_action = self.action(tools, 'Cancel OCR', self.cancel_recognition)
        self.cancel_action.setEnabled(False)
        tools.addSeparator()
        self.undo_action = self.action(tools, 'Undo', self.undo, 'Ctrl+Z')
        self.redo_action = self.action(tools, 'Redo', self.redo, 'Ctrl+Y')
        self.action(tools, 'Copy table', self.copy_table)
        self.action(tools, 'Mark selected reviewed', self.mark_reviewed)
        self.action(tools, 'Add row', self.add_row)
        self.action(tools, 'Remove selected rows', self.remove_rows)
        root = QWidget()
        layout = QVBoxLayout(root)
        guidance = QLabel('Offline OCR · Paste a screenshot (Ctrl+Shift+V, or Ctrl+V outside an editor), select images, '
            'then Recognize. Review the source before using the result. V1 reads Name/Nominal/Min/Max and Step Mode/Value; '
            'checkboxes and hidden weighting-button settings are not inferred.')
        guidance.setWordWrap(True)
        guidance.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(guidance)
        split = QSplitter()
        self.sources = QListWidget()
        self.sources.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sources.setMinimumWidth(150)
        self.sources.currentItemChanged.connect(self.show_source)
        split.addWidget(self.sources)
        self.tabs = QTabWidget()
        self.table_models, self.views = {}, {}
        for kind, label in [('parameters', 'Base Parameters'), ('steps', 'Multiple Step')]:
            model, view = WriterTableModel(self, kind), RangeSelectionTableView()
            view.setModel(model)
            view.setAlternatingRowColors(False)
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            view.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
            view.selectionModel().currentChanged.connect(lambda _index, _old: self.inspect_cell())
            view.installEventFilter(self)
            self.table_models[kind], self.views[kind] = model, view
            self.tabs.addTab(view, label)
        self.tabs.currentChanged.connect(self.inspect_cell)
        split.addWidget(self.tabs)
        inspector = QWidget()
        inspect_layout = QVBoxLayout(inspector)
        self.evidence_choice = QComboBox()
        self.evidence_choice.currentIndexChanged.connect(self.show_evidence)
        inspect_layout.addWidget(self.evidence_choice)
        self.use_button = QPushButton('Use selected candidate')
        self.use_button.clicked.connect(self.use_candidate)
        inspect_layout.addWidget(self.use_button)
        self.image_label = QLabel('Paste or open a table screenshot.')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(220, 150)
        self.image_label.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(True)
        inspect_layout.addWidget(scroll, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(220)
        inspect_layout.addWidget(self.details)
        split.addWidget(inspector)
        split.setSizes([180, 900, 330])
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.setCentralWidget(root)
        self._refresh()

    def current_kind(self):
        return 'parameters' if self.tabs.currentIndex() == 0 else 'steps'

    def current_cell(self):
        kind = self.current_kind()
        index = self.views[kind].currentIndex()
        if (index.isValid() and index.row() < len(self.writer.tables[kind])
                and index.column() < len(self.writer.columns[kind])):
            return kind, index.row(), index.column(), self.writer.tables[kind][index.row()][index.column()]
        return None

    def _remember(self):
        self._undo.append(self.writer.to_dict())
        del self._undo[:-40]
        self._redo.clear()

    def _changed(self):
        if hasattr(self, 'document'):
            self.document.identity_timer.start()
        self.undo_action.setEnabled(bool(self._undo) and self.worker is None)
        self.redo_action.setEnabled(bool(self._redo) and self.worker is None)

    def _repaint(self):
        for model in self.table_models.values():
            if model.rowCount():
                model.dataChanged.emit(model.index(0, 0), model.index(model.rowCount()-1, model.columnCount()-1))
        self.inspect_cell()
        self._changed()

    def _refresh(self):
        selected = self.sources.currentItem().data(Qt.ItemDataRole.UserRole) if self.sources.currentItem() else None
        self.sources.blockSignals(True)
        self.sources.clear()
        for source, value in self.writer.sources.items():
            item = QListWidgetItem(value['name'])
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setToolTip('Local screenshot · select multiple images to recognize and merge a scrolling table.')
            self.sources.addItem(item)
            if source == selected:
                self.sources.setCurrentItem(item)
        self.sources.blockSignals(False)
        for kind, model in self.table_models.items():
            model.beginResetModel()
            model.endResetModel()
            for col in range(model.columnCount()):
                self.views[kind].setColumnWidth(col, 180 if col == 0 or kind == 'steps' and col % 2 == 0 else 100)
        self._changed()
        self.inspect_cell()

    def undo(self):
        if self.worker is None and self._undo:
            commit_editors(self)
            self._redo.append(self.writer.to_dict())
            self.writer = WriterDocument.from_dict(self._undo.pop())
            self._refresh()

    def redo(self):
        if self.worker is None and self._redo:
            self._undo.append(self.writer.to_dict())
            self.writer = WriterDocument.from_dict(self._redo.pop())
            self._refresh()

    def add_image_bytes(self, png, name):
        if self.worker is not None:
            raise ValueError('Finish or cancel recognition before adding more images.')
        image = QImage.fromData(png)
        if image.isNull() or image.width()*image.height() > 16000000:
            raise ValueError('Cannot read image, or it exceeds 16 megapixels. Crop the table first.')
        source = hashlib.sha256(png).hexdigest()
        if source not in self.writer.sources:
            self._remember()
            self.writer.sources[source] = {'name': str(name), 'png': base64.b64encode(png).decode('ascii')}
            self._refresh()
        for index in range(self.sources.count()):
            item = self.sources.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == source:
                self.sources.setCurrentItem(item)
                item.setSelected(True)
        return source

    def open_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Open table screenshots', '', 'Images (*.png *.jpg *.jpeg *.bmp)')
        added = []
        for path in paths:
            try:
                added.append(self.add_image_bytes(Path(path).read_bytes(), Path(path).name))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Cannot add screenshot', f'{path}\n{error}')
        for index in range(self.sources.count()):
            item = self.sources.item(index)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in added)

    def paste_screenshot(self):
        image = QApplication.clipboard().image()
        if image.isNull():
            QMessageBox.information(self, 'No screenshot', 'Copy an image first, then Paste screenshot. Text is not an image.')
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        try:
            self.add_image_bytes(bytes(buffer.data()), f'Clipboard {len(self.writer.sources)+1}')
        except ValueError as error:
            QMessageBox.warning(self, 'Cannot paste screenshot', str(error))

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Paste) and QApplication.clipboard().mimeData().hasImage():
            self.paste_screenshot()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste) and QApplication.clipboard().mimeData().hasImage():
            self.paste_screenshot()
        else:
            super().keyPressEvent(event)

    def copy_screenshot(self):
        item = self.sources.currentItem()
        if item:
            value = self.writer.sources[item.data(Qt.ItemDataRole.UserRole)]
            QApplication.clipboard().setImage(QImage.fromData(base64.b64decode(value['png'])))

    def copy_table(self):
        commit_editors(self)
        QApplication.clipboard().setText(self.writer.tsv(self.current_kind()))

    def show_source(self, item, _previous=None):
        if item is None:
            return
        source = item.data(Qt.ItemDataRole.UserRole)
        value = self.writer.sources[source]
        image = QImage.fromData(base64.b64decode(value['png']))
        width = max(220, self.image_label.width()-10)
        self.image_label.setPixmap(QPixmap.fromImage(image).scaled(width, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.details.setPlainText(value['name'] + '\nLocal image only; select table cells to inspect source crops.')

    def show_cell_image(self, cell, label):
        source = self.writer.sources.get(cell.source)
        if not source or len(cell.bbox) != 4:
            label.clear()
            label.setText('No source crop: this field was entered manually or not collected.')
            return
        image = QImage.fromData(base64.b64decode(source['png']))
        left, top, right, bottom = cell.bbox
        image = image.copy(left, top, right-left, bottom-top)
        width = max(210, label.width()-10)
        label.setPixmap(QPixmap.fromImage(image).scaled(width, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))

    def inspect_cell(self, *_args):
        if not hasattr(self, 'evidence_choice'):
            return
        current = self.current_cell()
        self.evidence_choice.blockSignals(True)
        self.evidence_choice.clear()
        if current:
            cell = current[3]
            self.evidence_choice.addItem(f'Current: {cell.text or "(blank)"}', cell.to_dict())
            for candidate in cell.alternatives:
                self.evidence_choice.addItem(f'Other OCR: {candidate["text"] or "(blank)"}', candidate)
        self.evidence_choice.blockSignals(False)
        self.show_evidence()

    def show_evidence(self, *_args):
        current = self.current_cell()
        value = self.evidence_choice.currentData()
        self.use_button.setEnabled(bool(current and current[3].alternatives) and self.worker is None)
        if current and value:
            cell = Cell.from_dict(value)
            self.show_cell_image(cell, self.image_label)
            kind, row, col, _cell = current
            self.details.setPlainText('\n'.join(self.writer.issues(kind, row, col) + [
                f'Original OCR: {cell.raw}', f'Collection: {cell.status}', f'Confidence: {cell.confidence:.1%}',
                'Source: '+self.writer.sources.get(cell.source, {}).get('name', cell.source)]))

    def use_candidate(self):
        current, value = self.current_cell(), self.evidence_choice.currentData()
        if current and value and self.worker is None and current[3].alternatives:
            self._remember()
            self.writer.resolve(*current[:3], self.evidence_choice.currentIndex())
            self._repaint()

    def mark_reviewed(self):
        if self.worker is not None:
            return
        kind = self.current_kind()
        indexes = self.views[kind].selectionModel().selectedIndexes()
        if not indexes:
            return
        if any(self.writer.tables[kind][index.row()][index.column()].alternatives for index in indexes):
            QMessageBox.information(self, 'Resolve conflicts', 'Choose the intended candidate or edit each conflicting cell before marking it reviewed.')
            return
        self._remember()
        for index in indexes:
            cell = self.writer.tables[kind][index.row()][index.column()]
            if cell.collected:
                cell.reviewed = True
        self._repaint()

    def add_row(self):
        if self.worker is None:
            self._remember()
            kind = self.current_kind()
            self.writer.tables[kind].append([Cell(collected=False) for _ in self.writer.columns[kind]])
            self._refresh()

    def remove_rows(self):
        if self.worker is not None:
            return
        kind = self.current_kind()
        rows = {index.row() for index in self.views[kind].selectionModel().selectedIndexes()}
        if rows and QMessageBox.question(self, 'Remove rows', f'Remove {len(rows)} selected rows? Undo remains available.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._remember()
            self.writer.tables[kind] = [row for index, row in enumerate(self.writer.tables[kind]) if index not in rows]
            self._refresh()

    def apply_results(self, results):
        candidate = WriterDocument.from_dict(self.writer.to_dict())
        for result in results:
            candidate.merge(result)
        self._remember()
        self.writer = candidate
        self._refresh()
        if results:
            self.tabs.setCurrentIndex(0 if results[-1].kind == 'parameters' else 1)
        warnings = list(dict.fromkeys(message for result in results for message in result.warnings))
        self.statusBar().showMessage('Imported local OCR candidates. Amber: unreviewed; red: conflict/validation; gray: not collected. '
                                     + ' '.join(warnings))

    def start_recognition(self):
        if self.worker is not None:
            return
        inputs = [(item.data(Qt.ItemDataRole.UserRole), base64.b64decode(self.writer.sources[item.data(Qt.ItemDataRole.UserRole)]['png']))
                  for item in self.sources.selectedItems()]
        if not inputs:
            QMessageBox.information(self, 'Select screenshots', 'Paste/open images, then select one or more images in the left list.')
            return
        commit_editors(self)
        self._pending_results, self._worker_error = None, ''
        self.worker = RecognitionWorker(inputs, self.kind.currentData(), self, self.recognize_function)
        self.worker.result_ready.connect(self._receive_results)
        self.worker.failed.connect(self._receive_error)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.finished.connect(self._recognition_finished)
        self._set_busy(True)
        self.worker.start()

    def _receive_results(self, results):
        self._pending_results = results

    def _receive_error(self, error):
        self._worker_error = error

    def cancel_recognition(self):
        if self.worker:
            self.worker.requestInterruption()
            self.statusBar().showMessage('Cancelling after the current local OCR batch; no recognized values will be applied.')

    def _set_busy(self, busy):
        self.recognize_action.setEnabled(not busy)
        self.cancel_action.setEnabled(busy)
        for view in self.views.values():
            view.setEnabled(not busy)
        self._changed()

    def _recognition_finished(self):
        worker, self.worker = self.worker, None
        cancelled = worker.isInterruptionRequested()
        worker.deleteLater()
        self._set_busy(False)
        if self._close_requested:
            self._close_requested = False
            self.close()
            return
        if cancelled:
            self.statusBar().showMessage('Recognition cancelled. Existing tables and source images were preserved.')
        elif self._worker_error:
            QMessageBox.warning(self, 'Local recognition failed', self._worker_error)
        elif self._pending_results:
            dialog = CandidateDialog(self._pending_results, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.apply_results(self._pending_results)
            dialog.deleteLater()
        self._pending_results = None

    def workspace_snapshot(self):
        frames = {kind: pd.DataFrame([[cell.text for cell in row] for row in rows], columns=self.writer.columns[kind])
                  for kind, rows in self.writer.tables.items()}
        return WorkspaceSnapshot(self.workspace_type, frames, {'writer': self.writer.to_dict()})

    def restore_workspace(self, snapshot):
        if snapshot.workspace_type != self.workspace_type:
            raise ValueError('This project belongs to a different tool.')
        if 'writer' not in snapshot.states:
            raise ValueError('This AutoWeighting project is missing its recognition state.')
        writer = WriterDocument.from_dict(snapshot.states['writer'])
        for kind, rows in writer.tables.items():
            frame = snapshot.frames[kind]
            if list(frame.columns) != writer.columns[kind] or frame.values.tolist() != [[cell.text for cell in row] for row in rows]:
                raise ValueError('AutoWeighting tables and recognition metadata disagree; project was not partially loaded.')
        for source in writer.sources.values():
            image = QImage.fromData(base64.b64decode(source['png'], validate=True))
            if image.isNull() or image.width()*image.height() > 16000000:
                raise ValueError('Invalid saved screenshot.')
        self.writer = writer
        self._undo.clear()
        self._redo.clear()
        self._refresh()

    @recovery_decision
    def load_workspace(self, path):
        if self.worker is not None:
            raise ValueError('Finish or cancel recognition before opening another project.')
        snapshot = load_workspace(path, expected_type=self.workspace_type)
        if not self.document.confirm_close():
            return None
        if snapshot.revision != file_revision(path):
            snapshot = load_workspace(path, expected_type=self.workspace_type)
        if 'recovery' in snapshot.states:
            self.document.recover(path, snapshot)
        else:
            self.restore_workspace(snapshot)
            self.document.path, self.document.revision = Path(path).resolve(), snapshot.revision
            self.document.untrusted_recovery = False
            self.document.mark_clean()
            self.document.remember_recent()
        return snapshot

    def save_wkb(self):
        try:
            result = self.document.save()
            if result:
                self.statusBar().showMessage(f'Saved project: {result}')
            return result
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Cannot save project', str(error))
            return None

    def save_as(self):
        try:
            return self.document.save(save_as=True)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Cannot save project', str(error))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open AutoWeighting project', '', 'AutoWeighting Writer (*.waw *.bak);;Backups (*.bak)')
        if path:
            try:
                self.load_workspace(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Cannot open project', str(error))

    def recover_draft(self):
        from .workspace_document import recovery_directory
        path, _ = QFileDialog.getOpenFileName(self, 'Recover AutoWeighting draft', str(recovery_directory()), 'AutoWeighting Writer (*.waw *.bak)')
        if path:
            try:
                self.load_workspace(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Cannot recover project', str(error))

    def export_dialog(self):
        commit_editors(self)
        path, _ = QFileDialog.getSaveFileName(self, 'Export AutoWeighting tables', 'AutoWeighting.xlsx', 'Excel workbook (*.xlsx)')
        if path:
            try:
                export_excel(self.writer, path)
                self.statusBar().showMessage('Exported literal tables, Combined view and Collection & Review metadata. Verify OCR before using the data.')
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Cannot export Excel', str(error))

    def dragEnterEvent(self, event):
        if event.mimeData().hasImage() or any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp') for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                try:
                    path = Path(url.toLocalFile())
                    self.add_image_bytes(path.read_bytes(), path.name)
                except (OSError, ValueError) as error:
                    QMessageBox.warning(self, 'Cannot add screenshot', str(error))
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.worker is not None:
            self._close_requested = True
            self.cancel_recognition()
            event.ignore()
        elif self.document.confirm_close():
            self.document.closed()
            event.accept()
        else:
            event.ignore()

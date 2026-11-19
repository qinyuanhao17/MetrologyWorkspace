"""Editable source sheets, explicit wafer links and coordinate-Bias trends."""
from dataclasses import dataclass, field, fields
from html import escape
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, QSize, QPoint, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QCheckBox, QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QScrollArea, QFrame, QApplication, QDialog, QDialogButtonBox, QMessageBox,
    QStackedWidget)

from .widgets import CheckableListWidget, ScrollSafeComboBox
from .sheet import SheetModel, SheetView, DuplicateHeaderBanner
from .appearance import fit_window_to_screen, help_title_label
from .file_dialogs import choose_files, choose_folders
from .plotting import InteractivePlotWidget, PlotPanel, place_legend_above_frame
from .reference_alignment import (AlignmentColumns, infer_alignment_columns, wafer_groups,
    wafer_row_order, coordinate_row_order, coordinate_bias, load_alignment_output,
    scan_alignment_outputs, aligned_reference_data)


class AlignmentSheet(QFrame):
    changed = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName('sheetCard')
        self.vendor = 'Raw'
        self._loading = False
        self.source_rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16,14,16,12)
        layout.setSpacing(8)
        layout.addWidget(help_title_label(title,'Row 1 = headers · Ctrl+V paste · Ctrl+Shift+V replace table · Ctrl+Z undo.'))
        self.model = SheetModel()
        self.view = SheetView(self.model)
        layout.addWidget(DuplicateHeaderBanner(self.model))
        layout.addWidget(self.view, 1)
        self.coordinate_pair = ScrollSafeComboBox()
        self.coordinate_pair.setToolTip('Choose the CDSEM MP whose Wafer_X / Wafer_Y coordinates will be compared.')
        self.coordinate_pair.currentIndexChanged.connect(self._coordinate_pair_changed)
        layout.addWidget(self.coordinate_pair)
        mapping = QGridLayout()
        self.pickers = {}
        for index, (key, title) in enumerate((('wafer','Wafer ID'),('lot','Lot ID'),('pad','PAD / Slot'),
                ('field_x','Field X'),('field_y','Field Y'),('x','Absolute X'),('y','Absolute Y'),('unit','XY unit'))):
            combo = ScrollSafeComboBox()
            combo.setMinimumWidth(60)
            combo.currentIndexChanged.connect(self._mapping_changed)
            self.pickers[key] = combo
            row, column = divmod(index, 4)
            mapping.addWidget(QLabel(title), row * 2, column)
            mapping.addWidget(combo, row * 2 + 1, column)
        layout.addLayout(mapping)
        self.summary = QLabel('No data',objectName='hint')
        layout.addWidget(self.summary)
        self.model.changed.connect(self._data_changed)
        self._populate_columns()

    def frame(self):
        return self.model.document_frame()

    def columns(self):
        return AlignmentColumns(**{name: combo.currentData() for name, combo in self.pickers.items()})

    def set_frame(self, frame, vendor='Raw'):
        self.vendor = vendor
        self._loading = True
        self.model.load(frame)
        self.source_rows = list(range(2, len(frame) + 2))
        self._populate_columns(reset=True)
        self._loading = False
        self.changed.emit()

    def reorder(self, order):
        frame = self.frame().iloc[order].reset_index(drop=True)
        self.source_rows = [self.source_rows[i] for i in order]
        self._loading = True
        self.model.load(frame)
        self._loading = False

    def _populate_columns(self, reset=False):
        loading = self._loading
        self._loading = True
        frame = self.frame()
        guessed = infer_alignment_columns(frame, self.vendor)
        for field in fields(AlignmentColumns):
            combo = self.pickers[field.name]
            previous = combo.currentData()
            combo.clear()
            if field.name == 'unit':
                for label, value in (('Select unit', ''), ('mm','mm'), ('µm','µm'), ('nm','nm')):
                    combo.addItem(label, value)
            else:
                combo.addItem('—', None)
                for column in frame:
                    combo.addItem(str(column), str(column))
            choice = getattr(guessed, field.name) if reset or previous is None or (field.name=='unit' and not previous) else previous
            at = combo.findData(choice)
            combo.setCurrentIndex(at if at >= 0 else combo.findData(getattr(guessed, field.name)))
        previous = self.coordinate_pair.currentData()
        self.coordinate_pair.clear()
        self.coordinate_pair.addItem('Select CDSEM coordinate MP…',None)
        for column in frame:
            if str(column).endswith(' / Wafer_X'):
                y = str(column)[:-len('Wafer_X')] + 'Wafer_Y'
                if y in frame:
                    prefix = str(column).rsplit(' / ',1)[0]
                    self.coordinate_pair.addItem(prefix,prefix)
        if not reset:
            self.coordinate_pair.setCurrentIndex(max(0,self.coordinate_pair.findData(previous)))
        self.coordinate_pair.setVisible(self.coordinate_pair.count()>1)
        self.summary.setText(f'{len(frame):,} rows × {len(frame.columns):,} columns' if len(frame.columns) else 'No data')
        self._loading = loading

    def _coordinate_pair_changed(self):
        if self._loading:
            return
        pair = self.coordinate_pair.currentData()
        if pair:
            self._loading = True
            for key,column in zip(('x','y'),(pair+' / Wafer_X',pair+' / Wafer_Y')):
                self.pickers[key].setCurrentIndex(self.pickers[key].findData(column))
            self._loading = False
            self.changed.emit()

    def _data_changed(self):
        if self._loading:
            return
        self._populate_columns()
        count, _ = self.model.document_shape()
        if not self.model.preserves_record_positions:
            self.source_rows = list(range(2, count + 2))
        elif count > len(self.source_rows):
            first = max(self.source_rows, default=1) + 1
            self.source_rows.extend(range(first, first + count - len(self.source_rows)))
        elif count < len(self.source_rows):
            del self.source_rows[count:]
        self.changed.emit()

    def _mapping_changed(self):
        if not self._loading:
            self.changed.emit()


class WaferOrderList(QListWidget):
    moved = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.model().rowsMoved.connect(self._moved)

    def _moved(self, parent, start, end, destination, row):
        index = row - (end - start + 1) if row > start else row
        item = self.item(index)
        self.moved.emit(item.data(Qt.ItemDataRole.UserRole) if item else None)

    def keys(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]


class LinkCanvas(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setFixedWidth(90)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#2789c9'), 2))
        for ref, raw in self.page.links.items():
            positions = []
            for widget, key in ((self.page.ref_wafers, ref), (self.page.raw_wafers, raw)):
                item = next((widget.item(i) for i in range(widget.count()) if widget.item(i).data(Qt.ItemDataRole.UserRole) == key), None)
                if item is None:
                    break
                y = widget.visualItemRect(item).center().y()
                positions.append(self.mapFromGlobal(widget.viewport().mapToGlobal(QPoint(0,y))).y())
            if len(positions) == 2:
                path = QPainterPath()
                path.moveTo(0, positions[0])
                path.cubicTo(40, positions[0], 50, positions[1], 90, positions[1])
                painter.drawPath(path)


@dataclass
class AlignmentDataset:
    sheets: QSplitter
    ref: AlignmentSheet
    raw: AlignmentSheet
    path: Path | None = None
    links: dict = field(default_factory=dict)
    orders: tuple = ((), ())
    results: list = field(default_factory=list)


class ReferenceAlignmentPage(QWidget):
    plotted = pyqtSignal()
    alignment_changed = pyqtSignal()
    def __init__(self, trend_page, parent=None):
        super().__init__(parent)
        self.trend_page = trend_page
        self._rebuilding = False
        self._datasets = {}
        self._output_vendors = {}
        self._saved_output_frames = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(10)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('Ref output'))
        self.output_picker = ScrollSafeComboBox()
        self.output_picker.setMinimumWidth(250)
        self.output_picker.setSizeAdjustPolicy(ScrollSafeComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        trend_page.output_picker.setModel(self.output_picker.model())
        tools.addWidget(self.output_picker, 1)
        for text, callback in (('Load CSV…', self.choose_output_files),
                               ('Load folders…', self.choose_output_folders)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            tools.addWidget(button)
        self.raw_fixed = QCheckBox('Fix Raw wafer order')
        self.raw_fixed.setChecked(True)
        self.raw_fixed.toggled.connect(self._fixed_changed)
        tools.addWidget(self.raw_fixed)
        layout.addLayout(tools)
        vertical = QSplitter(Qt.Orientation.Vertical)
        self.sheet_stack = QStackedWidget()
        vertical.addWidget(self.sheet_stack)
        self._dataset = self._new_dataset()
        link_panel = QFrame(objectName='panel')
        link_layout = QVBoxLayout(link_panel)
        link_layout.setContentsMargins(16,14,16,12)
        link_layout.addWidget(help_title_label('Wafer alignment','Drag whole Ref wafer groups; select one Ref and one Raw wafer to link them one-to-one.'))
        link_tools = QHBoxLayout()
        for label, callback in (('Link selected',self.link_selected), ('Link aligned rows',self.link_aligned),
                                ('Unlink selected',self.unlink_selected), ('Clear links',self.clear_links)):
            button = QPushButton(label); button.clicked.connect(callback); link_tools.addWidget(button)
        link_layout.addLayout(link_tools)
        lists = QHBoxLayout()
        self.ref_wafers, self.raw_wafers = WaferOrderList(), WaferOrderList()
        self.canvas = LinkCanvas(self)
        lists.addWidget(self.ref_wafers,1); lists.addWidget(self.canvas); lists.addWidget(self.raw_wafers,1)
        link_layout.addLayout(lists)
        vertical.addWidget(link_panel)
        vertical.setSizes([480,200])
        layout.addWidget(vertical,1)
        sorting = QHBoxLayout()
        self.sort_basis = ScrollSafeComboBox(); self.sort_basis.addItem('Field X / Field Y','field'); self.sort_basis.addItem('Absolute X / Y','xy')
        self.primary = ScrollSafeComboBox(); self.primary.addItem('X first','x'); self.primary.addItem('Y first','y')
        self.x_order, self.y_order = ScrollSafeComboBox(), ScrollSafeComboBox()
        self.x_order.setAccessibleName('X sort direction')
        self.y_order.setAccessibleName('Y sort direction')
        for combo in (self.x_order, self.y_order):
            combo.addItem('Ascending',True); combo.addItem('Descending',False)
        for widget in (QLabel('Sort each wafer'), self.sort_basis, self.primary):
            sorting.addWidget(widget)
        for name, combo in (('X', self.x_order), ('Y', self.y_order)):
            pair = QHBoxLayout()
            pair.setSpacing(5)
            caption = QLabel(name)
            caption.setBuddy(combo)
            pair.addWidget(caption, 0, Qt.AlignmentFlag.AlignLeft)
            pair.addWidget(combo, 1)
            sorting.addLayout(pair)
        sort = QPushButton('Apply sort'); sort.clicked.connect(self.apply_sort); sorting.addWidget(sort)
        draw = QPushButton('Plot XY Bias',objectName='primary'); draw.clicked.connect(self.draw); sorting.addWidget(draw)
        layout.addLayout(sorting)
        self.status = QLabel()
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.output_picker.currentIndexChanged.connect(self._load_output)
        trend_page.output_picker.currentIndexChanged.connect(self._load_output)
        self.ref_wafers.moved.connect(lambda key: self._order_changed(self.ref_wafers,key))
        self.raw_wafers.moved.connect(lambda key: self._order_changed(self.raw_wafers,key))
        for widget in (self.ref_wafers,self.raw_wafers): widget.verticalScrollBar().valueChanged.connect(self.canvas.update)
        self._fixed_changed(True)

    @property
    def ref(self):
        return self._dataset.ref

    @property
    def raw(self):
        return self._dataset.raw

    @property
    def links(self):
        return self._dataset.links

    @property
    def results(self):
        return self._dataset.results

    def _new_dataset(self):
        sheets = QSplitter(Qt.Orientation.Horizontal)
        ref, raw = AlignmentSheet('Ref'), AlignmentSheet('Raw Data')
        sheets.addWidget(ref)
        sheets.addWidget(raw)
        sheets.setSizes([650, 650])
        dataset = AlignmentDataset(sheets, ref, raw)
        for sheet in (ref, raw):
            sheet.changed.connect(lambda: self._dataset_changed(dataset))
        self.sheet_stack.addWidget(sheets)
        return dataset

    def _dataset_changed(self, dataset):
        if dataset is self._dataset:
            self._tables_changed()
        else:
            dataset.results = []

    def set_report(self, report):
        vendor = report.request.vendor
        extensions = ('.xlsx', '.xlsm') if vendor == 'CDSEM1' else ('.csv',)
        self._add_outputs((path, vendor) for path in report.output_files
                          if not path.name.startswith('_') and path.suffix.lower() in extensions)

    def add_output_files(self, paths):
        entries = []
        for path in map(Path, paths):
            if path.suffix.casefold() != '.csv' or path.name.startswith(('_', '.')):
                continue
            prefixes = (path.name.upper(), path.parent.name.upper())
            vendor = next((name for name in ('NOVA', 'PMISH', 'KLA', 'CDSEM1')
                           if any(value.startswith(f'{name}_') for value in prefixes)), 'Ref')
            entries.append((path, vendor))
        self._add_outputs(entries)

    def choose_output_files(self, *_):
        paths = choose_files(self, 'Load Ref output CSV', 'Summary CSV files (*.csv)',
                             directory=self._dataset.path.parent if self._dataset.path else None)
        self.add_output_files(paths)

    def choose_output_folders(self, *_):
        folders = choose_folders(self, 'Load Ref output folders',
                                 directory=self._dataset.path.parent if self._dataset.path else None)
        if not folders:
            return
        paths = scan_alignment_outputs(folders)
        if not paths:
            self.status.setText('No measurement CSVs found in the selected folders.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Select Ref output CSVs')
        layout = QVBoxLayout(dialog)
        choices = CheckableListWidget()
        choices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for path in paths:
            item = QListWidgetItem(str(path))
            item.setToolTip(str(path))
            item.setCheckState(Qt.CheckState.Checked)
            choices.addItem(item)
        layout.addWidget(choices)

        def selected_paths():
            return [path for index, path in enumerate(paths)
                    if choices.item(index).checkState() == Qt.CheckState.Checked]

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        load = buttons.addButton('Load checked', QDialogButtonBox.ButtonRole.AcceptRole)
        choices.itemChanged.connect(lambda: load.setEnabled(bool(selected_paths())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        fit_window_to_screen(dialog, (740, 490), minimum=(460, 300))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_output_files(selected_paths())
        dialog.deleteLater()

    def _add_outputs(self, entries, *, select=True):
        first = None
        with QSignalBlocker(self.output_picker), QSignalBlocker(self.trend_page.output_picker):
            for path, vendor in entries:
                path = Path(path).resolve()
                index = self.output_picker.findData(str(path))
                if index < 0:
                    index = self.output_picker.count()
                    self.output_picker.addItem(str(path), str(path))
                    self.output_picker.setItemData(index, str(path), Qt.ItemDataRole.ToolTipRole)
                    self._output_vendors[path] = vendor
                if first is None:
                    first = index
        if first is not None and select:
            self._load_output(first)

    def _set_output_indexes(self, index):
        for picker in (self.output_picker, self.trend_page.output_picker):
            with QSignalBlocker(picker):
                picker.setCurrentIndex(index)
            picker.setToolTip(picker.currentData() or '')

    def _load_output(self, index):
        data = self.output_picker.itemData(index)
        if data is None:
            return
        path = Path(data)
        if self._dataset.path == path:
            self._set_output_indexes(index)
            return

        dataset = self._datasets.get(path)
        if dataset is None:
            try:
                frame = self._saved_output_frames.get(path)
                if frame is None:
                    frame = load_alignment_output(path)
            except (ValueError, OSError, StopIteration) as error:
                current = self._dataset.path
                self._set_output_indexes(self.output_picker.findData(str(current)) if current else -1)
                self.status.setText(str(error))
                QMessageBox.warning(self, 'Cannot load Ref output', f'{path.name}\n{error}')
                return
            dataset = self._new_dataset() if self._dataset.path else self._dataset
            with QSignalBlocker(dataset.ref):
                dataset.ref.set_frame(frame, self._output_vendors[path])
            dataset.path = path
            self._datasets[path] = dataset
            self._saved_output_frames.pop(path, None)

        if dataset is not self._dataset:
            self._dataset.orders = (self.ref_wafers.keys(), self.raw_wafers.keys())
            self._dataset = dataset
            self.sheet_stack.setCurrentWidget(dataset.sheets)
        self._set_output_indexes(index)
        self._rebuild_wafer_lists(dataset.orders)
        if dataset.results:
            self.trend_page.show_results(dataset.results)
        else:
            self.trend_page.clear()
        self.alignment_changed.emit()

    def paste_raw(self):
        from .matching_window import clipboard_frame
        try: self.raw.set_frame(clipboard_frame(QApplication.clipboard().text()))
        except (ValueError,TypeError) as error: self.status.setText(str(error))

    def _fixed_changed(self, fixed):
        self.raw_wafers.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop if fixed else QAbstractItemView.DragDropMode.InternalMove)

    def _invalidate(self):
        self._dataset.results = []
        self.trend_page.clear()
        self.alignment_changed.emit()

    def _tables_changed(self):
        if self._rebuilding: return
        self._rebuild_wafer_lists((self.ref_wafers.keys(), self.raw_wafers.keys()))
        self._invalidate()

    def reference_data(self):
        return aligned_reference_data(self.ref.frame(), self.raw.frame(),
                                      self.raw.columns(), self.results,
                                      self.ref.source_rows, self.raw.source_rows)

    def _rebuild_wafer_lists(self, previous):
        try:
            groups = [wafer_groups(sheet.frame(),sheet.columns()) for sheet in (self.ref,self.raw)]
            size = max(map(len,groups))
            self._rebuilding = True
            for widget, group, old in zip((self.ref_wafers,self.raw_wafers),groups,previous):
                order = [key for key in old if key is None or key in group]
                order += [key for key in group if key not in order]
                order = order[:size] if all(key in order[:size] for key in group) else list(group)
                order += [None] * (size - len(order))
                widget.clear()
                for key in order:
                    item = QListWidgetItem(' · '.join(part for part in key if part) if key else '—')
                    item.setData(Qt.ItemDataRole.UserRole,key); item.setSizeHint(QSize(0,32)); widget.addItem(item)
            self._dataset.links = {r:d for r,d in self.links.items() if r in groups[0] and d in groups[1]}
            self.status.setToolTip('')
            self.status.setText(f'{len(groups[0])} Ref wafers · {len(groups[1])} Raw wafers · {len(self.links)} linked pairs')
        except ValueError as error: self.status.setText(str(error))
        finally: self._rebuilding = False
        self.canvas.update()

    def _order_changed(self, widget, moved):
        if self._rebuilding: return
        sheet = self.ref if widget is self.ref_wafers else self.raw
        try:
            sheet.reorder(wafer_row_order(sheet.frame(),sheet.columns(),[key for key in widget.keys() if key is not None]))
            self._invalidate()
            index = widget.keys().index(moved) if moved is not None else -1
            other = self.raw_wafers if widget is self.ref_wafers else self.ref_wafers
            target = other.keys()[index] if 0 <= index < other.count() else None
            if moved and target:
                self.set_link(moved,target) if widget is self.ref_wafers else self.set_link(target,moved)
        except ValueError as error: self.status.setText(str(error))
        self.canvas.update()

    def set_link(self, ref, raw):
        if raw in self.links.values() and self.links.get(ref) != raw:
            raise ValueError('Raw wafer is already linked. Unlink it first; links must be one-to-one.')
        self.links[ref] = raw
        self._invalidate(); self.canvas.update()
        self.status.setText(f'{len(self.links)} linked pairs; unlinked wafers are excluded.')

    def link_selected(self):
        try:
            a,b = self.ref_wafers.currentItem(),self.raw_wafers.currentItem()
            if a and b and a.data(Qt.ItemDataRole.UserRole) and b.data(Qt.ItemDataRole.UserRole): self.set_link(a.data(Qt.ItemDataRole.UserRole),b.data(Qt.ItemDataRole.UserRole))
        except ValueError as error: self.status.setText(str(error))

    def link_aligned(self):
        self._dataset.links = {a:b for a,b in zip(self.ref_wafers.keys(),self.raw_wafers.keys()) if a is not None and b is not None}
        self._invalidate(); self.canvas.update(); self.status.setText(f'{len(self.links)} aligned pairs linked.')

    def unlink_selected(self):
        item = self.ref_wafers.currentItem()
        if item: self.links.pop(item.data(Qt.ItemDataRole.UserRole),None)
        self._invalidate(); self.canvas.update()

    def clear_links(self):
        self.links.clear(); self._invalidate(); self.canvas.update()

    def apply_sort(self):
        try:
            primary = self.primary.currentData()
            directions = (self.x_order.currentData(), self.y_order.currentData())
            if primary == 'y':
                directions = directions[::-1]
            orders = [coordinate_row_order(sheet.frame(), sheet.columns(), self.sort_basis.currentData(),
                                           primary, directions) for sheet in (self.ref, self.raw)]
            for sheet,order in zip((self.ref,self.raw),orders): sheet.reorder(order)
            self._invalidate(); self.status.setText('Both tables sorted within each wafer. Links retained; plot to compare the new row pairing.')
        except ValueError as error: self.status.setText(str(error)); self._invalidate()

    def draw(self):
        try:
            self.status.setToolTip('')
            if not self.links: raise ValueError('Link at least one Ref/Raw wafer pair first.')
            notes = []
            self._dataset.results = coordinate_bias(self.ref.frame(),self.raw.frame(),self.ref.columns(),self.raw.columns(),
                self.links, ref_source_rows=self.ref.source_rows, raw_source_rows=self.raw.source_rows, notes=notes)
            if not self.results:
                raise ValueError(notes[0] if notes else 'No aligned wafer points to plot.')
            self.trend_page.show_results(self.results)
            message = f'{len(self.results)} linked wafer trends · Bias = Raw − Ref ({self.raw.columns().unit})'
            if notes:
                message += f' · {len(notes)} alignment notes (hover for details)'
                self.status.setToolTip('\n'.join(notes))
            self.status.setText(message)
            self.alignment_changed.emit()
            self.plotted.emit()
        except ValueError as error:
            self._invalidate()
            self.status.setText(str(error))


class CoordinateTrendPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,12,10,10)
        layout.setSpacing(10)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('Ref output'))
        self.output_picker = ScrollSafeComboBox()
        self.output_picker.setMinimumWidth(220)
        self.output_picker.setSizeAdjustPolicy(ScrollSafeComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        tools.addWidget(self.output_picker, 1)
        tools.addWidget(QLabel('Columns', objectName='muted'))
        self.columns = ScrollSafeComboBox()
        self.columns.addItems(['1','2','3'])
        self.columns.setCurrentText('3')
        self.columns.setFixedWidth(60)
        self.columns.currentIndexChanged.connect(self.relayout)
        tools.addWidget(self.columns)
        self._results = []
        self.order_buttons = {}
        self._order = 'sorted'
        for order, title in (('raw', 'Raw order'), ('ref', 'Ref order'), ('sorted', 'XY sort order')):
            control = QPushButton(title)
            control.setCheckable(True)
            control.setChecked(order == self._order)
            control.setEnabled(False)
            control.clicked.connect(lambda _checked, value=order: self.set_order(value))
            self.order_buttons[order] = control
            tools.addWidget(control)
        tools.addStretch()
        self.summary = QLabel('0 linked wafers', objectName='accent')
        tools.addWidget(self.summary)
        layout.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().installEventFilter(self)
        layout.addWidget(self.scroll,1)
        self.plots = []
        self.panels = []

    def clear(self):
        self._results = []
        for control in self.order_buttons.values():
            control.setEnabled(False)
        self._clear_plots()

    def _clear_plots(self):
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.plots = []
        self.panels = []
        self.summary.setText('0 linked wafers')

    def relayout(self):
        # Reparent existing panels: column changes do not recreate curves or reset zoom.
        old = self.scroll.takeWidget()
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        columns = int(self.columns.currentText())
        for index, panel in enumerate(self.panels):
            grid.addWidget(panel, *divmod(index, columns))
        self._size_panels()
        self.scroll.setWidget(content)
        if old is not None:
            old.deleteLater()

    def _size_panels(self):
        width = max(280, min(640, (self.scroll.viewport().width() - 12) // 3))
        for panel in self.panels:
            panel.setFixedSize(width, 350)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._size_panels()
        return super().eventFilter(watched, event)

    def reset_views(self):
        for plot in self.plots:
            plot.getViewBox().autoRange()

    def show_results(self, results):
        self._results = results
        for control in self.order_buttons.values():
            control.setEnabled(bool(results))
        self.set_order(self._order)

    def set_order(self, order):
        self._order = order
        for value, control in self.order_buttons.items():
            control.setChecked(value == order)
        self._clear_plots()
        source = {'raw': 'Raw source row', 'ref': 'Ref source row'}.get(order)
        results = self._results
        if source:
            results = sorted(results, key=lambda result: result[2][source].min())
        for ref,raw,frame in results:
            if source:
                frame = frame.sort_values(source, kind='stable')
            unit = frame.attrs.get('unit','mm')
            from .spectra_plots import DecimalAxisItem
            plot = InteractivePlotWidget(background='white', axisItems={'left':DecimalAxisItem('left'), 'bottom':DecimalAxisItem('bottom')})
            for name in ('left','bottom'):
                axis = plot.getAxis(name)
                axis.enableAutoSIPrefix(False)
                axis.setPen('#555555'); axis.setTextPen('#333333')
            plot.setMinimumSize(0,280)
            title = ' · '.join(part for part in raw if part) + ' ↔ ' + ' · '.join(part for part in ref if part)
            heading = QLabel(f'<b>{escape(title)}</b>')
            heading.setStyleSheet('color: #20242a; padding: 6px;')
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setToolTip(title)
            plot.setToolTip('Ctrl+scroll to zoom · Ordinary scrolling moves the page')
            order_label = self.order_buttons[order].text()
            plot.setLabel('left',f'Bias ({unit})',color='#30343b'); plot.setLabel('bottom',f'Paired point ({order_label})',color='#30343b')
            plot.showGrid(x=False,y=True,alpha=.18); plot.addLegend(offset=None,labelTextColor='#333333')
            point = range(1, len(frame) + 1)
            plot.plot(point,frame[f'Bias X ({unit})'].to_numpy(),pen=pg.mkPen('#0072B2',width=2),symbol='o',symbolSize=4,symbolPen='#0072B2',symbolBrush='#0072B2',name='X: Raw − Ref')
            plot.plot(point,frame[f'Bias Y ({unit})'].to_numpy(),pen=pg.mkPen('#D55E00',width=2),symbol='t',symbolSize=4,symbolPen='#D55E00',symbolBrush='#D55E00',name='Y: Raw − Ref')
            plot.addItem(pg.InfiniteLine(pos=0,angle=0,pen=pg.mkPen('#888888',style=Qt.PenStyle.DashLine)))
            place_legend_above_frame(plot)
            plot.getPlotItem().layout.setRowFixedHeight(0,28)
            self.panels.append(PlotPanel(heading,plot))
            self.plots.append(plot)
        unit = results[0][2].attrs.get('unit','mm') if results else ''
        self.summary.setText(f'{len(self.plots)} linked wafers · Bias = Raw − Ref ({unit})')
        self.relayout()

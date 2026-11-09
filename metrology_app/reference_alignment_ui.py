"""Editable source sheets, explicit wafer links and coordinate-Bias trends."""
from dataclasses import fields
from html import escape
from math import ceil

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QCheckBox, QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QScrollArea, QFrame, QApplication)

from .widgets import ScrollSafeComboBox
from .sheet import SheetModel, SheetView, DuplicateHeaderBanner
from .appearance import help_title_label
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel, place_legend_above_frame
from .reference_alignment import (AlignmentColumns, infer_alignment_columns, wafer_groups,
    wafer_row_order, coordinate_row_order, coordinate_bias, load_alignment_output)


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
        if len(self.source_rows) != len(self.frame()):
            self.source_rows = list(range(2, len(self.frame()) + 2))
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


class ReferenceAlignmentPage(QWidget):
    plotted = pyqtSignal()
    def __init__(self, trend_page, parent=None):
        super().__init__(parent)
        self.trend_page = trend_page
        self.links = {}
        self._rebuilding = False
        self.results = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(10)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('Ref output'))
        self.output_picker = ScrollSafeComboBox()
        self.output_picker.setMinimumWidth(250)
        tools.addWidget(self.output_picker, 1)
        self.raw_fixed = QCheckBox('Fix Raw wafer order')
        self.raw_fixed.setChecked(True)
        self.raw_fixed.toggled.connect(self._fixed_changed)
        tools.addWidget(self.raw_fixed)
        layout.addLayout(tools)
        vertical = QSplitter(Qt.Orientation.Vertical)
        sheets = QSplitter(Qt.Orientation.Horizontal)
        self.ref = AlignmentSheet('Ref')
        self.raw = AlignmentSheet('Raw Data')
        sheets.addWidget(self.ref); sheets.addWidget(self.raw)
        sheets.setSizes([650,650])
        vertical.addWidget(sheets)
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
        self.first_order, self.second_order = ScrollSafeComboBox(), ScrollSafeComboBox()
        self.first_order.setToolTip('Primary coordinate sort direction')
        self.second_order.setToolTip('Secondary coordinate sort direction')
        for combo in (self.first_order,self.second_order):
            combo.addItem('Ascending',True); combo.addItem('Descending',False)
        for widget in (QLabel('Sort each wafer'),self.sort_basis,self.primary,self.first_order,self.second_order): sorting.addWidget(widget)
        sort = QPushButton('Apply sort'); sort.clicked.connect(self.apply_sort); sorting.addWidget(sort)
        draw = QPushButton('Plot XY Bias',objectName='primary'); draw.clicked.connect(self.draw); sorting.addWidget(draw)
        layout.addLayout(sorting)
        self.status = QLabel('Paste into the Raw Data table (Ctrl+V), then drag wafers into position or link selected wafers. Only linked pairs are plotted.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.output_picker.currentIndexChanged.connect(self._load_output)
        for sheet in (self.ref,self.raw): sheet.changed.connect(self._tables_changed)
        self.ref_wafers.moved.connect(lambda key: self._order_changed(self.ref_wafers,key))
        self.raw_wafers.moved.connect(lambda key: self._order_changed(self.raw_wafers,key))
        for widget in (self.ref_wafers,self.raw_wafers): widget.verticalScrollBar().valueChanged.connect(self.canvas.update)
        self._fixed_changed(True)

    def set_report(self, report):
        self.output_picker.blockSignals(True); self.output_picker.clear()
        for path in report.output_files:
            if path.name.startswith('_'): continue
            if report.request.vendor == 'CDSEM1' and path.suffix.lower() not in ('.xlsx','.xlsm'): continue
            if report.request.vendor != 'CDSEM1' and path.suffix.lower() != '.csv': continue
            self.output_picker.addItem(path.name,(str(path),report.request.vendor))
        self.output_picker.blockSignals(False)
        self._load_output()

    def _load_output(self, *_):
        data = self.output_picker.currentData()
        if data:
            try:
                self.links.clear()
                self.ref.set_frame(load_alignment_output(data[0]),data[1])
            except (ValueError,OSError,StopIteration) as error: self.status.setText(str(error))

    def paste_raw(self):
        from .matching_window import clipboard_frame
        try: self.raw.set_frame(clipboard_frame(QApplication.clipboard().text()))
        except (ValueError,TypeError) as error: self.status.setText(str(error))

    def _fixed_changed(self, fixed):
        self.raw_wafers.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop if fixed else QAbstractItemView.DragDropMode.InternalMove)

    def _invalidate(self):
        self.results = []; self.trend_page.clear()

    def _tables_changed(self):
        if self._rebuilding: return
        self._invalidate()
        try:
            groups = [wafer_groups(sheet.frame(),sheet.columns()) for sheet in (self.ref,self.raw)]
            size = max(map(len,groups))
            self._rebuilding = True
            for widget, group in zip((self.ref_wafers,self.raw_wafers),groups):
                old = widget.keys()
                order = [key for key in old if key is None or key in group]
                order += [key for key in group if key not in order]
                order = order[:size] if all(key in order[:size] for key in group) else list(group)
                order += [None] * (size - len(order))
                widget.clear()
                for key in order:
                    item = QListWidgetItem(' · '.join(part for part in key if part) if key else '—')
                    item.setData(Qt.ItemDataRole.UserRole,key); item.setSizeHint(QSize(0,32)); widget.addItem(item)
            self.links = {r:d for r,d in self.links.items() if r in groups[0] and d in groups[1]}
            self.status.setText(f'{len(groups[0])} Ref wafers · {len(groups[1])} Raw wafers · {len(self.links)} linked pairs')
        except ValueError as error: self.status.setText(str(error))
        finally: self._rebuilding = False
        self.canvas.update()

    def _order_changed(self, widget, moved):
        if self._rebuilding: return
        sheet = self.ref if widget is self.ref_wafers else self.raw
        try:
            sheet.reorder(wafer_row_order(sheet.frame(),sheet.columns(),[key for key in widget.keys() if key is not None]))
            index = widget.keys().index(moved) if moved is not None else -1
            other = self.raw_wafers if widget is self.ref_wafers else self.ref_wafers
            target = other.keys()[index] if 0 <= index < other.count() else None
            if moved and target:
                self.set_link(moved,target) if widget is self.ref_wafers else self.set_link(target,moved)
            self._invalidate(); self.canvas.update()
        except ValueError as error: self.status.setText(str(error))

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
        self.links = {a:b for a,b in zip(self.ref_wafers.keys(),self.raw_wafers.keys()) if a is not None and b is not None}
        self._invalidate(); self.canvas.update(); self.status.setText(f'{len(self.links)} aligned pairs linked.')

    def unlink_selected(self):
        item = self.ref_wafers.currentItem()
        if item: self.links.pop(item.data(Qt.ItemDataRole.UserRole),None)
        self._invalidate(); self.canvas.update()

    def clear_links(self):
        self.links.clear(); self._invalidate(); self.canvas.update()

    def apply_sort(self):
        try:
            orders = [coordinate_row_order(sheet.frame(),sheet.columns(),self.sort_basis.currentData(),self.primary.currentData(),
                       (self.first_order.currentData(),self.second_order.currentData())) for sheet in (self.ref,self.raw)]
            for sheet,order in zip((self.ref,self.raw),orders): sheet.reorder(order)
            self._invalidate(); self.status.setText('Both tables sorted within each wafer. Links retained; plot to compare the new row pairing.')
        except ValueError as error: self.status.setText(str(error)); self._invalidate()

    def draw(self):
        try:
            self._invalidate()
            if not self.links: raise ValueError('Link at least one Ref/Raw wafer pair first.')
            self.results = coordinate_bias(self.ref.frame(),self.raw.frame(),self.ref.columns(),self.raw.columns(),self.links,
                ref_source_rows=self.ref.source_rows,raw_source_rows=self.raw.source_rows)
            self.trend_page.show_results(self.results)
            self.status.setText(f'{len(self.results)} linked wafer trends · Bias = Raw − Ref ({self.raw.columns().unit})')
            self.plotted.emit()
        except ValueError as error: self.status.setText(str(error))


class CoordinateTrendPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,12,10,10)
        layout.setSpacing(10)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('Columns', objectName='muted'))
        self.columns = ScrollSafeComboBox()
        self.columns.addItems(['1','2'])
        self.columns.setCurrentText('2')
        self.columns.setFixedWidth(60)
        self.columns.currentIndexChanged.connect(self.relayout)
        tools.addWidget(self.columns)
        reset = QPushButton('Reset views')
        reset.setToolTip('Ctrl+scroll to zoom; ordinary scrolling moves the page.')
        reset.clicked.connect(self.reset_views)
        tools.addWidget(reset)
        tools.addStretch()
        self.summary = QLabel('0 linked wafers', objectName='accent')
        tools.addWidget(self.summary)
        layout.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll,1)
        self.plots = []
        self.panels = []

    def clear(self):
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.plots = []
        self.panels = []
        self.summary.setText('0 linked wafers')

    def relayout(self):
        # Reparent existing panels: column changes do not recreate curves or reset zoom.
        old = self.scroll.takeWidget()
        grid = PanelGrid(int(self.columns.currentText()))
        grid.set_fixed_row_height(ceil(len(self.panels) / grid.columns),350)
        for panel in self.panels:
            panel.setParent(None)
            grid.add_panel(panel)
        grid.complete_last_row()
        self.scroll.setWidget(grid)
        if old is not None:
            old.deleteLater()

    def reset_views(self):
        for plot in self.plots:
            plot.getViewBox().autoRange()

    def show_results(self, results):
        self.clear()
        for ref,raw,frame in results:
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
            plot.setLabel('left',f'Bias ({unit})',color='#30343b'); plot.setLabel('bottom','Paired point (sorted table order)',color='#30343b')
            plot.showGrid(x=False,y=True,alpha=.18); plot.addLegend(offset=None,labelTextColor='#333333')
            plot.plot(frame['Point'].to_numpy(),frame[f'Bias X ({unit})'].to_numpy(),pen=pg.mkPen('#0072B2',width=2),symbol='o',symbolSize=4,symbolPen='#0072B2',symbolBrush='#0072B2',name='X: Raw − Ref')
            plot.plot(frame['Point'].to_numpy(),frame[f'Bias Y ({unit})'].to_numpy(),pen=pg.mkPen('#D55E00',width=2),symbol='t',symbolSize=4,symbolPen='#D55E00',symbolBrush='#D55E00',name='Y: Raw − Ref')
            plot.addItem(pg.InfiniteLine(pos=0,angle=0,pen=pg.mkPen('#888888',style=Qt.PenStyle.DashLine)))
            place_legend_above_frame(plot)
            plot.getPlotItem().layout.setRowFixedHeight(0,28)
            self.panels.append(PlotPanel(heading,plot))
            self.plots.append(plot)
        unit = results[0][2].attrs.get('unit','mm') if results else ''
        self.summary.setText(f'{len(self.plots)} linked wafers · Bias = Raw − Ref ({unit})')
        self.relayout()

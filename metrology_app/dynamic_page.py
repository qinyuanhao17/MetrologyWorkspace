"""Qt page for Dynamic cycle tables and per-die 3σ bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSplitter, QTableView, QVBoxLayout, QWidget,
)
from pyqtgraph.graphicsItems.LegendItem import ItemSample, LegendItem

from .dynamic import (changed_dynamic_parameters, dynamic_pivot,
                      prepare_dynamic_frame, selected_measurement_rows)
from .plotting import InteractivePlotWidget
from .settings import get_settings
from .sheet import clipboard_rows


PLOT_WIDTH = 420
PLOT_HEIGHT = 270
PLOT_SPACING = 14
PLOT_COLUMNS = 3
SERIES_COLOURS = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#000000",
)


class CompactBarLegendSample(ItemSample):
    """Small colour swatch for the combined Dynamic chart legend."""

    SIZE = 10

    def __init__(self, item):
        super().__init__(item)
        self.setFixedWidth(self.SIZE)
        self.setFixedHeight(self.SIZE)

    def boundingRect(self):
        return QRectF(0, 0, self.SIZE, self.SIZE)

    def paint(self, painter, *_args):
        painter.setPen(pg.mkPen(self.item.opts["pen"]))
        painter.setBrush(pg.mkBrush(self.item.opts["brush"]))
        painter.drawRect(QRectF(1, 1, self.SIZE - 2, self.SIZE - 2))


class DynamicPivotModel(QAbstractTableModel):
    """Cycle × Die pivot whose measurement cells edit the shared Data sheet.

    The Cycle / Die labels and the derived ``3 Sigma`` row stay read-only; only
    the numbered cells are editable, which is how an engineer drops an outlier
    before the repeatability statistics are recomputed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()
        self.cell_sources = {}
        self.edit_callback = None

    def set_frame(self, frame, cell_sources=None, edit_callback=None):
        self.beginResetModel()
        self.frame = frame.copy()
        self.cell_sources = dict(cell_sources or {})
        self.edit_callback = edit_callback
        self.endResetModel()

    def update_values(self, frame):
        """Keep the editor and its selection alive for a same-shape update."""
        old = self.frame
        self.frame = frame.copy()
        for column in range(len(frame.columns)):
            changed = ~(old.iloc[:, column].eq(frame.iloc[:, column])
                        | (old.iloc[:, column].isna() & frame.iloc[:, column].isna()))
            rows = np.flatnonzero(changed.to_numpy())
            if len(rows):
                self.dataChanged.emit(self.index(int(rows[0]), column),
                                      self.index(int(rows[-1]), column))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.frame.iat[index.row(), index.column()]
            if pd.isna(value):
                return ""
            return f"{float(value):.8g}" if isinstance(value, (float, np.floating)) else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if self.frame.index[index.row()] == "3 Sigma":
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            column = self.frame.columns[section]
            if isinstance(column, tuple) and len(column) >= 2:
                return f"{column[0]}\nDie {column[1]}"
            return f"Die {column}"
        return str(self.frame.index[section])

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and (index.row(), index.column()) in self.cell_sources:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        return self.edit({(index.row(), index.column()): str(value)})

    def edit(self, changes):
        """Send edited cells to the Data sheet and show them straight away."""
        if self.edit_callback is None:
            return False
        targets = {}
        for (row, column), value in changes.items():
            source = self.cell_sources.get((row, column))
            if source is not None:
                targets[(row, column)] = (source, str(value))
        if not targets:
            return False
        self.edit_callback({source: value for source, value in targets.values()})
        self._show_edits({cell: value for cell, (_source, value) in targets.items()})
        return True

    def _show_edits(self, changes):
        """Paint the edited cells and recompute the derived row immediately."""
        edited_columns = set()
        for (row, column), value in changes.items():
            if not 0 <= row < len(self.frame) or not 0 <= column < len(self.frame.columns):
                continue
            if row == len(self.frame) - 1:
                continue
            try:
                numeric = float(value) if str(value).strip() else np.nan
            except ValueError:
                self.frame.iat[row, column] = value
            else:
                self.frame.iat[row, column] = numeric
            edited_columns.add(column)
        if not edited_columns:
            return
        for column in edited_columns:
            values = pd.to_numeric(self.frame.iloc[:-1, column], errors="coerce")
            self.frame.iat[-1, column] = values.std(ddof=1) * 3.0
            self.dataChanged.emit(
                self.index(0, column), self.index(len(self.frame) - 1, column),
            )


class DynamicPivotView(QTableView):
    """Pivot grid with the same clipboard and undo keys as the Data sheet."""

    def __init__(self, model, history=None):
        super().__init__()
        self.setModel(model)
        self.history = history
        self.setAlternatingRowColors(True)
        self.setSelectionMode(self.SelectionMode.ContiguousSelection)
        self.setHorizontalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(28)

    def undo_stack(self):
        """The Data sheet's history, so one Ctrl+Z undoes one edit anywhere."""
        return getattr(self.history, "undo", None)

    def paste(self):
        matrix = clipboard_rows(QApplication.clipboard().text())
        index = self.currentIndex()
        if not matrix or not index.isValid():
            return
        changes = {
            (index.row() + row, index.column() + column): value
            for row, line in enumerate(matrix)
            for column, value in enumerate(line)
        }
        self.model().edit(changes)

    def copy(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = range(min(i.row() for i in indexes), max(i.row() for i in indexes) + 1)
        columns = range(
            min(i.column() for i in indexes), max(i.column() for i in indexes) + 1
        )
        output = []
        for row in rows:
            output.append("\t".join(
                self.model().data(self.model().index(row, column)) or ""
                for column in columns
            ))
        QApplication.clipboard().setText("\n".join(output))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif event.matches(QKeySequence.StandardKey.Undo):
            stack = self.undo_stack()
            if stack is not None:
                stack.undo()
        elif event.matches(QKeySequence.StandardKey.Redo):
            stack = self.undo_stack()
            if stack is not None:
                stack.redo()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            indexes = self.selectedIndexes()
            if not indexes and self.currentIndex().isValid():
                indexes = [self.currentIndex()]
            self.model().edit({
                (index.row(), index.column()): ""
                for index in indexes
            })
        else:
            super().keyPressEvent(event)


class DynamicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, objectName="dynamicPage")
        self.frame = pd.DataFrame()
        self.baseline = pd.DataFrame()
        self.selection = {}
        self.data_model = None
        self.current_cells = {}
        self.parameter_models = {}
        self.parameter_tables = {}
        self.parameter_sections = []
        self.plots = []
        self.bar_items = []
        self.comparison_legend = None
        self.plot = None
        self.pivot_model = None
        self.table = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        self.message = QLabel(
            "Select one measurement set and at least one numeric parameter in Data.",
            objectName="subtitle",
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.content = QFrame(objectName="panel")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)
        dark = get_settings().get("theme") == "dark"
        self._plot_background = "#17121d" if dark else "#f8f7fa"
        self._plot_foreground = "#cfc4d5" if dark else "#5f5965"

        self.results_splitter = QSplitter(Qt.Orientation.Vertical)
        self.results_splitter.setObjectName("dynamicResultsSplitter")
        self.results_splitter.setChildrenCollapsible(False)

        self.table_scroll = QScrollArea(objectName="dynamicTableScroll")
        self.table_scroll.setWidgetResizable(True)
        self.table_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table_host = QWidget(objectName="dynamicTableHost")
        self.table_layout = QVBoxLayout(self.table_host)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.setSpacing(PLOT_SPACING)
        self.table_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.table_scroll.setWidget(self.table_host)

        self.plot_scroll = QScrollArea(objectName="dynamicPlotScroll")
        self.plot_scroll.setWidgetResizable(False)
        self.plot_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_host = QWidget(objectName="dynamicPlotHost")
        self.plot_layout = QGridLayout(self.plot_host)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.setHorizontalSpacing(PLOT_SPACING)
        self.plot_layout.setVerticalSpacing(PLOT_SPACING)
        self.plot_scroll.setWidget(self.plot_host)

        self.results_splitter.addWidget(self.table_scroll)
        self.results_splitter.addWidget(self.plot_scroll)
        self.results_splitter.setStretchFactor(0, 1)
        self.results_splitter.setStretchFactor(1, 1)
        self.results_splitter.setSizes([1, 1])
        content_layout.addWidget(self.results_splitter, 1)
        layout.addWidget(self.content, 1)
        self.content.hide()

    def set_input(self, frame, selection):
        changed = changed_dynamic_parameters(self.frame, frame, self.selection, selection)
        self.frame = pd.DataFrame(frame).copy()
        self.selection = dict(selection)
        if (changed is not None and self.parameter_models
                and self._update_parameters(changed)):
            return
        self.refresh()

    def _update_parameters(self, changed):
        """Recalculate only edited parameters; retain all widgets and zooms."""
        if not changed:
            return True
        try:
            prepared = prepare_dynamic_frame(self._selected_rows())
            pivots = {parameter: dynamic_pivot(prepared, parameter) for parameter in changed}
        except ValueError:
            return False
        if any(not pivot.index.equals(self.parameter_models[parameter].frame.index)
               or not pivot.columns.equals(self.parameter_models[parameter].frame.columns)
               for parameter, pivot in pivots.items()):
            return False
        parameters = list(self.parameter_models)
        comparison = len(parameters) > 1
        dies = list(dict.fromkeys(die for model in self.parameter_models.values()
                                  for die in model.frame.columns))
        for parameter, pivot in pivots.items():
            self.parameter_models[parameter].update_values(pivot)
            index = parameters.index(parameter)
            sigma = pivot.loc["3 Sigma"].to_numpy(float)
            finite = np.isfinite(sigma)
            x = np.arange(1, len(sigma) + 1, dtype=float)
            self.bar_items[index + (len(parameters) if comparison else 0)].setOpts(
                x=x[finite], height=sigma[finite])
            if comparison:
                sigma = pivot.loc["3 Sigma"].reindex(dies).to_numpy(float)
                finite = np.isfinite(sigma)
                x = np.arange(1, len(dies) + 1, dtype=float)
                offset = (index - (len(parameters) - 1) / 2.0) * .78 / len(parameters)
                self.bar_items[index].setOpts(x=(x + offset)[finite], height=sigma[finite])
        return True

    def set_data_model(self, model):
        """Edit the loaded table through the Data sheet's own undo history."""
        self.data_model = model

    def set_baseline(self, frame):
        """Remember the loaded values so Restore can return the table to them."""
        self.baseline = pd.DataFrame(frame).copy()

    def restore_parameter(self, parameter):
        """Put one parameter's cells back to the values it was loaded with."""
        if self.data_model is None or parameter not in self.frame.columns:
            return False
        if parameter not in self.baseline.columns:
            return False
        column = self.frame.columns.get_loc(parameter)

        def text(value):
            return "" if pd.isna(value) else str(value)

        changes = {}
        for row in range(min(len(self.frame), len(self.baseline))):
            original = self.baseline.iloc[row][parameter]
            if text(self.frame.iloc[row][parameter]) != text(original):
                changes[(row + 1, column)] = text(original)
        if not changes:
            return False
        self.data_model.edit(changes)
        return True

    def _edit_pivot_cells(self, changes):
        """Route pivot edits to the shared Data sheet as one undoable step."""
        if self.data_model is None:
            return
        self.data_model.edit({
            cell: str(value) for cell, value in changes.items()
        })

    def _selected_rows(self):
        return selected_measurement_rows(self.frame, self.selection)

    def _pivot_cell_sources(self, prepared, source_rows, pivot, column):
        """Map each editable pivot cell to its Data sheet cell."""
        positions = {
            (cycle, die): row
            for row, (cycle, die) in zip(
                source_rows, zip(prepared["Cycle"], prepared["Die Seq"])
            )
        }
        return {
            (row, pivot_column): (
                positions[(pivot.index[row], pivot.columns[pivot_column])] + 1,
                column,
            )
            for row in range(max(0, len(pivot) - 1))
            for pivot_column in range(len(pivot.columns))
            if (pivot.index[row], pivot.columns[pivot_column]) in positions
        }

    def refresh(self, *_args):
        table_scroll = self.table_scroll.verticalScrollBar().value()
        plot_scroll = (
            self.plot_scroll.verticalScrollBar().value(),
            self.plot_scroll.horizontalScrollBar().value(),
        )
        self.current_cells = {
            parameter: (table.currentIndex().row(), table.currentIndex().column())
            for parameter, table in self.parameter_tables.items()
            if table.currentIndex().isValid()
        }
        self._clear_results()
        parameters = list(self.selection.get("metrics", ()))
        if not parameters:
            self.content.hide()
            self.message.setText(
                "Select one measurement set and at least one numeric parameter in Data."
            )
            self.message.show()
            return
        try:
            rows = self._selected_rows().drop(columns=["Cycle"], errors="ignore")
            prepared = prepare_dynamic_frame(rows)
            source_rows = list(rows.index)
            pivots = {
                parameter: dynamic_pivot(prepared, parameter)
                for parameter in parameters
            }
        except ValueError as error:
            self.content.hide()
            self.message.setText(str(error))
            self.message.show()
            return

        if len(parameters) > 1:
            self._add_comparison_plot(parameters, pivots)
        for index, parameter in enumerate(parameters):
            self._add_parameter_section(
                parameter,
                pivots[parameter],
                self._pivot_cell_sources(
                    prepared, source_rows, pivots[parameter],
                    self.frame.columns.get_loc(parameter),
                ),
            )
            self._add_parameter_plot(
                parameter, pivots[parameter],
                SERIES_COLOURS[index % len(SERIES_COLOURS)],
            )
        plot_columns = min(PLOT_COLUMNS, len(self.plots))
        plot_rows = (len(self.plots) + PLOT_COLUMNS - 1) // PLOT_COLUMNS
        plot_width = plot_columns * PLOT_WIDTH
        plot_width += max(0, plot_columns - 1) * PLOT_SPACING
        plot_height = plot_rows * PLOT_HEIGHT
        plot_height += max(0, plot_rows - 1) * PLOT_SPACING
        self.plot_host.setFixedSize(plot_width, plot_height)
        self.plot = self.plots[0]
        self.pivot_model = self.parameter_models[parameters[0]]
        self.table = self.parameter_tables[parameters[0]]
        # Keep both panes where the engineer left them: deleting an outlier must
        # not scroll the table back to the top.
        self.table_scroll.verticalScrollBar().setValue(table_scroll)
        self.plot_scroll.verticalScrollBar().setValue(plot_scroll[0])
        self.plot_scroll.horizontalScrollBar().setValue(plot_scroll[1])
        self.message.hide()
        self.content.show()

    def _clear_results(self):
        self.bar_items = []
        self.comparison_legend = None
        self.plot = None
        self.pivot_model = None
        self.table = None
        while self.table_layout.count():
            item = self.table_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.deleteLater()
        while self.plot_layout.count():
            item = self.plot_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.deleteLater()
        self.parameter_models = {}
        self.parameter_tables = {}
        self.parameter_sections = []
        self.plots = []

    def _new_plot(self, title):
        plot = InteractivePlotWidget(
            background=self._plot_background, frame_tick_length=3
        )
        plot.setFixedSize(PLOT_WIDTH, PLOT_HEIGHT)
        plot.setLabel("bottom", "Die Seq")
        plot.setLabel("left", "3 Sigma (nm)")
        plot.setToolTip(
            "Ctrl+scroll to zoom · Drag to pan · Ordinary scrolling moves the page"
        )
        plot.getAxis("left").enableAutoSIPrefix(False)
        frame_pen = pg.mkPen(self._plot_foreground)
        plot.getPlotItem().getViewBox().setBorder(None)
        for axis_name in ("top", "right", "bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(frame_pen)
            axis.setTextPen(frame_pen)
        plot.showGrid(x=True, y=True, alpha=0.18)
        if title:
            plot.setTitle(title)
            accessible_title = str(title)
        else:
            plot.setTitle(None)
            accessible_title = "selected parameters"
        plot.setAccessibleName(f"Dynamic 3 Sigma — {accessible_title}")
        row, column = divmod(len(self.plots), PLOT_COLUMNS)
        self.plot_layout.addWidget(plot, row, column)
        self.plots.append(plot)
        return plot

    def _add_parameter_section(self, parameter, pivot, cell_sources=None):
        section = QFrame(objectName="dynamicParameterSection")
        section.setProperty("parameter", parameter)
        section.setAccessibleName(f"Dynamic results — {parameter}")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(10, 10, 10, 10)
        section_layout.setSpacing(10)

        heading = QHBoxLayout()
        heading.addWidget(QLabel(str(parameter), objectName="sectionTitle"))
        heading.addStretch()
        restore = QPushButton("Restore", objectName="subtle")
        restore.setToolTip(
            "Put this parameter's cells back to the values it was loaded with.\n"
            "Ctrl+Z still undoes one step at a time."
        )
        restore.clicked.connect(
            lambda _checked=False, name=parameter: self.restore_parameter(name)
        )
        heading.addWidget(restore)
        section_layout.addLayout(heading)

        model = DynamicPivotModel(section)
        model.set_frame(pivot, cell_sources, self._edit_pivot_cells)
        table = DynamicPivotView(model, self.data_model)
        table.setObjectName("dynamicParameterTable")
        table.setAccessibleName(f"Dynamic pivot — {parameter}")
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setMinimumHeight(42)
        table.setFixedHeight(42 + len(pivot) * 28 + 22)
        cell = self.current_cells.get(parameter)
        if cell is not None and 0 <= cell[0] < len(pivot) and 0 <= cell[1] < len(pivot.columns):
            table.setCurrentIndex(model.index(*cell))
            table.selectionModel().select(
                model.index(*cell),
                table.selectionModel().SelectionFlag.Select,
            )
        section_layout.addWidget(table)

        self.parameter_models[parameter] = model
        self.parameter_tables[parameter] = table
        self.parameter_sections.append(section)
        self.table_layout.addWidget(section)

    @staticmethod
    def _set_die_ticks(plot, dies):
        x = np.arange(1, len(dies) + 1, dtype=float)
        plot.getAxis("bottom").setTicks([
            [(float(position), str(label)) for position, label in zip(x, dies)]
        ])
        return x

    def _add_comparison_plot(self, parameters, pivots):
        plot = self._new_plot(None)
        plot_item = plot.getPlotItem()
        plot_item.layout.removeItem(plot_item.titleLabel)
        legend = LegendItem(
            offset=None,
            horSpacing=4,
            verSpacing=0,
            pen=None,
            brush=None,
            frame=False,
            labelTextColor=self._plot_foreground,
            labelTextSize="8pt",
            colCount=len(parameters),
            sampleType=CompactBarLegendSample,
        )
        plot_item.layout.addItem(
            legend, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        plot_item.layout.setRowFixedHeight(0, 22)
        self.comparison_legend = legend
        dies = list(dict.fromkeys(
            die for parameter in parameters for die in pivots[parameter].columns
        ))
        x = self._set_die_ticks(plot, dies)
        group_width = 0.78
        bar_width = group_width / len(parameters)
        for index, parameter in enumerate(parameters):
            colour = SERIES_COLOURS[index % len(SERIES_COLOURS)]
            sigma = pivots[parameter].loc["3 Sigma"].reindex(dies).to_numpy(float)
            finite = np.isfinite(sigma)
            offset = (index - (len(parameters) - 1) / 2.0) * bar_width
            bars = pg.BarGraphItem(
                x=(x + offset)[finite], height=sigma[finite],
                width=bar_width * 0.86, brush=pg.mkBrush(colour),
                pen=pg.mkPen(colour, width=1),
            )
            plot.addItem(bars)
            legend.addItem(bars, parameter)
            self.bar_items.append(bars)

    def _add_parameter_plot(self, parameter, pivot, colour):
        plot = self._new_plot(parameter)
        dies = list(pivot.columns)
        x = self._set_die_ticks(plot, dies)
        sigma = pivot.loc["3 Sigma"].to_numpy(float)
        finite = np.isfinite(sigma)
        bars = pg.BarGraphItem(
            x=x[finite], height=sigma[finite], width=0.72,
            brush=pg.mkBrush(colour), pen=pg.mkPen(colour, width=1),
        )
        plot.addItem(bars)
        self.bar_items.append(bars)


__all__ = ["DynamicPage", "DynamicPivotModel", "DynamicPivotView"]

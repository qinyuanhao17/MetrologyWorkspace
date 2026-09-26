"""Qt workspace for multi-parameter Reference/Raw card matching."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen
from .data import inspect_table
from .matching import MAX_ROWS, MatchWorkbook, ParameterMapping, extrema_sample_indices
from .settings import apply_theme
from .sheet import SheetModel, SheetView


PLOT_LIMIT = 20_000


def _label(text, role="muted"):
    widget = QLabel(text)
    widget.setObjectName(role)
    return widget


def clipboard_frame(text):
    """Parse an Excel/CSV clipboard block while preserving identifiers as text."""
    if not text or not text.strip():
        raise ValueError("The clipboard does not contain a table.")
    delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
    frame = pd.read_csv(StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    if frame.empty or not len(frame.columns):
        raise ValueError("The clipboard table has headers but no data rows.")
    return frame


class DataFrameModel(QAbstractTableModel):
    """Read-only, lazy Qt view over a DataFrame; no per-cell object cache."""

    def __init__(self, frame=None, parent=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()

    def set_frame(self, frame):
        self.beginResetModel()
        self.frame = frame
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        value = self.frame.iat[index.row(), index.column()]
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{value:.8g}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self.frame.columns[section])
        return str(section + 1)


class MatchingWindow(QMainWindow):
    """Build Preview or Final results from one row-aligned matching workbook."""

    def __init__(self, wafer_window_factory=None):
        super().__init__()
        self.setWindowTitle("Card Matching Workbook")
        fit_window_to_screen(self, (1520, 930), minimum=(1050, 700))
        apply_theme(self)
        self.reference_frame = pd.DataFrame()
        self.raw_frame = pd.DataFrame()
        self.preview_frame = pd.DataFrame()
        self.final_frame = pd.DataFrame()
        self.workbook = None
        self.result = None
        self._loading_input_sheets = False
        self._input_sheet_errors = {"reference": "", "raw": ""}
        self._wafer_window_factory = wafer_window_factory or self._default_wafer_window_factory
        self._stage_windows = []
        self.reference_model = SheetModel()
        self.raw_model = SheetModel()
        self.preview_model = DataFrameModel(parent=self)
        self.final_model = DataFrameModel(parent=self)
        self.summary_model = DataFrameModel(parent=self)
        self.wafer_summary_model = DataFrameModel(parent=self)
        self._build_ui()
        self.reference_model.changed.connect(
            lambda: self._input_sheet_changed("reference")
        )
        self.raw_model.changed.connect(lambda: self._input_sheet_changed("raw"))
        self._install_shortcuts()
        self._update_state()

    def _build_ui(self):
        root = QWidget(objectName="appRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 12, 20, 10)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = _label("Card Matching Workbook", "pageTitle")
        top.addWidget(title)
        top.addStretch()
        self.open_button = QPushButton("Open WKB", objectName="subtle")
        self.open_button.clicked.connect(self.open_wkb_dialog)
        self.save_button = QPushButton("Save WKB", objectName="subtle")
        self.save_button.clicked.connect(self.save_wkb_dialog)
        self.export_button = QPushButton("Export Excel", objectName="subtle")
        self.export_button.clicked.connect(self.export_excel_dialog)
        self.images_button = QPushButton("Save images", objectName="subtle")
        self.images_button.clicked.connect(self.save_images_dialog)
        top.addWidget(self.open_button)
        top.addWidget(self.save_button)
        top.addWidget(self.export_button)
        top.addWidget(self.images_button)
        layout.addLayout(top)

        self.tabs = QTabWidget(objectName="workspaceTabs")
        self.setup_page = self._build_setup_page()
        self.results_page = self._build_results_page()
        self.fullmap_page = self._build_fullmap_page()
        self.tabs.addTab(self.setup_page, "1. Setup")
        self.tabs.addTab(self.results_page, "2. Results")
        self.tabs.addTab(self.fullmap_page, "3. FullMap")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _install_shortcuts(self):
        for title, shortcut, handler in (
            ("Open WKB", "Ctrl+O", self.open_wkb_dialog),
            ("Save WKB", "Ctrl+S", self.save_wkb_dialog),
            ("Run analysis", "Ctrl+Return", self._run_analysis_clicked),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            self.addAction(action)

    def _build_setup_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        config = QFrame(objectName="panel")
        grid = QGridLayout(config)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.addWidget(_label("MATCH TYPE", "sectionTitle"), 0, 0)
        self.match_type = QComboBox()
        self.match_type.addItems(["KLA", "NOVA", "TEM"])
        grid.addWidget(self.match_type, 1, 0)
        grid.addWidget(_label("RESULT", "sectionTitle"), 0, 1)
        self.result_mode = QComboBox()
        self.result_mode.addItems(["Preview", "Final"])
        grid.addWidget(self.result_mode, 1, 1)
        grid.addWidget(_label("BIAS", "sectionTitle"), 0, 2)
        self.bias_mode = QComboBox()
        self.bias_mode.addItems(["Absolute", "Percent"])
        grid.addWidget(self.bias_mode, 1, 2)
        self.match_type.currentTextChanged.connect(self._invalidate_analysis)
        self.result_mode.currentTextChanged.connect(self._invalidate_analysis)
        self.bias_mode.currentTextChanged.connect(self._invalidate_analysis)
        grid.setColumnStretch(3, 1)
        self.status = _label("Paste a Reference table to begin.", "hint")
        grid.addWidget(self.status, 0, 4, 2, 1)
        layout.addWidget(config)

        inputs = QSplitter(Qt.Orientation.Horizontal)
        reference_card, self.reference_view, self.reference_source, self.reference_paste_button = self._table_card(
            "Reference", "Paste the prepared table first.", self.reference_model, self.paste_reference
        )
        raw_card, self.raw_view, self.raw_source, self.raw_paste_button = self._table_card(
            "Raw Data", "Rows are matched to Reference from top to bottom.", self.raw_model, self.paste_raw
        )
        inputs.addWidget(reference_card)
        inputs.addWidget(raw_card)
        inputs.setSizes([720, 720])
        inputs.setChildrenCollapsible(False)
        layout.addWidget(inputs, 3)

        mapping_card = QFrame(objectName="panel")
        mapping_layout = QVBoxLayout(mapping_card)
        mapping_layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(_label("Parameter mapping", "panelTitle"))
        heading.addWidget(_label(
            "Numeric Reference columns are listed; “Reference” suffix columns pair by name.",
            "hint",
        ))
        heading.addStretch()
        self.analyze_button = QPushButton("Run analysis", objectName="primary")
        self.analyze_button.clicked.connect(self._run_analysis_clicked)
        heading.addWidget(self.analyze_button)
        mapping_layout.addLayout(heading)
        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setHorizontalHeaderLabels(["Use", "Parameter", "Reference column", "Raw Data column"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.itemChanged.connect(self._invalidate_analysis)
        mapping_layout.addWidget(self.mapping_table, 1)
        layout.addWidget(mapping_card, 2)
        return page

    def _table_card(self, title, subtitle, model, paste_handler, paste_text=None):
        card = QFrame(objectName="sheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(_label(title, "panelTitle"))
        heading.addWidget(_label(subtitle, "hint"))
        heading.addStretch()
        paste = QPushButton(paste_text or f"Paste {title}", objectName="subtle")
        paste.clicked.connect(paste_handler)
        heading.addWidget(paste)
        layout.addLayout(heading)
        if isinstance(model, SheetModel):
            view = SheetView(model)
        else:
            view = QTableView()
            view.setModel(model)
            view.setAlternatingRowColors(True)
            view.setWordWrap(False)
            view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
            view.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
            view.horizontalHeader().setDefaultSectionSize(140)
        layout.addWidget(view, 1)
        footer = QHBoxLayout()
        source = _label("No data", "hint")
        footer.addWidget(source)
        footer.addStretch()
        if isinstance(model, SheetModel):
            footer.addWidget(_label("Row 1 = headers · Ctrl+V paste · Ctrl+Z undo", "hint"))
        layout.addLayout(footer)
        return card, view, source, paste

    def _build_fullmap_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        intro = QFrame(objectName="panel")
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(18, 14, 18, 14)
        intro_layout.addWidget(_label("FULLMAP STAGES", "sectionTitle"))
        intro_layout.addWidget(_label(
            "Preview applies the fitted Card to new FullMap Raw Data. "
            "Final uses OCD output directly and never applies Card again.",
            "hint",
        ))
        layout.addWidget(intro)

        inputs = QSplitter(Qt.Orientation.Horizontal)
        preview_card, self.preview_view, self.preview_source, self.preview_paste_button = self._table_card(
            "Preview FullMap",
            "For TEM, paste the later FullMap run here.",
            self.preview_model,
            self.paste_preview,
            "Paste data",
        )
        final_card, self.final_view, self.final_source, self.final_paste_button = self._table_card(
            "Final Raw Data",
            "Paste OCD output that already contains the approved Card.",
            self.final_model,
            self.paste_final,
            "Paste data",
        )
        inputs.addWidget(preview_card)
        inputs.addWidget(final_card)
        inputs.setSizes([720, 720])
        inputs.setChildrenCollapsible(False)
        layout.addWidget(inputs, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.preview_open_button = QPushButton("Open Preview Wafer Map / Radius", objectName="primary")
        self.preview_open_button.clicked.connect(lambda: self._open_stage_clicked("preview"))
        self.final_open_button = QPushButton("Open Final Wafer Map / Radius", objectName="primary")
        self.final_open_button.clicked.connect(lambda: self._open_stage_clicked("final"))
        actions.addWidget(self.preview_open_button)
        actions.addWidget(self.final_open_button)
        layout.addLayout(actions)
        return page

    def _build_results_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.addWidget(_label("Parameter", "sectionTitle"))
        self.parameter_picker = QComboBox()
        self.parameter_picker.currentTextChanged.connect(self._draw_parameter)
        controls.addWidget(self.parameter_picker)
        self.linear_fit = QCheckBox("Show linear fit")
        self.linear_fit.setChecked(True)
        self.linear_fit.toggled.connect(self._draw_parameter)
        controls.addWidget(self.linear_fit)
        controls.addStretch()
        self.result_status = _label("Run an analysis to see results.", "hint")
        controls.addWidget(self.result_status)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.summary_view = QTableView()
        self.summary_view.setModel(self.summary_model)
        self.summary_view.setAlternatingRowColors(True)
        self.summary_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.summary_view.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.summary_view)

        self.result_plots = QTabWidget()
        self.match_plot = self._plot_widget("Raw Data", "Reference")
        self.trend_plot = self._plot_widget("Row", "Value")
        self.bias_plot = self._plot_widget("Row", "Bias")
        self.result_plots.addTab(self.match_plot, "Match")
        self.result_plots.addTab(self.trend_plot, "Trend")
        self.result_plots.addTab(self.bias_plot, "Bias")

        wafer_page = QWidget()
        wafer_layout = QVBoxLayout(wafer_page)
        wafer_layout.setContentsMargins(4, 4, 4, 4)
        self.wafer_summary_view = QTableView()
        self.wafer_summary_view.setModel(self.wafer_summary_model)
        self.wafer_summary_view.setMaximumHeight(190)
        self.wafer_summary_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        wafer_layout.addWidget(self.wafer_summary_view)
        wafer_plots = QSplitter(Qt.Orientation.Horizontal)
        self.wafer_r2_plot = self._plot_widget("Wafer", "R²")
        self.wafer_slope_plot = self._plot_widget("Wafer", "Slope")
        wafer_plots.addWidget(self.wafer_r2_plot)
        wafer_plots.addWidget(self.wafer_slope_plot)
        wafer_layout.addWidget(wafer_plots, 1)
        self.wafer_tab_index = self.result_plots.addTab(wafer_page, "Single-wafer metrics")
        splitter.addWidget(self.result_plots)
        splitter.setSizes([220, 560])
        layout.addWidget(splitter, 1)
        return page

    @staticmethod
    def _plot_widget(bottom, left):
        plot = pg.PlotWidget(background=None)
        plot.showGrid(x=True, y=True, alpha=0.18)
        plot.setLabel("bottom", bottom)
        plot.setLabel("left", left)
        plot.getPlotItem().showAxis("right")
        plot.getPlotItem().getAxis("right").setStyle(showValues=False)
        return plot

    def paste_reference(self):
        try:
            self.set_reference_frame(clipboard_frame(QApplication.clipboard().text()), "Clipboard")
        except Exception as error:
            QMessageBox.warning(self, "Reference", str(error))

    def paste_raw(self):
        try:
            self.set_raw_frame(clipboard_frame(QApplication.clipboard().text()), "Clipboard")
        except Exception as error:
            QMessageBox.warning(self, "Raw Data", str(error))

    def paste_preview(self):
        try:
            self.set_preview_frame(
                clipboard_frame(QApplication.clipboard().text()),
                "Clipboard",
            )
        except Exception as error:
            QMessageBox.warning(self, "Preview FullMap", str(error))

    def paste_final(self):
        try:
            self.set_final_frame(
                clipboard_frame(QApplication.clipboard().text()),
                "Clipboard",
            )
        except Exception as error:
            QMessageBox.warning(self, "Final Raw Data", str(error))

    def set_reference_frame(self, frame, source="Reference"):
        self._validate_input_frame(frame, "Reference")
        self.reference_frame = frame.reset_index(drop=True)
        self._load_input_sheet(self.reference_model, self.reference_frame)
        self._input_sheet_errors["reference"] = ""
        self.reference_source.setText(self._source_text(source, self.reference_frame))
        self.raw_frame = pd.DataFrame()
        self._load_input_sheet(self.raw_model, self.raw_frame)
        self._input_sheet_errors["raw"] = ""
        self.raw_source.setText("No data")
        self._clear_stage_frames()
        self._populate_mappings()
        self._invalidate_analysis()

    def set_raw_frame(self, frame, source="Raw Data"):
        if self.reference_frame.empty:
            raise ValueError("Paste the Reference table before Raw Data.")
        self._validate_input_frame(frame, "Raw Data")
        self.raw_frame = frame.reset_index(drop=True)
        self._load_input_sheet(self.raw_model, self.raw_frame)
        self._input_sheet_errors["raw"] = ""
        self.raw_source.setText(self._source_text(source, self.raw_frame))
        self._clear_stage_frames()
        self._populate_mappings()
        self._invalidate_analysis()

    def _load_input_sheet(self, model, frame):
        self._loading_input_sheets = True
        try:
            model.load(frame)
        finally:
            self._loading_input_sheets = False

    def _input_sheet_changed(self, name):
        """Synchronize an editable grid with the matching domain frames."""
        if self._loading_input_sheets:
            return
        model = self.reference_model if name == "reference" else self.raw_model
        title = "Reference" if name == "reference" else "Raw Data"
        try:
            frame = model.frame().reset_index(drop=True)
            if not frame.empty:
                self._validate_input_frame(frame, title)
            error = ""
        except ValueError as exc:
            frame = pd.DataFrame()
            error = str(exc)
        self._input_sheet_errors[name] = error
        if name == "reference":
            self.reference_frame = frame
            source = self.reference_source
        else:
            self.raw_frame = frame
            source = self.raw_source
        source.setText(
            f"Fix table · {error}" if error
            else ("No data" if frame.empty else self._source_text("Edited", frame))
        )
        selected = self._valid_selected_mappings()
        self._populate_mappings(selected)
        self._invalidate_analysis()

    def _valid_selected_mappings(self):
        """Return complete checked mappings without rejecting an in-progress edit."""
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            use = self.mapping_table.item(row, 0)
            name = self.mapping_table.item(row, 1)
            reference = self.mapping_table.item(row, 2)
            picker = self.mapping_table.cellWidget(row, 3)
            if (
                use is not None
                and use.checkState() == Qt.CheckState.Checked
                and name is not None
                and reference is not None
                and picker is not None
                and name.text().strip()
                and picker.currentText()
            ):
                mappings.append(ParameterMapping(
                    name.text().strip(), reference.text(), picker.currentText()
                ))
        return tuple(mappings)

    def _clear_stage_frames(self):
        self.preview_frame = pd.DataFrame()
        self.final_frame = pd.DataFrame()
        self.preview_model.set_frame(self.preview_frame)
        self.final_model.set_frame(self.final_frame)
        self.preview_source.setText("No data")
        self.final_source.setText("No data")

    def set_preview_frame(self, frame, source="Preview FullMap"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Preview FullMap.")
        self._validate_input_frame(frame, "Preview FullMap")
        self.preview_frame = frame.reset_index(drop=True)
        self.preview_model.set_frame(self.preview_frame)
        self.preview_source.setText(self._source_text(source, self.preview_frame))
        self._update_state()

    def set_final_frame(self, frame, source="Final Raw Data"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Final Raw Data.")
        self._validate_input_frame(frame, "Final Raw Data")
        self.final_frame = frame.reset_index(drop=True)
        self.final_model.set_frame(self.final_frame)
        self.final_source.setText(self._source_text(source, self.final_frame))
        self._update_state()

    @staticmethod
    def _validate_input_frame(frame, name):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"{name} must contain headers and at least one data row.")
        if len(frame) > MAX_ROWS:
            raise ValueError(f"{name} supports at most {MAX_ROWS:,} rows.")
        if not frame.columns.is_unique:
            raise ValueError(f"{name} column names must be unique.")

    @staticmethod
    def _source_text(source, frame):
        return f"{source} · {len(frame):,} rows × {len(frame.columns)} columns"

    def _populate_mappings(self, selected=None):
        selected = tuple(selected or ())
        selected_by_reference = {mapping.reference_column: mapping for mapping in selected}
        suggestions = MatchWorkbook.suggest_mappings(self.reference_frame, self.raw_frame)
        suggestion_by_reference = {mapping.reference_column: mapping for mapping in suggestions}
        numeric_columns = set(inspect_table(self.reference_frame)[2])
        reference_columns = [
            str(column)
            for column in self.reference_frame.columns
            if column in numeric_columns
            or str(column).strip().lower().endswith(" reference")
        ]
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(reference_columns))
        for row, reference_column in enumerate(reference_columns):
            mapping = selected_by_reference.get(reference_column) or suggestion_by_reference.get(reference_column)
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            use.setCheckState(Qt.CheckState.Checked if mapping else Qt.CheckState.Unchecked)
            self.mapping_table.setItem(row, 0, use)
            default_name = (
                reference_column[:-len(" Reference")].strip()
                if reference_column.strip().lower().endswith(" reference")
                else reference_column.strip()
            )
            self.mapping_table.setItem(row, 1, QTableWidgetItem(mapping.name if mapping else default_name))
            reference_item = QTableWidgetItem(reference_column)
            reference_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.mapping_table.setItem(row, 2, reference_item)
            raw_picker = QComboBox()
            raw_picker.addItem("")
            raw_picker.addItems([str(column) for column in self.raw_frame.columns])
            if mapping:
                raw_picker.setCurrentText(mapping.raw_column)
            raw_picker.currentTextChanged.connect(self._invalidate_analysis)
            self.mapping_table.setCellWidget(row, 3, raw_picker)
        self.mapping_table.blockSignals(False)

    def selected_mappings(self):
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            use = self.mapping_table.item(row, 0)
            if use is None or use.checkState() != Qt.CheckState.Checked:
                continue
            name = self.mapping_table.item(row, 1).text().strip()
            reference_column = self.mapping_table.item(row, 2).text()
            raw_column = self.mapping_table.cellWidget(row, 3).currentText()
            if not raw_column:
                raise ValueError(f"Choose a Raw Data column for {reference_column}.")
            mappings.append(ParameterMapping(name, reference_column, raw_column))
        if not mappings:
            raise ValueError("Select at least one parameter mapping.")
        return tuple(mappings)

    def _invalidate_analysis(self, *_):
        if self.result is None and self.workbook is None:
            self._update_state()
            return
        self.result = None
        self.workbook = None
        self.summary_model.set_frame(pd.DataFrame())
        self.wafer_summary_model.set_frame(pd.DataFrame())
        self.parameter_picker.clear()
        for plot in (self.match_plot, self.trend_plot, self.bias_plot,
                     self.wafer_r2_plot, self.wafer_slope_plot):
            plot.clear()
        self.result_status.setText("Settings changed. Run the analysis again.")
        self.tabs.setCurrentWidget(self.setup_page)
        self._update_state()
    def _update_state(self, *_):
        has_reference = not self.reference_frame.empty
        has_raw = not self.raw_frame.empty
        self.raw_paste_button.setEnabled(has_reference)
        self.raw_view.setEnabled(has_reference)
        self.preview_paste_button.setEnabled(has_raw)
        self.final_paste_button.setEnabled(has_raw)
        valid_rows = has_reference and has_raw and len(self.reference_frame) == len(self.raw_frame)
        has_mapping = False
        if valid_rows:
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, 0)
                picker = self.mapping_table.cellWidget(row, 3)
                if item and item.checkState() == Qt.CheckState.Checked and picker and picker.currentText():
                    has_mapping = True
                    break
        self.analyze_button.setEnabled(bool(valid_rows and has_mapping))
        self.save_button.setEnabled(bool(valid_rows and has_mapping))
        self.export_button.setEnabled(self.result is not None)
        self.images_button.setEnabled(self.result is not None)
        preview_ready = (
            self.result is not None
            and (self.match_type.currentText() != "TEM" or not self.preview_frame.empty)
        )
        self.preview_open_button.setEnabled(preview_ready)
        self.final_open_button.setEnabled(
            self.result is not None and not self.final_frame.empty
        )
        input_error = self._input_sheet_errors["reference"] or self._input_sheet_errors["raw"]
        if input_error:
            message = input_error
        elif not has_reference:
            message = "Paste a Reference table to begin."
        elif not has_raw:
            message = "Reference loaded. Paste the row-aligned Raw Data."
        elif len(self.reference_frame) != len(self.raw_frame):
            message = (f"Row count differs: Reference {len(self.reference_frame):,}; "
                       f"Raw Data {len(self.raw_frame):,}.")
        elif not has_mapping:
            message = "Select at least one valid parameter mapping."
        else:
            message = "Ready to run. Rows will be matched from top to bottom."
        self.status.setText(message)

    def current_workbook(self):
        return MatchWorkbook(
            reference=self.reference_frame,
            raw=self.raw_frame,
            mappings=self.selected_mappings(),
            match_type=self.match_type.currentText(),
            result_mode=self.result_mode.currentText().lower(),
            bias_mode=self.bias_mode.currentText().lower(),
            preview_raw=None if self.preview_frame.empty else self.preview_frame,
            final_raw=None if self.final_frame.empty else self.final_frame,
        )

    @staticmethod
    def _default_wafer_window_factory():
        from .window import MainWindow
        return MainWindow()

    def open_stage_workspace(self, stage):
        if self.result is None:
            self.run_analysis()
        self.workbook = self.current_workbook()
        frame = self.workbook.stage_frame(stage)
        workspace = self._wafer_window_factory()
        title = f"{str(stage).title()} · Card Matching Workbook"
        workspace.set_table(frame, title)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{str(stage).title()} Wafer Map / Radius")
        self._stage_windows.append(workspace)
        if hasattr(workspace, "destroyed"):
            workspace.destroyed.connect(
                lambda *_args, window=workspace: self._forget_stage_workspace(window)
            )
        workspace.show()
        return workspace

    def _forget_stage_workspace(self, workspace):
        if workspace in self._stage_windows:
            self._stage_windows.remove(workspace)

    def _open_stage_clicked(self, stage):
        try:
            self.open_stage_workspace(stage)
        except Exception as error:
            QMessageBox.warning(self, f"Cannot open {stage.title()}", str(error))

    def run_analysis(self):
        self.workbook = self.current_workbook()
        self.result = self.workbook.analyze()
        self.summary_model.set_frame(self.result.summary)
        self.parameter_picker.blockSignals(True)
        self.parameter_picker.clear()
        self.parameter_picker.addItems(list(self.result.parameter_names))
        self.parameter_picker.blockSignals(False)
        self._result_descriptor = (
            f"{self.workbook.match_type} · {self.workbook.result_mode.title()} · "
            f"{len(self.result.parameter_names)} parameters"
        )
        self.result_status.setText(self._result_descriptor)
        self._draw_parameter()
        self.tabs.setCurrentWidget(self.results_page)
        self._update_state()
        return self.result

    def _run_analysis_clicked(self):
        try:
            self.run_analysis()
        except Exception as error:
            QMessageBox.warning(self, "Cannot run analysis", str(error))

    def _draw_parameter(self, *_):
        if self.result is None or not self.parameter_picker.currentText():
            return
        parameter = self.parameter_picker.currentText()
        data = self.result.series(parameter)
        card = self.result.card(parameter)
        reference_all = data["Reference"].to_numpy(float)
        raw_all = data["Raw"].to_numpy(float)
        evaluated_all = data["Evaluated Value"].to_numpy(float)
        bias_all = data["Selected Bias"].to_numpy(float)
        indices = extrema_sample_indices(
            reference_all, raw_all, evaluated_all, bias_all, limit=PLOT_LIMIT
        )
        row = np.arange(1, len(data) + 1, dtype=float)[indices]
        reference = reference_all[indices]
        raw = raw_all[indices]
        evaluated = evaluated_all[indices]
        bias = bias_all[indices]
        display_note = ""
        if len(indices) < len(data):
            display_note = f" · display {len(indices):,}/{len(data):,}; calculations use all rows"
        descriptor = getattr(self, "_result_descriptor", "")
        self.result_status.setText(descriptor + display_note)

        self.match_plot.clear()
        self.match_plot.addLegend(offset=(12, 12))
        valid = np.isfinite(raw) & np.isfinite(reference)
        self.match_plot.plot(raw[valid], reference[valid], pen=None, symbol="o", symbolSize=5,
                             symbolBrush="#4f8bd6", symbolPen=None, name="Rows")
        if self.linear_fit.isChecked() and valid.any():
            low, high = float(np.min(raw[valid])), float(np.max(raw[valid]))
            x_line = np.array([low, high])
            self.match_plot.plot(x_line, card.slope * x_line + card.intercept,
                                 pen=pg.mkPen("#e09f3e", width=2), name="Linear fit")
        self.match_plot.setTitle(f"{parameter} · R² {card.r_squared:.6g}{display_note}")

        self.trend_plot.clear()
        self.trend_plot.addLegend(offset=(12, 12))
        self.trend_plot.plot(row, reference, pen=pg.mkPen("#8a8f98", width=1.5, style=Qt.PenStyle.DashLine), name="Reference")
        self.trend_plot.plot(row, evaluated, pen=pg.mkPen("#4f8bd6", width=1.5), name=self.workbook.result_mode.title())
        self.trend_plot.setTitle(f"{parameter} trend{display_note}")

        self.bias_plot.clear()
        self.bias_plot.plot(row, bias, pen=pg.mkPen("#4f8bd6", width=1.3))
        self.bias_plot.addLine(y=0, pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine))
        unit = "%" if self.workbook.bias_mode == "percent" else ""
        self.bias_plot.setLabel("left", f"Bias {unit}".strip())
        self.bias_plot.setTitle(f"{parameter} bias{display_note}")
        self._draw_wafer_metrics(parameter)

    def _draw_wafer_metrics(self, parameter):
        enabled = self.workbook.match_type in {"NOVA", "KLA"}
        if not enabled:
            self.wafer_summary_model.set_frame(pd.DataFrame())
            self.wafer_r2_plot.clear()
            self.wafer_slope_plot.clear()
            self.result_plots.setTabEnabled(self.wafer_tab_index, False)
            return
        try:
            summary = self.result.wafer_summary(parameter)
        except ValueError:
            summary = pd.DataFrame()
            enabled = False
        self.result_plots.setTabEnabled(self.wafer_tab_index, enabled)
        self.wafer_summary_model.set_frame(summary)
        self.wafer_r2_plot.clear()
        self.wafer_slope_plot.clear()
        if summary.empty:
            return
        x = np.arange(len(summary), dtype=float)
        labels = [(int(index), str(wafer)) for index, wafer in enumerate(summary["Wafer"])]
        self.wafer_r2_plot.getAxis("bottom").setTicks([labels])
        self.wafer_slope_plot.getAxis("bottom").setTicks([labels])
        r_squared = summary["R²"].to_numpy(float)
        slope = summary["Slope"].to_numpy(float)
        valid_r2 = np.isfinite(r_squared)
        valid_slope = np.isfinite(slope)
        if valid_r2.any():
            self.wafer_r2_plot.plot(x[valid_r2], r_squared[valid_r2], pen=None,
                                    symbol="o", symbolSize=8, symbolBrush="#4f8bd6")
        if valid_slope.any():
            self.wafer_slope_plot.plot(x[valid_slope], slope[valid_slope], pen=None,
                                       symbol="o", symbolSize=8, symbolBrush="#e09f3e")
        self.wafer_r2_plot.setTitle(f"{parameter} · single-wafer R²")
        self.wafer_slope_plot.setTitle(f"{parameter} · single-wafer slope")

    def export_excel(self, path):
        """Export an optional human-readable workbook; WKB remains the primary store."""
        if self.result is None:
            self.run_analysis()
        else:
            self.workbook = self.current_workbook()
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        derived = {}
        for parameter in self.result.parameter_names:
            series = self.result.series(parameter)
            for column in ("Card Value", "Evaluated Value", "Bias", "Bias %"):
                derived[f"{parameter} | {column}"] = series[column].to_numpy()
        result_frame = pd.DataFrame(derived)
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            self.result.summary.to_excel(writer, sheet_name="Summary", index=False)
            self.reference_frame.to_excel(writer, sheet_name="Reference", index=False)
            self.raw_frame.to_excel(writer, sheet_name="Raw Data", index=False)
            result_frame.to_excel(writer, sheet_name=self.workbook.result_mode.title(), index=False)
            if self.workbook.preview_raw is not None:
                self.workbook.stage_frame("preview").to_excel(
                    writer, sheet_name="Preview FullMap", index=False
                )
            if self.workbook.final_raw is not None:
                self.workbook.stage_frame("final").to_excel(
                    writer, sheet_name="Final FullMap", index=False
                )
        self.result_status.setText(f"Exported {target.name}")
        return target

    def export_excel_dialog(self):
        try:
            default = str(Path.home() / f"matching-{self.workbook.result_mode if self.workbook else 'result'}.xlsx")
            path, _ = QFileDialog.getSaveFileName(self, "Export Excel", default, "Excel Workbook (*.xlsx)")
            if path:
                self.export_excel(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot export Excel", str(error))

    def save_plot_images(self, folder):
        """Save separate PNG files for every selected parameter and plot type."""
        if self.result is None:
            self.run_analysis()
        else:
            self.workbook = self.current_workbook()
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        original = self.parameter_picker.currentText()
        saved = []
        plot_specs = [
            ("match", self.match_plot),
            ("trend", self.trend_plot),
            ("bias", self.bias_plot),
        ]
        if self.workbook.match_type in {"NOVA", "KLA"}:
            plot_specs.extend([
                ("single-wafer-r2", self.wafer_r2_plot),
                ("single-wafer-slope", self.wafer_slope_plot),
            ])
        for parameter in self.result.parameter_names:
            self.parameter_picker.setCurrentText(parameter)
            QApplication.processEvents()
            safe_parameter = _safe_filename(parameter)
            for suffix, widget in plot_specs:
                output = target / f"{safe_parameter}-{suffix}.png"
                exporter = pg.exporters.ImageExporter(widget.getPlotItem())
                exporter.parameters()["width"] = 1600
                exporter.export(str(output))
                saved.append(output)
        if original:
            self.parameter_picker.setCurrentText(original)
        self.result_status.setText(f"Saved {len(saved)} plot images")
        return tuple(saved)

    def save_images_dialog(self):
        try:
            folder = QFileDialog.getExistingDirectory(self, "Save plot images")
            if folder:
                self.save_plot_images(folder)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save images", str(error))
    def save_workbook(self, path):
        workbook = self.current_workbook()
        saved = workbook.save(path)
        self.workbook = workbook
        self.status.setText(f"Saved {saved.name}")
        return saved

    def save_wkb_dialog(self):
        try:
            default = str(Path.home() / "matching-analysis.wkb")
            path, _ = QFileDialog.getSaveFileName(self, "Save Matching Workbook", default,
                                                  "Matching Workbook (*.wkb)")
            if path:
                self.save_workbook(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save WKB", str(error))

    def load_workbook(self, path):
        workbook = MatchWorkbook.load(path)
        self.reference_frame = workbook.reference
        self.raw_frame = workbook.raw
        self.preview_frame = (
            pd.DataFrame() if workbook.preview_raw is None else workbook.preview_raw
        )
        self.final_frame = (
            pd.DataFrame() if workbook.final_raw is None else workbook.final_raw
        )
        self._load_input_sheet(self.reference_model, self.reference_frame)
        self._load_input_sheet(self.raw_model, self.raw_frame)
        self._input_sheet_errors = {"reference": "", "raw": ""}
        self.preview_model.set_frame(self.preview_frame)
        self.final_model.set_frame(self.final_frame)
        self.reference_source.setText(self._source_text(Path(path).name, self.reference_frame))
        self.raw_source.setText(self._source_text(Path(path).name, self.raw_frame))
        self.preview_source.setText(
            "No data" if self.preview_frame.empty
            else self._source_text(Path(path).name, self.preview_frame)
        )
        self.final_source.setText(
            "No data" if self.final_frame.empty
            else self._source_text(Path(path).name, self.final_frame)
        )
        self.match_type.setCurrentText(workbook.match_type)
        self.result_mode.setCurrentText(workbook.result_mode.title())
        self.bias_mode.setCurrentText(workbook.bias_mode.title())
        self._populate_mappings(workbook.mappings)
        self._update_state()
        self.workbook = workbook
        self.result = workbook.analyze()
        self._result_descriptor = (
            f"{workbook.match_type} · {workbook.result_mode.title()} · "
            f"{len(self.result.parameter_names)} parameters"
        )
        self.result_status.setText(self._result_descriptor)
        self.summary_model.set_frame(self.result.summary)
        self.parameter_picker.blockSignals(True)
        self.parameter_picker.clear()
        self.parameter_picker.addItems(list(self.result.parameter_names))
        self.parameter_picker.blockSignals(False)
        self._draw_parameter()
        self.tabs.setCurrentWidget(self.results_page)
        self._update_state()
        return workbook

    def open_wkb_dialog(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "Open Matching Workbook", "",
                                                  "Matching Workbook (*.wkb)")
            if path:
                self.load_workbook(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot open WKB", str(error))


def _safe_filename(value):
    safe = "".join(character if character.isalnum() or character in "-_" else "-"
                   for character in str(value).strip())
    return safe.strip("-") or "parameter"



__all__ = ["DataFrameModel", "MatchingWindow", "clipboard_frame"]

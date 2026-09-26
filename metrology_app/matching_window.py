"""Qt workspace for multi-parameter Reference/Raw card matching."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
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
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
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
        self.setWindowTitle("Match Workbook")
        fit_window_to_screen(self, (1520, 930), minimum=(1050, 700))
        apply_theme(self)
        self.reference_frame = pd.DataFrame()
        self.raw_frame = pd.DataFrame()
        self.preview_frame = pd.DataFrame()
        self.final_frame = pd.DataFrame()
        self.workbook = None
        self.result = None
        self._primary_bias_mode = "absolute"
        self._auto_run_enabled = False
        self._auto_run_pending = False
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
        self.raw_view.table_pasted.connect(self._raw_table_pasted)
        self._install_shortcuts()
        self._update_state()

    def _build_ui(self):
        root = QWidget(objectName="appRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.title_label = _label("Match Workbook", "panelTitle")
        top.addWidget(self.title_label)
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

        self.result_mode = QComboBox(self)
        self.result_mode.addItems(["Preview", "Final"])
        self.result_mode.hide()

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_tabs = QTabBar()
        self.mode_tabs.setObjectName("workspaceModeTabs")
        self.mode_tabs.setExpanding(False)
        self.mode_tabs.addTab("Preview")
        self.mode_tabs.addTab("Final")
        mode_row.addWidget(self.mode_tabs)
        mode_row.addStretch()
        self.preview_open_button = QPushButton(
            "Open Preview Wafer Map / Radius", objectName="primary"
        )
        self.preview_open_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.preview_open_button.clicked.connect(
            lambda: self._open_stage_clicked("preview")
        )
        self.final_open_button = QPushButton(
            "Open Final Wafer Map / Radius", objectName="primary"
        )
        self.final_open_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.final_open_button.clicked.connect(
            lambda: self._open_stage_clicked("final")
        )
        mode_row.addWidget(self.preview_open_button)
        mode_row.addWidget(self.final_open_button)
        layout.addLayout(mode_row)

        self.setup_page = self._build_setup_page()
        layout.addWidget(self.setup_page, 1)
        self.setCentralWidget(root)
        self.mode_tabs.currentChanged.connect(self._mode_tab_changed)
        self.result_mode.currentIndexChanged.connect(self._result_mode_changed)
        self._update_mode_actions()

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

    def _mode_tab_changed(self, index):
        if index >= 0 and self.result_mode.currentIndex() != index:
            self.result_mode.setCurrentIndex(index)
        self._update_mode_actions()

    def _result_mode_changed(self, index):
        if index >= 0 and self.mode_tabs.currentIndex() != index:
            self.mode_tabs.setCurrentIndex(index)
        self._update_mode_actions()

    def _update_mode_actions(self):
        preview = self.result_mode.currentText().lower() == "preview"
        self.preview_open_button.setVisible(preview)
        self.final_open_button.setVisible(not preview)

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
        grid.addWidget(_label("BIAS", "sectionTitle"), 0, 1)
        bias_options = QWidget()
        bias_layout = QHBoxLayout(bias_options)
        bias_layout.setContentsMargins(0, 0, 0, 0)
        bias_layout.setSpacing(12)
        self.absolute_bias = QCheckBox("Bias")
        self.absolute_bias.setChecked(True)
        self.percent_bias = QCheckBox("Bias %")
        bias_layout.addWidget(self.absolute_bias)
        bias_layout.addWidget(self.percent_bias)
        grid.addWidget(bias_options, 1, 1)
        self.match_type.currentTextChanged.connect(self._invalidate_analysis)
        self.result_mode.currentTextChanged.connect(self._invalidate_analysis)
        grid.setColumnStretch(2, 1)
        self.status = _label("Paste a Reference table to begin.", "hint")
        grid.addWidget(self.status, 0, 3, 2, 1)
        layout.addWidget(config)

        inputs = QSplitter(Qt.Orientation.Horizontal)
        reference_card, self.reference_view, self.reference_source = self._table_card(
            "Reference", "Paste the prepared table first.", self.reference_model
        )
        raw_card, self.raw_view, self.raw_source = self._table_card(
            "Raw Data", "Rows are matched to Reference from top to bottom.", self.raw_model
        )
        inputs.addWidget(reference_card)
        inputs.addWidget(raw_card)
        inputs.setSizes([720, 720])
        inputs.setChildrenCollapsible(False)
        for card in (reference_card, raw_card):
            card.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
            )
        inputs.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
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
        self.mapping_table = QTableWidget(0, 10)
        self.mapping_table.setHorizontalHeaderLabels([
            "Use", "Parameter", "Reference column", "Raw Data column",
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode",
        ])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((52, 150, 180, 210, 100, 100, 90, 95, 100, 105)):
            self.mapping_table.setColumnWidth(column, width)
        self.mapping_table.itemChanged.connect(self._invalidate_analysis)
        mapping_layout.addWidget(self.mapping_table, 1)
        mapping_card.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )

        self.results_panel = self._build_results_panel()
        self.results_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self.setup_splitter = QSplitter(Qt.Orientation.Vertical)
        self.setup_splitter.setChildrenCollapsible(False)
        self.setup_splitter.setHandleWidth(10)
        self.setup_splitter.addWidget(inputs)
        self.setup_splitter.addWidget(mapping_card)
        self.setup_splitter.addWidget(self.results_panel)
        self.setup_splitter.setSizes([430, 190, 520])
        self.setup_splitter.setMinimumHeight(1120)

        self.setup_scroll = QScrollArea()
        self.setup_scroll.setObjectName("matchingSetupScroll")
        self.setup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setWidget(self.setup_splitter)
        layout.addWidget(self.setup_scroll, 1)
        self.absolute_bias.toggled.connect(self._bias_view_changed)
        self.percent_bias.toggled.connect(self._bias_view_changed)
        self._update_bias_plot_visibility()
        return page

    def _table_card(self, title, subtitle, model):
        card = QFrame(objectName="sheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(_label(title, "panelTitle"))
        heading.addWidget(_label(subtitle, "hint"))
        heading.addStretch()
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
        return card, view, source

    def _build_results_panel(self):
        panel = QFrame(objectName="panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.addWidget(_label("Parameter", "sectionTitle"))
        self.parameter_picker = QComboBox()
        self.parameter_picker.currentTextChanged.connect(self._draw_parameter)
        controls.addWidget(self.parameter_picker)
        controls.addStretch()
        self.result_status = _label("Run an analysis to see results.", "hint")
        controls.addWidget(self.result_status)
        layout.addLayout(controls)

        self.primary_plot_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.primary_plot_splitter.setChildrenCollapsible(False)
        self.primary_plot_splitter.setHandleWidth(8)
        self.match_plot = self._plot_widget("Raw Data", "Reference")
        self.trend_plot = self._plot_widget("Row", "Value")
        self.bias_plot = self._plot_widget("Row", "Bias")
        self.bias_percent_plot = self._plot_widget("Row", "Bias %")
        for plot in (
            self.match_plot, self.trend_plot, self.bias_plot, self.bias_percent_plot
        ):
            plot.setMinimumWidth(220)
            self.primary_plot_splitter.addWidget(plot)
        self.primary_plot_splitter.setSizes([420, 420, 420, 420])
        self.primary_plot_splitter.setMinimumWidth(920)
        self.primary_plot_splitter.setMinimumHeight(390)
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setObjectName("matchingPlotScroll")
        self.plot_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.plot_scroll.setWidgetResizable(True)
        self.plot_scroll.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self.plot_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.plot_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.plot_scroll.setWidget(self.primary_plot_splitter)
        self.plot_scroll.setMinimumHeight(420)
        layout.addWidget(self.plot_scroll, 1)

        self.single_wafer_panel = QFrame(objectName="sheetCard")
        wafer_layout = QVBoxLayout(self.single_wafer_panel)
        wafer_layout.setContentsMargins(12, 10, 12, 10)
        wafer_layout.addWidget(_label("Single-wafer metrics", "panelTitle"))
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
        layout.addWidget(self.single_wafer_panel)
        self.single_wafer_panel.hide()
        panel.setMinimumHeight(520)
        return panel

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
        self._clear_stage_frames()
        selected = self._valid_selected_mappings()
        self._populate_mappings(selected)
        self._invalidate_analysis()

    def _raw_table_pasted(self):
        """Re-run a valid workbook after the user has opted in by running once."""
        if not self._auto_run_enabled or self._auto_run_pending:
            return
        self._auto_run_pending = True
        QTimer.singleShot(0, self._run_paste_analysis)

    def _run_paste_analysis(self):
        self._auto_run_pending = False
        if not self._auto_run_enabled or not self.analyze_button.isEnabled():
            return
        try:
            self.run_analysis()
        except Exception as error:
            self.status.setText(f"Automatic analysis could not run: {error}")

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

    def set_preview_frame(self, frame, source="Preview FullMap"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Preview FullMap.")
        self._validate_input_frame(frame, "Preview FullMap")
        self.preview_frame = frame.reset_index(drop=True)
        self.preview_model.set_frame(self.preview_frame)
        self._update_state()

    def set_final_frame(self, frame, source="Final Raw Data"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Final Raw Data.")
        self._validate_input_frame(frame, "Final Raw Data")
        self.final_frame = frame.reset_index(drop=True)
        self.final_model.set_frame(self.final_frame)
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
            for column in range(4, 10):
                result_item = QTableWidgetItem("")
                result_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self.mapping_table.setItem(row, column, result_item)
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

    def _selected_bias_views(self):
        views = []
        if self.absolute_bias.isChecked():
            views.append("absolute")
        if self.percent_bias.isChecked():
            views.append("percent")
        return tuple(views)

    def _bias_view_changed(self, checked):
        if not self._selected_bias_views():
            checkbox = self.sender()
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        views = self._selected_bias_views()
        if self._primary_bias_mode not in views:
            self._primary_bias_mode = views[0]
        self._update_bias_plot_visibility()
        if self.result is not None:
            self._draw_parameter()

    def _update_bias_plot_visibility(self):
        self.bias_plot.setVisible(self.absolute_bias.isChecked())
        self.bias_percent_plot.setVisible(self.percent_bias.isChecked())

    def _clear_mapping_results(self):
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            for column in range(4, 10):
                item = self.mapping_table.item(row, column)
                if item is not None:
                    item.setText("")
        self.mapping_table.blockSignals(False)

    def _show_mapping_results(self):
        if self.result is None:
            self._clear_mapping_results()
            return
        summaries = {
            str(row["Reference column"]): row
            for _, row in self.result.summary.iterrows()
        }
        fields = (
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode"
        )
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            reference_item = self.mapping_table.item(row, 2)
            summary = summaries.get(reference_item.text()) if reference_item else None
            for column, field in enumerate(fields, start=4):
                item = self.mapping_table.item(row, column)
                value = None if summary is None else summary[field]
                if value is None or pd.isna(value):
                    text = ""
                elif isinstance(value, (float, np.floating)):
                    text = f"{float(value):.8g}"
                else:
                    text = str(value)
                item.setText(text)
        self.mapping_table.blockSignals(False)

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
                     self.bias_percent_plot, self.wafer_r2_plot, self.wafer_slope_plot):
            plot.clear()
        self._clear_mapping_results()
        self.result_status.setText("Settings changed. Run the analysis again.")
        self._update_state()

    def _update_state(self, *_):
        has_reference = not self.reference_frame.empty
        has_raw = not self.raw_frame.empty
        self.raw_view.setEnabled(has_reference)
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
        self.preview_open_button.setEnabled(self.result is not None)
        self.final_open_button.setEnabled(self.result is not None)
        self._update_mode_actions()
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
            bias_mode=self._primary_bias_mode,
            bias_views=self._selected_bias_views(),
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
        title = f"{str(stage).title()} · Match Workbook"
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
        self._show_mapping_results()
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
        QTimer.singleShot(
            0, lambda: self.setup_scroll.ensureWidgetVisible(self.results_panel, 0, 24)
        )
        self._update_state()
        return self.result

    def _run_analysis_clicked(self):
        try:
            self.run_analysis()
            self._auto_run_enabled = True
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
        bias_all = data["Bias"].to_numpy(float)
        bias_percent_all = data["Bias %"].to_numpy(float)
        indices = extrema_sample_indices(
            reference_all, raw_all, evaluated_all, bias_all, bias_percent_all,
            limit=PLOT_LIMIT,
        )
        row = np.arange(1, len(data) + 1, dtype=float)[indices]
        reference = reference_all[indices]
        raw = raw_all[indices]
        evaluated = evaluated_all[indices]
        bias = bias_all[indices]
        bias_percent = bias_percent_all[indices]
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
        if valid.any():
            low, high = float(np.min(raw[valid])), float(np.max(raw[valid]))
            x_line = np.array([low, high])
            self.match_plot.plot(x_line, card.slope * x_line + card.intercept,
                                 pen=pg.mkPen("#e09f3e", width=2), name="Linear fit")
        self.match_plot.setTitle(
            f"Match · {parameter} · R² {card.r_squared:.6g}{display_note}"
        )

        self.trend_plot.clear()
        self.trend_plot.addLegend(offset=(12, 12))
        self.trend_plot.plot(row, reference, pen=pg.mkPen("#8a8f98", width=1.5, style=Qt.PenStyle.DashLine), name="Reference")
        self.trend_plot.plot(row, evaluated, pen=pg.mkPen("#4f8bd6", width=1.5), name=self.workbook.result_mode.title())
        self.trend_plot.setTitle(f"Trend · {parameter}{display_note}")

        self.bias_plot.clear()
        self.bias_plot.plot(row, bias, pen=pg.mkPen("#4f8bd6", width=1.3))
        self.bias_plot.addLine(y=0, pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine))
        self.bias_plot.setTitle(f"Bias · {parameter}{display_note}")

        self.bias_percent_plot.clear()
        self.bias_percent_plot.plot(
            row, bias_percent, pen=pg.mkPen("#4f8bd6", width=1.3)
        )
        self.bias_percent_plot.addLine(
            y=0, pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine)
        )
        self.bias_percent_plot.setTitle(f"Bias % · {parameter}{display_note}")
        self._update_bias_plot_visibility()
        self._draw_wafer_metrics(parameter)

    def _draw_wafer_metrics(self, parameter):
        enabled = self.workbook.match_type in {"NOVA", "KLA"}
        if not enabled:
            self.wafer_summary_model.set_frame(pd.DataFrame())
            self.wafer_r2_plot.clear()
            self.wafer_slope_plot.clear()
            self.single_wafer_panel.hide()
            return
        try:
            summary = self.result.wafer_summary(parameter)
        except ValueError:
            summary = pd.DataFrame()
            enabled = False
        self.single_wafer_panel.setVisible(enabled)
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
        ]
        if self.absolute_bias.isChecked():
            plot_specs.append(("bias", self.bias_plot))
        if self.percent_bias.isChecked():
            plot_specs.append(("bias-percent", self.bias_percent_plot))
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
        self.match_type.setCurrentText(workbook.match_type)
        self.result_mode.setCurrentText(workbook.result_mode.title())
        self.absolute_bias.blockSignals(True)
        self.percent_bias.blockSignals(True)
        self._primary_bias_mode = workbook.bias_mode
        self.absolute_bias.setChecked("absolute" in workbook.bias_views)
        self.percent_bias.setChecked("percent" in workbook.bias_views)
        self.absolute_bias.blockSignals(False)
        self.percent_bias.blockSignals(False)
        self._update_bias_plot_visibility()
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
        self._show_mapping_results()
        self.parameter_picker.blockSignals(True)
        self.parameter_picker.clear()
        self.parameter_picker.addItems(list(self.result.parameter_names))
        self.parameter_picker.blockSignals(False)
        self._draw_parameter()
        QTimer.singleShot(
            0, lambda: self.setup_scroll.ensureWidgetVisible(self.results_panel, 0, 24)
        )
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

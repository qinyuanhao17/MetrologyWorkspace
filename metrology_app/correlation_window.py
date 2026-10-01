"""Loadable Correlation and Trend workspace with separate source tables."""

from pathlib import Path

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .appearance import help_title_label
from .correlation_page import CorrelationPage
from .data import inspect_table, read_table
from .sequence_page import SequencePage
from .sheet import SheetModel, SheetView, clipboard_rows
from .window import MainWindow as DataWorkspaceWindow, parameter_checked_by_default


REFERENCE_COLOR = "#ed7d31"
RAW_COLOR = "#5b9bd5"
SOURCE_COLUMN = "Source"
IDENTITY_COLUMNS = (
    ("Wafer ID", ("waferid", "wafer", "waferno")),
    ("Lot ID", ("lotid", "lot", "lotno")),
    ("PAD Name", ("padname", "pad")),
    ("Die Seq", ("dieseq", "diesequence", "diesequenceno", "dieid")),
)


def _normalized(value):
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _first_column(frame, aliases):
    columns = {_normalized(column): column for column in frame.columns}
    return next((columns[alias] for alias in aliases if alias in columns), None)


def _aligned_reference_frame(reference, raw, mappings):
    """Keep Reference values while taking row identity from aligned Raw Data."""
    reference = reference.reset_index(drop=True).copy()
    raw = raw.reset_index(drop=True)
    if len(reference) != len(raw):
        raise ValueError("Reference and Raw Data must have the same row count.")
    identity_names = {
        source
        for _target, aliases in IDENTITY_COLUMNS
        for source in (_first_column(reference, aliases),)
        if source is not None
    }
    values = reference.drop(columns=list(identity_names), errors="ignore")
    values = values.rename(columns={
        mapping.reference_column: mapping.name
        for mapping in mappings
        if mapping.reference_column in values
    })
    aligned = pd.DataFrame(index=reference.index)
    for target, aliases in IDENTITY_COLUMNS:
        source = _first_column(raw, aliases)
        if source is not None:
            aligned[target] = raw[source].to_numpy(copy=True)
    if "Die Seq" not in aligned:
        aligned["Die Seq"] = np.arange(1, len(reference) + 1)
    for column in values:
        if column not in aligned:
            aligned[column] = values[column].to_numpy(copy=True)
    return aligned


def _analysis_raw_frame(raw, mappings):
    """Use canonical mapping names for plots without changing the Raw table."""
    frame = raw.reset_index(drop=True).copy()
    return frame.rename(columns={
        mapping.raw_column: mapping.name
        for mapping in mappings
        if mapping.raw_column in frame and mapping.name not in frame
    })


class CorrelationWindow(DataWorkspaceWindow):
    """Two editable source tables followed by the standard analysis pages."""

    def __init__(self):
        self._workbook_sources = ()
        self._source_mappings = ()
        self._analysis_frame = pd.DataFrame()
        self._reset_source_choices = False
        self._loading_workbook_sources = False
        super().__init__()
        self.setWindowTitle("Correlation and Trend")
        self.raw_model = self.model
        self.raw_sheet = self.sheet
        self.tabs.removeTab(2)
        self.tabs.removeTab(1)
        self.tabs.setTabText(0, "2. Raw Data")

        self.reference_model = SheetModel()
        self.reference_sheet = SheetView(self.reference_model)
        self.reference_page = self._build_reference_page()
        self.tabs.insertTab(0, self.reference_page, "1. Ref Data")
        self.reference_model.changed.connect(self.refresh_timer.start)
        self.correlation_page = CorrelationPage()
        self.tabs.addTab(self.correlation_page, "3. Correlation")
        self.sequence_page = SequencePage()
        self.tabs.addTab(self.sequence_page, "4. Trend")
        self.update_plan()

    def _build_reference_page(self):
        page = QWidget(objectName="referenceDataPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        card = QFrame(objectName="sheetCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 15, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(
            "Reference table",
            "Reference values use the row-aligned Raw Data identity fields.",
        ))
        heading.addStretch()
        for title, callback in (
            ("New", lambda: self.set_reference_table(pd.DataFrame())),
            ("Open file", self.open_reference_file),
            ("Paste table", self.paste_reference_table),
            ("Save CSV", self.save_reference_csv),
        ):
            control = QPushButton(title)
            control.setObjectName("primary" if title == "Open file" else "subtle")
            control.setFixedSize(104, 34)
            control.clicked.connect(callback)
            heading.addWidget(control)
        card_layout.addLayout(heading)
        card_layout.addWidget(self.reference_sheet, 1)
        self.reference_footer = QLabel("Ref Data", objectName="hint")
        card_layout.addWidget(self.reference_footer)
        layout.addWidget(card, 1)
        return page

    def open_reference_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Reference table", "", "Tables (*.csv *.xlsx)"
        )
        if path:
            self.set_reference_table(read_table(path, dtype=str), Path(path).name)

    def paste_reference_table(self):
        matrix = clipboard_rows(QApplication.clipboard().text())
        if len(matrix) < 2:
            return
        width = max(map(len, matrix))
        matrix = [row + [""] * (width - len(row)) for row in matrix]
        self.set_reference_table(
            pd.DataFrame(matrix[1:], columns=matrix[0]), "Clipboard"
        )

    def save_reference_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Reference table", "reference.csv", "CSV (*.csv)"
        )
        if path:
            self.reference_model.frame().to_csv(
                str(Path(path).with_suffix(".csv")), index=False,
                encoding="utf-8-sig",
            )
            self.reference_model.undo.setClean()

    def set_reference_table(self, frame, source="Ref Data"):
        self.reference_model.load(frame.reset_index(drop=True))
        self.reference_footer.setText(str(source))
        self.tabs.setCurrentWidget(self.reference_page)
        raw = self.raw_model.frame()
        if not frame.empty and len(frame) == len(raw):
            self._reset_source_choices = not bool(self._workbook_sources)
            self._rebuild_source_analysis()
        elif frame.empty:
            self._workbook_sources = ()
            self._analysis_frame = pd.DataFrame()
            self.update_plan()
        elif not raw.empty:
            self.reference_footer.setText(
                f"{source} · {len(frame)} rows; Raw Data has {len(raw)} rows"
            )

    def change_tab(self, index):
        if index in (2, 3) and self.refresh_timer.isActive():
            self.recognize()

    def default_parameters(self, metrics):
        """Correlation starts with all useful numeric columns selected."""
        return [metric for metric in metrics if parameter_checked_by_default(metric)]

    def set_table(self, frame, source):
        if not self._loading_workbook_sources:
            self._workbook_sources = ()
            self._source_mappings = ()
            self._analysis_frame = pd.DataFrame()
        super().set_table(frame, source)
        if (not self._loading_workbook_sources
                and hasattr(self, "reference_model")
                and not self.reference_model.frame().empty
                and len(self.reference_model.frame()) == len(frame)):
            self._reset_source_choices = True
            self._rebuild_source_analysis()

    def set_sources(self, reference, raw, mappings, mode="Preview"):
        """Load row-aligned WKB sources without merging their visible tables."""
        self._source_mappings = tuple(mappings)
        self._reset_source_choices = True
        reference_frame = _aligned_reference_frame(
            reference, raw, self._source_mappings
        )
        self._loading_workbook_sources = True
        try:
            super().set_table(raw.reset_index(drop=True), f"{mode} Raw Data")
            self.reference_model.load(reference_frame)
        finally:
            self._loading_workbook_sources = False
        self._workbook_sources = True
        self._rebuild_source_analysis()
        self.tabs.setCurrentIndex(0)
        self.setWindowTitle(f"{mode} Correlation and Trend")

    def _rebuild_source_analysis(self):
        reference = _aligned_reference_frame(
            self.reference_model.frame(), self.raw_model.frame(),
            self._source_mappings,
        )
        if not reference.equals(self.reference_model.frame().reset_index(drop=True)):
            self.reference_model.blockSignals(True)
            try:
                self.reference_model.load(reference)
            finally:
                self.reference_model.blockSignals(False)
        raw_analysis = _analysis_raw_frame(
            self.raw_model.frame(), self._source_mappings
        )
        reference.insert(0, SOURCE_COLUMN, "Reference")
        raw_analysis.insert(0, SOURCE_COLUMN, "Raw Data")
        self._analysis_frame = pd.concat(
            [reference, raw_analysis], ignore_index=True, sort=False
        )
        split = len(reference)
        self._workbook_sources = (
            {"name": "Reference", "color": REFERENCE_COLOR,
             "rows": tuple(range(split)), "keys": ("Reference",)},
            {"name": "Raw Data", "color": RAW_COLOR,
             "rows": tuple(range(split, len(self._analysis_frame))),
             "keys": ("Raw Data",)},
        )
        self._populate_source_choices()
        self.update_plan()

    def _populate_source_choices(self):
        selected_metrics = set(self.selected(self.parameter_list))
        mapped = [mapping.name for mapping in self._source_mappings]
        _wafer, _counts, raw_numeric = inspect_table(self.raw_model.frame())
        raw_names = {
            mapping.raw_column: mapping.name
            for mapping in self._source_mappings
        }
        raw_numeric = [raw_names.get(name, name) for name in raw_numeric]
        _wafer, _counts, reference_numeric = inspect_table(
            self.reference_model.frame()
        )
        metrics = list(dict.fromkeys((*mapped, *reference_numeric, *raw_numeric)))
        if self._reset_source_choices:
            selected_metrics = set(mapped or metrics)
            self._reset_source_choices = False
        elif not selected_metrics:
            selected_metrics = set(mapped or metrics)
        self.wafer_list.blockSignals(True)
        self.parameter_list.blockSignals(True)
        self.wafer_list.clear()
        for source in ("Reference", "Raw Data"):
            item = QTreeWidgetItem([source, str(len(self.raw_model.frame()))])
            item.setData(0, Qt.ItemDataRole.UserRole, source)
            item.setCheckState(0, Qt.CheckState.Checked)
            self.wafer_list.addTopLevelItem(item)
        self.parameter_list.clear()
        for metric in metrics:
            item = QTreeWidgetItem([metric, "NUMERIC"])
            item.setData(0, Qt.ItemDataRole.UserRole, metric)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
            item.setCheckState(
                0, Qt.CheckState.Checked
                if metric in selected_metrics else Qt.CheckState.Unchecked,
            )
            self.parameter_list.addTopLevelItem(item)
        self.wafer_list.blockSignals(False)
        self.parameter_list.blockSignals(False)
        self.wafer_count.setText("2 data sources")
        self.parameter_count.setText(f"{len(metrics)} numeric headers detected")

    def recognize(self):
        if self._workbook_sources and not self._loading_workbook_sources:
            self.refresh_timer.stop()
            self._rebuild_source_analysis()
            return
        super().recognize()

    def update_plan(self, *_args):
        if not self._workbook_sources:
            super().update_plan()
            if hasattr(self, "correlation_page"):
                self.correlation_page.set_input(self._frame, self.selection)
            if hasattr(self, "sequence_page"):
                self.sequence_page.set_input(self._frame, self.selection)
            return
        wafers = tuple(self.selected(self.wafer_list))
        metrics = tuple(self.selected(self.parameter_list))
        split = len(self.reference_model.frame())
        sources = tuple(
            source for source in self._workbook_sources
            if source["name"] in wafers
        )
        self.selection = {
            "wafers": list(wafers),
            "metrics": list(metrics),
            "wafer_column": "Wafer ID",
            "groups": {
                "Reference": tuple(range(split)),
                "Raw Data": tuple(range(split, len(self._analysis_frame))),
            },
            "labels": {name: name for name in wafers},
            "sources": sources,
        }
        self.correlation_page.set_input(self._analysis_frame, self.selection)
        self.sequence_page.set_input(self._analysis_frame, self.selection)
        self.statusBar().showMessage(
            f"{len(wafers)} data sources selected    ·    "
            f"{len(metrics)} parameters selected"
        )


__all__ = ["CorrelationWindow", "RAW_COLOR", "REFERENCE_COLOR"]

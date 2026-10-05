"""Loadable Correlation and Trend workspace with separate source tables."""

from pathlib import Path
from copy import deepcopy

import numpy as np
import pandas as pd
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QPushButton, QScrollArea, QSplitter, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .appearance import help_title_label
from .correlation_page import CorrelationPage
from .data import inspect_table, read_table
from .measurements import default_identity_columns, detect_measurements
from .matching import MatchWorkbook, ParameterMapping
from .match_groups import row_ids, participation_source_keys
from .sequence_page import SequencePage
from .sheet import DuplicateHeaderBanner, SheetModel, SheetView, clipboard_rows
from .window import (
    CheckMenu, MainWindow as DataWorkspaceWindow, choices, label,
    parameter_checked_by_default,
)


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


class CorrelationWindow(DataWorkspaceWindow):
    """Two editable source tables followed by the standard analysis pages."""
    workspace_type = "correlation_trend"

    def __init__(self):
        self._workbook_sources = ()
        self._source_mappings = ()
        self._analysis_frame = pd.DataFrame()
        self._reset_reference_selection = True
        self.reference_measurements = []
        self._loading_workbook_sources = False
        self._match_groups = None
        self._group_plan = None
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
        self.sequence_page.document_scoped = True
        self.document.mark_clean()

    def set_workbook_groups(self, book):
        """Classification belongs to exact source records, not just wafer names."""
        from .match_groups import applied_state
        effective = applied_state(book.grouping_state)
        if not (effective["enabled"] or effective["mark_enabled"]) and effective["data_selection"] is None:
            self._match_groups = None
            self._group_plan = None
            return
        state = deepcopy(book.grouping_state)
        for config in (state, state.get("applied", {})):
            for spec in (*config.get("filters", []), *config.get("sort", [])):
                if spec.get("table") == "reference":
                    mapping = next((m for m in book.mappings if m.reference_column == spec.get("column")), None)
                    if mapping is not None:
                        spec["column"] = mapping.name
        self._match_groups = {"grouping": state,
                              "flags": book.test_flags.iloc[:, 0].tolist() if book.test_flags is not None else [],
                              "identities": list(row_ids(self.raw_model.frame())),
                              "provenance": list(participation_source_keys(self.raw_model.frame())),
                              "mappings": [{"name": m.name, "reference_column": m.name, "raw_column": m.raw_column} for m in book.mappings],
                              "result_mode": book.result_mode, "match_type": book.match_type}
        self._refresh_group_results()
        self.update_plan()

    def _refresh_group_results(self):
        self._group_plan = None
        context = self._match_groups
        if not context:
            return
        raw = self.raw_model.frame()
        if (list(row_ids(raw)) != context["identities"] or
                ("provenance" in context and list(participation_source_keys(raw)) != context["provenance"])):
            self._match_groups = None
            self.statusBar().showMessage("Group classification detached: source record identities changed.")
            return
        try:
            book = MatchWorkbook(self.reference_model.frame(), raw,
                                 [ParameterMapping(**m) for m in context["mappings"]],
                                 test_flags=pd.DataFrame({"TestFlag": context["flags"]}),
                                 grouping_state=context["grouping"], match_type=context["match_type"],
                                 result_mode=context["result_mode"])
            self._group_plan = book.analyze().group_plan
        except ValueError as error:
            self.statusBar().showMessage(f"Group analysis unavailable: {error}")

    def set_workbook_participation(self, book):
        if self._match_groups:
            from .match_groups import applied_state
            selection = applied_state(book.grouping_state)["data_selection"]
            configs = self._match_groups["grouping"]
            configs["data_selection"] = deepcopy(selection)
            configs.setdefault("applied", {})["data_selection"] = deepcopy(selection)
            self._refresh_group_results()
        super().set_workbook_participation(book)

    def workspace_snapshot(self, *, include_drafts=False):
        snapshot = super().workspace_snapshot(include_drafts=include_drafts)
        if self._match_groups:
            snapshot.states["match_groups"] = deepcopy(self._match_groups)
        return snapshot

    def restore_workspace(self, snapshot):
        super().restore_workspace(snapshot)
        self._match_groups = deepcopy(snapshot.states.get("match_groups"))
        if self._match_groups:
            self._refresh_group_results()
            self.update_plan()
            # Grouped curve keys exist only after rebuilding the saved plan.
            self.restore_selection(snapshot.states.get("ui", {}).get("selection", {}))

    def _grouped_trend_selection(self, selection):
        if not self._match_groups or self._group_plan is None or not self._group_plan.enabled:
            return selection
        plan = self._group_plan
        split = len(self.reference_model.frame())
        grouped = {**selection, "wafers": [], "groups": {}, "labels": {},
                   "group_labels": {}, "available_cells": set()}
        source_keys = {}
        for source in selection["sources"]:
            name = source["name"]
            offset = 0 if name == "Reference" else split
            source_keys[name] = []
            for n, span in enumerate(plan.trend_spans()):
                for old_key in selection["wafers"]:
                    if old_key[0] != name:
                        continue
                    allowed = set(selection["groups"][old_key])
                    rows = tuple(offset + row for row in span["rows"] if offset + row in allowed)
                    if not rows:
                        continue
                    key = (name, f"group:{n}:{old_key[1]}")
                    grouped["wafers"].append(key)
                    grouped["groups"][key] = rows
                    grouped["labels"][key] = f"{name} · {span['label']}"
                    grouped["group_labels"][key] = plan.label(span["group"], multiline=True)
                    source_keys[name].append(key)
                    for old_cell, metric in selection["available_cells"]:
                        if old_cell == old_key:
                            grouped["available_cells"].add((key, metric))
        grouped["sources"] = tuple({**source, "keys": tuple(source_keys[source["name"]])} for source in selection["sources"])
        grouped["preserve_group_order"] = True
        return grouped

    def _build_reference_page(self):
        page = QWidget(objectName="referenceDataPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        self.reference_warning_banner = DuplicateHeaderBanner(
            self.reference_model
        )
        layout.addWidget(self.reference_warning_banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_reference_sheet_card())
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(14)
        side_layout.addWidget(self._build_reference_wafer_card(), 2)
        side_layout.addWidget(self._build_reference_parameter_card(), 3)
        side.setMinimumWidth(340)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setMinimumWidth(355)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll, 1)
        splitter.addWidget(sidebar)
        splitter.setSizes([1080, 365])
        splitter.setStretchFactor(0, 1)
        splitter.setHandleWidth(16)
        layout.addWidget(splitter, 1)
        return page

    def _build_reference_sheet_card(self):
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
            ("Export CSV", self.save_reference_csv),
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
        return card

    def _reference_card_header(self, layout, title, subtitle, tree):
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(title, subtitle))
        heading.addStretch()
        for text, checked in (("All", True), ("None", False)):
            control = QPushButton(text, objectName="link")
            control.clicked.connect(
                lambda _value=False, target=tree, state=checked:
                self.check_all(target, state)
            )
            heading.addWidget(control)
        layout.addLayout(heading)

    def _build_reference_wafer_card(self):
        card = QFrame(objectName="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.reference_wafer_list = choices(["Wafer ID", "Records"])
        self.reference_wafer_list.setUniformRowHeights(False)
        self.reference_wafer_list.setHeaderHidden(True)
        self.reference_wafer_list.setMinimumHeight(170)
        self._reference_card_header(
            layout, "Wafers",
            "Checked metadata headers form one Reference measurement identity.",
            self.reference_wafer_list,
        )
        self.reference_group_picker = QPushButton(
            "Select grouping columns", objectName="groupPicker"
        )
        self.reference_group_menu = CheckMenu(self.reference_group_picker)
        self.reference_group_picker.setMenu(self.reference_group_menu)
        self.reference_group_menu.aboutToShow.connect(
            lambda: self.reference_group_menu.setMinimumWidth(
                self.reference_group_picker.width()
            )
        )
        self.reference_group_checks = {}
        layout.addWidget(self.reference_group_picker)
        layout.addWidget(self.reference_wafer_list, 1)
        self.reference_wafer_list.itemChanged.connect(self.update_plan)
        self.reference_wafer_count = label("No wafers detected", "hint")
        layout.addWidget(self.reference_wafer_count)
        return card

    def _build_reference_parameter_card(self):
        card = QFrame(objectName="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.reference_parameter_list = choices(["Column header", "Type"])
        self.reference_parameter_list.setMinimumHeight(190)
        self._reference_card_header(
            layout, "Parameters",
            "Reference parameters are selected independently from Raw Data.",
            self.reference_parameter_list,
        )
        self.reference_search = QLineEdit()
        self.reference_search.setPlaceholderText("Find a column…")
        self.reference_search.textChanged.connect(
            self._filter_reference_parameters
        )
        search_row = QHBoxLayout()
        search_row.addWidget(self.reference_search, 1)
        self.reference_numeric_only = QCheckBox("Numeric")
        self.reference_numeric_only.setChecked(True)
        self.reference_numeric_only.toggled.connect(
            self._filter_reference_parameters
        )
        search_row.addWidget(self.reference_numeric_only)
        layout.addLayout(search_row)
        layout.addWidget(self.reference_parameter_list, 1)
        self.reference_parameter_list.itemChanged.connect(self.update_plan)
        self.reference_parameter_count = label("No headers detected", "hint")
        layout.addWidget(self.reference_parameter_count)
        return card

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

    def _reference_group_columns(self):
        return [
            column for column, action in self.reference_group_checks.items()
            if action.isChecked()
        ]

    def _update_reference_group_picker(self):
        selected = self._reference_group_columns()
        summary = " / ".join(selected) if selected else "Select grouping columns"
        self.reference_group_picker.setText(summary)
        self.reference_group_picker.setToolTip(
            summary + "\nChecked metadata fields form the Reference measurement identity."
        )

    def _set_reference_group_columns(self, columns):
        self.reference_group_menu.clear()
        self.reference_group_checks = {}
        for column, checked in columns:
            action = QAction(column, self.reference_group_menu)
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(self._change_reference_group_columns)
            self.reference_group_menu.addAction(action)
            self.reference_group_checks[column] = action
        self._update_reference_group_picker()
        self.reference_group_picker.setEnabled(bool(columns))

    def _change_reference_group_columns(self):
        self._update_reference_group_picker()
        self._reset_reference_selection = False
        self._populate_reference_choices()
        self.check_all(self.reference_wafer_list, True)

    def _filter_reference_parameters(self, *_args):
        query = self.reference_search.text().strip().lower()
        numeric_only = self.reference_numeric_only.isChecked()
        for index in range(self.reference_parameter_list.topLevelItemCount()):
            item = self.reference_parameter_list.topLevelItem(index)
            numeric = item.data(0, Qt.ItemDataRole.UserRole + 1)
            item.setHidden(
                query not in item.text(0).lower() or (numeric_only and not numeric)
            )

    def _populate_reference_choices(self):
        """Recognize Ref Data without borrowing Raw Data's selector widgets."""
        try:
            frame = self.reference_model.frame()
        except ValueError:
            self.reference_measurements = []
            self.reference_wafer_list.clear()
            self.reference_parameter_list.clear()
            self.reference_wafer_count.setText("Fix duplicate row-1 headers")
            self.reference_parameter_count.setText("Headers must be unique")
            return
        reset = self._reset_reference_selection
        previous_wafers = set(self.selected(self.reference_wafer_list))
        previous_metrics = set(self.selected(self.reference_parameter_list))
        previous_groups = self._reference_group_columns()
        detected_wafer, counts, metrics = inspect_table(frame)
        normalize = lambda name: "".join(
            character.lower() for character in str(name) if character.isalnum()
        )
        excluded = {
            "fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey",
            "dieseq", "diesequence", "diesequenceno",
        }
        hints = (
            "wafer", "lot", "pad", "sample", "id", "name", "tool",
            "recipe", "group", "run", "batch",
        )
        candidates = [
            column for column in frame
            if (column not in metrics or any(hint in normalize(column) for hint in hints))
            and normalize(column) not in excluded
            and "path" not in column.lower()
        ]
        if reset:
            lot_column = next(
                (column for column in candidates
                 if normalize(column) in {"lotid", "lot", "lotno"}),
                None,
            )
            pad_column = next(
                (column for column in candidates
                 if normalize(column) in {"padname", "pad"}),
                None,
            )
            chosen_groups = default_identity_columns(
                frame, detected_wafer, lot_column, pad_column
            )
        else:
            chosen_groups = [
                column for column in candidates if column in previous_groups
            ]
        if reset or list(self.reference_group_checks) != candidates:
            self._set_reference_group_columns([
                (column, column in chosen_groups) for column in candidates
            ])
        primary = next(
            (column for column in chosen_groups
             if normalize(column) in {"waferid", "wafer", "waferno"}),
            chosen_groups[0] if chosen_groups else None,
        )
        if primary:
            _wafer, counts, _metrics = inspect_table(frame, primary)
        self.reference_measurements = detect_measurements(
            frame, primary, chosen_groups, use_die_seq=False
        ) if primary else []
        mapped = [
            mapping.name for mapping in self._source_mappings
            if mapping.name in metrics
        ]
        chosen_metrics = (
            set(mapped or self.default_parameters(metrics))
            if reset else previous_metrics
        )
        for tree in (self.reference_wafer_list, self.reference_parameter_list):
            tree.blockSignals(True)
            tree.clear()
        for measurement in self.reference_measurements:
            item = QTreeWidgetItem([
                measurement.label, str(len(measurement.rows))
            ])
            item.setSizeHint(
                0, QSize(0, 20 * len(measurement.label.splitlines()) + 12)
            )
            item.setToolTip(0, measurement.detail)
            item.setToolTip(1, measurement.detail)
            item.setData(0, Qt.ItemDataRole.UserRole, measurement.key)
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if reset or measurement.key in previous_wafers
                else Qt.CheckState.Unchecked,
            )
            self.reference_wafer_list.addTopLevelItem(item)
        for column in frame:
            numeric = column in metrics
            item = QTreeWidgetItem([
                column, "NUMERIC" if numeric else "METADATA"
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, column)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, numeric)
            item.setToolTip(0, column)
            if numeric:
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if column in chosen_metrics else Qt.CheckState.Unchecked,
                )
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.reference_parameter_list.addTopLevelItem(item)
        self.reference_wafer_list.blockSignals(False)
        self.reference_parameter_list.blockSignals(False)
        self.reference_wafer_count.setText(
            f"{len(self.reference_measurements)} measurement sets / "
            f"{len(counts)} {primary or 'groups'} values"
        )
        self.reference_parameter_count.setText(
            f"{len(metrics)} numeric / {len(frame.columns)} headers detected"
        )
        self._reset_reference_selection = False
        self._filter_reference_parameters()

    def set_reference_table(self, frame, source="Ref Data"):
        self._reset_reference_selection = True
        self.reference_model.load(frame.reset_index(drop=True))
        self.reference_footer.setText(
            f"{len(frame):,} rows × {len(frame.columns)} columns")
        self.tabs.setCurrentWidget(self.reference_page)
        if self.reference_model.duplicate_header_count():
            self.reference_footer.setText(
                f"{len(frame):,} rows × {len(frame.columns)} columns"
                " · Fix duplicate row-1 headers")
            self._populate_reference_choices()
            return
        if self.raw_model.duplicate_header_count():
            self._populate_reference_choices()
            return
        raw = self.raw_model.frame()
        if not frame.empty and len(frame) == len(raw):
            self._rebuild_source_analysis()
        elif frame.empty:
            self._workbook_sources = ()
            self._analysis_frame = pd.DataFrame()
            self._populate_reference_choices()
            self.update_plan()
        elif not raw.empty:
            self.reference_footer.setText(
                f"{len(frame):,} rows × {len(frame.columns)} columns; "
                f"Raw Data has {len(raw):,} rows"
            )
            self._populate_reference_choices()
        else:
            self._populate_reference_choices()

    def change_tab(self, index):
        if index in (2, 3) and self.refresh_timer.isActive():
            self.recognize()

    def default_parameters(self, metrics):
        """Correlation starts with all useful numeric columns selected."""
        return [metric for metric in metrics if parameter_checked_by_default(metric)]

    def set_table(self, frame, source, **kwargs):
        if not self._loading_workbook_sources:
            self._match_groups = None
            self._group_plan = None
            self._workbook_sources = ()
            self._source_mappings = ()
            self._analysis_frame = pd.DataFrame()
        super().set_table(frame, source, **kwargs)
        if (not self._loading_workbook_sources
                and hasattr(self, "reference_model")
                and not self.model.duplicate_header_count()
                and not self.reference_model.duplicate_header_count()
                and not self.reference_model.frame().empty
                and len(self.reference_model.frame()) == len(frame)):
            self._reset_reference_selection = True
            self._rebuild_source_analysis()

    def set_sources(self, reference, raw, mappings, mode="Preview"):
        """Load row-aligned WKB sources without merging their visible tables."""
        self._source_mappings = tuple(mappings)
        self._match_groups = None
        self._group_plan = None
        self._reset_reference_selection = True
        reference_frame = _aligned_reference_frame(
            reference, raw, self._source_mappings
        )
        self._loading_workbook_sources = True
        try:
            super().set_table(raw.reset_index(drop=True), f"{mode} Raw Data",
                              keep_local_selection=True)
            self._set_checked_values(
                self.parameter_list,
                [mapping.raw_column for mapping in self._source_mappings],
            )
            self.reference_model.load(reference_frame)
            self.reference_footer.setText(
                f"{len(reference_frame):,} rows × {len(reference_frame.columns)} columns")
        finally:
            self._loading_workbook_sources = False
        self._workbook_sources = True
        self._rebuild_source_analysis()
        self.tabs.setCurrentIndex(0)
        self.setWindowTitle(f"{mode} Correlation and Trend")

    @staticmethod
    def _encoded_draw_state(page):
        state = page.draw_state()
        cells = []
        for wafer, metric in state.get("cells", ()):
            if isinstance(wafer, (tuple, list)) and len(wafer) == 2:
                source, wafer_key = wafer
            else:
                source, wafer_key = "Data", wafer
            cells.append((str(source), str(wafer_key), str(metric)))
        return {
            "enabled": state.get("enabled") is True,
            "cells": tuple(sorted(cells)),
        }

    @staticmethod
    def _decoded_draw_state(state, raw_metric_names=None):
        if not isinstance(state, dict):
            return None
        cells = []
        for cell in state.get("cells", ()):
            if isinstance(cell, (str, bytes)) or len(cell) != 3:
                continue
            source, wafer_key, metric = (str(value) for value in cell)
            if source == "Raw Data":
                metric = (raw_metric_names or {}).get(metric, metric)
            wafer = wafer_key if source == "Data" else (source, wafer_key)
            cells.append((wafer, metric))
        return {
            "enabled": state.get("enabled") is True,
            "cells": tuple(cells),
        }

    def set_second_axis_ratio(self, ratio, *, show_control=False):
        """Let the Match Workbook's Analysis menu drive the auto threshold."""
        self.sequence_page.restore_axis_ratio(ratio)
        self.sequence_page.set_axis_ratio_control_visible(show_control)

    def set_trend_axis_mode(self, mode, *, show_control=False):
        """Apply the Match Workbook's auto/dual/single axis policy."""
        self.sequence_page.restore_axis_mode(mode)
        self.sequence_page.set_axis_ratio_control_visible(show_control)

    def selection_state(self):
        """Return independent Ref/Raw choices plus both page draw states."""
        if not hasattr(self, "reference_wafer_list"):
            return super().selection_state()
        return {
            "source_parameter_names": True,
            "reference": {
                "wafers": tuple(self.selected(self.reference_wafer_list)),
                "metrics": tuple(self.selected(self.reference_parameter_list)),
            },
            "raw": {
                "wafers": tuple(self.selected(self.wafer_list)),
                "metrics": tuple(self.selected(self.parameter_list)),
            },
            "correlation_draw": self._encoded_draw_state(
                self.correlation_page
            ),
            "trend_draw": self._encoded_draw_state(self.sequence_page),
            "trend_axis_ratio": self.sequence_page.axis_ratio_limit(),
            "trend_axis_mode": self.sequence_page.axis_mode_value(),
        }

    def restore_selection(self, state):
        """Restore WKB choices, then redraw pages that succeeded previously."""
        if not isinstance(state, dict) or not hasattr(
            self, "reference_wafer_list"
        ):
            return
        if "reference" not in state and "raw" not in state:
            super().restore_selection(state)
            return
        reference = state.get("reference", {})
        raw = state.get("raw", {})
        self._set_checked_values(
            self.reference_wafer_list,
            reference.get("wafers", ()),
            keep_current_if_missing=True,
        )
        self._set_checked_values(
            self.reference_parameter_list, reference.get("metrics", ())
        )
        self._set_checked_values(
            self.wafer_list,
            raw.get("wafers", ()),
            keep_current_if_missing=True,
        )
        self._set_checked_values(
            self.parameter_list, raw.get("metrics", ())
        )
        self.update_plan()
        self.sequence_page.restore_axis_ratio(state.get("trend_axis_ratio"))
        self.sequence_page.restore_axis_mode(state.get("trend_axis_mode", "auto"))
        # Earlier WKB draw states used match aliases for Raw parameters.
        legacy_raw_names = {} if state.get("source_parameter_names") else {
            mapping.name: mapping.raw_column for mapping in self._source_mappings
        }
        self.correlation_page.restore_draw_state(
            self._decoded_draw_state(state.get("correlation_draw"), legacy_raw_names)
        )
        self.sequence_page.restore_draw_state(
            self._decoded_draw_state(state.get("trend_draw"), legacy_raw_names)
        )

    def closeEvent(self, event):
        """Cancel deferred redraws before Qt disposes their controls."""
        super().closeEvent(event)
        if not event.isAccepted():
            return
        if hasattr(self, "correlation_page"):
            self.correlation_page.input_refresh_timer.stop()
            self.correlation_page.update_timer.stop()
        if hasattr(self, "sequence_page"):
            self.sequence_page.input_refresh_timer.stop()
            self.sequence_page.compare_timer.stop()

    def _rebuild_source_analysis(self):
        if (self.reference_model.duplicate_header_count()
                or self.raw_model.duplicate_header_count()):
            self._populate_reference_choices()
            return
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
        # Parameter identity comes from its source tab, not the match alias.
        raw_analysis = self.raw_model.frame().reset_index(drop=True).copy()
        reference.insert(0, SOURCE_COLUMN, "Reference")
        raw_analysis.insert(0, SOURCE_COLUMN, "Raw Data")
        self._analysis_frame = pd.concat(
            [reference, raw_analysis], ignore_index=True, sort=False
        )
        self._populate_reference_choices()
        split = len(reference)
        reference_keys = tuple(
            ("Reference", measurement.key)
            for measurement in self.reference_measurements
        )
        raw_keys = tuple(
            ("Raw Data", measurement.key) for measurement in self.measurements
        )
        self._workbook_sources = (
            {"name": "Reference", "color": REFERENCE_COLOR,
             "rows": tuple(range(split)), "keys": reference_keys},
            {"name": "Raw Data", "color": RAW_COLOR,
             "rows": tuple(range(split, len(self._analysis_frame))),
             "keys": raw_keys},
        )
        self._refresh_group_results()
        self.update_plan()

    def recognize(self):
        if self._workbook_sources and not self._loading_workbook_sources:
            self.refresh_timer.stop()
            super().recognize()
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
        reference_wafers = set(self.selected(self.reference_wafer_list))
        raw_wafers = set(self.selected(self.wafer_list))
        reference_metrics = tuple(self.selected(self.reference_parameter_list))
        raw_metrics = tuple(self.selected(self.parameter_list))
        metrics = tuple(dict.fromkeys((*reference_metrics, *raw_metrics)))
        split = len(self.reference_model.frame())
        reference_groups = {
            ("Reference", measurement.key): tuple(measurement.rows)
            for measurement in self.reference_measurements
        }
        raw_groups = {
            ("Raw Data", measurement.key): tuple(
                split + row for row in measurement.rows
            )
            for measurement in self.measurements
        }
        selected_reference_keys = [
            key for key in reference_groups if key[1] in reference_wafers
        ]
        selected_raw_keys = [key for key in raw_groups if key[1] in raw_wafers]
        wafers = tuple((*selected_reference_keys, *selected_raw_keys))
        sources = tuple(source for source in self._workbook_sources if (
            source["name"] == "Reference"
            and selected_reference_keys and reference_metrics
        ) or (
            source["name"] == "Raw Data" and selected_raw_keys and raw_metrics
        ))
        labels = {
            ("Reference", measurement.key):
            f"Reference · {measurement.label}"
            for measurement in self.reference_measurements
        }
        labels.update({
            ("Raw Data", measurement.key): f"Raw Data · {measurement.label}"
            for measurement in self.measurements
        })
        available_cells = {
            (key, metric)
            for key in selected_reference_keys for metric in reference_metrics
        }
        available_cells.update({
            (key, metric) for key in selected_raw_keys for metric in raw_metrics
        })
        self.selection = {
            "wafers": list(wafers),
            "metrics": list(metrics),
            "wafer_column": "Wafer ID",
            "groups": {**reference_groups, **raw_groups},
            "labels": labels,
            "sources": sources,
            "available_cells": available_cells,
        }
        if self._group_plan is not None and getattr(self, "_workbook_selection_applies", True):
            allowed = set(self._group_plan.included_rows)
            self.selection["groups"] = {key: tuple(row for row in rows
                if (row if key[0] == "Reference" else row - split) in allowed)
                for key, rows in self.selection["groups"].items()}
        allowed = self.participating_positions(self.raw_model.frame())
        self.selection["groups"] = {key: tuple(row for row in rows
            if (row if key[0] == "Reference" else row - split) in allowed)
            for key, rows in self.selection["groups"].items()}
        self.correlation_page.set_input(self._analysis_frame, self.selection)
        self.sequence_page.set_input(self._analysis_frame, self._grouped_trend_selection(self.selection))
        self.statusBar().showMessage(
            f"{len(wafers)} measurement sets selected    ·    "
            f"{len(metrics)} parameters selected"
        )


__all__ = ["CorrelationWindow", "RAW_COLOR", "REFERENCE_COLOR"]

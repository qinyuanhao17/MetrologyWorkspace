"""Loadable Correlation and Trend workspace with separate source tables."""

from pathlib import Path
from copy import deepcopy
from collections import Counter
from itertools import chain

import numpy as np
import pandas as pd
from PyQt6.QtCore import QSignalBlocker, QSize, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QTreeWidgetItem,
    QVBoxLayout, QWidget, QWidgetAction,
)

from .appearance import help_title_label
from .correlation_page import CorrelationPage
from .data import inspect_table, read_table
from .measurements import default_identity_columns, detect_measurements
from .match_groups import GroupPlan, row_ids, participation_source_keys
from .sequence_page import SequencePage
from .wafer_statistics_page import WaferStatisticsPage
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


def _available_source_frame(model):
    """Exclude an invalid source from analysis without blocking its valid peer."""
    return pd.DataFrame() if model.duplicate_header_count() else model._analysis_view()


def _aligned_reference_frame(reference, raw):
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


def _reference_with_default_identity(reference, raw):
    """Seed a value-only import once, never replace supplied identity fields."""
    if (reference.empty or not reference.columns.is_unique or len(reference) != len(raw)
            or any(_first_column(reference, aliases) is not None
                   for _target, aliases in IDENTITY_COLUMNS)):
        return reference
    return _aligned_reference_frame(reference, raw)


class CorrelationWindow(DataWorkspaceWindow):
    """Two editable source tables followed by the standard analysis pages."""
    workspace_type = "correlation_trend"

    def __init__(self):
        self._copy_reference_from_wkb = False
        self._workbook_reference_rows = ()
        self._workbook_sources = ()
        self._source_mappings = ()
        self._analysis_frame = pd.DataFrame()
        self._reset_reference_selection = True
        self.reference_measurements = []
        self._loading_workbook_sources = False
        self._restoring_source_tables = False
        self._match_groups = None
        self._group_plan = None
        self._group_result_cache = None
        self.display_options = None
        self._reference_excluded = set()
        self._reference_selection_view = {}
        super().__init__()
        self._chart_edits.point_edit = self._apply_point_participation
        self.setWindowTitle("Correlation and Trend")
        self.raw_model = self.model
        self.raw_sheet = self.sheet
        self.tabs.removeTab(2)
        self.tabs.removeTab(1)
        self.tabs.setTabText(0, "2. Raw Data")

        self.reference_model = SheetModel()
        derived = getattr(self, "derived_table", False)
        self.reference_sheet = SheetView(self.reference_model, read_only=derived, metadata_locks=not derived)
        self.reference_page = self._build_reference_page()
        self.tabs.insertTab(0, self.reference_page, "1. Ref Data")
        self.reference_model.changed.connect(self.refresh_timer.start)
        self.reference_model.changed.connect(self._refresh_table_sizes)
        self.reference_model.modelReset.connect(self._refresh_table_sizes)
        self.reference_model.metadata_locks_changed.connect(self.document.identity_timer.start)
        self.correlation_page = CorrelationPage()
        self.correlation_page.data_point_edits = self._chart_edits
        self.correlation_page.axes_changed.connect(self.document.identity_timer.start)
        self.correlation_page.point_double_clicked.connect(self._toggle_correlation_point)
        self.tabs.addTab(self.correlation_page, "3. Correlation")
        self.sequence_page = SequencePage(defer_initial_input=True)
        self.sequence_page.data_point_edits = self._chart_edits
        self.sequence_page.point_double_clicked.connect(self._toggle_correlation_point)
        self.tabs.addTab(self.sequence_page, "4. Trend")
        self.wafer_statistics_page = WaferStatisticsPage()
        self.wafer_statistics_page.data_point_edits = self._chart_edits
        self.wafer_statistics_page.point_double_clicked.connect(self._toggle_correlation_point)
        self.tabs.addTab(self.wafer_statistics_page, "5. Wafer Mean / Sigma")
        self._build_chart_analysis_menu()
        from .correlation_options import CorrelationOptions
        self.display_options = CorrelationOptions(self)
        self.reference_selection_action = QAction("Ref Data selection…", self)
        self.reference_selection_action.triggered.connect(self.open_reference_selection)
        self.data_menu.insertAction(self.copy_wkb_selection_action, self.reference_selection_action)
        self._refresh_table_sizes()
        self.copy_from_wkb_action.setText("Copy Raw Data from WKB")
        self.copy_from_wkb_action.setToolTip(
            "Copy Raw Data from the owning Match Workbook and follow its changes. "
            "The Ref copy is controlled separately.")
        self.copy_reference_from_wkb_action = QAction("Copy Ref from WKB", self, checkable=True)
        actions = self.data_menu.actions()
        self.data_menu.insertAction(actions[actions.index(self.copy_from_wkb_action) + 1],
                                    self.copy_reference_from_wkb_action)
        self.copy_reference_from_wkb_action.setVisible(False)
        self.copy_reference_from_wkb_action.toggled.connect(self._copy_reference_changed)
        self.update_plan()
        self.sequence_page.document_scoped = True
        self.wafer_statistics_page.document_scoped = True
        self.document.mark_clean()

    def workbook_copy_sources(self):
        return {"raw_data": self._copy_from_wkb, "reference_data": self._copy_reference_from_wkb}

    def _build_chart_analysis_menu(self):
        self.analysis_menu = self.menuBar().addMenu("Analysis")
        for name, page in (("Trend Y Axes", self.sequence_page),
                           ("Mean/Sigma Y Axes", self.wafer_statistics_page)):
            menu = self.analysis_menu.addMenu(name)
            page.set_axis_ratio_control_visible(False)
            modes = QActionGroup(menu)
            for index in range(page.axis_mode.count()):
                if index == 1:
                    row = QWidget(menu)
                    layout = QHBoxLayout(row)
                    layout.addWidget(QLabel("Median ratio >"))
                    layout.addWidget(page.axis_ratio)
                    page.axis_ratio.show()
                    action = QWidgetAction(menu)
                    action.setDefaultWidget(row)
                    menu.addAction(action)
                    menu.addSeparator()
                mode = page.axis_mode.itemData(index)
                action = menu.addAction({"auto": "Auto (median ratio)",
                                         "dual": "Always two Y axes",
                                         "single": "Always one Y axis"}[mode])
                action.setCheckable(True)
                modes.addAction(action)
                action.setChecked(mode == page.axis_mode_value())
                action.triggered.connect(lambda _checked, value=mode, target=page: target.restore_axis_mode(value))
                page.axis_mode.currentIndexChanged.connect(
                    lambda _index, choice=action, value=mode, target=page:
                    choice.setChecked(target.axis_mode_value() == value))
            page.axis_mode.currentIndexChanged.connect(lambda _index: self.document.identity_timer.start())
            page.axis_ratio.valueChanged.connect(lambda _value: self.document.identity_timer.start())

        action = QWidgetAction(self.analysis_menu)
        row = QWidget(self.analysis_menu)
        layout = QHBoxLayout(row)
        layout.addWidget(QLabel("Plot decimal places"))
        self.plot_decimal_places = QSpinBox(row)
        self.plot_decimal_places.setRange(0, 10)
        self.plot_decimal_places.setValue(3)
        self.plot_decimal_places.valueChanged.connect(self._set_plot_decimals)
        layout.addWidget(self.plot_decimal_places)
        action.setDefaultWidget(row)
        self.analysis_menu.addSeparator()
        self.analysis_menu.addAction(action)

    def _set_plot_decimals(self, value):
        for page in (self.sequence_page, self.wafer_statistics_page):
            page.plot_decimals = value
            if page.ready:
                page.draw_plot()
        self.document.identity_timer.start()

    def configure_workbook_owner(self, owner, scope):
        super().configure_workbook_owner(owner, scope)
        self.copy_reference_from_wkb_action.setVisible(True)
        self.data_menu.removeAction(self.reference_selection_action)
        self.reference_selection_action.setVisible(False)

    def set_copy_reference_from_wkb(self, checked):
        self._copy_reference_from_wkb = bool(checked)
        with QSignalBlocker(self.copy_reference_from_wkb_action):
            self.copy_reference_from_wkb_action.setChecked(checked)
        self._update_workbook_selection_actions(self.copy_from_wkb_action.isEnabled())

    def _copy_reference_changed(self, checked):
        owner = getattr(self, "_managed_owner", None)
        if owner is None:
            self.set_copy_reference_from_wkb(False)
        else:
            owner.set_child_reference_copy(self, checked)

    def workbook_reference_frame(self, reference, raw):
        if not reference.empty and len(reference) == len(raw):
            self._workbook_reference_rows = participation_source_keys(raw)
            reference = _aligned_reference_frame(reference, raw)
        else:
            self._workbook_reference_rows = ()
        if self.reference_model.clipboard_locks and not reference.empty:
            reference = self.reference_model.merge_clipboard_frame(reference)
        return reference

    def set_workbook_reference(self, reference):
        if not self.reference_model.matches_document(reference):
            if not self.reference_model.update_headers(reference):
                self.reference_model.load(reference)
            self._rebuild_source_analysis()
            self.refresh_timer.stop()

    def set_workbook_sources(self, raw, mappings, mode="Preview", *, reference=None):
        if self.raw_model.clipboard_locks:
            raw = self.raw_model.merge_clipboard_frame(raw)
        existing_reference = self.reference_model._document_view()
        if reference is not None and not self.reference_model.matches_document(reference):
            self._prepared_group_result = None
            prepared = getattr(self.raw_model, '_linked_prepared_load', None)
            if prepared is not None and 'value_changes' in prepared:
                self.raw_model._linked_prepared_load = None
        prepared = getattr(self.raw_model, '_linked_prepared_load', None)
        if prepared is not None and 'value_changes' in prepared:
            self.raw_model._linked_prepared_load = None
            if self._set_workbook_values(raw, mappings, mode, prepared):
                return
        if reference is None and not existing_reference.empty and len(existing_reference) != len(raw):
            # Keep the manual Reference literally intact. A changed Raw row
            # count cannot establish new cross-table pairs on its behalf.
            self.set_table(raw, f"{mode} Raw Data", keep_local_selection=True)
            self._refresh_table_sizes()
            self._populate_reference_choices()
            return
        self.set_sources(existing_reference if reference is None else reference, raw, mappings, mode,
                         align_reference=False)

    def _linked_value_context(self):
        numeric = tuple(self.parameter_list.topLevelItem(i).text(0)
                        for i in range(self.parameter_list.topLevelItemCount())
                        if self.parameter_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1))
        return (self.include_fit_quality, bool(self.card_check.isChecked()),
                tuple(self.group_checks), tuple(self.group_columns()), numeric)

    def linked_value_baseline(self):
        """Detached qualification inputs, never live widgets in the worker."""
        if (type(self.raw_model) is not SheetModel or self.raw_model.clipboard_locks
                or self.card_check.isChecked() or not self._workbook_sources
                or self._reset_selection):
            return None
        context = self._linked_value_context()
        return {'document': self.raw_model.document_frame(), 'analysis': self._frame.copy(deep=True),
                'revision': self.raw_model.revision, 'context': context,
                'numeric_columns': context[-1], 'identity_columns': context[2]}

    def _set_workbook_values(self, raw, mappings, mode, prepared):
        if self._linked_value_context() != prepared['value_context']:
            return False
        self._loading_workbook_sources = True
        try:
            if not self.raw_model.apply_linked_values(prepared, raw):
                return False
            self._frame = self.raw_model.frame()
            self._source_mappings = tuple(mappings)
            self._match_groups = self._group_plan = self._group_result_cache = None
            self.source_path = f'{mode} Raw Data'
            self.file_label.setText(self.source_path)
            self.file_label.setToolTip(self.source_path)
            self._refresh_table_sizes()
            self._rebuild_source_analysis()
            self.setWindowTitle(f'{mode} Correlation and Trend')
            return True
        finally:
            self.refresh_timer.stop()
            self._loading_workbook_sources = False

    def _copy_from_wkb_changed(self, checked):
        owner = getattr(self, "_managed_owner", None)
        if owner is None:
            self.set_copy_from_wkb(self._copy_from_wkb)
            return
        if checked:
            if not owner.reset_child_to_workbook(self, confirm=not self.raw_model.document_frame().empty):
                self.set_copy_from_wkb(False)
            return
        with self.input_update():
            self.set_table(pd.DataFrame(), "Manual Raw Data")
        if not self._copy_reference_from_wkb:
            self._workbook_selection_applies = False
        self.set_copy_from_wkb(False)
        self._use_workbook_data = False
        self._independent_data = True
        self.document.refresh_identity()

    def set_workbook_groups(self, book):
        """Classification belongs to exact source records, not just wafer names."""
        from .correlation_groups import prepare_group_context
        raw = self.raw_model._analysis_view()
        applies = getattr(self, "_workbook_selection_applies", True)
        if self.display_options is not None and not self.display_options.follow_groups.isChecked():
            context = prepare_group_context(book,raw,applies)
            self.display_options.remember_workbook(context)
            self._match_groups = self.display_options.context(context)
            self._refresh_group_results()
            self.update_plan()
            return
        prepared = getattr(self, "_prepared_group_result", None)
        if (prepared is not None and prepared["book_state"] is book.grouping_state
                and prepared["applies"] == applies and self.raw_model.matches_analysis(prepared["raw"])
                and prepared["reference"].equals(self.reference_model.frame())):
            self._match_groups, self._group_plan = prepared["context"], prepared["plan"]
            self._trend_parts_cache = prepared.get("trend_parts")
            self._group_result_cache = ((self.reference_model.revision, self.raw_model.revision),
                                        prepared["comparison"], self._group_plan)
            if self.display_options is not None:
                self.display_options.remember_workbook(self._match_groups)
            if prepared["error"]:
                self.statusBar().showMessage(f"Group analysis unavailable: {prepared['error']}")
            self.update_plan()
            return
        self._match_groups = prepare_group_context(book, raw, applies)
        if self.display_options is not None:
            self.display_options.remember_workbook(self._match_groups)
        if self._match_groups is None:
            self._group_plan = self._group_result_cache = None
            self.update_plan()
            return
        self._refresh_group_results()
        self.update_plan()

    def _refresh_group_results(self):
        if self.display_options is not None:
            self._match_groups = self.display_options.context(self._match_groups)
        context = self._match_groups
        if not context:
            self._group_plan = None
            self._group_result_cache = None
            return
        revisions = (self.reference_model.revision, self.raw_model.revision)
        cached = self._group_result_cache
        if cached is not None and cached[0] == revisions and cached[1] == context:
            self._group_plan = cached[2]
            return
        self._group_plan = None
        raw = self.raw_model.frame()
        if (list(row_ids(raw)) != context["identities"] or
                ("provenance" in context and list(participation_source_keys(raw)) != context["provenance"])):
            self._match_groups = None
            self.statusBar().showMessage("Group classification detached: source record identities changed.")
            return
        try:
            # Classification and display order do not require a regression or
            # populated manual Ref columns. Reuse the same pure Group plan.
            self._group_plan = GroupPlan(
                raw, pd.DataFrame({"TestFlag": context["flags"]}),
                context["grouping"], self.reference_model.frame())
            self._group_result_cache = (revisions, deepcopy(context), self._group_plan)
        except ValueError as error:
            self.statusBar().showMessage(f"Group analysis unavailable: {error}")

    def set_workbook_participation(self, book):
        prepared = getattr(self, "_prepared_group_result", None)
        installed = (prepared is not None and self._match_groups is prepared["context"]
                     and prepared["book_state"] is book.grouping_state
                     and prepared["applies"] == getattr(self, "_workbook_selection_applies", True))
        if self._match_groups and not installed and (self.display_options is None or self.display_options.follow_groups.isChecked()):
            from .match_groups import applied_state
            selection = applied_state(book.grouping_state)["data_selection"]
            if not getattr(self, "_workbook_selection_applies", True):
                existing = applied_state(self._match_groups["grouping"])["data_selection"]
                selection = {**deepcopy(existing), "excluded": []} if existing is not None else None
            configs = self._match_groups["grouping"]
            configs["data_selection"] = deepcopy(selection)
            configs.setdefault("applied", {})["data_selection"] = deepcopy(selection)
            self._refresh_group_results()
        super().set_workbook_participation(book)

    def workspace_snapshot(self, *, include_drafts=False, readonly=False):
        snapshot = super().workspace_snapshot(include_drafts=include_drafts, readonly=readonly)
        snapshot.states["ui"]["copy_reference_from_wkb"] = self._copy_reference_from_wkb
        selection = snapshot.states["data_selection"]
        if self._reference_excluded:
            selection["reference_excluded"] = sorted(self._reference_excluded)
        if self._reference_selection_view:
            selection["reference_view"] = (self._reference_selection_view if readonly
                                          else deepcopy(self._reference_selection_view))
        if self._match_groups:
            snapshot.states["match_groups"] = self._match_groups if readonly else deepcopy(self._match_groups)
        if self.display_options is not None:
            snapshot.states['correlation_display'] = self.display_options.snapshot()
        return snapshot

    def restore_workspace(self, snapshot):
        ui = snapshot.states.get("ui", {})
        self.set_copy_reference_from_wkb(isinstance(ui, dict) and ui.get("copy_reference_from_wkb") is True)
        selection = snapshot.states.get("data_selection", {})
        if not isinstance(selection, dict):
            selection = {}
        excluded = selection.get("reference_excluded", [])
        view = selection.get("reference_view", {})
        if not isinstance(excluded, list) or any(not isinstance(key, str) for key in excluded):
            raise ValueError("Invalid Ref Data selection.")
        if not isinstance(view, dict):
            raise ValueError("Invalid Ref Data selection view.")
        self._reference_excluded = set(excluded)
        self._reference_selection_view = deepcopy(view)
        super().restore_workspace(snapshot)

    def _independent_reference_rows(self):
        if not hasattr(self, "reference_model"):
            return False
        reference_rows, _ = self.reference_model.document_shape()
        raw_rows, _ = self.raw_model.document_shape()
        return bool(reference_rows and reference_rows != raw_rows)

    def _refresh_table_sizes(self):
        super()._refresh_table_sizes()
        if hasattr(self, "reference_selection_action"):
            self.reference_selection_action.setVisible(
                getattr(self, "_managed_owner", None) is None and self._independent_reference_rows())

    def _table_selection_hidden(self, name):
        if name == "reference" and self._independent_reference_rows():
            return self._reference_selection_view.get("hide_excluded", False)
        return super()._table_selection_hidden(name)

    def _table_participating_positions(self, name, frame):
        if name == "reference" and self._copy_reference_from_wkb and (
                self._workbook_reference_rows and len(frame) == len(self._workbook_reference_rows)):
            excluded = getattr(self, "_participation_excluded", set()) if self._workbook_selection_applies else set()
            local = self._reference_excluded
            keys = participation_source_keys(frame) if local else (None,) * len(frame)
            return {row for row, (parent_key, key) in enumerate(zip(self._workbook_reference_rows, keys))
                    if parent_key not in excluded and key not in local}
        if name == "reference" and self._independent_reference_rows():
            if not self._reference_excluded:
                return set(range(len(frame)))
            return {row for row, key in enumerate(participation_source_keys(frame))
                    if key not in self._reference_excluded}
        return super()._table_participating_positions(name, frame)

    def open_reference_selection(self):
        from .data_selection import FrameSelectionDialog
        frame = _available_source_frame(self.reference_model)
        if frame.empty or not self._independent_reference_rows():
            return
        view = self._reference_selection_view
        dialog = FrameSelectionDialog(frame, self._reference_excluded, self,
                                      filters=view.get("filters"), row_bools=view.get("row_bools"),
                                      group_bools=view.get("group_bools"), show=view.get("show", "all"),
                                      search=view.get("search", ""), context=view.get("context"),
                                      hide_excluded=view.get("hide_excluded", False))
        dialog.setWindowTitle("Data selection — Ref Data")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reference_excluded = set(dialog.excluded)
            self._reference_selection_view = dialog.view_state()
            self.update_plan()
            self.document.refresh_identity()
        dialog.deleteLater()

    def _chart_records(self):
        raw = super()._chart_records()
        if not self._workbook_sources:
            return raw
        reference = participation_source_keys(_available_source_frame(self.reference_model))
        independent = self._independent_reference_rows() or (self._copy_reference_from_wkb and not self._copy_from_wkb)
        ref = tuple(("Reference", key) for key in reference) if independent else raw[:len(reference)]
        return (*ref, *raw)

    def _chart_source_rows(self, rows):
        if not self._workbook_sources:
            return set(rows), set()
        reference = _available_source_frame(self.reference_model)
        split = len(reference)
        independent = self._independent_reference_rows() or (self._copy_reference_from_wkb and not self._copy_from_wkb)
        raw = {row - split for row in rows if row >= split}
        ref = {row for row in rows if row < split}
        return (raw, ref) if independent else (raw | ref, set())

    def _change_chart_checks(self, rows, checked):
        if not self._workbook_sources:
            return super()._change_chart_checks(rows, checked)
        raw, independent = self._chart_source_rows(rows)
        reference = _available_source_frame(self.reference_model)
        keys = participation_source_keys(reference)
        before = set(self._reference_excluded)
        changed = {row for row in independent if 0 <= row < len(keys)
                   and (keys[row] in before) == checked}
        updated = {keys[row] for row in changed}
        if changed:
            self._reference_excluded = before - updated if checked else before | updated
        changed_raw = super()._change_chart_checks(raw, checked)
        if changed and not changed_raw:
            self.update_plan()
            self.document.refresh_identity()
        split = len(reference)
        return changed | {row for row in rows
                          if (row - split if row >= split else row) in changed_raw and row not in independent}

    def _write_chart_flags(self, rows, value):
        raw, reference = self._chart_source_rows(rows)
        if raw:
            super()._write_chart_flags(raw, value)
        if reference:
            self._write_sheet_flags(self.reference_model, reference, value)

    def _toggle_correlation_point(self, widget, row):
        if self.refresh_timer.isActive() or getattr(self, "_source_refresh_pending", False):
            return
        self._chart_edits.uncheck({row}, plot=widget)

    def set_workbook_plot_labels(self, options):
        self.display_options.set_workbook_labels(options)

    def restore_linked_workspace(self, snapshot):
        """Restore plot choices with the already prepared Workbook classification."""
        self._restore_reference_column_names(snapshot)
        previous = snapshot.states.pop("match_groups", None)
        current = self._match_groups
        if current is not None:
            snapshot.states["match_groups"] = deepcopy(current)
        if previous != current or current is not None:
            def measurement_key(key):
                parts = str(key).split(":", 2)
                return parts[2] if len(parts) == 3 and parts[0] == "group" and parts[1].isdigit() else key
            # Group span numbers are presentation keys, not source identities.
            # Reconcile to the same source measurement before applying boxes.
            available = {}
            for wafer in self.sequence_page.selection.get("wafers", ()):
                if isinstance(wafer, (tuple, list)) and len(wafer) == 2:
                    source, key = wafer
                    available.setdefault((source, measurement_key(key)), []).append(key)
            def keys(source, key):
                base = measurement_key(key)
                return available.get((source, base), [base if not self._group_plan or not self._group_plan.enabled else key])
            ui = snapshot.states["ui"]
            draw = ui.get("selection", {}).get("trend_draw", {})
            draw["cells"] = list(dict.fromkeys(
                (source, replacement, metric)
                for source, key, metric in draw.get("cells", ())
                for replacement in keys(source, key)))
            for page_name in ("sequence_page", "wafer_statistics_page"):
                page = ui.get("pages", {}).get(page_name, {})
                boxes = []
                for wafer, metric in page.get("boxes", ()):
                    if isinstance(wafer, (tuple, list)) and len(wafer) == 2:
                        boxes.extend(((wafer[0], key), metric) for key in keys(*wafer))
                    else:
                        boxes.append((wafer, metric))
                page["boxes"] = list(dict.fromkeys(boxes))
        self.restore_workspace(snapshot)

    def _restore_reference_column_names(self, snapshot):
        """Migrate linked legacy aliases without renaming Raw or changing any values."""
        ui = snapshot.states["ui"]
        selection = ui.get("selection", {})
        if selection.get("reference_column_names"):
            return
        current = self.reference_model.document_frame()
        owner = getattr(self, "_managed_owner", None)
        if current.empty and owner is not None:
            reference = owner.reference_frame
            raw = self.raw_model.document_frame()
            if not reference.empty and len(reference) == len(raw):
                current = _aligned_reference_frame(reference, raw)
        aliases = {mapping.name: mapping.reference_column for mapping in self._source_mappings
                   if mapping.name not in current.columns and mapping.reference_column in current.columns}
        stored = snapshot.frames.get("reference_data")
        if stored is not None and stored.shape == current.shape and stored.columns.is_unique:
            # Earlier linked snapshots lack explicit header provenance. Only
            # reconcile positional aliases when the entire literal column is
            # unchanged; never infer a correspondence from numeric similarity.
            for old, original in zip(stored.columns, current.columns):
                if (old not in current.columns and original not in stored.columns
                        and stored[old].equals(current[original])):
                    aliases[old] = original
        if stored is not None and aliases:
            renamed = stored.rename(columns=aliases)
            if not renamed.columns.is_unique:
                raise ValueError("Legacy Reference aliases are ambiguous; copy Workbook data again.")
            snapshot.frames["reference_data"] = renamed
        selection["reference_column_names"] = True
        if not aliases:
            return

        def metric(source, name):
            return aliases.get(name, name) if source == "Reference" else name

        reference = selection.get("reference", {})
        if "metrics" in reference:
            reference["metrics"] = list(dict.fromkeys(aliases.get(name, name) for name in reference["metrics"]))
        for field in ("correlation_draw", "trend_draw", "wafer_stats_draw"):
            draw = selection.get(field, {})
            if "cells" in draw:
                draw["cells"] = list(dict.fromkeys((source, key, metric(source, name))
                                                   for source, key, name in draw["cells"]))
        raw_columns = set(self.raw_model.document_frame().columns)
        for field in ("correlation_page", "sequence_page", "wafer_statistics_page"):
            page = ui.get("pages", {}).get(field, {})
            if "boxes" in page:
                page["boxes"] = [[wafer, metric(wafer[0], name)]
                                 if isinstance(wafer, (list, tuple)) and len(wafer) == 2 else [wafer, name]
                                 for wafer, name in page["boxes"]]
            active = page.get("parameter_filter")
            if active is not None:
                names = [active] if isinstance(active, str) else active
                updated = []
                for name in names:
                    updated.append(aliases.get(name, name))
                    if name in aliases and name in raw_columns:
                        updated.append(name)  # The former filter also matched this Raw parameter.
                updated = list(dict.fromkeys(updated))
                page["parameter_filter"] = updated[0] if len(updated) == 1 else updated
            for panel in page.get("source_overlay", []):
                panel["metric"] = metric(panel["source"], panel["metric"])
                for compare in panel.get("comparisons", []):
                    compare["metric"] = metric(compare["source"], compare["metric"])
            if "axis_directions" in page:
                directions = []
                for choice in page["axis_directions"]:
                    sources = choice["sources"]
                    if "Reference" in sources and (choice["x"] in aliases or choice["y"] in aliases):
                        directions.append({"sources": ["Reference"], "x": aliases.get(choice["x"], choice["x"]),
                                           "y": aliases.get(choice["y"], choice["y"])})
                        sources = [source for source in sources if source != "Reference"]
                    if sources:
                        directions.append({**choice, "sources": sources})
                page["axis_directions"] = directions

    def _restore_workspace_tables(self, snapshot):
        # Old selections refer to the previous source/Group keys. Drawing them
        # between the two table loads is both wasteful and temporarily wrong.
        self._restoring_source_tables = True
        try:
            if self.display_options is not None:
                self.display_options.restore(snapshot.states.get('correlation_display',{}))
            super()._restore_workspace_tables(snapshot)
        finally:
            self._restoring_source_tables = False
        self._match_groups = deepcopy(snapshot.states.get("match_groups"))
        # Install the saved sidebar choices before any derived source plan.
        # A wide Raw table may contain dozens of useful but unselected columns.
        self._apply_selection_state(snapshot.states.get("ui", {}).get("selection", {}))
        if not self.raw_model.duplicate_header_count() and not self.reference_model.duplicate_header_count():
            raw, reference = self.raw_model.frame(), self.reference_model.frame()
            if not raw.empty and ((not reference.empty and len(raw) == len(reference))
                                  or self._match_groups is not None):
                # restore_analysis_state recognizes both sources immediately
                # after installing the saved grouping choices. Avoid preparing
                # an intermediate plan with the previous sidebar first.
                self._workbook_sources = True
        # The base restore now applies the full UI once, after Group keys exist:
        # overlays, pending Draw choices, page index and saved boxes included.

    def _trend_source_parts(self, selection):
        """Reuse row ownership across sidebar checks, not across source/group edits."""
        cached = getattr(self, "_trend_parts_cache", None)
        plan = self._group_plan
        split = len(self.reference_model.frame())
        groups = selection["groups"]
        if cached is not None and cached[:2] == (plan, split) and cached[2] == groups:
            return cached[3]
        from .correlation_groups import prepare_trend_parts
        result = prepare_trend_parts(plan, split, groups)
        self._trend_parts_cache = (plan, split, groups.copy(), result)
        return result

    def _grouped_trend_selection(self, selection):
        if self.display_options is not None and not self.display_options.enabled.isChecked():
            return selection
        if "available_cells" not in selection or not self._match_groups or self._group_plan is None:
            return selection
        plan = self._group_plan
        if not plan.enabled and plan.state["trend_order"] == "groups":
            return selection
        grouped = {**selection, "wafers": [], "groups": {}, "labels": {},
                   "group_labels": {}, "combined_labels": {}, "wafer_caption_keys": set(),
                   "available_cells": set()}
        combined = {}
        for spec in plan.state["combined_groups"]:
            for member in spec["members"]:
                combined.setdefault(member, []).append(spec["name"])
        show_wafer = set(plan.state["show_wafer_groups"])
        metrics_by_key = {}
        for old_key, metric in selection["available_cells"]:
            metrics_by_key.setdefault(old_key, []).append(metric)
        parts_by_source, group_labels = self._trend_source_parts(selection)
        selected = set(selection["wafers"])
        source_keys = {}
        for source in selection["sources"]:
            name = source["name"]
            source_keys[name] = []
            parts, occurrences = parts_by_source[name]
            for n, span, matches in parts:
                for old_key, rows in matches:
                    if old_key not in selected:
                        continue
                    key = (old_key if not plan.enabled and occurrences[old_key] == 1
                           else (name, f"group:{n}:{old_key[1]}"))
                    grouped["wafers"].append(key)
                    grouped["groups"][key] = rows
                    grouped["labels"][key] = f"{name} · {span['label']}"
                    grouped["group_labels"][key] = group_labels[span["group"]]
                    if span["group"] in show_wafer:
                        grouped["wafer_caption_keys"].add(key)
                    if span["group"] in combined:
                        grouped["combined_labels"][key] = "\n".join(combined[span["group"]])
                    source_keys[name].append(key)
                    for metric in metrics_by_key.get(old_key, ()):
                        grouped["available_cells"].add((key, metric))
        grouped["sources"] = tuple({**source, "keys": tuple(source_keys[source["name"]])} for source in selection["sources"])
        grouped["preserve_group_order"] = True
        # Row preservation is independent of classification captions. A source
        # order without Groups must still display Wafer / LOT / PAD, not Heads.
        grouped["show_group_labels"] = plan.enabled
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
        reference_panel = self._build_reference_sheet_card()
        splitter.addWidget(reference_panel)
        from .floating_editor import FloatingEditor
        self.reference_floating_editor = FloatingEditor(
            self, reference_panel, self.reference_sheet, splitter,
            title="Reference table")
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
            "Paired Reference data from Wafer Alignment." if self.reference_sheet.read_only else
            "Editable Reference values and identities. Value-only imports can use identity fields from row-aligned Raw Data.",
        ))
        heading.addStretch()
        for title, callback in (
            ("New", lambda: self.set_reference_table(pd.DataFrame())),
            ("Open file", self.open_reference_file),
            ("Paste table", self.paste_reference_table),
            ("Export CSV", self.save_reference_csv),
        ):
            if self.reference_sheet.read_only and title != "Export CSV":
                continue
            control = QPushButton(title)
            control.setObjectName("primary" if title == "Open file" else "subtle")
            control.setFixedSize(104, 34)
            control.clicked.connect(callback)
            heading.addWidget(control)
        card_layout.addLayout(heading)
        card_layout.addWidget(self.reference_sheet, 1)
        self.reference_footer = QLabel("0 rows × 0 columns", objectName="hint")
        self.reference_footer.setAccessibleName('Reference table dimensions')
        self.reference_footer.setMinimumHeight(22)
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
        self.reference_wafer_count = label("No Wafers detected", "hint")
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
        try:
            self.set_reference_table(
                pd.DataFrame(matrix[1:], columns=matrix[0]), "Clipboard", report_paste=True
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to paste", str(error))

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
            frame = _reference_with_default_identity(
                self.reference_model.frame(), _available_source_frame(self.raw_model))
        except ValueError:
            self.reference_measurements = []
            self.reference_wafer_list.clear()
            self.reference_parameter_list.clear()
            self.reference_wafer_count.setText("Fix duplicate row-1 headers")
            self.reference_parameter_count.setText("Headers must be unique")
            return
        reset = self._reset_reference_selection
        select_new_identity = reset or not self.reference_measurements
        previous_wafers = set(self.selected(self.reference_wafer_list))
        previous_selected_rows = {row for measurement in self.reference_measurements
                                  if measurement.key in previous_wafers for row in measurement.rows}
        previous_metrics = set(self.selected(self.reference_parameter_list))
        previous_numeric = {self.reference_parameter_list.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
                            for index in range(self.reference_parameter_list.topLevelItemCount())
                            if self.reference_parameter_list.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole + 1)}
        previous_groups = self._reference_group_columns()
        detected_wafer, counts, metrics = inspect_table(frame)
        # A newly pasted Wafer field gets useful defaults. An existing field's
        # explicit grouping choice (including none) remains authoritative even
        # while the source has no recognizable measurements.
        reset_groups = reset or (detected_wafer is not None
                                 and detected_wafer not in self.reference_group_checks)
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
        if reset_groups:
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
        if reset_groups or list(self.reference_group_checks) != candidates:
            self._set_reference_group_columns([
                (column, column in chosen_groups) for column in candidates
            ])
        primary = next(
            (column for column in chosen_groups
             if normalize(column) in {"waferid", "wafer", "waferno"}),
            chosen_groups[0] if chosen_groups else None,
        )
        if primary and primary != detected_wafer:
            _wafer, counts, _metrics = inspect_table(frame, primary)
        self.reference_measurements = detect_measurements(
            frame, primary, chosen_groups, use_die_seq=False
        ) if primary else []
        chosen_metrics = (
            set(self.default_reference_parameters(metrics))
            if reset else previous_metrics | (set(self.default_reference_parameters(metrics)) - previous_numeric)
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
                if (select_new_identity or measurement.key in previous_wafers
                    or (measurement.rows and set(measurement.rows) <= previous_selected_rows))
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
        self._reset_reference_selection = frame.empty
        self._filter_reference_parameters()

    def set_reference_table(self, frame, source="Ref Data", *, report_paste=False):
        if report_paste:
            frame = self.reference_model.merge_clipboard_frame(frame)
        if not self.raw_model.duplicate_header_count() and not self._restoring_source_tables:
            frame = _reference_with_default_identity(frame, self.raw_model.frame())
        self._reset_reference_selection = True
        self.reference_model.load(frame.reset_index(drop=True), report_paste=report_paste)
        if report_paste and len(frame.columns):
            self.reference_sheet.mark_pasted_range((0, 0, len(frame), len(frame.columns) - 1))
        self._refresh_table_sizes()
        self.tabs.setCurrentWidget(self.reference_page)
        if self._restoring_source_tables:
            self._populate_reference_choices()
            return
        # Each source has its own identities and row positions. Unequal lengths
        # prevent implicit identity seeding, not independent Ref/Raw plots.
        self._rebuild_source_analysis()

    def change_tab(self, index):
        if index in (2, 3) and self.refresh_timer.isActive():
            self.recognize()

    def default_parameters(self, metrics):
        """Correlation starts with all useful numeric columns selected."""
        return [metric for metric in metrics if parameter_checked_by_default(metric)]

    def default_reference_parameters(self, metrics):
        return self.default_parameters(metrics)

    def set_table(self, frame, source, **kwargs):
        if kwargs.get("report_paste"):
            self.model.validate_clipboard_frame(frame)
        if not self._loading_workbook_sources:
            self._match_groups = None
            self._group_plan = None
            self._workbook_sources = ()
            self._source_mappings = ()
            self._analysis_frame = pd.DataFrame()
        super().set_table(frame, source, **kwargs)
        if (not self._loading_workbook_sources
                and not self._restoring_source_tables
                and hasattr(self, "reference_model")
                and not self.model.duplicate_header_count()
                and not self.reference_model.duplicate_header_count()
                and not self.reference_model.frame().empty
                and len(self.reference_model.frame()) == len(frame)):
            reference = self.reference_model.frame()
            seeded = _reference_with_default_identity(reference, frame)
            if not seeded.equals(reference):
                self.reference_model.load(seeded)
                self._reset_reference_selection = True
            self._rebuild_source_analysis()

    def set_sources(self, reference, raw, mappings, mode="Preview", *, align_reference=True):
        """Load row-aligned WKB sources without merging their visible tables."""
        self._source_mappings = tuple(mappings) if mappings is not None else ()
        self._match_groups = None
        self._group_plan = None
        if align_reference:
            self._reset_reference_selection = True
        reference_frame = (_aligned_reference_frame(reference, raw)
                           if align_reference and not reference.empty else reference.copy())
        prepared = getattr(self.raw_model, '_linked_prepared_load', None)
        prepared_source = prepared.get('source_frame') if prepared is not None else None
        source_matches = prepared_source is not None and (self.raw_model._prepared_source_matches(prepared, raw)
                                                        or prepared_source.equals(raw))
        raw_frame = prepared_source if source_matches else raw.reset_index(drop=True)
        same_raw = (bool(self._workbook_sources)
                    and self.raw_model.matches_document(raw if source_matches else raw_frame.fillna("").astype(str)))
        self._loading_workbook_sources = True
        try:
            if not same_raw:
                super().set_table(raw_frame, f"{mode} Raw Data", keep_local_selection=True)
            else:
                # Mapping/Card changes are not a replacement of Raw's editable
                # cells. Preserve their revision, selection and undo history.
                self.source_path = f"{mode} Raw Data"
                self.file_label.setText(self.source_path)
                self.file_label.setToolTip(self.source_path)
            if mappings is not None:
                self._set_checked_values(self.parameter_list, [mapping.raw_column for mapping in self._source_mappings])
            if not reference_frame.fillna("").astype(str).equals(self.reference_model.document_frame()):
                if not self.reference_model.update_headers(reference_frame):
                    self.reference_model.load(reference_frame)
            self._refresh_table_sizes()
        finally:
            self._loading_workbook_sources = False
        self._workbook_sources = True
        self._rebuild_source_analysis()
        # Loading Reference schedules the ordinary edit debounce, but both
        # sources have just been recognized synchronously. Do not recognize
        # them again after the new window becomes usable; later edits restart
        # this same timer normally.
        self.refresh_timer.stop()
        if not getattr(self, "_defer_plot_refresh", False):
            self.tabs.setCurrentIndex(0)
        self.setWindowTitle(f"{mode} Correlation and Trend")
        self.document.identity_timer.stop()
        self.document.refresh_identity()

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
        self.wafer_statistics_page.restore_axis_ratio(ratio)

    def set_trend_axis_mode(self, mode, *, show_control=False):
        """Apply the Match Workbook's auto/dual/single axis policy."""
        self.sequence_page.restore_axis_mode(mode)
        self.wafer_statistics_page.restore_axis_mode(mode)

    def selection_state(self):
        """Return independent Ref/Raw choices plus both page draw states."""
        if not hasattr(self, "reference_wafer_list"):
            return super().selection_state()
        return {
            "source_parameter_names": True,
            "reference_column_names": True,
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
            "wafer_stats_draw": self._encoded_draw_state(self.wafer_statistics_page),
            "trend_axis_ratio": self.sequence_page.axis_ratio_limit(),
            "trend_axis_mode": self.sequence_page.axis_mode_value(),
            "trend_axis_local": True,
            "mean_sigma_axis_ratio": self.wafer_statistics_page.axis_ratio_limit(),
            "mean_sigma_axis_mode": self.wafer_statistics_page.axis_mode_value(),
            "plot_decimal_places": self.plot_decimal_places.value(),
        }

    def _apply_selection_state(self, state):
        """Apply source choices without publishing a plan or drawing a page."""
        if not isinstance(state, dict):
            return
        if (not hasattr(self, "reference_wafer_list")
                or ("reference" not in state and "raw" not in state)):
            super()._apply_selection_state(state)
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

    def restore_selection(self, state):
        """Restore WKB choices, then redraw pages that succeeded previously."""
        if self._restoring_source_tables:
            return
        if not isinstance(state, dict) or not hasattr(self, "reference_wafer_list"):
            return
        if "reference" not in state and "raw" not in state:
            super().restore_selection(state)
            return
        self._apply_selection_state(state)
        self.update_plan()
        if state.get("trend_axis_local") or "trend_axis_mode" in state or "trend_axis_ratio" in state:
            self._local_axis_policy_loaded = True
            self.sequence_page.restore_axis_ratio(state.get("trend_axis_ratio"))
            self.sequence_page.restore_axis_mode(state.get("trend_axis_mode", "auto"))
            self.wafer_statistics_page.restore_axis_ratio(state.get("mean_sigma_axis_ratio", state.get("trend_axis_ratio")))
            self.wafer_statistics_page.restore_axis_mode(state.get("mean_sigma_axis_mode", state.get("trend_axis_mode", "auto")))
        decimals = state.get("plot_decimal_places", 3)
        if type(decimals) is int and 0 <= decimals <= 10:
            self.plot_decimal_places.setValue(decimals)
        # set_input queued automatic redraws of the old page choices. Saved
        # draw state supersedes them: Correlation processes Qt events while
        # fitting, which would otherwise run the Trend timer mid-restoration
        # and draw it again below with the actual saved boxes.
        for page in (self.correlation_page, self.sequence_page, self.wafer_statistics_page):
            page.input_refresh_timer.stop()
        # Earlier WKB draw states used match aliases for Raw parameters.
        legacy_raw_names = {} if state.get("source_parameter_names") else {
            mapping.name: mapping.raw_column for mapping in self._source_mappings
        }
        self._restore_page_draw(self.correlation_page,
            self._decoded_draw_state(state.get("correlation_draw"), legacy_raw_names)
        )
        self._restore_page_draw(self.sequence_page,
            self._decoded_draw_state(state.get("trend_draw"), legacy_raw_names)
        )
        self._restore_page_draw(self.wafer_statistics_page,
            self._decoded_draw_state(state.get("wafer_stats_draw"), legacy_raw_names)
        )

    def closeEvent(self, event):
        """Cancel deferred redraws before Qt disposes their controls."""
        from .export_job import finish_export_before_close
        if finish_export_before_close(self, event):
            return
        super().closeEvent(event)
        if not event.isAccepted():
            return
        self.reference_floating_editor.dock()
        if hasattr(self, "correlation_page"):
            self.correlation_page.input_refresh_timer.stop()
            self.correlation_page.update_timer.stop()
        if hasattr(self, "sequence_page"):
            self.sequence_page.input_refresh_timer.stop()
            self.sequence_page.compare_timer.stop()
        if hasattr(self, "wafer_statistics_page"):
            self.wafer_statistics_page.input_refresh_timer.stop()
            self.wafer_statistics_page.compare_timer.stop()

    def _rebuild_source_analysis(self):
        raw_analysis = _available_source_frame(self.raw_model)
        # A value-only Ref may become row-aligned after ordinary grid edits.
        # Derive its default identity from the current Raw for analysis only;
        # recognizing must not reload the literal table or clear its Undo.
        reference = _reference_with_default_identity(
            _available_source_frame(self.reference_model), raw_analysis)
        # Recognition and selector changes are read-only. Reloading this model
        # here used to overwrite edited identities and clear the undo history.
        if self.reference_model.literal_version is None:
            reference = reference.reset_index(drop=True).copy()
        # Parameter identity comes from its source tab, not the match alias.
        if self.raw_model.literal_version is None:
            raw_analysis = raw_analysis.reset_index(drop=True).copy()
        source_column = SOURCE_COLUMN
        while source_column in reference or source_column in raw_analysis:
            source_column = "_" + source_column
        reference.insert(0, source_column, "Reference")
        raw_analysis.insert(0, source_column, "Raw Data")
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
        self._workbook_sources = tuple(source for source in (
            {"name": "Reference", "color": REFERENCE_COLOR,
             "die_column": _first_column(reference, IDENTITY_COLUMNS[-1][1]),
             "identity_columns": {aliases[0]: _first_column(reference, aliases)
                                  for _target, aliases in IDENTITY_COLUMNS[:3]},
             "rows": tuple(range(split)), "keys": reference_keys},
            {"name": "Raw Data", "color": RAW_COLOR,
             "die_column": _first_column(raw_analysis, IDENTITY_COLUMNS[-1][1]),
             "identity_columns": {aliases[0]: _first_column(raw_analysis, aliases)
                                  for _target, aliases in IDENTITY_COLUMNS[:3]},
             "rows": tuple(range(split, len(self._analysis_frame))),
             "keys": raw_keys},
        ) if source["rows"])
        self._refresh_group_results()
        self.update_plan()

    def recognize(self):
        with self.input_update():
            super().recognize()
            if (self._loading_workbook_sources or self._restoring_source_tables
                    or not hasattr(self, "reference_model")):
                return
            reference = _available_source_frame(self.reference_model)
            explicit_identity = _first_column(reference, IDENTITY_COLUMNS[0][1]) is not None
            if self._workbook_sources or (not reference.empty and (
                    len(reference) == len(self._frame) or explicit_identity)):
                self._rebuild_source_analysis()
            else:
                self._populate_reference_choices()

    def update_plan(self, *_args):
        if self._input_update_depth:
            self._input_plan_pending = True
            return
        if self._restoring_source_tables or self._workbook_sources is True:
            return  # No provisional selection/plots between the two table loads.
        self._refresh_table_projection()
        if not self._workbook_sources:
            super().update_plan()
            return
        reference_wafers = set(self.selected(self.reference_wafer_list))
        raw_wafers = set(self.selected(self.wafer_list))
        reference_metrics = tuple(self.selected(self.reference_parameter_list))
        raw_metrics = tuple(self.selected(self.parameter_list))
        metrics = tuple(dict.fromkeys((*reference_metrics, *raw_metrics)))
        reference = _available_source_frame(self.reference_model)
        split = len(reference)
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
        raw = _available_source_frame(self.raw_model)
        allowed = self.participating_positions(raw)
        # Shared exclusions are row-aligned only when both tables have the
        # same extent. An empty Raw table must not exclude every Ref row.
        reference_allowed = (allowed if len(raw) == split and
                             (self._copy_from_wkb or not self._copy_reference_from_wkb) else
                             self._table_participating_positions("reference", reference))
        self.selection["groups"] = {key: tuple(row for row in rows
            if (row in reference_allowed if key[0] == "Reference" else row - split in allowed))
            for key, rows in self.selection["groups"].items()}
        self._publish_plot_inputs(self._analysis_frame, self.selection)
        self.statusBar().showMessage(
            f"{len(wafers)} measurement sets selected    ·    "
            f"{len(metrics)} parameters selected"
        )

    def _publish_plot_inputs(self, frame, selection):
        if not hasattr(self, "sequence_page"):
            super()._publish_plot_inputs(frame, selection)
            return
        trend_selection = self._grouped_trend_selection(selection)
        if self._point_edit_target is not None:
            widget, _row, removed = self._point_edit_target
            for page, updated in ((self.correlation_page, selection), (self.sequence_page, trend_selection)):
                if widget in page.plot_widgets and page.ready and not page.background_render_pending:
                    # Aligned Ref/Raw can both change from a single checkbox.
                    before = set(chain.from_iterable(page.selection.get("groups", {}).values()))
                    after = set(chain.from_iterable(updated.get("groups", {}).values()))
                    rows = before - after if removed else after - before
                    self.correlation_page.set_point_selection(selection)
                    self.sequence_page.set_point_selection(trend_selection)
                    self.wafer_statistics_page.set_point_selection(trend_selection)
                    if not rows or page.repaint_points(widget, rows, removed):
                        return
                    break
        self.correlation_page.set_input(frame, selection)
        self.sequence_page.set_input(frame, trend_selection)
        self.wafer_statistics_page.set_input(frame, trend_selection)


__all__ = ["CorrelationWindow", "RAW_COLOR", "REFERENCE_COLOR"]

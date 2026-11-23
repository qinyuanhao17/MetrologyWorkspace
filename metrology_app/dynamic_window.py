"""Dynamic-analysis workspace built on the shared editable data tab."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import QInputDialog

from . import dynamic_grr
from .data import die_sequence_column
from .dynamic import prepare_dynamic_frame
from .dynamic_detrend import METHODS, MIN_R_SQUARED, VALIDATION_HELP
from .dynamic_page import DynamicPage
from .dynamic_trend import DynamicTrendPage
from .window import MainWindow as DataWorkspaceWindow


class DynamicWindow(DataWorkspaceWindow):
    workspace_type = "dynamic"
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dynamic")
        # Dynamic owns its input; its menu exposes local Data selection only.
        # Retain the saved scope fields for existing WKB compatibility.
        self.data_menu.removeAction(self.workbook_selection_action)
        self.data_menu.removeAction(self.full_data_action)
        self.tabs.removeTab(2)
        self.tabs.removeTab(1)
        self.dynamic_page = DynamicPage()
        self.dynamic_page.data_point_edits = self._chart_edits
        self.dynamic_page.set_data_model(self.model)
        self.tabs.addTab(self.dynamic_page, "2. Dynamic")
        self.dynamic_trend = DynamicTrendPage()
        self.dynamic_trend.data_point_edits = self._chart_edits
        self.tabs.addTab(self.dynamic_trend, "3. Trend")
        self.analysis_menu = self.menuBar().addMenu("Analysis")
        detrend_menu = self.analysis_menu.addMenu("Detrend")
        detrend_menu.setToolTipsVisible(True)
        self.detrend_methods = QActionGroup(detrend_menu)
        for method, label in METHODS.items():
            action = detrend_menu.addAction(label)
            action.setCheckable(True)
            action.setData(method)
            if method != "raw":
                action.setToolTip(VALIDATION_HELP)
            self.detrend_methods.addAction(action)
            action.setChecked(method == "raw")
        self.detrend_methods.triggered.connect(self._detrend_changed)
        self.detrend_r_squared = MIN_R_SQUARED
        self.detrend_threshold_action = self.analysis_menu.addAction('Detrend Minimum R²…')
        self.detrend_threshold_action.triggered.connect(self._edit_detrend_threshold)
        self._update_detrend_threshold_label()
        self.show_detrend_fit = self.analysis_menu.addAction("Show Detrend Fit in Trend")
        self.show_detrend_fit.setCheckable(True)
        self.show_detrend_fit.triggered.connect(self._detrend_changed)
        self.refresh_timer.setInterval(50)
        self.update_plan()
        self.document.mark_clean()

    def _detrend_state(self):
        return {"method": self.detrend_methods.checkedAction().data(),
                "show_fit": self.show_detrend_fit.isChecked(), "min_r_squared": self.detrend_r_squared}

    def _update_detrend_threshold_label(self):
        self.detrend_threshold_action.setText(f'Detrend Minimum R² ({self.detrend_r_squared:.2f})…')

    def _edit_detrend_threshold(self):
        value, accepted = QInputDialog.getDouble(
            self, 'Detrend Minimum R²', 'Minimum fit R²', self.detrend_r_squared, 0., 1., 2)
        if accepted and value != self.detrend_r_squared:
            self.detrend_r_squared = value
            self._update_detrend_threshold_label()
            self._detrend_changed()

    def _detrend_changed(self, *_):
        self._apply_detrend()
        self.document.identity_timer.start()

    def _apply_detrend(self):
        state = self._detrend_state()
        method = state["method"]
        page = self.dynamic_page
        if (page.detrend_method, page.detrend_r_squared) != (method, self.detrend_r_squared):
            page.detrend_method = method
            page.detrend_r_squared = self.detrend_r_squared
            page.refresh()
        self.dynamic_trend.set_detrend_display(page.detrend_results, state["show_fit"])

    def is_parameter_selectable(self, column, numeric):
        return bool(numeric and str(column).strip().lower() != "cycle")

    def set_table(self, frame, source, **kwargs):
        frame = pd.DataFrame(frame)
        chosen = self.die_picker.currentData()
        column = chosen if chosen in frame.columns else die_sequence_column(frame.columns)
        prepared = prepare_dynamic_frame(frame, die_column=column) if column else frame.reset_index(drop=True)
        self.dynamic_page.set_baseline(prepared)
        super().set_table(prepared, source, **kwargs)

    def workspace_snapshot(self, *, include_drafts=False, readonly=False):
        snapshot = super().workspace_snapshot(include_drafts=include_drafts, readonly=readonly)
        page = getattr(self, "dynamic_page", None)
        if page is not None and page.grr_requested:
            snapshot.states["grr"] = page.grr_state()
        if hasattr(self, "detrend_methods"):
            state = self._detrend_state()
            if state["method"] != "raw" or state["show_fit"] or state["min_r_squared"] != MIN_R_SQUARED:
                snapshot.states["detrend"] = state
        return snapshot

    def restore_workspace(self, snapshot):
        self.dynamic_page.restore_grr(snapshot.states.get("grr"))
        super().restore_workspace(snapshot)
        state = snapshot.states.get("detrend", {})
        state = state if isinstance(state, dict) else {}
        method = state.get("method", "raw")
        if not isinstance(method, str) or method not in METHODS:
            method = "raw"
        for action in self.detrend_methods.actions():
            if action.data() == method:
                action.setChecked(True)
                break
        self.show_detrend_fit.setChecked(state.get("show_fit") is True)
        threshold = state.get("min_r_squared", MIN_R_SQUARED)
        self.detrend_r_squared = (float(threshold) if type(threshold) in (int, float) and 0 <= threshold <= 1
                                   else MIN_R_SQUARED)
        self._update_detrend_threshold_label()
        self._apply_detrend()

    def prepare_grr_save(self):
        if self.refresh_timer.isActive() and (
            self.dynamic_page.grr_requested or dynamic_grr.cached_template_path().is_file()
        ):
            self.recognize()

    def change_tab(self, index):
        if index >= 1 and self.refresh_timer.isActive():
            self.recognize()

    def update_plan(self, *_args):
        super().update_plan()
        if hasattr(self, "dynamic_page"):
            self.dynamic_page.set_input(self._frame, self.selection)
        if hasattr(self, "dynamic_trend"):
            self.dynamic_trend.set_input(self._frame, self.selection, self.dynamic_page.detrend_results)

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.dynamic_page.close_grr_preview()
            self.measurement_floating_editor.dock()


__all__ = ["DynamicWindow"]

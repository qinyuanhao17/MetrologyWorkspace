"""Dynamic-analysis workspace built on the shared editable data tab."""

from __future__ import annotations

from .dynamic import prepare_dynamic_frame
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
        self.refresh_timer.setInterval(50)
        self.update_plan()
        self.document.mark_clean()

    def is_parameter_selectable(self, column, numeric):
        return bool(numeric and str(column).strip().lower() != "cycle")

    def set_table(self, frame, source, **kwargs):
        prepared = prepare_dynamic_frame(frame)
        self.dynamic_page.set_baseline(prepared)
        super().set_table(prepared, source, **kwargs)

    def workspace_snapshot(self, *, include_drafts=False, readonly=False):
        snapshot = super().workspace_snapshot(include_drafts=include_drafts, readonly=readonly)
        page = getattr(self, "dynamic_page", None)
        if page is not None and page.grr_requested:
            snapshot.states["grr"] = page.grr_state()
        return snapshot

    def restore_workspace(self, snapshot):
        self.dynamic_page.restore_grr(snapshot.states.get("grr"))
        super().restore_workspace(snapshot)

    def prepare_grr_save(self):
        if self.dynamic_page.grr_requested and self.refresh_timer.isActive():
            self.recognize()

    def change_tab(self, index):
        if index >= 1 and self.refresh_timer.isActive():
            self.recognize()

    def update_plan(self, *_args):
        super().update_plan()
        if hasattr(self, "dynamic_page"):
            self.dynamic_page.set_input(self._frame, self.selection)
        if hasattr(self, "dynamic_trend"):
            self.dynamic_trend.set_input(self._frame, self.selection)

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.measurement_floating_editor.dock()


__all__ = ["DynamicWindow"]

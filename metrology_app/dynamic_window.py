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
        self.tabs.removeTab(2)
        self.tabs.removeTab(1)
        self.dynamic_page = DynamicPage()
        self.dynamic_page.set_data_model(self.model)
        self.tabs.addTab(self.dynamic_page, "2. Dynamic")
        self.dynamic_trend = DynamicTrendPage()
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

    def change_tab(self, index):
        if index >= 1 and self.refresh_timer.isActive():
            self.recognize()

    def update_plan(self, *_args):
        super().update_plan()
        if hasattr(self, "dynamic_page"):
            self.dynamic_page.set_input(self._frame, self.selection)
        if hasattr(self, "dynamic_trend"):
            self.dynamic_trend.set_input(self._frame, self.selection)


__all__ = ["DynamicWindow"]

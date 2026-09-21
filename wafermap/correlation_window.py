"""Loadable correlation-analysis workspace reusing the WaferMap data editor."""

from .correlation_page import CorrelationPage
from .window import MainWindow as DataWorkspaceWindow, parameter_checked_by_default


class CorrelationWindow(DataWorkspaceWindow):
    """The same Data tab followed by a pairwise lmfit plotting tab."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Correlation Analysis")
        self.tabs.removeTab(2)
        self.tabs.removeTab(1)
        self.correlation_page = CorrelationPage()
        self.tabs.addTab(self.correlation_page, "2. Pairwise Fit")
        self.update_plan()

    def change_tab(self, index):
        if index == 1 and self.refresh_timer.isActive():
            self.recognize()

    def default_parameters(self, metrics):
        """Correlation starts with all useful numeric columns selected."""
        return [metric for metric in metrics if parameter_checked_by_default(metric)]

    def update_plan(self, *_args):
        super().update_plan()
        if hasattr(self, "correlation_page"):
            self.correlation_page.set_input(self._frame, self.selection)


__all__ = ["CorrelationWindow"]

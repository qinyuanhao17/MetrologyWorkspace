"""Closing accepted child analyses must not stall the Workbook UI."""
from time import perf_counter
import unittest
from unittest.mock import patch
from threading import Event

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from metrology_app.matching_window import MatchingWindow
from metrology_app.matching import ParameterMapping
from metrology_app.window import MainWindow

APP = QApplication.instance() or QApplication([])


class AnalysisCloseTests(unittest.TestCase):
    def test_closing_during_noninterruptible_surface_work_does_not_wait_or_publish_late_results(self):
        entered, release = Event(), Event()
        window = MainWindow()
        worker = None
        def interpolation(*args, **kwargs):
            entered.set()
            release.wait(2)  # A single SciPy call cannot observe the cancellation flag.
            return None
        try:
            page = window.plot_page
            frame = pd.DataFrame({"Wafer ID": ["W1"]*4, "X(mm)": [-1, 1, -1, 1],
                                  "Y(mm)": [-1, -1, 1, 1], "CD": ["1.00"]*4})
            page.set_input(frame, {"wafers": ["W1"], "metrics": ["CD"], "wafer_column": "Wafer ID"})
            with patch("metrology_app.plot_page.prepare_array", side_effect=interpolation), \
                    patch.object(page, "render_result") as render:
                page.draw_maps()
                worker = page.worker
                self.assertIsNotNone(worker)
                self.assertTrue(entered.wait(1))
                start = perf_counter()
                window.close()
                elapsed = perf_counter()-start
                self.assertLess(elapsed, .25, "Closing waits for an in-progress interpolation")
                self.assertTrue(worker.isRunning())
                self.assertIsNone(worker.parent())
                release.set()
                self.assertTrue(worker.wait(3000))
                APP.processEvents()
                render.assert_not_called()
                page.finished()  # A stale event can have no surviving sender.
                from metrology_app.plot_page import _CANCELLED_JOBS
                self.assertNotIn(worker, _CANCELLED_JOBS)
        finally:
            release.set()
            if worker is not None:
                try:
                    worker.wait(3000)
                except RuntimeError:  # Already deleted by its completed-thread cleanup.
                    pass
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_closing_unchanged_managed_analyses_is_responsive_and_keeps_source(self):
        self.close_children(dirty=False)

    def test_closing_changed_analysis_state_is_responsive_and_keeps_source(self):
        self.close_children(dirty=True)

    def close_children(self, *, dirty):
        parent = MatchingWindow()
        children = []
        try:
            count = 3000
            values = np.arange(count, dtype=float)+10
            raw = pd.DataFrame({"Wafer ID": ["W1"]*count, "Die Seq": np.arange(count)%69+1,
                                "Cycle": np.arange(count)//69+1, "X(mm)": np.arange(count)%69,
                                "Y(mm)": np.arange(count)//69, "CD": [f"{v:.8f}" for v in values]})
            for column in range(30):
                raw[f"P{column}"] = [f"{v+column:.8f}" for v in values]
            parent.match_type.setCurrentText("NOVA")
            parent.set_reference_frame(pd.DataFrame({"CD Reference": values*1.02+.3}))
            parent.set_raw_frame(raw)
            parent._populate_mappings([ParameterMapping("CD", "CD Reference", "CD")])
            parent.run_analysis()
            children = [parent.open_stage_workspace("preview"), parent.open_correlation_workspace(),
                        parent.open_dynamic_workspace("preview")]
            QTest.qWait(150)
            original = parent.raw_model.document_frame().copy(deep=True)
            for child in children:
                child.document.mark_clean()
                if dirty:
                    child.tabs.setCurrentIndex(1)
                    self.assertTrue(child.document.is_dirty())
                start = perf_counter()
                child.close()
                elapsed = perf_counter()-start
                print(f"{child.workspace_type} close seconds: {elapsed:.6f}", flush=True)
                self.assertFalse(child.isVisible())
                self.assertLess(elapsed, .25, f"{child.workspace_type} close blocks the GUI")
            pd.testing.assert_frame_equal(parent.raw_model.document_frame(), original)
        finally:
            for child in children:
                child.document.force_close = True
                child.close()
            parent.document.force_close = True
            parent.close()
            parent.deleteLater()
            APP.processEvents()

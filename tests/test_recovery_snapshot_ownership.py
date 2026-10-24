"""Background recovery owns the exact state captured before later GUI edits."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
from time import monotonic
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app import recovery
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.match_groups import row_ids
from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_document import same_snapshot, unpack_snapshot
from metrology_app.workspace_store import WorkspaceSnapshot, file_revision, load_workspace


APP = QApplication.instance() or QApplication([])


class RecoverySnapshotOwnershipTests(unittest.TestCase):
    def wait_for(self, condition):
        deadline = monotonic() + 10
        while not condition() and monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), "Recovery did not reach the expected state")

    def test_independent_correlation_freezes_tables_and_nested_state_before_worker_reads(self):
        self.check_capture_isolation(managed=False)

    def test_managed_correlation_freezes_draft_and_accepted_basis_before_worker_reads(self):
        self.check_capture_isolation(managed=True)

    def check_capture_isolation(self, *, managed):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original_prepare = recovery._prepare

        def delayed_prepare(*args):
            entered.set()
            try:
                if not release.wait(10):
                    raise TimeoutError("test recovery read wait expired")
                return original_prepare(*args)
            finally:
                finished.set()

        raw = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["01", "02", "03"],
                            "CD": ["1.0000", "2.0000", "3.0000"]})
        reference = pd.DataFrame({"CD Reference": ["2.0000", "4.0000", "6.0000"]})
        mappings = [ParameterMapping("CD", "CD Reference", "CD")]
        book = MatchWorkbook(reference, raw, mappings, grouping_state={
            "enabled": False, "mark_enabled": True,
            "data_selection": {"records": [{"key": key, "id": str(row)}
                                             for row, key in enumerate(row_ids(raw))], "excluded": []}})
        owner = window = None
        with tempfile.TemporaryDirectory() as directory:
            try:
                if managed:
                    owner = MatchingWindow()
                    owner.set_reference_frame(reference)
                    owner.set_raw_frame(raw)
                    owner.run_analysis()
                    window = owner.open_correlation_workspace()
                else:
                    window = CorrelationWindow()
                    window.set_sources(reference, raw, mappings)
                window.set_workbook_groups(book)
                window._local_view = {"filters": [[{"column": "CD", "minimum": 1.0}]],
                                      "row_bools": [[]], "group_bools": [], "show": "filtered"}
                document = owner.document if managed else window.document
                extension = ".mwkb" if managed else ".wct"
                original = document.save(Path(directory) / ("accepted" + extension))
                original_revision = file_revision(original)
                document.recovery_path = Path(directory) / ("draft" + extension)
                document.timer.stop()
                APP.processEvents()
                column = window.raw_model.document_frame().columns.get_loc("CD")
                window.raw_model.edit({(1, column): "9.9900"})
                first_draft = window.workspace_snapshot()
                first_baseline = deepcopy(window.document.baseline)

                with patch.object(recovery, "_prepare", side_effect=delayed_prepare):
                    document.request_recovery()
                    self.wait_for(entered.is_set)
                    # The worker has not read its inputs yet. Every one of these
                    # objects remains editable in the GUI after capture returns.
                    window.raw_model.edit({(1, column): "11.5000"})
                    window._local_view["filters"][0][0]["minimum"] = 2.0
                    window._match_groups["grouping"]["data_selection"]["records"][0]["id"] = "later-record"
                    window.document.baseline.frames["raw_data"].iat[0, column] = "7.7700"
                    window.document.baseline.states["data_selection"]["view"]["filters"][0][0]["minimum"] = 3.0
                    release.set()
                    self.wait_for(lambda: not document.recovery_pending)

                scope = window._managed_scope if managed else None
                saved_draft, saved_baseline = self.recovered_parts(load_workspace(document.recovery_path), scope)
                self.assertTrue(same_snapshot(saved_draft, first_draft), "A later edit leaked into the captured draft")
                self.assertTrue(same_snapshot(saved_baseline, first_baseline), "The accepted basis was not detached")
                second_draft = window.workspace_snapshot()
                second_baseline = deepcopy(window.document.baseline)
                document.request_recovery()
                self.wait_for(lambda: not document.recovery_pending)
                saved_draft, saved_baseline = self.recovered_parts(load_workspace(document.recovery_path), scope)
                self.assertTrue(same_snapshot(saved_draft, second_draft), "The next request lost the latest edits")
                self.assertTrue(same_snapshot(saved_baseline, second_baseline))
                self.assertEqual(file_revision(original), original_revision)
            finally:
                release.set()
                if entered.is_set() and not finished.is_set():
                    self.wait_for(finished.is_set)
                for target in (window, owner):
                    if target is not None:
                        target.document.force_close = True
                        target.close()
                        target.deleteLater()
                APP.processEvents()

    @staticmethod
    def recovered_parts(snapshot, scope):
        info = snapshot.states["recovery"]
        if scope is not None:
            child = info["children"][scope]
            return unpack_snapshot(snapshot, child["draft"]), unpack_snapshot(snapshot, child["baseline"])
        draft = WorkspaceSnapshot(snapshot.workspace_type,
            {name: frame for name, frame in snapshot.frames.items() if not name.startswith("__recovery__.")},
            {name: value for name, value in snapshot.states.items() if name != "recovery"})
        return draft, unpack_snapshot(snapshot, info["baseline"])

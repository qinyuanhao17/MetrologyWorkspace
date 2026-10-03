"""Portable documents through the public save/load interface."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sqlite3
import os
import shutil
from contextlib import closing

import pandas as pd

from metrology_app.workspace_store import WorkspaceSnapshot, load_workspace, save_workspace


class WorkspaceStoreTests(unittest.TestCase):
    def test_backup_failure_preserves_the_formal_document(self):
        snapshot = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["1.00"]})})
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "dynamic.wdyn", snapshot)
            original = path.read_bytes()
            with patch.object(shutil, "copyfile", side_effect=OSError("backup unavailable")):
                with self.assertRaisesRegex(OSError, "backup unavailable"):
                    save_workspace(path, snapshot)
            self.assertEqual(path.read_bytes(), original)

    def test_lock_cleanup_failure_after_commit_does_not_report_unsaved(self):
        snapshot = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["2.00"]})})
        unlink = Path.unlink
        def unavailable_lock(path, *args, **kwargs):
            if path.suffix == ".lock":
                raise PermissionError("cleanup unavailable")
            return unlink(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, "unlink", unavailable_lock):
                saved = save_workspace(Path(directory) / "dynamic.wdyn", snapshot)
            self.assertEqual(load_workspace(saved).frames["input_data"].iloc[0, 0], "2.00")
            self.assertIsNotNone(snapshot.revision)

    def test_destination_changed_during_backup_is_not_overwritten(self):
        snapshot = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["1.00"]})})
        newer = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["3.00"]})})
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "dynamic.wdyn", snapshot)
            other = save_workspace(Path(directory) / "other.wdyn", newer)
            replace = os.replace
            def external_change(source, target):
                result = replace(source, target)
                if str(target).endswith(".bak"):
                    shutil.copyfile(other, path)
                return result
            with patch.object(os, "replace", side_effect=external_change):
                with self.assertRaisesRegex(ValueError, "changed in another"):
                    save_workspace(path, snapshot)
            self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "3.00")

    def test_wrong_extension_and_wrong_existing_type_are_refused(self):
        snapshot = WorkspaceSnapshot("wafer_map", {"input_data": pd.DataFrame()})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must be saved"):
                save_workspace(Path(directory) / "map.wdyn", snapshot)
            wrong = save_workspace(Path(directory) / "other.wdyn", WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame()}))
            wrong = wrong.rename(Path(directory) / "other.wmap")
            original = wrong.read_bytes()
            with self.assertRaises(ValueError):
                save_workspace(wrong, snapshot)
            self.assertEqual(wrong.read_bytes(), original)

    def test_each_document_uses_its_own_extension(self):
        for kind, suffix, frames, states in (
            ("match_workbook", ".wkb", {"reference": pd.DataFrame(), "raw": pd.DataFrame()}, {"match": {}}),
            ("wafer_map", ".wmap", {"input_data": pd.DataFrame()}, {}),
            ("dynamic", ".wdyn", {"input_data": pd.DataFrame()}, {}),
            ("correlation_trend", ".wct", {"reference_data": pd.DataFrame(), "raw_data": pd.DataFrame()}, {}),
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                saved = save_workspace(Path(directory) / "analysis.v1", WorkspaceSnapshot(kind, frames, states))
                self.assertEqual(saved.name, "analysis.v1" + suffix)
                self.assertEqual(load_workspace(saved).workspace_type, kind)

    def test_backup_and_conflict_keep_the_latest_accepted_file(self):
        old = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["1.00"]})})
        new = WorkspaceSnapshot("dynamic", {"input_data": pd.DataFrame({"CD": ["2.00"]})})
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "dynamic.wkb", old)
            revision = load_workspace(path).revision
            save_workspace(path, new, expected_revision=revision)
            pd.testing.assert_frame_equal(load_workspace(str(path) + ".bak").frames["input_data"], old.frames["input_data"])
            with self.assertRaisesRegex(ValueError, "changed in another"):
                save_workspace(path, old, expected_revision=revision)
            pd.testing.assert_frame_equal(load_workspace(path).frames["input_data"], new.frames["input_data"])
            self.assertFalse(Path(str(path) + ".lock").exists())

    def test_failed_write_leaves_original_and_removes_temporary_files(self):
        snapshot = WorkspaceSnapshot("wafer_map", {"input_data": pd.DataFrame({"CD": ["1"]})})
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "map.wkb", snapshot)
            original = path.read_bytes()
            with patch.object(pd.DataFrame, "to_sql", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    save_workspace(path, snapshot)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual([item.resolve() for item in Path(directory).iterdir()], [path])

    def test_wrong_type_newer_version_and_missing_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "map.wkb", WorkspaceSnapshot("wafer_map", {"input_data": pd.DataFrame()}))
            with self.assertRaises(ValueError):
                load_workspace(path, expected_type="dynamic")
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE workspace_manifest SET format_version=999")
            with self.assertRaisesRegex(ValueError, "version"):
                load_workspace(path)
            missing = Path(directory) / "missing.wkb"
            with self.assertRaises(FileNotFoundError):
                load_workspace(missing)
            self.assertFalse(missing.exists())

    def test_round_trip_keeps_measurement_text_duplicate_headers_and_state(self):
        frame = pd.DataFrame([
            ["001", "2.1000", "NA", "", "测试"],
            ["002", "-0.000", "3", "4", 'a"b'],
        ], columns=["Wafer ID", "CD", "CD", "cd", "__row_order__"])
        snapshot = WorkspaceSnapshot("wafer_map", {"input_data": frame},
                                     {"ui": {"columns": 2, "selected": ["CD"]}})
        with tempfile.TemporaryDirectory() as directory:
            path = save_workspace(Path(directory) / "measurements", snapshot)
            self.assertEqual(path.suffix, ".wmap")
            restored = load_workspace(path, expected_type="wafer_map")
            pd.testing.assert_frame_equal(restored.frames["input_data"], frame)
            self.assertEqual(restored.states, snapshot.states)
            self.assertEqual(restored.workspace_type, "wafer_map")


if __name__ == "__main__":
    unittest.main()

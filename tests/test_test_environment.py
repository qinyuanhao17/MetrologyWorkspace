"""The test runner must never inherit the application's persistence paths."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from run_tests import isolate_settings


class TestEnvironmentTests(unittest.TestCase):
    def test_legacy_file_entry_rejects_before_importing_app_with_user_paths(self):
        for name in ("benchmark_matching", "benchmark_workspace_store", "benchmark_match_groups",
                     "validate_workbook_fixtures"):
            with self.subTest(script=name), tempfile.TemporaryDirectory() as folder:
                sentinel = Path(folder) / "user-settings.yaml"
                sentinel.write_text("theme: light\n", encoding="utf-8")
                inherited = dict(os.environ, METROLOGY_SETTINGS_PATH=str(sentinel),
                                 METROLOGY_RECOVERY_DIR=folder, METROLOGY_REMINDERS_PATH=str(sentinel),
                                 MPLCONFIGDIR=folder)
                result = subprocess.run([sys.executable, str(Path("benchmarks") / (name + ".py")), "--help"],
                                        env=inherited, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("python -m benchmarks." + name, result.stderr)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "theme: light\n")
                self.assertEqual(list(Path(folder).iterdir()), [sentinel])

    def test_benchmark_module_entry_isolates_all_inherited_persistence_paths(self):
        keys = ("METROLOGY_SETTINGS_PATH", "METROLOGY_RECOVERY_DIR",
                "METROLOGY_REMINDERS_PATH", "MPLCONFIGDIR")
        inherited = dict(os.environ, **{key: "do-not-use-user-state" for key in keys})
        result = subprocess.run([sys.executable, "-c",
            "import benchmarks, os, json; "
            f"print(json.dumps({{key: os.environ[key] for key in {keys!r}}}))"],
            env=inherited, capture_output=True, text=True, check=True)
        environment = json.loads(result.stdout)
        paths = [Path(environment[key]) for key in keys]
        self.assertTrue(all(path.is_absolute() for path in paths))
        self.assertEqual(len({path.parent for path in paths}), 1)
        self.assertFalse(paths[0].parent.exists(), "Benchmark scratch must be removed at exit")

    def test_inherited_user_paths_are_replaced_by_one_scratch_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            user_file = Path(folder) / "user-settings.yaml"
            user_file.write_text("theme: light\n", encoding="utf-8")
            inherited = {key: str(user_file) for key in (
                "METROLOGY_SETTINGS_PATH", "METROLOGY_RECOVERY_DIR",
                "METROLOGY_REMINDERS_PATH", "MPLCONFIGDIR")}
            with patch.dict(os.environ, inherited):
                actual = isolate_settings(Path(folder) / "scratch")
                self.assertEqual(actual, Path(os.environ["METROLOGY_SETTINGS_PATH"]))
                for key in inherited:
                    self.assertEqual(Path(os.environ[key]).parent, actual.parent)
                self.assertNotEqual(actual, user_file)
                self.assertTrue(actual.parent.is_dir())
            self.assertEqual(user_file.read_text(encoding="utf-8"), "theme: light\n")

    def test_default_runs_do_not_share_mutable_settings_or_recovery(self):
        with patch.dict(os.environ):
            first = isolate_settings()
            second = isolate_settings()
            try:
                self.assertNotEqual(first.parent, second.parent)
            finally:
                for path in {first.parent, second.parent}:
                    if path.exists() and not any(path.iterdir()):
                        path.rmdir()

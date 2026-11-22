"""Run the unit test suite against a scratch settings file.

The application persists theme, recent workbooks and other preferences in one
YAML file. Tests exercise the same code paths. This runner overrides inherited
persistence paths with a fresh temporary directory before importing the app
(a saved light theme and Open Recent WKB list were once lost without isolation).

    python run_tests.py                    # whole suite
    python run_tests.py tests.test_settings -v
"""
import gc
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class IsolatedTextTestResult(unittest.TextTestResult):
    """Release Qt and persisted state between independent cases."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        self._app = app
        self._font = app.font() if app is not None else None
        self._palette = app.palette() if app is not None else None
        self._style_sheet = app.styleSheet() if app is not None else ""

    def stopTest(self, test):
        super().stopTest(test)
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            if app.font() != self._font:
                app.setFont(self._font)
            if app.palette() != self._palette:
                app.setPalette(self._palette)
            if app.styleSheet() != self._style_sheet:
                app.setStyleSheet(self._style_sheet)
        from metrology_app.recovery import wait_for_recovery
        wait_for_recovery(5)
        from metrology_app import settings
        try:
            settings.SETTINGS_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        settings.load_settings(settings.SETTINGS_PATH)
        gc.collect()


class IsolatedTextTestRunner(unittest.TextTestRunner):
    resultclass = IsolatedTextTestResult


def isolate_settings(directory=None):
    """Override inherited application paths before importing application code.

    Each invocation owns its directory: parallel runs must not share mutable
    settings, recovery candidates or reminders. Callers may supply a dedicated
    scratch directory, but production environment variables are never reused.
    """
    root = Path(directory or tempfile.mkdtemp(prefix="metrology-workspace-tests-"))
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / "settings.yaml"
    os.environ["METROLOGY_SETTINGS_PATH"] = str(scratch)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["METROLOGY_RECOVERY_DIR"] = str(root / "recovery")
    os.environ["METROLOGY_REMINDERS_PATH"] = str(root / "reminders.sqlite3")
    os.environ["MPLCONFIGDIR"] = str(root / "matplotlib")
    return scratch


def main(argv):
    # Windows TEMP may use an 8.3 alias; keep fixture and saved paths identical.
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    with tempfile.TemporaryDirectory(prefix="metrology-workspace-tests-") as directory:
        isolate_settings(directory)
        return isolated_suite(argv)


def isolated_suite(argv):
    # Fixture teardown must not wait for a human. Save/Cancel workflow tests
    # override this default locally and assert the actual document behavior.
    from PyQt6.QtWidgets import QMessageBox
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard), \
            patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        return run_suite(argv)


def run_suite(argv):
    if argv:
        program = unittest.main(
            module=None,
            argv=["run_tests.py", *argv],
            exit=False,
            testRunner=IsolatedTextTestRunner,
        )
        return 0 if program.result.wasSuccessful() else 1
    tests = str(Path(__file__).resolve().parent / "tests")
    suite = unittest.TestLoader().discover(tests)
    result = IsolatedTextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Run the unit test suite against a scratch settings file.

The application persists theme, recent workbooks and other preferences in one
YAML file. Tests exercise the same code paths, so running them without
METROLOGY_SETTINGS_PATH would rewrite the settings of whoever launched them
(that is how a saved light theme and the Open Recent WKB list were lost once).

    python run_tests.py                    # whole suite
    python run_tests.py tests.test_settings -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path


def isolate_settings():
    """Point the application at a scratch settings file for this process."""
    scratch = Path(tempfile.gettempdir()) / "metrology-workspace-tests" / "settings.yaml"
    os.environ.setdefault("METROLOGY_SETTINGS_PATH", str(scratch))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return scratch


def main(argv):
    isolate_settings()
    if argv:
        program = unittest.main(module=None, argv=["run_tests.py", *argv], exit=False)
        return 0 if program.result.wasSuccessful() else 1
    tests = str(Path(__file__).resolve().parent / "tests")
    suite = unittest.TestLoader().discover(tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

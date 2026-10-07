"""Time the source application's lazy shell startup in a fresh process.

python -m benchmarks.benchmark_startup
Run each sample in a new process; settings/cache/recovery are isolated.
No analysis window is opened. Offscreen timings are not frozen-EXE timings.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter


def main():
    with tempfile.TemporaryDirectory(prefix="metrology-startup-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["MPLCONFIGDIR"] = str(Path(scratch) / "matplotlib")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        start = perf_counter()
        from PyQt6.QtWidgets import QApplication
        from metrology_app.shell import MainWindow
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.settings import load_settings
        imported = perf_counter()
        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        configure_fonts(app)
        settings = load_settings()
        set_theme_palette(settings["theme"])
        window = MainWindow()
        window.show()
        app.processEvents()
        print(json.dumps({"imports_ms": (imported - start) * 1000,
                          "shell_visible_ms": (perf_counter() - start) * 1000,
                          "analysis_modules_loaded": [name for name in (
                              "metrology_app.matching_window", "metrology_app.window",
                              "metrology_app.correlation_window", "metrology_app.dynamic_window")
                              if name in sys.modules]}), flush=True)
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

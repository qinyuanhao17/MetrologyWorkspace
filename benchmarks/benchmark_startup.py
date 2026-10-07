"""Time the source application's lazy shell startup in a fresh process.

python -m benchmarks.benchmark_startup
Run each sample in a new process; settings/cache/recovery are isolated.
Optionally --wkb FILE also measures the shell's real first Open handler,
including its on-demand imports. Offscreen timings are not frozen-EXE timings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wkb', type=Path)
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest() if args.wkb else None
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
        if args.wkb:
            from PyQt6.QtCore import QTimer
            from PyQt6.QtTest import QTest
            ticks = [perf_counter()]
            timer = QTimer(interval=10)
            timer.timeout.connect(lambda: ticks.append(perf_counter()))
            timer.start()
            opened = perf_counter()
            component = window.load_path(args.wkb)
            callback = (perf_counter() - opened) * 1000
            app.processEvents()
            import pyqtgraph as pg
            plots = [p for p in component.findChildren(pg.PlotWidget) if p.isVisible()]
            for plot in plots:
                plot.viewport().repaint()
            deadline = opened + 30
            while any(getattr(item, 'render_pending', False)
                      for plot in plots for item in plot.listDataItems()):
                if perf_counter() > deadline:
                    raise AssertionError('The first Open did not finish full visible curves')
                QTest.qWait(5)
            for plot in plots:
                plot.viewport().repaint()
            component.repaint()
            visible = (perf_counter() - opened) * 1000
            QTest.qWait(150)
            assert component._analysis_current and component.result is not None
            print(json.dumps({'first_shell_wkb_callback_ms': callback,
                              'first_shell_wkb_visible_ms': visible,
                              'max_gap_ms': max(b-a for a, b in zip(ticks, ticks[1:])) * 1000,
                              'source_sha256': source_hash}), flush=True)
            timer.stop()
            component.document.timer.stop()
            component.document.identity_timer.stop()
            component.document.force_close = True
            component.close()
            app.processEvents()
            assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == source_hash
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

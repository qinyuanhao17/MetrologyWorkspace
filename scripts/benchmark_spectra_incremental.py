"""Repeat check/legend interactions on real SME data with fixed plot ranges."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-incremental-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_plots import SpectrumPlotPanel
        from metrology_app.spectra_viewer import SpectraViewerWindow

        app = QApplication([])
        window = SpectraViewerWindow()
        window.resize(1800, 1000)
        window.show()
        result = load_folder(args.folder)
        window.apply_load_result(result, replace=True)
        window.check_all_spectra()

        def settle():
            deadline = time.perf_counter() + 90
            for _ in range(4):
                QTest.qWait(5)
            while window.plot_render_pending and time.perf_counter() < deadline:
                QTest.qWait(5)
            assert not window.plot_render_pending

        settle()
        panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
        for panel in panels:
            panel.plot.setXRange(400, 600, padding=0)
            panel.plot.setYRange(-1, 1, padding=0)
        settle()
        source = result.spectra[0]
        window.select_spectrum_keys({source.key})
        settle()
        legend_key = window.legends["Mueller"].item(0).data(Qt.ItemDataRole.UserRole)
        ticks = []
        heartbeat = QTimer(interval=10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        heartbeat.start()
        report = {"spectra": len(result.spectra), "qt_platform": app.platformName(),
                  "device_pixel_ratio": window.devicePixelRatioF(), "actions": {}}
        original = SpectrumPlotPanel._add_group

        def timed(name, action):
            counts = []
            def add(panel, *args, **kwargs):
                counts.append(1)
                return original(panel, *args, **kwargs)
            ticks.clear()
            start = time.perf_counter()
            ticks.append(start)
            with patch.object(SpectrumPlotPanel, "_add_group", add):
                action()
                submit = time.perf_counter() - start
                settle()
            end = time.perf_counter()
            ticks.append(end)
            report["actions"][name] = {
                "submit_seconds": submit, "complete_seconds": end - start,
                "max_heartbeat_gap_seconds": max(b-a for a, b in zip(ticks, ticks[1:])),
                "new_curve_items": len(counts),
                "manual_range_preserved": all(
                    panel.plot.getViewBox().viewRange() == [[400, 600], [-1, 1]] for panel in panels),
            }
            print(name, report["actions"][name], flush=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

        for repeat in range(3):
            timed(f"uncheck_{repeat}", window.uncheck_selected_spectra)
            timed(f"recheck_{repeat}", window.check_selected_spectra)
            timed(f"legend_hide_{repeat}", lambda: window.toggle_channel(legend_key))
            timed(f"legend_show_{repeat}", lambda: window.toggle_channel(legend_key))
        heartbeat.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

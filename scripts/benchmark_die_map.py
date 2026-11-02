"""Compare full-page replacement with incremental point-checkbox updates.

Run with the application's Python environment and an SME source directory.
Both modes settle the initial page, toggle the same source five times and
include processing/painting the resulting page in the measured interval.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--mode", choices=("rebuild", "incremental"), default="incremental")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as scratch:
        from run_tests import isolate_settings
        isolate_settings(scratch)
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtTest import QTest
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_map import SpectraMapWindow
        app = QApplication([])
        data = load_folder(args.folder)
        window = SpectraMapWindow()
        window.resize(1600, 1000)
        window.show()
        checked = {s.key for s in data.spectra}
        window.set_data(data.spectra, checked_keys=checked)
        def settle():
            while window._pending_page_wafers:
                app.processEvents()
            QTest.qWait(15)
            window.grab()
        settle()
        QTest.qWait(250)
        window.grab()
        QTest.qWait(50)
        timings, replaced, stable = [], [], []
        for _ in range(5):
            plots = tuple(window.wafer_plots.values())
            sizes = [p.plot.size() for p in plots]
            checked.symmetric_difference_update({data.spectra[0].key})
            sources = tuple(replace(s) for s in data.spectra) if args.mode == "rebuild" else data.spectra
            start = time.perf_counter()
            window.set_data(sources, checked_keys=checked)
            settle()
            timings.append((time.perf_counter() - start) * 1000)
            replaced.append(any(a is not b for a, b in zip(plots, window.wafer_plots.values())))
            stable.append(sizes == [p.plot.size() for p in window.wafer_plots.values()])
        result = {"mode": args.mode, "spectra": len(data.spectra), "maps": len(window.wafer_plots),
                  "milliseconds": timings, "median_ms": sorted(timings)[2],
                  "plots_replaced": replaced, "final_sizes_stable": stable}
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()

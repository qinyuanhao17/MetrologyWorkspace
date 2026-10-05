"""Repeatable grouped workbook edit/undo benchmark and styled UI inspection.

Run: python benchmarks/benchmark_match_groups.py [--table pasted.tsv] [--render]
Settings/recovery always use a temporary directory, never the user's preferences.
"""
import argparse
import csv
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

scratch = Path(tempfile.mkdtemp(prefix="metrology-groups-"))
os.environ["METROLOGY_SETTINGS_PATH"] = str(scratch / "settings.yaml")
os.environ["METROLOGY_RECOVERY_DIR"] = str(scratch / "recovery")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from metrology_app.match_group_ui import split_combined_table
from metrology_app.match_groups import row_ids
from metrology_app.matching_window import MatchingWindow
from metrology_app.settings import apply_theme, save_settings
from metrology_app.appearance import configure_fonts, set_theme_palette


def fixture(n=3000):
    x = np.linspace(20, 30, n)
    raw = pd.DataFrame({"Wafer ID": [f"W{i // 30:03d}" for i in range(n)],
                        "Lot ID": ["L1"] * n, "PAD Name": ["ARRAY"] * n,
                        "Die Seq": np.arange(n) % 30 + 1})
    reference = pd.DataFrame()
    for p in range(4):
        raw[f"P{p}"] = x + p
        reference[f"P{p} Reference"] = (1 + p * .05) * x + p + np.sin(x) * .01
    return reference, raw, pd.DataFrame({"TestFlag": np.arange(n) % 3 - 1})


def load_table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        matrix = list(csv.reader(stream, delimiter="\t"))
    roles = ["TestFlag", "Ignore"] + ["Raw Data"] * (len(matrix[0]) - 2)
    # Explicit user-source schema: first OCD_DEPTH1 is Ref, second is Raw.
    roles[16] = "Reference"
    return split_combined_table(matrix, roles)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    window = MatchingWindow()
    ref, raw, flags = load_table(args.table) if args.table else fixture()
    if args.table:
        window._import_group_frames(ref, raw, flags)
    else:
        window.set_reference_frame(ref)
        window.set_raw_frame(raw)
    window.group_controls.restore({"enabled": True, "head_names": {"0": "Head A", "1": "Head B", "-1": "Unknown"}}, flags)
    window.run_analysis()
    print("rows", len(raw), "flags", flags.iloc[:, 0].astype(str).value_counts().to_dict(),
          "sets", len(window.result.group_plan.measurements))
    column = next(m.raw_column for m in window.workbook.mappings)
    column_index = raw.columns.get_loc(column)
    original = window.raw_model.cells[(1, column_index)]
    for label, rebuild in (("forced full rebuild", True), ("affected plots only", False)):
        times = []
        for i in range(args.iterations):
            if rebuild:
                window._plot_layout_key = None
            start = time.perf_counter()
            window.raw_model.edit({(1, column_index): str(float(original) + .001 * (i + 1))})
            app.processEvents()
            if rebuild:
                window._plot_layout_key = None
            window.raw_model.undo.undo()
            app.processEvents()
            times.append(time.perf_counter() - start)
        print(label, "median edit+undo seconds", round(statistics.median(times), 4), "samples", [round(t, 4) for t in times])
    if args.render:
        ref, raw, flags = fixture(15)
        raw["Wafer ID"] = ["W1"] * 5 + ["W2"] * 5 + ["W3"] * 5
        flags["TestFlag"] = [0] * 5 + [1] * 5 + [-1] * 5
        for theme in ("light", "dark"):
            save_settings({"theme": theme})
            set_theme_palette(theme)
            apply_theme(window, theme)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "new_rows": list(row_ids(raw)[5:10]),
                                           "head_names": {"0": "Head A", "1": "Head B", "-1": "Unknown"}}, flags)
            window.run_analysis()
            window.resize(1500, 950)
            window.show()
            app.processEvents()
            path = scratch / f"setup-{theme}.png"
            window.grab().save(str(path))
            print(path)
            window.results_tabs.setCurrentWidget(window.group_plot_page)
            app.processEvents()
            path = scratch / f"groups-{theme}.png"
            window.group_plot_page.page_image().save(str(path))
            print(path)
    window.document.identity_timer.stop()
    window.document.timer.stop()
    window.hide()
    window.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()

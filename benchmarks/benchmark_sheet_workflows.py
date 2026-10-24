"""Synthetic sheet keyboard baseline with exact text and one-step Undo checks.

python -m benchmarks.benchmark_sheet_workflows --output .cache/sheets.json
Separate from full-workbook analysis latency; offscreen timings are not FPS.
"""
import argparse
import cProfile
import csv
import json
import math
import os
from io import StringIO
from pathlib import Path
import statistics
import sys
import pstats
from time import perf_counter, process_time

from .benchmark_correlation_restore import digest, memory_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[1000, 10000, 100000])
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--profile-actions", nargs="*", default=[],
                        help="Profile selected operations separately from acceptance timings")
    args = parser.parse_args()
    if args.count < 1 or any(rows < 1 for rows in args.rows):
        parser.error("Row counts and repetition count must be positive")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(args.code_root.resolve()))
    import pandas as pd
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from metrology_app.match_group_ui import ProjectedSheetModel
    from metrology_app.sheet import SheetModel, SheetView
    import metrology_app
    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    settings = Path(__file__).resolve().parents[1] / "config/settings.yaml"
    before = digest(settings)
    samples = []
    for rows in args.rows:
        frame = pd.DataFrame({"Wafer ID": [f"W{i // 20:06}" for i in range(rows)],
                              "Die Seq": [f"{i % 20 + 1:02}" for i in range(rows)],
                              "CD": ["1.123456789000000"] * rows,
                              "Depth": ["" if i % 7 == 0 else "2.000000000000001" for i in range(rows)]})
        for iteration in range(args.count):
            model, target = SheetModel(), SheetModel()
            model.load(frame)
            view, destination = SheetView(model), SheetView(target)
            projected = ProjectedSheetModel(model)
            visible_rows = list(range(rows - 1, -1, -2))
            projected.set_rows(visible_rows)
            projection = SheetView(projected)
            views = (view, destination, projection)
            for widget in views:
                widget.resize(850, 330)
                widget.show()
            app.processEvents()

            def measure(name, widget, key, control=True):
                ticks = []
                timer = QTimer(interval=10)
                timer.timeout.connect(lambda: ticks.append(perf_counter()))
                timer.start()
                profiler = cProfile.Profile() if name in args.profile_actions else None
                if profiler is not None:
                    profiler.enable()
                cpu, start = process_time(), perf_counter()
                ticks.append(start)
                QTest.keyClick(widget, key, Qt.KeyboardModifier.ControlModifier
                               if control else Qt.KeyboardModifier.NoModifier)
                app.processEvents()
                end = perf_counter()
                ticks.append(end)
                timer.stop()
                if profiler is not None:
                    profiler.disable()
                samples.append({"rows": rows, "iteration": iteration, "operation": name,
                                "wall_ms": (end - start) * 1000,
                                "cpu_ms": (process_time() - cpu) * 1000,
                                "max_gap_ms": max(b - a for a, b in zip(ticks, ticks[1:])) * 1000,
                                **memory_info()})
                if profiler is not None:
                    report = args.output.with_name(f"{args.output.stem}-{rows}-{iteration}-{name}.profile.txt")
                    with report.open("w", encoding="utf-8") as stream:
                        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)

            try:
                measure("select_all", view, Qt.Key.Key_A)
                measure("copy", view, Qt.Key.Key_C)
                copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
                assert copied == [list(frame.columns), *frame.values.tolist()]
                destination.setCurrentIndex(target.index(0, 0))
                measure("paste", destination, Qt.Key.Key_V)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                assert target.undo.count() == 1
                measure("undo", destination, Qt.Key.Key_Z)
                assert target.document_frame().empty and target.undo.index() == 0
                measure("redo", destination, Qt.Key.Key_Y)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                destination.selectAll()
                measure("delete", destination, Qt.Key.Key_Delete, control=False)
                assert target.document_frame().empty
                measure("undo_delete", destination, Qt.Key.Key_Z)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                measure("projected_select_all", projection, Qt.Key.Key_A)
                measure("projected_copy", projection, Qt.Key.Key_C)
                copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
                assert copied == [list(frame.columns), *frame.iloc[visible_rows].values.tolist()]
                pd.testing.assert_frame_equal(model.document_frame(), frame)
                assert model.undo.isClean()
                print(json.dumps({"rows": rows, "iteration": iteration, "exact_text_and_undo": "pass"}), flush=True)
            finally:
                for widget in views:
                    widget.close()
                    widget.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
    assert digest(settings) == before, "Real settings changed during the benchmark"
    summary = []
    for rows, name in dict.fromkeys((row["rows"], row["operation"]) for row in samples):
        group = [row for row in samples if row["rows"] == rows and row["operation"] == name]
        result = {"rows": rows, "operation": name, "count": len(group)}
        for key in ("wall_ms", "cpu_ms", "max_gap_ms", "rss", "private", "peak"):
            values = sorted(row[key] for row in group if row[key] is not None)
            result[key] = ({"p50": statistics.median(values),
                            "p95": values[math.ceil(len(values) * .95) - 1], "max": max(values)}
                           if values else None)
        summary.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"count": args.count, "columns": 4,
                                      "code_root": str(args.code_root.resolve()),
                                      "profile_actions": args.profile_actions,
                                      "fixture": "Exact text; repeated wafers/dies; high precision; empty values",
                                      "measurement": "Same-process repetitions, fresh views; process peak includes setup",
                                      "settings_sha256": before, "samples": samples, "summary": summary}, indent=2),
                           encoding="utf-8")


if __name__ == "__main__":
    main()

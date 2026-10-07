"""Read-only real-WKB UI benchmark. Outputs JSON; never saves the source file.

python -m benchmarks.benchmark_workbook_interaction --wkb FILE --iterations 3
Use --profile to attribute time, --budget-ms to make a repeatable failing probe.
Timings are offscreen CPU/event-loop measurements, not monitor frame rates.
"""
import argparse
import cProfile
import json
import os
from pathlib import Path
import statistics
import tempfile
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--budget-ms", type=float)
    parser.add_argument("--mode", choices=("cell", "bulk"), default="cell")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="metrology-performance-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        start = perf_counter()
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        imports_ms = (perf_counter() - start) * 1000
        app = QApplication.instance() or QApplication([])
        start = perf_counter()
        window = MatchingWindow()
        construction_ms = (perf_counter() - start) * 1000
        profiler = cProfile.Profile()
        if args.profile:
            profiler.enable()
        start = perf_counter()
        window.load_workbook(args.wkb)
        app.processEvents()
        open_ms = (perf_counter() - start) * 1000
        window.resize(1500, 950)
        window.show()
        app.processEvents()
        model = window.final_raw_model if window.workbook.result_mode == "final" else window.raw_model
        raw = window._active_raw_frame()
        column = raw.columns.get_loc(window.workbook.mappings[0].raw_column)
        original = model.cells[(1, column)]
        matrix = [list(raw.columns)] + raw.fillna("").astype(str).values.tolist()
        edit_ms, undo_ms, gaps = [], [], []
        last_tick = perf_counter()

        def tick():
            nonlocal last_tick
            now = perf_counter()
            gaps.append((now - last_tick) * 1000)
            last_tick = now

        heartbeat = QTimer(interval=10)
        heartbeat.timeout.connect(tick)
        heartbeat.start()
        for i in range(args.iterations):
            start = perf_counter()
            value = str(float(original) + .001 * (i + 1))
            if args.mode == "bulk":
                matrix[1][column] = value
                model.replace_matrix(matrix)
            else:
                model.edit({(1, column): value})
            app.processEvents()
            # Dirty-title timer is part of the real post-edit workflow.
            window.document.identity_timer.stop()
            window.document.refresh_identity()
            app.processEvents()
            edit_ms.append((perf_counter() - start) * 1000)
            start = perf_counter()
            model.undo.undo()
            app.processEvents()
            window.document.identity_timer.stop()
            window.document.refresh_identity()
            app.processEvents()
            undo_ms.append((perf_counter() - start) * 1000)
        heartbeat.stop()
        profiler.disable()
        metrics = {"file": args.wkb.name, "mode": args.mode, "rows": len(raw), "columns": len(raw.columns),
                   "parameters": len(window.workbook.mappings), "imports_ms": imports_ms,
                   "construction_ms": construction_ms, "open_ms": open_ms,
                   "edit_ms": edit_ms, "undo_ms": undo_ms,
                   "edit_median_ms": statistics.median(edit_ms),
                   "max_event_loop_gap_ms": max(gaps, default=0)}
        print(json.dumps(metrics, ensure_ascii=False), flush=True)
        if args.profile:
            import pstats
            pstats.Stats(profiler).strip_dirs().sort_stats("cumtime").print_stats(35)
        window.document.identity_timer.stop()
        window.document.timer.stop()
        window.hide()
        window.deleteLater()
        app.processEvents()
        if args.budget_ms is not None and metrics["edit_median_ms"] > args.budget_ms:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

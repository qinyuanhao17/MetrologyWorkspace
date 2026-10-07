"""Read-only WKB recovery probe with scratch settings and recovery files.

python -m benchmarks.benchmark_workbook_recovery --wkb FILE [--iterations 3] [--profile]
Use --automatic to measure timer-style recovery and GUI heartbeat gaps.
This never saves the input and does not measure monitor FPS.
"""
import argparse
import cProfile
import hashlib
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
    parser.add_argument("--profile", action="store_true", help="Profile repeat checks, excluding the first write")
    parser.add_argument("--budget-ms", type=float)
    parser.add_argument("--automatic", action="store_true", help="Measure automatic background recovery (old source falls back to sync)")
    args = parser.parse_args()
    if args.iterations < 1 or (args.profile and args.iterations < 2):
        parser.error("Use at least one callback, or two to profile repeat checks")
    if args.profile and args.automatic:
        parser.error("Profile the sync path separately; cProfile would omit the background thread")
    original_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="metrology-recovery-probe-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer
        from PyQt6.QtTest import QTest
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_store import load_workspace
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.load_workbook(args.wkb)
            app.processEvents()
            window.document.timer.stop()
            raw = window._active_raw_frame()
            model = window.final_raw_model if window.workbook.result_mode == "final" else window.raw_model
            column = raw.columns.get_loc(window.workbook.mappings[0].raw_column)
            value = str(float(model.cells[(1, column)]) + .001)
            model.edit({(1, column): value})
            app.processEvents()
            window.document.identity_timer.stop()
            window._plot_layout_identity_timer.stop()
            times, stamps, completion, gaps = [], [], [], []
            profiler = cProfile.Profile()
            heartbeat = QTimer(window, interval=20)
            ticks = []
            heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
            for iteration in range(args.iterations):
                if args.profile and iteration == 1:
                    profiler.enable()
                ticks.clear()
                if args.automatic:
                    heartbeat.start()
                    QTest.qWait(25)
                    ticks[:] = [perf_counter()]
                start = perf_counter()
                callback = (getattr(window.document, "request_recovery", window.document.write_recovery)
                            if args.automatic else window.document.write_recovery)
                callback()
                times.append((perf_counter() - start) * 1000)
                if args.automatic:
                    deadline = start + 60
                    while getattr(window.document, "recovery_pending", False) and perf_counter() < deadline:
                        QTest.qWait(5)
                    assert not getattr(window.document, "recovery_pending", False), "Recovery timed out"
                completion.append((perf_counter() - start) * 1000)
                if args.automatic:
                    QTest.qWait(25)
                    heartbeat.stop()
                    gaps.append(max((right - left for left, right in zip(ticks, ticks[1:])), default=0) * 1000)
                stamps.append(window.document.recovery_path.stat().st_mtime_ns)
            profiler.disable()
            saved = load_workspace(window.document.recovery_path)
            frame_name = "final_match_raw" if window.workbook.result_mode == "final" else "raw"
            assert saved.frames[frame_name].iloc[0, column] == value
            assert len(saved.frames[frame_name]) == len(raw)
            assert saved.states["recovery"]["payload_version"] == 2
            metrics = {"file": args.wkb.name, "rows": len(raw), "columns": len(raw.columns),
                       "callback_ms": times, "repeat_median_ms": statistics.median(times[1:] or times),
                       "completion_ms": completion, "heartbeat_maxgap_ms": gaps,
                       "file_rewrites": len(set(stamps)), "recovery_bytes": window.document.recovery_path.stat().st_size}
            print(json.dumps(metrics), flush=True)
            if args.profile:
                import pstats
                pstats.Stats(profiler).strip_dirs().sort_stats("cumtime").print_stats(30)
            if args.budget_ms is not None and metrics["repeat_median_ms"] > args.budget_ms:
                raise SystemExit(1)
        finally:
            window.document.force_close = True
            window.document.identity_timer.stop()
            window.document.timer.stop()
            window.close()
            window.deleteLater()
            app.processEvents()
            assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == original_hash


if __name__ == "__main__":
    main()

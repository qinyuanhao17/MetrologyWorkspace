"""Exact Dirty/title checks on a read-only real workbook, with isolated settings.

python -m benchmarks.benchmark_dirty_checks --wkb FILE --output .cache/dirty.json
Setup/edit/analysis time is excluded: this measures the subsequent Dirty check.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
from time import perf_counter, process_time

from .benchmark_correlation_restore import digest, memory_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    sys.path.insert(0, str(args.code_root.resolve()))
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.workspace_store import json_text
    import metrology_app
    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()

    settings = Path(__file__).resolve().parents[1] / "config/settings.yaml"
    settings_hash, source_hash = digest(settings), digest(args.wkb)
    app = QApplication.instance() or QApplication([])
    window = MatchingWindow()
    samples = []

    def settle():
        QTest.qWait(160)
        window.document.timer.stop()
        window.document.identity_timer.stop()
        window._plot_layout_identity_timer.stop()

    def measure(name, expected, *, title=False):
        for iteration in range(args.count):
            ticks = [perf_counter()]
            heartbeat = QTimer(interval=10)
            heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
            heartbeat.start()
            cpu, start = process_time(), perf_counter()
            if title:
                window.document.refresh_identity()
                dirty = window.isWindowModified()
            else:
                dirty = window.document.is_dirty()
            end, cpu_end = perf_counter(), process_time()
            app.processEvents()
            ticks.append(perf_counter())
            heartbeat.stop()
            assert dirty is expected, (name, dirty, expected)
            samples.append({"case": name, "iteration": iteration, "dirty": dirty,
                            "wall_ms": (end - start) * 1000,
                            "cpu_ms": (cpu_end - cpu) * 1000,
                            "max_gap_ms": max(b - a for a, b in zip(ticks, ticks[1:])) * 1000,
                            **memory_info()})
        print(json.dumps({"case": name, "checks": args.count, "dirty": expected}), flush=True)

    try:
        window.load_workbook(args.wkb)
        window.run_analysis()
        settle()
        model = window.final_raw_model if window.workbook.result_mode == "final" else window.raw_model
        column = model.source_headers().index(window.workbook.mappings[0].raw_column)
        original_frame = model.document_frame()
        # Old saved group metadata can normalize its order on the first edit.
        # Warm up that existing behavior before establishing the accepted basis.
        model.edit({(1, column): str(float(model.cells[(1, column)]) + .001)})
        settle()
        model.undo.undo()
        settle()
        assert model.document_frame().equals(original_frame)
        window.document.mark_clean()
        rows = len(window.raw_model.document_frame())
        measure("clean", False)
        measure("clean_title", False, title=True)
        model.edit({(1, column): str(float(model.cells[(1, column)]) + .001)})
        settle()
        measure("raw_edit", True)
        model.undo.undo()
        settle()
        assert model.document_frame().equals(original_frame)
        measure("raw_undo", False)

        selected = next(i for i in range(window.mapping_table.rowCount())
                        if window.mapping_table.item(i, 0).checkState() == Qt.CheckState.Checked)
        window.mapping_table.item(selected, 0).setCheckState(Qt.CheckState.Unchecked)
        settle()
        measure("mapping_off", True)
        window.mapping_table.item(selected, 0).setCheckState(Qt.CheckState.Checked)
        settle()
        # Rechecking a mapping can retain changed plot/selection metadata. Use
        # the original encoder as the oracle, never assume that checkbox Undo
        # also undoes those independent document controls.
        current = window.workspace_snapshot(readonly=True, validate=False)
        baseline = window.document.baseline
        expected = not (current.frames.keys() == baseline.frames.keys()
                        and all(frame.equals(baseline.frames[name]) for name, frame in current.frames.items())
                        and json_text(current.states) == json_text(baseline.states))
        measure("mapping_rechecked", expected)
        window.document.mark_clean()

        # Baselines remain mutable: an identity/revision cache cannot prove this
        # check clean. Compare a late record edit and its exact restoration.
        records = window.document.baseline.states["match"]["grouping_state"]["data_selection"]["records"]
        old = records[-1]["id"]
        records[-1]["id"] = "changed-baseline-record"
        measure("baseline_record_edit", True)
        records[-1]["id"] = old
        measure("baseline_restored", False)
    finally:
        window.document.force_close = True
        window.close()
        window.deleteLater()
        app.processEvents()
        assert digest(settings) == settings_hash, "Real settings changed"
        assert digest(args.wkb) == source_hash, "Source workbook changed"

    summary = []
    for name in dict.fromkeys(row["case"] for row in samples):
        group = [row for row in samples if row["case"] == name]
        result = {"case": name, "count": len(group)}
        for key in ("wall_ms", "cpu_ms", "max_gap_ms", "rss", "private", "peak"):
            values = sorted(row[key] for row in group if row[key] is not None)
            result[key] = ({"p50": statistics.median(values),
                            "p95": values[math.ceil(len(values) * .95) - 1], "max": max(values)}
                           if values else None)
        summary.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"code_root": str(args.code_root.resolve()), "rows": rows,
                                      "source_sha256": source_hash, "settings_sha256": settings_hash,
                                      "samples": samples, "summary": summary}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

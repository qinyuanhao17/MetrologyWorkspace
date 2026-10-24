"""NOVA 0/1/3/5 named-window sync matrix using existing isolated probe helpers.

Each scale runs in its own process. Correlation pages are drawn; mixed probes
also include undrawn Map and independent empty Dynamic editors. No source save.
"""
import argparse
from contextlib import ExitStack
import cProfile
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter, process_time
from unittest.mock import patch

from .benchmark_correlation_restore import digest, memory_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", type=Path, required=True)
    parser.add_argument("--children", type=int, choices=(0, 1, 3, 5), required=True)
    parser.add_argument("--kind", choices=("correlation", "mixed"), default="correlation")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=("raw", "mapping", "group", "stage"))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.code_root.resolve()))
    import pandas as pd
    import metrology_app
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.workspace_document import same_snapshot
    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()
    source_hash, settings_hash = digest(args.wkb), digest(Path("config/settings.yaml"))
    app = QApplication.instance() or QApplication([])
    parent, children, records = MatchingWindow(), [], {}
    references = {}
    counts, spans, ticks = {}, {}, []
    heartbeat = QTimer(interval=10)
    heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
    heartbeat.start()

    def drain():
        deadline = perf_counter() + 30
        while True:
            app.processEvents()
            pending = parent._auto_run_pending or parent._raw_keyboard_timer.isActive()
            for child in children:
                timer = getattr(child, "refresh_timer", None)
                pending |= bool(timer is not None and timer.isActive())
                for name in ("sequence_page", "correlation_page", "plot_page", "radius_page"):
                    page = getattr(child, name, None)
                    if page is not None:
                        pending |= bool(getattr(page, "worker", None) is not None)
                        for timer_name in ("input_refresh_timer", "update_timer"):
                            timer = getattr(page, timer_name, None)
                            pending |= bool(timer is not None and timer.isActive())
            if not pending:
                break
            if perf_counter() > deadline:
                raise RuntimeError("Sync/analysis did not settle")
            QTest.qWait(5)
        for window in (parent, *children):
            window.repaint()
        app.processEvents()

    def verify():
        assert parent._analysis_current
        assert parent.result.result_mode == parent.result_mode.currentText().lower()
        expected = parent._active_raw_frame().fillna("").astype(str)
        for child in children:
            kind, _stage = parent._stage_window_context[child]
            if kind == "correlation":
                pd.testing.assert_frame_equal(child.raw_model.document_frame(), expected)
                pd.testing.assert_frame_equal(child.reference_model.document_frame(), references[child])
            elif kind == "dynamic":
                assert child.model.document_frame().empty

    def hook(name):
        original = getattr(parent, name)

        def timed(*a, **kw):
            start = perf_counter()
            counts[name] = counts.get(name, 0) + 1
            try:
                return original(*a, **kw)
            finally:
                spans[name] = spans.get(name, 0) + (perf_counter() - start)*1000
        return patch.object(parent, name, timed)

    def measure(name, action):
        samples = []
        if args.only and name not in args.only:
            return
        for index in range(args.count + 1):
            drain()
            counts.clear()
            spans.clear()
            ticks[:] = [perf_counter()]
            profile = cProfile.Profile()
            if args.profile == name:
                profile.enable()
            start, cpu = perf_counter(), process_time()
            action(index)
            dispatch = (perf_counter()-start)*1000
            drain()
            complete = (perf_counter()-start)*1000
            QTest.qWait(25)
            profile.disable()
            sample = dict(dispatch_ms=dispatch, complete_ms=complete,
                          cpu_ms=(process_time()-cpu)*1000,
                          max_gap_ms=max((r-l for l, r in zip(ticks, ticks[1:])), default=0)*1000,
                          calls=dict(counts), inclusive_ms=dict(spans), memory=memory_info())
            if index:
                samples.append(sample)
            if args.profile == name and index == 1:
                with args.output.with_suffix(".profile.txt").open("w", encoding="utf-8") as stream:
                    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime")
                    stats.print_stats(45)
                    stats.print_callers("fillna|astype|_commit_stage_workspace")
            verify()
        records[name] = samples
        print(json.dumps({"children": args.children, "action": name,
                          "complete_ms": [round(s["complete_ms"], 2) for s in samples]}), flush=True)

    try:
        parent.load_workbook(args.wkb)
        parent.document.timer.stop()
        parent.result_mode.setCurrentText("Preview")
        original_raw = parent.raw_model.document_frame().copy(deep=True)
        manual_ref = parent.reference_frame.fillna("").astype(str).copy(deep=True)
        # Both stages have valid independent scratch input before timing.
        parent.result_mode.setCurrentText("Final")
        final = original_raw.copy(deep=True)
        parameter = parent.selected_mappings()[0].raw_column
        column = final.columns.get_loc(parameter)
        final.iat[0, column] = str(float(final.iat[0, column]) + .25)
        parent.set_raw_frame(final, "Isolated Final fixture")
        parent.run_analysis()
        parent.result_mode.setCurrentText("Preview")
        parent.resize(1500, 950)
        parent.show()
        kinds = ["correlation"]*5 if args.kind == "correlation" else ["correlation", "map", "dynamic", "correlation", "map"]
        for index, kind in enumerate(kinds[:args.children]):
            stage = "preview"
            scope = f"{kind}.{index+1:032x}.{stage}"
            parent._workspace_states[scope] = {"window": {"name": f"Sync probe {index+1}", "checked": True}}
            if kind == "correlation":
                child = parent.open_correlation_workspace(scope=scope)
                child.set_reference_table(manual_ref, "Independent manual Reference")
                for page in (child.sequence_page, child.correlation_page):
                    metrics = page.selection["metrics"][:2]
                    page.selector.set_selected_cells({(w, m) for w in page.selection["wafers"] for m in metrics})
                    page.draw_plot()
                references[child] = child.reference_model.document_frame().copy(deep=True)
            elif kind == "map":
                child = parent.open_stage_workspace(stage, scope=scope)
            else:
                child = parent.open_dynamic_workspace(stage, scope=scope)
            child.document.timer.stop()
            children.append(child)
        drain()
        verify()

        def raw(index):
            parent.raw_model.edit({(1, column): str(float(original_raw.iat[0, column]) + .001*(index+1))})

        def mapping(index):
            item = parent.mapping_table.item(0, 0)
            item.setCheckState(Qt.CheckState.Checked if index % 2 else Qt.CheckState.Unchecked)

        def group(index):
            combo = parent.group_controls.order
            alternate = "groups" if combo.findData("groups") >= 0 else "wafers"
            combo.setCurrentIndex(combo.findData("original" if index % 2 else alternate))
            parent.group_controls.apply_button.click()

        def stage(index):
            parent.result_mode.setCurrentText("Final" if index % 2 == 0 else "Preview")

        def parameter_selection(index):
            for child in children:
                if child.parameter_list.topLevelItemCount() > 1:
                    child.parameter_list.topLevelItem(0).setCheckState(
                        0, Qt.CheckState.Checked if index % 2 else Qt.CheckState.Unchecked)

        def card(_):
            name = parent.result.parameter_names[0]
            parent.plot_groups[name]["plots"]["trend"].card_checkbox.click()
            for child in children:
                check = getattr(child, "card_check", None)
                if check is not None and check.isEnabled():
                    check.click()

        with ExitStack() as stack:
            for name in ("sync_stage_windows", "_refresh_stage_workspace", "_commit_stage_workspace"):
                stack.enter_context(hook(name))
            for name, action in (("raw", raw), ("mapping", mapping), ("group", group),
                                 ("stage", stage), ("parameter", parameter_selection), ("card", card),
                                 ("unchanged_sync", lambda _: parent.sync_stage_windows())):
                measure(name, action)

        # Separate ownership check, outside timing: a manual Raw sentinel must
        # survive further parent edits; linked siblings must continue following.
        detached = next((c for c in children if parent._stage_window_context[c][0] == "correlation"), None)
        if detached is not None:
            detached.raw_model.edit({(1, column): "99.12345000"})
            detached.recognize()
            drain()
            expected_draft = detached.raw_model.document_frame().copy(deep=True)
            expected_ref = detached.reference_model.document_frame().copy(deep=True)
            expected_baseline = detached.document.baseline
            from metrology_app.recovery import freeze_snapshot
            baseline_copy = freeze_snapshot(expected_baseline)
            raw(args.count+10)
            drain()
            assert not detached.copy_from_wkb_action.isChecked()
            pd.testing.assert_frame_equal(detached.raw_model.document_frame(), expected_draft)
            pd.testing.assert_frame_equal(detached.reference_model.document_frame(), expected_ref)
            assert same_snapshot(detached.document.baseline, baseline_copy)
            for child in children:
                if child is not detached and parent._stage_window_context[child][0] == "correlation":
                    pd.testing.assert_frame_equal(child.raw_model.document_frame(), parent._active_raw_frame().fillna("").astype(str))
        args.output.write_text(json.dumps(dict(children=args.children, kind=args.kind, count=args.count,
            platform=app.platformName(), source_sha256=source_hash, settings_sha256=settings_hash,
            ownership_checked=detached is not None, samples=records), indent=2), encoding="utf-8")
    finally:
        heartbeat.stop()
        for window in (*reversed(children), parent):
            window.document.force_close = True
            window.document.timer.stop()
            window.close()
            window.deleteLater()
        app.processEvents()
        assert digest(args.wkb) == source_hash
        assert digest(Path("config/settings.yaml")) == settings_hash


if __name__ == "__main__":
    main()

"""Read-only WKB button/idle/child-window probe; settings and recovery are temporary.

python -m benchmarks.benchmark_workbook_windows --wkb FILE [--profile] [--budget-ms 250]
Times include queued GUI work. Offscreen timings are not display frame rates.
"""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter, process_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", required=True, type=Path)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--profile-actions", nargs="*", help="Profile only these measured actions")
    parser.add_argument("--controls", action="store_true", help="Draw a bounded map sample and probe plot controls")
    parser.add_argument("--input-controls", action="store_true", help="Probe mapping Use and actual Raw Data keyboard workflows")
    parser.add_argument("--map-first", action="store_true", help="Open Wafer Map before Correlation to measure first-use imports")
    parser.add_argument("--budget-ms", type=float)
    args = parser.parse_args()
    original_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="metrology-window-probe-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["MPLCONFIGDIR"] = str(Path(scratch) / "matplotlib")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtCore import QEventLoop, Qt, QTimer
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.resize(1500, 950)
        gaps, metrics = [], {}
        last_tick = perf_counter()

        def tick():
            nonlocal last_tick
            now = perf_counter()
            gaps.append((now - last_tick) * 1000)
            last_tick = now

        heartbeat = QTimer(interval=10)
        heartbeat.timeout.connect(tick)
        heartbeat.start()

        def measure(name, action, settle_ms=600, until=None):
            nonlocal last_tick
            gaps.clear()
            last_tick = perf_counter()
            profiler = cProfile.Profile()
            profiling = args.profile or name in (args.profile_actions or ())
            if profiling:
                profiler.enable()
            start, cpu_start = perf_counter(), process_time()
            action()
            direct_ms = (perf_counter() - start) * 1000
            completed_ms = direct_ms
            if until is not None:
                completion = QEventLoop()
                poll = QTimer(interval=10)
                poll.timeout.connect(lambda: completion.quit() if until() else None)
                timeout = QTimer(interval=20_000, singleShot=True)
                timeout.timeout.connect(completion.quit)
                poll.start()
                timeout.start()
                completion.exec()
                poll.stop()
                timeout.stop()
                if not until():
                    raise RuntimeError(f"{name} did not complete within 20 seconds")
                completed_ms = (perf_counter() - start) * 1000
            loop = QEventLoop()
            QTimer.singleShot(settle_ms, loop.quit)
            loop.exec()
            profiler.disable()
            metrics[name] = {"direct_ms": round(direct_ms, 2),
                             "completed_ms": round(completed_ms, 2),
                             "settled_ms": round((perf_counter() - start) * 1000, 2),
                             "cpu_ms": round((process_time() - cpu_start) * 1000, 2),
                             "max_gap_ms": round(max(gaps, default=0), 2)}
            print(json.dumps({name: metrics[name]}), flush=True)
            if profiling:
                import pstats
                print(f"PROFILE {name}", flush=True)
                stats = pstats.Stats(profiler).strip_dirs().sort_stats("cumtime")
                stats.print_stats(40)
                stats.print_stats("inspect_table|set_array")

        try:
            measure("open", lambda: (window.load_workbook(args.wkb), window.show()))
            if args.controls or args.input_controls:
                # Isolate widget callbacks from recovery; measure that write
                # explicitly below. This does not alter the application's timer.
                window.document.timer.stop()
            measure("idle", lambda: None, 2200)
            measure("group_settings", window.group_settings_action.trigger)
            window.group_settings_dialog.reject()

            def metrics_dialog():
                def reject_dialog():
                    dialog = app.activeModalWidget()
                    if dialog is not None:
                        dialog.reject()
                QTimer.singleShot(20, reject_dialog)
                window.metric_highlighting_action.trigger()

            measure("analysis_settings", metrics_dialog)
            measure("dirty_check", window.document.refresh_identity)
            measure("group_apply", window.group_controls.apply_button.click)
            if args.input_controls:
                from PyQt6.QtTest import QTest
                checked = next((window.mapping_table.item(i, 0) for i in range(window.mapping_table.rowCount())
                                if window.mapping_table.item(i, 0).checkState() == Qt.CheckState.Checked), None)
                if checked is not None and len(window.result.parameter_names) > 1:
                    finished = lambda: not window._auto_run_pending and window._analysis_current
                    measure("mapping_uncheck", lambda: checked.setCheckState(Qt.CheckState.Unchecked), until=finished)
                    measure("mapping_check", lambda: checked.setCheckState(Qt.CheckState.Checked), until=finished)
                view = window.raw_view
                model = window.final_raw_model if window.result_mode.currentText() == "Final" else window.raw_model
                expected = model.document_frame().copy(deep=True)
                view.setFocus()
                view.setCurrentIndex(view.model().index(1, 0))
                measure("raw_select_all", lambda: QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier))
                ranges = view.selectionModel().selection()
                assert sum(cell.width() * cell.height() for cell in ranges) == view.model().rowCount() * view.model().columnCount()
                measure("raw_delete_selected", lambda: QTest.keyClick(view, Qt.Key.Key_Delete))
                measure("raw_undo", lambda: QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier),
                        until=lambda: not window._auto_run_pending and window._analysis_current)
                import pandas as pd
                pd.testing.assert_frame_equal(model.document_frame(), expected)
            if args.map_first:
                measure("map_first_use", lambda: window.open_stage_workspace("preview"))
            measure("correlation", window.open_correlation_workspace)
            child = window.open_correlation_workspace()
            for name, tree in (("raw_wafer", child.wafer_list),
                               ("reference_wafer", child.reference_wafer_list),
                               ("raw_parameter", child.parameter_list),
                               ("reference_parameter", child.reference_parameter_list)):
                item = next((tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                             if tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked), None)
                if item is not None:
                    measure(f"uncheck_{name}", lambda target=item: target.setCheckState(0, Qt.CheckState.Unchecked))
                    measure(f"check_{name}", lambda target=item: target.setCheckState(0, Qt.CheckState.Checked))
            measure("map", lambda: window.open_stage_workspace("preview"))
            if args.controls:
                # Sidebar toggles intentionally invalidate Draw. Exercise the
                # following controls on drawn plots, not on empty selector pages.
                measure("correlation_redraw", child.correlation_page.draw_plot)
                measure("trend_redraw", child.sequence_page.draw_plot)
                for name, action in (("correlation_font", lambda: child.correlation_page.font_size.setCurrentText("12")),
                                     ("correlation_min_rsq", lambda: child.correlation_page.min_rsq.setValue(.6)),
                                     ("trend_font", lambda: child.sequence_page.font_size.setCurrentText("12"))):
                    measure(name, action)
                map_window = window.open_stage_workspace("preview")
                measure("map_numeric_filter", lambda: map_window.numeric_only.setChecked(False))
                measure("map_numeric_filter_restore", lambda: map_window.numeric_only.setChecked(True))
                page = map_window.plot_page
                def choose_map_sample():
                    wanted = {mapping.name for mapping in window.workbook.mappings}
                    tree = map_window.parameter_list
                    candidates = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                                  if tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) in wanted]
                    map_window.check_all(tree, False)
                    for item in candidates[:2]:
                        item.setCheckState(0, Qt.CheckState.Checked)
                    map_window.check_all(map_window.wafer_list, True)
                measure("map_sample_selection", choose_map_sample)
                if page.x_column.currentData() is not None and page.y_column.currentData() is not None:
                    wafers = page.selection.get("wafers", [])[:2]
                    parameters = page.selection.get("metrics", [])[:2]
                    page.selector.set_selected_cells({(wafer, parameter) for wafer in wafers for parameter in parameters})
                    map_window.tabs.setCurrentWidget(page)
                    measure("map_draw_sample", page.draw_maps, until=lambda: page.worker is None)
                    if page.result is not None:
                        for name, control in (("map_labels", page.labels), ("map_points", page.points),
                                              ("map_contour", page.contour), ("map_colorbar", page.scale_bar)):
                            measure(name, lambda target=control: target.setChecked(not target.isChecked()))
                        measure("map_fill_edge", lambda: page.fill_edge.setChecked(not page.fill_edge.isChecked()),
                                until=lambda: page.worker is None)
                    else:
                        print(json.dumps({"map_controls_skipped": page.empty.text()}), flush=True)
                else:
                    print(json.dumps({"map_controls_skipped": "No coordinate columns are selected"}), flush=True)
                measure("recovery_after_controls", window.document.write_recovery)
            measure("children_idle", lambda: None, 2200)
            print(json.dumps({"file": args.wkb.name, "metrics": metrics}), flush=True)
        finally:
            heartbeat.stop()
            for child in list(window._stage_windows):
                child.document.force_close = True
                child.document.identity_timer.stop()
                child.document.timer.stop()
                child.close()
            window.document.force_close = True
            window.document.identity_timer.stop()
            window.document.timer.stop()
            window.close()
            window.deleteLater()
            app.processEvents()
            assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == original_hash
        if args.budget_ms is not None and any(
                metrics[name]["max_gap_ms"] > args.budget_ms
                for name in ("idle", "group_settings", "analysis_settings", "children_idle")):
            raise SystemExit(1)


if __name__ == "__main__":
    main()

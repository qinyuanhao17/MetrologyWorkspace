"""First-use and warm WKB timings in one independent, read-only process.

Run each sample in a fresh interpreter. Full-visible timings wait for current
numerical data, queued layouts and full-data curve images, then repaint actual
visible viewports. Offscreen timings are not physical display frame rates.
"""
import argparse
import cProfile
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wkb', required=True, type=Path)
    parser.add_argument('--scratch-root', required=True, type=Path)
    parser.add_argument('--profile-actions', nargs='*', default=[])
    parser.add_argument('--map-first', action='store_true')
    parser.add_argument('--save-fixture', type=Path, help='Save a derived WKB only inside scratch-root')
    args = parser.parse_args()
    if args.save_fixture is not None:
        args.save_fixture.resolve().relative_to(args.scratch_root.resolve())
        if args.save_fixture.resolve() == args.wkb.resolve():
            parser.error('The original WKB cannot be a fixture destination')
        if args.save_fixture.exists():
            parser.error('Choose a new fixture path; the probe never overwrites a WKB')
    original_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(dir=args.scratch_root, prefix='cold-wkb-') as scratch:
        os.environ['METROLOGY_SETTINGS_PATH'] = str(Path(scratch) / 'settings.yaml')
        os.environ['METROLOGY_RECOVERY_DIR'] = str(Path(scratch) / 'recovery')
        os.environ['MPLCONFIGDIR'] = str(Path(scratch) / 'matplotlib')
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        started = perf_counter()
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        import pyqtgraph as pg
        from metrology_app.matching_window import MatchingWindow
        faulthandler.dump_traceback_later(45, repeat=True)
        print(json.dumps({'imports_ms': (perf_counter() - started) * 1000}), flush=True)
        app = QApplication.instance() or QApplication([])
        ticks = []
        timer = QTimer(interval=10)
        timer.timeout.connect(lambda: ticks.append(perf_counter()))
        timer.start()

        def measure(name, action, widget, current=lambda: True):
            ticks[:] = [perf_counter()]
            profiler = cProfile.Profile()
            if name in args.profile_actions:
                profiler.enable()
            start = perf_counter()
            value = action()
            callback = (perf_counter() - start) * 1000
            deadline = start + 30
            while not current():
                if perf_counter() > deadline:
                    raise AssertionError(f'{name}: numerical results not current')
                QTest.qWait(5)
            numerical = (perf_counter() - start) * 1000
            target = widget() if callable(widget) else widget
            app.processEvents()
            plots = [p for p in target.findChildren(pg.PlotWidget) if p.isVisible()]
            for plot in plots:
                plot.viewport().repaint()
            while any(getattr(item, 'render_pending', False)
                      for plot in plots for item in plot.listDataItems()):
                if perf_counter() > deadline:
                    raise AssertionError(f'{name}: full visible curves did not finish')
                QTest.qWait(5)
            app.processEvents()
            for plot in plots:
                plot.viewport().repaint()
            target.repaint()
            visible = (perf_counter() - start) * 1000
            QTest.qWait(150)
            profiler.disable()
            print(json.dumps({'operation': name, 'callback_ms': callback,
                              'numerical_ms': numerical, 'visible_ms': visible,
                              'max_gap_ms': max((b-a for a, b in zip(ticks, ticks[1:])), default=0) * 1000,
                              'visible_plot_count': len(plots)}), flush=True)
            if name in args.profile_actions:
                import pstats
                pstats.Stats(profiler).strip_dirs().sort_stats('cumtime').print_stats(45)
            return value

        window = measure('construct', MatchingWindow, lambda: app.topLevelWidgets()[0])
        window.resize(1500, 950)
        try:
            measure('wkb_open', lambda: (window.load_workbook(args.wkb), window.show()), window,
                    lambda: window._analysis_current and window.result is not None)
            window.document.timer.stop()
            mode = window.result_mode.currentText()
            other = 'Preview' if mode == 'Final' else 'Final'
            for name, stage in (('stage_first', other), ('stage_back', mode), ('stage_warm', other)):
                measure(name, lambda s=stage: window.result_mode.setCurrentText(s), window,
                        lambda: window._analysis_current and not window._auto_run_pending)
            window.result_mode.setCurrentText(mode)
            QTest.qWait(150)
            measure('group_settings_first', window.group_settings_action.trigger, window)
            window.group_settings_dialog.reject()
            measure('group_apply_first', window.group_controls.apply_button.click, window,
                    lambda: window._analysis_current)
            enabled = window.group_controls.enabled.isChecked()
            window.group_controls.enabled.setChecked(not enabled)
            measure('group_apply_changed', window.group_controls.apply_button.click, window,
                    lambda: window._analysis_current)
            window.group_controls.enabled.setChecked(enabled)
            window.group_controls.apply_button.click()
            QTest.qWait(150)
            view = window.raw_view
            view.setFocus()
            measure('raw_select_all_first', lambda: QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier), window)
            measure('raw_single_first', lambda: QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                    pos=view.visualRect(view.model().index(1, 0)).center()), window)
            assert len(view.selectedIndexes()) == 1
            item = next(window.mapping_table.item(row, 0) for row in range(window.mapping_table.rowCount())
                        if window.mapping_table.item(row, 0).checkState() == Qt.CheckState.Checked)
            measure('mapping_uncheck_first', lambda: item.setCheckState(Qt.CheckState.Unchecked), window,
                    lambda: window._analysis_current and not window._auto_run_pending)
            measure('mapping_check_first', lambda: item.setCheckState(Qt.CheckState.Checked), window,
                    lambda: window._analysis_current and not window._auto_run_pending)

            def map_open():
                saved = window._workspace_states.get(f'map.{mode.lower()}', {})
                draw = saved.get('ui', {}).get('selection', {}).get('map_draw', {})

                def restored_map_current():
                    page = window._stage_windows[-1].plot_page
                    return (page.worker is None and not page.input_refresh_timer.isActive()
                            and (draw.get('enabled') is not True or page.result is not None))

                return measure('map_open_first', lambda: window.open_stage_workspace(mode.lower()),
                               lambda: window._stage_windows[-1], restored_map_current)

            map_window = map_open() if args.map_first else None
            child = measure('correlation_open_first', window.open_correlation_workspace,
                            lambda: window._stage_windows[-1])
            child.correlation_page.min_rsq.setValue(0)
            for name, page in (('correlation', child.correlation_page), ('trend', child.sequence_page)):
                child.tabs.setCurrentWidget(page)
                page.selector.selectAll()
                # A genuine fitted result can have no pairs above the saved R²
                # threshold; keep that UI choice and measure the complete result.
                current = lambda p=page: p.ready or bool(getattr(p, 'all_fits', []))
                print(json.dumps({'draw_selection': name, 'metrics': page.selection['metrics'],
                                  'cells': len(page.selector.selected_cells()),
                                  'already_drawn': page.has_drawn_once}), flush=True)
                measure(name + '_draw_first', page.draw_plot, page, current)
                measure(name + '_draw_warm', page.draw_plot, page, current)
            snapshot = child.workspace_snapshot()
            measure('correlation_restore', lambda: child.restore_workspace(snapshot), child,
                    lambda: child.correlation_page.ready and child.sequence_page.ready)
            child.hide()
            if map_window is None:
                map_window = map_open()
            page = map_window.plot_page
            wanted = {m.name for m in window.workbook.mappings}
            tree = map_window.parameter_list
            candidates = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                          if tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) in wanted]
            map_window.check_all(tree, False)
            for selected in candidates[:2]:
                selected.setCheckState(0, Qt.CheckState.Checked)
            map_window.check_all(map_window.wafer_list, True)
            page.selector.set_selected_cells({(wafer, metric) for wafer in page.selection['wafers'][:2]
                                              for metric in page.selection['metrics'][:2]})
            map_window.tabs.setCurrentWidget(page)
            for name in ('map_draw_first', 'map_draw_warm'):
                measure(name, page.draw_maps, page, lambda: page.worker is None and page.result is not None)
                assert len(page.result['scenes']) == 4
            if args.save_fixture is not None:
                measure('wkb_save_derived_fixture', lambda: window.save_workbook(args.save_fixture), window)
            print(json.dumps({'source_sha256': original_hash, 'result_parameters': window.result.parameter_names}), flush=True)
        finally:
            timer.stop()
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
            faulthandler.cancel_dump_traceback_later()
            assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == original_hash


if __name__ == '__main__':
    main()

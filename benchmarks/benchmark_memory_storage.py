"""Sequential resource soak using real Shell lifecycle and existing isolation.

python -m benchmarks.benchmark_memory_storage --cycles 12 --rows 10000 --columns 30 --scenario mixed --output FILE
Run each scenario/scale in a fresh process. Tracing is opt-in because it changes
timings; Working Set alone is never a leak verdict. Only synthetic owned WKBs
are written. No production teardown, ownership or persistence behavior is patched.
"""
import argparse
from collections import Counter
import ctypes
import gc
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import threading
from time import perf_counter, process_time
import tracemalloc
import weakref

from .benchmark_correlation_restore import digest, memory_info


def trend(samples, key):
    """Descriptive early/late medians and slope, never a leak threshold."""
    values = [sample[key] for sample in samples if sample.get(key) is not None]
    if not values:
        return None
    size = max(1, len(values) // 3)
    centre = (len(values) - 1) / 2
    denominator = sum((index - centre)**2 for index in range(len(values)))
    slope = (sum((index - centre) * value for index, value in enumerate(values))
             / denominator if denominator else 0.)
    early, late = statistics.median(values[:size]), statistics.median(values[-size:])
    return dict(first=values[0], last=values[-1], early_median=early,
                late_median=late, late_minus_early=late-early, slope_per_cycle=slope)


def fixture(rows, columns):
    """Exact-width source strings; two mappings, remaining measurements retained."""
    import numpy as np
    import pandas as pd
    from metrology_app.matching import MatchWorkbook, ParameterMapping
    index = np.arange(rows)
    site = index % 100
    data = {
        'Wafer ID': [f'W{i // 1000:04d}' for i in index],
        'Die Seq': [f'{i + 1:03d}' for i in site],
        'Cycle': [str(i // 100 % 10 + 1) for i in index],
        'X(mm)': [f'{(i % 10 - 4.5) * 20:.4f}' for i in site],
        'Y(mm)': [f'{(i // 10 - 4.5) * 20:.4f}' for i in site],
        'Lot ID': ['L001'] * rows,
    }
    for number in range(columns - len(data)):
        data[f'P{number}'] = [f'{10 + number + i * .0001 + (i % 100) * .01:.12f}' for i in index]
    raw = pd.DataFrame(data)
    reference = pd.DataFrame({f'P{i} Reference': [f'{float(v) * 1.02 + .3:.12f}'
                            for v in raw[f'P{i}']] for i in range(2)})
    flags = pd.DataFrame({'TestFlag': ['0' if i < rows // 2 else '1' for i in index]})
    return MatchWorkbook(reference, raw,
        [ParameterMapping(f'P{i}', f'P{i} Reference', f'P{i}') for i in range(2)],
        match_type='NOVA', final_match_raw=raw.copy(), test_flags=flags,
        grouping_state={'enabled': False, 'mark_enabled': False})


def resources(app):
    from PyQt6 import sip
    from PyQt6.QtCore import QObject, QThread, QTimer
    from metrology_app.workspace_document import DOCUMENTS
    from metrology_app.plot_page import _CANCELLED_JOBS
    widgets = app.allWidgets()
    roots = [app, *app.topLevelWidgets()]
    objects = {}
    for root in roots:
        for obj in (root, *root.findChildren(QObject)):
            if not sip.isdeleted(obj):
                objects[int(sip.unwrapinstance(obj))] = obj
    timers = [obj for obj in objects.values() if isinstance(obj, QTimer)]
    threads = [obj for obj in objects.values() if isinstance(obj, QThread)]
    kinds = Counter(type(obj).__name__ for obj in gc.get_objects())
    memory = memory_info()
    handles = None
    if sys.platform == 'win32':
        from ctypes import wintypes
        value = wintypes.DWORD()
        query = ctypes.WinDLL('kernel32', use_last_error=True).GetProcessHandleCount
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        if not query(wintypes.HANDLE(-1), ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        handles = value.value
    current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, None)
    return {**memory, 'handles': handles, 'traced_current': current, 'traced_peak': peak,
            'tracemalloc_bookkeeping': (tracemalloc.get_tracemalloc_memory()
                                        if tracemalloc.is_tracing() else None),
            'qt_objects_reachable_from_roots': len(objects), 'widgets': len(widgets),
            'top_level_widgets': len(app.topLevelWidgets()),
            'visible_top_level_widgets': sum(w.isVisible() for w in app.topLevelWidgets()),
            'qt_timers': len(timers), 'active_qt_timers': sum(t.isActive() for t in timers),
            'qt_threads_from_roots': len(threads),
            'python_threads': len(threading.enumerate()),
            'python_thread_names': [t.name for t in threading.enumerate()],
            'documents': len(DOCUMENTS), 'cancelled_jobs': len(_CANCELLED_JOBS),
            'python_resources': {key: kinds[key] for key in (
                'DataFrame', 'Figure', 'SurfaceJob', 'PlotDataItem', 'ImageItem')}}


def settle(app, windows=(), *, timeout=120, idle_ms=50):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtTest import QTest
    deadline = perf_counter() + timeout
    while True:
        app.processEvents()
        pending = False
        for window in windows:
            pending |= bool(getattr(window, '_auto_run_pending', False))
            pending |= bool(getattr(window, 'linked_updates_pending', False))
            document = getattr(window, 'document', None)
            pending |= bool(document is not None and document.recovery_pending)
            for name in ('refresh_timer', '_raw_keyboard_timer'):
                timer = getattr(window, name, None)
                pending |= bool(timer is not None and timer.isActive())
            # Screen curve rasterization is asynchronous too. Completion
            # includes every currently drawn primary/secondary curve.
            import pyqtgraph as pg
            for plot in window.findChildren(pg.PlotWidget):
                items = plot.listDataItems() + [item
                    for view in getattr(plot, 'secondary_views', ()) for item in view.addedItems]
                pending |= any(getattr(item, 'render_pending', False) for item in items)
            for name in ('plot_page', 'radius_page', 'sequence_page', 'correlation_page'):
                page = getattr(window, name, None)
                if page is not None:
                    pending |= bool(getattr(page, 'background_render_pending', False))
                    pending |= getattr(page, 'worker', None) is not None
                    for timer_name in ('input_refresh_timer', 'update_timer'):
                        timer = getattr(page, timer_name, None)
                        pending |= bool(timer is not None and timer.isActive())
        if not pending:
            break
        if perf_counter() > deadline:
            raise TimeoutError('Analysis/recovery did not settle')
        QTest.qWait(10)
    QTest.qWait(idle_ms)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def select_and_draw(window, plot_wafers=2):
    """Draw actual full curves, and two wafers x two parameters for maps."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance()
    settle(app, [window])
    # Data-tab participation/parameter checks precede the plot's own boxes.
    # An empty plot selection is not evidence that anything was rendered.
    wafer_limit = 1 if window.workspace_type == 'dynamic' else plot_wafers
    for name, limit in (('parameter_list', 2), ('wafer_list', wafer_limit)):
        tree = getattr(window, name, None)
        if tree is not None:
            keys = [tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(tree.topLevelItemCount())]
            chosen = ['P0', 'P1'] if name == 'parameter_list' and {'P0', 'P1'} <= set(keys) else keys[:limit]
            window._set_checked_values(tree, chosen)
    window.update_plan()
    settle(app, [window])
    rendered = {}
    for name in ('sequence_page', 'correlation_page', 'plot_page', 'radius_page'):
        page = getattr(window, name, None)
        if page is None or window.tabs.indexOf(page) < 0 or not page.selection.get('metrics'):
            continue
        wafers = page.selection['wafers'][:plot_wafers]
        metrics = page.selection['metrics'][:2]
        page.selector.set_selected_cells({(w, m) for w in wafers for m in metrics})
        window.tabs.setCurrentWidget(page)
        if name == 'plot_page':
            page.draw_maps()
        else:
            page.draw_plot()
        settle(app, [window])
        if name == 'plot_page':
            rendered['map_scenes'] = len((page.result or {}).get('scenes', ()))
            assert rendered['map_scenes'] > 0, page.empty.text()
        elif name == 'radius_page':
            rendered['radius_series'] = len(page.plot_sources)
            assert rendered['radius_series'] > 0, page.status.text()
        elif name == 'correlation_page':
            rendered['correlation_fits'] = len(page.all_fits)
            assert rendered['correlation_fits'] > 0, page.status.text()
        else:
            rendered['trend_panels'] = len(page.panel_specs) if page.ready else 0
            assert rendered['trend_panels'] > 0, page.status.text()
    if hasattr(window, 'dynamic_page'):
        window.tabs.setCurrentWidget(window.dynamic_page)
        window.dynamic_page.refresh()
        rendered['dynamic_pivots'] = len(window.dynamic_page.parameter_models)
    required = {'wafer_map': {'map_scenes', 'radius_series'},
                'correlation_trend': {'trend_panels', 'correlation_fits'}}
    assert required.get(window.workspace_type, set()) <= rendered.keys(), (
        f'{window.workspace_type} source/selection was not ready for drawing: {rendered}')
    return rendered


def cycle(shell, path, scenario, iteration, app, plot_wafers=2, populate_dynamic=False):
    import pandas as pd
    from metrology_app.workspace_store import load_workspace
    from metrology_app.workspace_document import same_snapshot
    if scenario == 'settings':
        from PyQt6.QtCore import QTimer
        from metrology_app.settings_dialog import SettingsDialog
        QTimer.singleShot(0, lambda: shell.findChildren(SettingsDialog)[-1].reject())
        shell.open_settings()
        return resources(app), []
    windows = []
    references = []
    rendered = []
    try:
        parent = shell.open_component('card_matching', initialize=lambda w: w.load_workbook(path))
        windows.append(parent)
        references.append(weakref.ref(parent))
        settle(app, windows)
        before = parent.raw_model.document_frame()
        summary = parent.result.summary.copy(deep=True)
        if scenario == 'mixed':
            windows.extend([parent.open_correlation_workspace(),
                            parent.open_stage_workspace('preview'),
                            parent.open_dynamic_workspace('preview')])
            if windows[-2].model.document_frame().empty:
                windows[-2].set_table(before.copy(), 'P1 owned Map source')
            references.extend(weakref.ref(w) for w in windows[1:])
            if populate_dynamic:
                dynamic = windows[-1]
                dynamic.set_table(before.copy(), 'P1 owned Dynamic source')
                dynamic._set_checked_values(dynamic.parameter_list, ['P0', 'P1'])
                dynamic.update_plan()
            for window in windows[1:]:
                rendered.append(select_and_draw(window, plot_wafers))
            if populate_dynamic:
                assert rendered[-1].get('dynamic_pivots', 0) > 0, dynamic.dynamic_page.message.text()
            settle(app, windows)
            parent._populate_mappings(list(reversed(parent.selected_mappings())))
            parent.run_analysis()
            settle(app, windows)
            state = dict(parent.group_controls.state)
            state['enabled'] = True
            parent.group_controls.restore(state, parent.group_controls.flags_frame())
            parent.run_analysis()
            settle(app, windows)
            for stage in ('Final', 'Preview'):
                parent.result_mode.setCurrentText(stage)
                settle(app, windows)
            assert parent._analysis_current
            if populate_dynamic:
                # Cycle is inferred by Dynamic's existing import contract;
                # every source measurement string/position remains exact.
                pd.testing.assert_frame_equal(
                    dynamic.model.document_frame().drop(columns=['Cycle']),
                    before.drop(columns=['Cycle']))
        column = before.columns.get_loc('P0')
        value = f'{float(before.iat[0, column]) + .001:.12f}'
        parent.raw_model.edit({(1, column): value})
        settle(app, windows)
        parent.raw_model.undo.undo()
        settle(app, windows)
        pd.testing.assert_frame_equal(parent.raw_model.document_frame(), before)
        if scenario != 'mixed':
            pd.testing.assert_frame_equal(parent.result.summary, summary)
        parent.raw_model.undo.redo()
        settle(app, windows)
        assert parent.raw_model.document_frame().iat[0, column] == value
        if scenario == 'workbook':
            formal = parent.document.save(path.with_name(f'saved-{iteration}.mwkb'))
            assert formal is not None
            formal = Path(formal)
            old_hash = digest(formal)
            parent.raw_model.edit({(1, column): '001.234567890123'})
            parent.document.request_recovery()
            parent.raw_model.edit({(1, column): '002.345678901234'})
            parent.document.request_recovery()
            settle(app, windows)
            draft = load_workspace(parent.document.recovery_path)
            assert draft.frames['raw'].iat[0, column] == '002.345678901234'
            expected = parent.workspace_snapshot()
            restored = shell.open_component('card_matching')
            windows.append(restored)
            references.append(weakref.ref(restored))
            restored.document.recover(parent.document.recovery_path, snapshot=draft)
            assert same_snapshot(restored.workspace_snapshot(), expected)
            assert digest(formal) == old_hash
            reopened = load_workspace(formal)
            assert reopened.frames['raw'].iat[0, column] == value
        if scenario == 'tasks':
            child = parent.open_stage_workspace('preview')
            if child.model.document_frame().empty:
                child.set_table(before.copy(), 'P1 owned Map source')
            windows.append(child)
            references.append(weakref.ref(child))
            rendered.append(select_and_draw(child, plot_wafers))
            settle(app, windows)
            child.plot_page.draw_maps()
            assert child.plot_page.worker is not None, child.plot_page.status.text()
            # Close immediately during the real SurfaceJob, without blocking
            # or replacing its numerical work. Parent owns its normal disposal.
        opened = resources(app)
        opened['verified_rendering'] = rendered
    finally:
        # Production parent close explicitly disposes managed children. Shell
        # disposes independent windows via WA_DeleteOnClose. Do not add a
        # benchmark deleteLater workaround that could hide a lifecycle defect.
        for window in reversed(windows):
            if getattr(window, '_managed_owner', None) is not None:
                continue
            window.document.force_close = True
            if not window.close():
                raise AssertionError('Owned benchmark window refused close')
    return opened, references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=12)
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--columns', type=int, default=30)
    parser.add_argument('--scenario', choices=('workbook', 'mixed', 'tasks', 'settings'), default='workbook')
    parser.add_argument('--platform', default='windows' if sys.platform == 'win32' else 'offscreen')
    parser.add_argument('--tracemalloc', action='store_true')
    parser.add_argument('--plot-wafers', type=int, default=2)
    parser.add_argument('--populate-dynamic', action='store_true',
                        help='Give the independent Dynamic child its own full-width source table')
    parser.add_argument('--gc-every', type=int, default=1, help='Collect every N cycles, or 0 for natural GC only')
    parser.add_argument('--idle-ms', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (args.cycles < 1 or not 1 <= args.rows <= 100000 or not 8 <= args.columns <= 56
            or args.idle_ms < 1 or args.plot_wafers < 1 or args.gc_every < 0):
        parser.error('cycles/plot-wafers/idle-ms >=1, rows 1..100000, columns 8..56 and gc-every >=0 required')
    real_settings = Path(__file__).resolve().parents[1] / 'config/settings.yaml'
    if args.output.suffix.lower() != '.json' or args.output.resolve() == real_settings.resolve():
        parser.error('Use a dedicated .json benchmark output, never an application settings/workspace file')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    settings_hash = digest(real_settings)
    from run_tests import isolate_settings
    with tempfile.TemporaryDirectory(prefix='metrology-p1-memory-') as temporary:
        isolate_settings(temporary)
        os.environ['QT_QPA_PLATFORM'] = args.platform
        from PyQt6.QtCore import QTimer, QT_VERSION_STR
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from unittest.mock import patch
        from metrology_app.shell import MainWindow
        from metrology_app.plot_page import _CANCELLED_JOBS
        print(json.dumps({'progress': 'imports_complete', 'platform': args.platform}), flush=True)
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        book = fixture(args.rows, args.columns)
        path = book.save(Path(temporary) / 'input.wkb')
        source_hash = digest(path)
        print(json.dumps({'progress': 'fixture_saved', 'rows': args.rows}), flush=True)
        del book
        shell = MainWindow()
        shell.show()
        settle(app)
        print(json.dumps({'progress': 'shell_ready'}), flush=True)
        gc.collect()
        if args.tracemalloc:
            tracemalloc.start(1)
        ticks = []
        heartbeat = QTimer(interval=20)
        heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
        heartbeat.start()
        report = {'benchmark_sha256': digest(Path(__file__)),
                  'environment': {'python': platform.python_version(), 'os': platform.platform(),
                  'qt': QT_VERSION_STR, 'qt_platform': app.platformName(), 'pid': os.getpid()},
                  'arguments': {**vars(args), 'output': str(args.output)},
                  'baseline': resources(app), 'samples': [], 'failures': [],
                  'limits': ['Synthetic exact-width source, two mapped parameters; not original NOVA data',
                             'Map/Radius/Correlation/Trend select configured wafers and two parameters; full source tables retained',
                             'Qt object counts are reachable root descendants, not every native C++ allocation',
                             'CPU time and Qt heartbeat are process/GUI observations, not DWM FPS',
                             'Tracing and resource inventory affect latency; traced runs are separate',
                             'GC measurement is a diagnostic intervention, not a production fix',
                             'Finite soak trends do not by themselves prove absence or presence of a leak']}
        snapshot = None
        try:
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard), \
                    patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok):
                for iteration in range(args.cycles):
                    ticks[:] = [perf_counter()]
                    start, cpu = perf_counter(), process_time()
                    opened, references = cycle(shell, path, args.scenario, iteration, app,
                                               args.plot_wafers, args.populate_dynamic)
                    settle(app, idle_ms=args.idle_ms)
                    deadline = perf_counter() + 120
                    while _CANCELLED_JOBS:
                        if perf_counter() > deadline:
                            raise TimeoutError('Cancelled surface work did not drain')
                        settle(app, idle_ms=25)
                    pre_gc = resources(app)
                    collected = args.gc_every > 0 and (iteration + 1) % args.gc_every == 0
                    if collected:
                        gc.collect()
                    settle(app, idle_ms=args.idle_ms)
                    after_gc = resources(app)
                    alive = sum(ref() is not None for ref in references)
                    sample = {'cycle': iteration + 1, 'elapsed_ms': (perf_counter()-start)*1000,
                              'cpu_ms': (process_time()-cpu)*1000,
                              'max_event_loop_gap_ms': max((b-a for a,b in zip(ticks,ticks[1:])), default=0)*1000,
                              'opened': opened, 'closed_before_gc': pre_gc, 'closed_after_gc': after_gc,
                              'explicit_gc_performed': collected,
                              'window_wrappers_alive_after_gc': alive}
                    report['samples'].append(sample)
                    if args.tracemalloc and iteration == min(2, args.cycles-1):
                        snapshot = tracemalloc.take_snapshot()
                    print(json.dumps({'cycle': iteration+1, 'private': after_gc['private'],
                                      'widgets': after_gc['widgets'], 'alive': alive}), flush=True)
                    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            if snapshot is not None:
                report['traced_diff_after_warmup'] = [str(line) for line in
                    tracemalloc.take_snapshot().compare_to(snapshot, 'lineno')[:20]]
            closed = [row['closed_after_gc'] for row in report['samples']]
            report['trends'] = {key: trend(closed, key) for key in (
                'private', 'rss', 'traced_current', 'handles', 'widgets',
                'qt_objects_reachable_from_roots', 'active_qt_timers', 'documents', 'python_threads')}
            report['source_unchanged'] = digest(path) == source_hash
            assert report['source_unchanged']
        except Exception as error:
            report['failures'].append({'type': type(error).__name__, 'message': str(error)})
            raise
        finally:
            report['settings_unchanged'] = digest(real_settings) == settings_hash
            report['real_settings_sha256'] = settings_hash
            report['completed_cycles'] = len(report['samples'])
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            heartbeat.stop()
            # Also drain normal WA_DeleteOnClose events after an exception,
            # before Shell queries the documents that were just closed.
            for instances in tuple(shell.loaded_components.values()):
                for window in tuple(instances):
                    window.document.force_close = True
                    window.close()
            settle(app)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
                shell.close()
            shell.deleteLater()
            settle(app)
            if args.tracemalloc:
                tracemalloc.stop()
            assert report['settings_unchanged'], 'Real user settings changed during benchmark'


if __name__ == '__main__':
    main()

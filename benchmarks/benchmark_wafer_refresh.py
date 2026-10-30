"""Native Wafermap/linked-refresh probe, reusing existing fixtures and memory tools.

Use --baseline-tag v4.3.5 before/after with identical arguments. Inclusive method
spans overlap: do not add them. Timings include actual Qt viewport painting.
"""
import argparse
from contextlib import ExitStack
import cProfile
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
from time import perf_counter, process_time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=('maps', 'linked'), default='maps')
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--parameters', type=int, default=50)
    parser.add_argument('--maps', type=int, nargs='+', default=[10, 30, 50])
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--mapped-parameters', type=int, default=2)
    parser.add_argument('--baseline-tag')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--light', action='store_true', help='Linked control: 6 correlations and 2 maps')
    parser.add_argument('--platform', default='windows')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output.resolve() == (root / 'config/settings.yaml').resolve():
        raise ValueError('Benchmark output must not overwrite user settings')
    if (args.cycles < 1 or args.rows < 120 or args.parameters < 5
            or not 1 <= args.mapped_parameters <= args.parameters):
        raise ValueError('Use >=120 rows, >=5 parameters and a valid mapping count')
    if any(n not in (10, 30, 50) for n in args.maps):
        raise ValueError('Map workloads are 10, 30 or 50 actual panels')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import run_tests
    run_tests.isolate_settings(args.output.parent / (args.output.stem + '-isolation'))
    os.environ['QT_QPA_PLATFORM'] = args.platform
    if args.baseline_tag:
        for name in ('wafer_graphics', 'plot_page', 'matching_window'):
            source = subprocess.check_output(['git', 'show', f'{args.baseline_tag}:metrology_app/{name}.py'], cwd=root)
            path = args.output.with_name(args.output.stem + '-' + name + '.py')
            path.write_bytes(source)
            fullname = 'metrology_app.' + name
            spec = importlib.util.spec_from_file_location(fullname, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[fullname] = module
            spec.loader.exec_module(module)
    import numpy as np
    import pandas as pd
    import pyqtgraph as pg
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt, QRectF
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QMessageBox, QGraphicsScene
    from benchmarks.benchmark_memory_storage import fixture, settle
    from benchmarks.benchmark_correlation_restore import memory_info
    from metrology_app import wafer_graphics as graphics, plot_page as maps_module
    from metrology_app import matching_window as matching_module, correlation_page, sequence_page
    from metrology_app.matching import ParameterMapping
    from metrology_app.data import number
    app = QApplication.instance() or QApplication([])
    owner_thread = threading.get_ident()
    samples, active_spans, cleanup = [], [], []
    active = False
    counters = {}

    def hook(stack, cls, name):
        if not hasattr(cls, name):
            return
        original = getattr(cls, name)
        label = cls.__name__ + '.' + name
        def measured(self, *a, **kw):
            begin = perf_counter()
            try:
                return original(self, *a, **kw)
            finally:
                if active:
                    active_spans.append({'method': label, 'ms': (perf_counter() - begin) * 1000,
                                         'gui': threading.get_ident() == owner_thread})
                    counters[label] = counters.get(label, 0) + 1
        stack.enter_context(patch.object(cls, name, measured))

    def synthetic_book():
        book = fixture(args.rows, args.parameters + 6)
        indices = np.arange(args.rows)
        wafers = min(20, args.rows // 6)
        group = indices * wafers // args.rows
        xy = np.empty((args.rows, 2))
        for wafer in range(wafers):
            rows = np.flatnonzero(group == wafer)
            i = np.arange(len(rows))
            radius = 142 * np.sqrt((i + .5) / len(rows))
            angle = i * np.pi * (3 - np.sqrt(5))
            xy[rows, 0], xy[rows, 1] = radius * np.cos(angle), radius * np.sin(angle)
            book.raw.loc[rows, 'Die Seq'] = [f'{j+1:03d}' for j in i]
        book.raw['Wafer ID'] = [f'W{i:04d}' for i in group]
        book.raw['Cycle'] = '1'
        book.raw['X(mm)'] = [f'{v:.12f}' for v in xy[:, 0]]
        book.raw['Y(mm)'] = [f'{v:.12f}' for v in xy[:, 1]]
        for i in range(args.parameters):
            values = (10 + i + .03 * group + .001 * xy[:, 0] + .002 * xy[:, 1]
                      + .04 * np.sin(xy[:, 0] / (20 + i % 5 * 8))
                      + .03 * np.cos(xy[:, 1] / (25 + i % 7 * 6)))
            book.raw[f'P{i}'] = [f'{value:.12f}' for value in values]
        book.reference = pd.DataFrame({f'P{i} Reference': [f'{float(v)*1.02+.3:.12f}' for v in book.raw[f'P{i}']]
                                       for i in range(args.mapped_parameters)})
        book.mappings = [ParameterMapping(f'P{i}', f'P{i} Reference', f'P{i}')
                         for i in range(args.mapped_parameters)]
        book.final_match_raw = book.raw.copy(deep=True)
        return book

    def pending(windows):
        for window in windows:
            if getattr(window, '_auto_run_pending', False) or getattr(window, 'linked_updates_pending', False):
                return True
            for name in ('refresh_timer', '_raw_keyboard_timer'):
                timer = getattr(window, name, None)
                if timer is not None and timer.isActive():
                    return True
            pages = [window] if isinstance(window, maps_module.PlotPage) else [
                getattr(window, name, None) for name in ('plot_page', 'correlation_page', 'sequence_page')]
            for page in pages:
                if page is None:
                    continue
                if (getattr(page, 'worker', None) is not None or getattr(page, 'background_render_pending', False)
                        or getattr(page, 'pending_input_refresh', False)):
                    return True
                for name in ('input_refresh_timer', 'update_timer', 'style_timer', 'font_timer', 'overlay_timer'):
                    timer = getattr(page, name, None)
                    if timer is not None and timer.isActive():
                        return True
            for plot in window.findChildren(pg.PlotWidget):
                if any(getattr(item, 'render_pending', False) for item in plot.listDataItems()):
                    return True
        return False

    def measure(name, action, windows, count, cycle):
        nonlocal active
        active_spans.clear()
        counters.clear()
        before = memory_info()
        ticks, state = [], {}
        loop = QEventLoop()
        heartbeat = QTimer(interval=2)
        heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
        poll, timeout = QTimer(interval=5), QTimer(singleShot=True, interval=180000)
        stable = 0
        def check():
            nonlocal stable
            if pending(windows):
                stable = 0
                return
            stable += 1
            if stable < 2:
                return
            for window in windows:
                pages = [window] if isinstance(window, maps_module.PlotPage) else [
                    getattr(window, n, None) for n in ('plot_page', 'correlation_page')]
                for page in pages:
                    if page is not None:
                        scroll = getattr(page, 'scroll', None)
                        if hasattr(scroll, 'viewport'):
                            scroll.viewport().repaint()
                        for widget in getattr(page, 'plot_widgets', ()):
                            widget.viewport().repaint()
            if not pending(windows):
                state['end'] = perf_counter()
                loop.quit()
        def checked():
            try:
                check()
            except BaseException as error:
                state['error'] = error
                loop.quit()
        poll.timeout.connect(checked)
        timeout.timeout.connect(loop.quit)
        started, cpu = perf_counter(), process_time()
        profiler = cProfile.Profile() if args.profile else None
        ticks.append(started)
        active = True
        heartbeat.start()
        timeout.start()
        try:
            if profiler:
                profiler.enable()
            action()
            dispatch = (perf_counter() - started) * 1000
            poll.start()
            loop.exec()
        finally:
            if profiler:
                profiler.disable()
                profiler.dump_stats(str(args.output.with_name(args.output.stem + f'-{count}-{cycle}-{name}.prof')))
            active = False
            heartbeat.stop()
            poll.stop()
            timeout.stop()
        if 'error' in state:
            raise state['error']
        if 'end' not in state:
            raise TimeoutError(f'{name}: not all data, workers and graphics finished')
        ticks.append(state['end'])
        aggregate = {}
        for span in active_spans:
            key = span['method']
            item = aggregate.setdefault(key, {'calls': 0, 'inclusive_ms': 0, 'max_ms': 0, 'gui': span['gui']})
            item['calls'] += 1
            item['inclusive_ms'] += span['ms']
            item['max_ms'] = max(item['max_ms'], span['ms'])
        sample = {'operation': name, 'maps': count, 'cycle': cycle, 'dispatch_ms': dispatch,
                  'complete_ms': (state['end'] - started) * 1000,
                  'max_qt_gap_ms': max(b-a for a,b in zip(ticks, ticks[1:])) * 1000,
                  'max_gui_callback_ms': max(dispatch, max((s['ms'] for s in active_spans if s['gui']), default=0)),
                  'cpu_ms': (process_time()-cpu)*1000, 'methods': aggregate,
                  'memory_before': before, 'memory_after': memory_info()}
        samples.append(sample)
        print(json.dumps({k:v for k,v in sample.items() if k not in ('methods', 'memory_before', 'memory_after')}), flush=True)
        args.output.write_text(json.dumps({'samples': samples}, indent=2), encoding='utf-8')
        return sample

    def validate_map(page, count):
        assert page.result is not None and not page.dirty, page.status.text()
        assert page.map_grid.valid_count == count, (page.map_grid.valid_count, page.status.text())
        digest = hashlib.sha256()
        for panel, scene in zip(page.map_grid.panels, page.result['scenes']):
            if scene.get('skip'):
                continue
            assert not scene['error'], scene['error']
            groups = page.selection.get('groups')
            part = (page.frame.iloc[list(groups[scene['wafer']])] if groups else
                    page.frame[page.frame[page.selection['wafer_column']].astype(str).str.strip() == scene['wafer']])
            expected = pd.DataFrame({'x':number(part[page.x_column.currentData()]),
                                     'y':number(part[page.y_column.currentData()]),
                                     'value':number(part[scene['metric']])}).dropna().reset_index(drop=True)
            np.testing.assert_array_equal(scene['layer'][['x','y','value']].to_numpy(float), expected.to_numpy(float))
            np.testing.assert_array_equal(panel.positions, scene['surface'][0])
            for array in (scene['layer']['value'].to_numpy(float), *scene['surface'][:3], scene['surface'][3].data,
                          panel.rgba, panel._pixel_positions, panel.drawn_indices):
                value = np.asarray(array)
                digest.update(str(value.shape).encode())
                digest.update(value.tobytes())
        return digest.hexdigest()

    def capture(page, suffix):
        rect = page.map_grid.boundingRect()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        try:
            QGraphicsScene.render(page.scene, painter, QRectF(image.rect()), rect)
        finally:
            painter.end()
        target = args.output.with_name(args.output.stem + '-' + suffix + '.png')
        assert image.save(str(target))
        return {'path': str(target), 'size': [image.width(), image.height()], 'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}

    def dispose(window):
        if hasattr(window, 'document'):
            window.document.force_close = True
        if isinstance(window, maps_module.PlotPage):
            window.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    book = synthetic_book()
    changed = book.raw.copy(deep=True)
    for i in range(args.parameters):
        changed[f'P{i}'] = pd.to_numeric(changed[f'P{i}']).add(.001*(i+1)).map(lambda v: f'{v:.12f}')
    with ExitStack() as stack:
        stack.enter_context(patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard))
        stack.enter_context(patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok))
        for cls, names in ((graphics.WaferPanel, ('__init__','update_palette','set_geometry','_prepare_labels','_prepare_contours','_prepare_bar','paint')),
                           (graphics.WaferMapGrid, ('clear','set_result','relayout','_render_batch','_publish','cancel_render')),
                           (graphics.StaticMapView, ('paintEvent',)), (graphics.WaferImage, ('setImage','render','paint')),
                           (maps_module.PlotPage, ('render_result','refresh_canvas','apply_plot_style','_publish_map_result')),
                           (maps_module.SurfaceJob, ('run',)),
                           (matching_module.MatchingWindow, ('run_analysis','queue_stage_refresh','sync_stage_windows','_commit_linked_step')),
                           (correlation_page.CorrelationPage, ('draw_plot','request_background_draw','render_interactive','_render_next_panels'))):
            for name in names:
                hook(stack, cls, name)
        if args.scenario == 'maps':
            for count in args.maps:
                for cycle in range(args.cycles):
                    page = maps_module.PlotPage()
                    page.resize(1400, 900)
                    page.show()
                    selection = {'wafer_column':'Wafer ID', 'wafers':list(dict.fromkeys(book.raw['Wafer ID']))[:count//5],
                                 'metrics':[f'P{i}' for i in range(5)]}
                    page.set_input(book.raw, selection)
                    page.selector.selectAll()
                    page.page_size.setValue(20)
                    for name, action in (
                        ('first_draw', page.draw_maps),
                        ('data_update', lambda: page.set_input(changed, selection)),
                        ('style', lambda: (page.color_map.setCurrentIndex(page.color_map.findData('viridis')),
                                           page.opacity.setCurrentIndex(page.opacity.findData(80)),
                                           page.contour.setChecked(True)))):
                        sample = measure(name, action, [page], count, cycle)
                        sample['map_data_sha256'] = validate_map(page,count)
                        sample['grid_stats'] = dict(getattr(page.map_grid, 'render_stats', {}))
                        if args.capture and cycle == 0:
                            sample['capture'] = capture(page, f'{count}-{name}')
                    dispose(page)
                    cleanup.append({'maps':count,'cycle':cycle,'widgets':len(app.allWidgets()),'memory':memory_info()})
        else:
            clipboard = app.clipboard()
            original_clipboard = clipboard.text()
            edited_tsv = changed.to_csv(sep='\t', index=False, lineterminator='\n')
            try:
                for cycle in range(args.cycles):
                    parent = matching_module.MatchingWindow()
                    parent.match_type.setCurrentText('NOVA')
                    parent.set_reference_frame(book.reference)
                    parent.set_raw_frame(book.raw)
                    parent._populate_mappings(book.mappings)
                    parent.run_analysis()
                    cor = parent.open_correlation_workspace()
                    wafer = parent.open_stage_workspace('preview')
                    cor.set_reference_table(pd.DataFrame())
                    settle(app,[parent,cor,wafer])
                    for child in (cor,wafer):
                        child.document.timer.stop()
                        child._set_checked_values(child.wafer_list,[child.wafer_list.topLevelItem(i).data(0,Qt.ItemDataRole.UserRole)
                                                                   for i in range(child.wafer_list.topLevelItemCount())])
                        child._set_checked_values(child.parameter_list,[f'P{i}' for i in range(args.parameters)])
                        child.update_plan()
                        child.resize(1250,850)
                        child.show()
                    cp, mp = cor.correlation_page, wafer.plot_page
                    cor.tabs.setCurrentWidget(cp)
                    wafer.tabs.setCurrentWidget(mp)
                    panel_count, map_count = (6, 2) if args.light else (24, 50)
                    cp.page_size.setCurrentText(str(panel_count))
                    cp.selector.selectAll()
                    cp.start_draw()
                    mp.page_size.setValue(20)
                    wafers = mp.selection['wafers'][:1 if args.light else 10]
                    mp.selector.set_selected_cells({(w,f'P{i}') for w in wafers for i in range(2 if args.light else 5)})
                    mp.draw_maps()
                    settle(app,[parent,cor,wafer])
                    measure('initial_complete',lambda:None,[parent,cor,wafer],map_count,cycle)
                    validate_map(mp,map_count)
                    assert len(cp.all_fits) == args.parameters*(args.parameters-1)//2
                    assert len(cp.plot_widgets) == panel_count
                    parent.show()
                    parent.setup_scroll.ensureWidgetVisible(parent.raw_view)
                    def paste():
                        clipboard.setText(edited_tsv)
                        parent.raw_view.setCurrentIndex(parent.raw_model.index(0,0))
                        QTest.keyClick(parent.raw_view,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
                        QTest.keyClick(parent.raw_view,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
                    def undo():
                        QTest.keyClick(parent.raw_view,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
                    def redo():
                        QTest.keyClick(parent.raw_view,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier)
                    for name, action, expected in (('paste',paste,changed), ('undo',undo,book.raw), ('redo',redo,changed),
                                                    ('rapid_vzy',lambda:(paste(),undo(),redo()),changed)):
                        sample = measure(name,action,[parent,cor,wafer],map_count,cycle)
                        pd.testing.assert_frame_equal(parent.raw_model.document_frame(),expected)
                        pd.testing.assert_frame_equal(cor.raw_model.document_frame(),expected)
                        sample['map_data_sha256'] = validate_map(mp,map_count)
                        sample['grid_stats'] = dict(getattr(mp.map_grid, 'render_stats', {}))
                        assert len(cp.all_fits) == args.parameters*(args.parameters-1)//2
                        assert len(cp.plot_widgets) == panel_count
                        sample['correlation_pairs'] = len(cp.all_fits)
                        sample['correlation_panels'] = len(cp.plot_widgets)
                        sample['source_rows_and_strings_exact'] = True
                    for child in (wafer,cor,parent):
                        dispose(child)
                    cleanup.append({'cycle':cycle,'widgets':len(app.allWidgets()),'memory':memory_info()})
            finally:
                if clipboard.text() == edited_tsv:
                    clipboard.setText(original_clipboard)
    report = {'scenario':args.scenario, 'rows':args.rows, 'raw_parameters':args.parameters,
              'raw_shape':list(book.raw.shape), 'mapped_parameters':args.mapped_parameters,
              'cycles':args.cycles, 'platform':args.platform, 'baseline_tag':args.baseline_tag, 'light':args.light,
              'profiled':args.profile, 'samples':samples, 'cleanup':cleanup,
              'methodology':'Inclusive method spans overlap; complete includes worker/data/graphics and viewport paint. Capture is outside timing.',
              'source_sha256':{name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                  for name,module in [('wafer_graphics',graphics),('plot_page',maps_module),('matching_window',matching_module),
                                      ('correlation_page',correlation_page)]},
              'p50_ms':{f'{count}/{name}':{field:statistics.median(s[field] for s in samples if s['maps']==count and s['operation']==name)
                  for field in ('dispatch_ms','complete_ms','max_qt_gap_ms','max_gui_callback_ms')}
                  for count,name in sorted({(s['maps'],s['operation']) for s in samples})}}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()

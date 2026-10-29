"""Native Correlation rendering only; fitting happens before each measurement.

python -m benchmarks.benchmark_correlation_render --baseline-tag v4.3.4 --output .cache/p1a/before.json
python -m benchmarks.benchmark_correlation_render --output .cache/p1a/after.json
Use matching rows/parameters/page-size/cycles/platform for both runs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rows', type=int, default=10000)
    p.add_argument('--parameters', type=int, default=50)
    p.add_argument('--page-size', type=int, choices=(6, 12, 24), default=24)
    p.add_argument('--cycles', type=int, default=3)
    p.add_argument('--platform', default='windows')
    baseline = p.add_mutually_exclusive_group()
    baseline.add_argument('--baseline-tag')
    baseline.add_argument('--baseline-source', type=Path)
    p.add_argument('--baseline-curve-source', type=Path)
    p.add_argument('--profile', type=Path)
    p.add_argument('--max-retained-callback-ms', type=float)
    p.add_argument('--collect-between-cycles', action='store_true',
                   help='Diagnostic GC after page destruction, outside all timed operations')
    p.add_argument('--batch-size', type=int, choices=(2, 3))
    p.add_argument('--capture', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    import run_tests
    run_tests.isolate_settings(a.output.parent / (a.output.stem + '-isolation'))
    os.environ['QT_QPA_PLATFORM'] = a.platform
    if a.baseline_curve_source:
        name = 'metrology_app.plotting.curve'
        spec = importlib.util.spec_from_file_location(name, a.baseline_curve_source)
        curve_module = importlib.util.module_from_spec(spec)
        sys.modules[name] = curve_module
        spec.loader.exec_module(curve_module)
    if a.baseline_tag or a.baseline_source:
        source = (a.baseline_source.read_bytes() if a.baseline_source else
                  subprocess.run(['git', 'show', f'{a.baseline_tag}:metrology_app/correlation_page.py'],
                                 check=True, capture_output=True).stdout)
        target = a.output.with_name(a.output.stem + '-baseline.py')
        target.write_bytes(source)
        name = 'metrology_app.correlation_page'
        spec = importlib.util.spec_from_file_location(name, target)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    from PyQt6 import sip
    from PyQt6.QtCore import QEventLoop, QTimer, QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication
    import numpy as np
    import pandas as pd
    from metrology_app import correlation_page as module
    if a.batch_size is not None:
        module.RENDER_BATCH_SIZE = a.batch_size
    from benchmarks.benchmark_correlation_restore import memory_info
    app = QApplication.instance() or QApplication([])
    callback_costs = []
    def timed_render(method, name):
        def measured(self, *args, **kwargs):
            started = perf_counter()
            try:
                return method(self, *args, **kwargs)
            finally:
                callback_costs.append({'callback': name, 'ms': (perf_counter() - started) * 1000})
        return measured
    # Install before construction: QTimer connects the actual measured slot.
    # This supplements event-loop gaps with direct GUI render callback costs.
    for name in ('render_interactive', '_render_next_panels'):
        if hasattr(module.CorrelationPage, name):
            setattr(module.CorrelationPage, name, timed_render(getattr(module.CorrelationPage, name), name))
    rng = np.random.default_rng(12398)
    latent = rng.normal(size=a.rows)
    names = [f'P{i}' for i in range(a.parameters)]
    seeds = [pd.DataFrame({name: 10 + i + (i % 5 + 1) * latent +
                           rng.normal(0, .08 + ((i + shift) % a.parameters) / a.parameters, a.rows)
                           for i, name in enumerate(names)}) for shift in (0, 17)]
    frames = [seeds[0], seeds[0] * 1.001 + .01, seeds[1]]
    selection = {'wafers': ['W'], 'metrics': names,
                 'groups': {'W': tuple(range(a.rows))},
                 'sources': ({'name': 'Raw Data', 'rows': tuple(range(a.rows)), 'color': '#4472c4'},)}
    fits = [module.source_pairwise_linear_fits(frame, names, selection['sources'], None, None)[0]
            for frame in frames]
    assert all(len(values) == a.parameters * (a.parameters - 1) // 2 for values in fits)
    assert [module.CorrelationPage.axis_key(fit) for fit in fits[0][:a.page_size]] == [
        module.CorrelationPage.axis_key(fit) for fit in fits[1][:a.page_size]]
    samples, cleanup_samples = [], []
    for cycle in range(a.cycles):
        page = module.CorrelationPage()
        page.resize(1200, 850)
        page.page_size.setCurrentText(str(a.page_size))
        page.show()
        app.processEvents()
        def install(index):
            page.set_input(frames[index], selection)
            page.input_refresh_timer.stop()
            page.all_fits = page.fits = list(fits[index])
            page.drawn_metrics = names
            page.ready = True
            page.has_drawn_once = True
            page.page_index = page.user_page = 0
        for scenario in ('initial', 'retained_refresh', 'ranked_refresh'):
            install({'initial': 0, 'retained_refresh': 1, 'ranked_refresh': 2}[scenario])
            callback_costs.clear()
            before = memory_info()
            ticks, finished, construction_events = [], {}, []
            loop = QEventLoop()
            heartbeat = QTimer(interval=2)
            heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
            poll = QTimer(interval=5)
            deadline = QTimer(singleShot=True, interval=30000)
            deadline.timeout.connect(loop.quit)
            started = perf_counter()
            ticks.append(started)
            def pending():
                return page.background_render_pending or any(
                    getattr(item, 'render_pending', False)
                    for widget in page.plot_widgets for item in widget.listDataItems())
            def check():
                if finished.get('finishing') or pending():
                    return
                finished['finishing'] = True
                poll.stop()
                for widget in page.plot_widgets:
                    widget.viewport().repaint()
                if pending():
                    finished['finishing'] = False
                    poll.start()
                    return
                finished['end'] = perf_counter()
                loop.quit()
            poll.timeout.connect(check)
            original = module.InteractivePlotWidget
            built = []
            def create(*args, **kwargs):
                widget = original(*args, **kwargs)
                built.append(widget)
                if len(built) % 2 == 0:
                    QTimer.singleShot(0, lambda: construction_events.append(len(built)))
                return widget
            module.InteractivePlotWidget = create
            profiler = None
            if a.profile:
                import cProfile
                a.profile.mkdir(parents=True, exist_ok=True)
                profiler = cProfile.Profile()
            heartbeat.start()
            deadline.start()
            try:
                if profiler is not None:
                    profiler.enable()
                page.render_fits()
                dispatch_ms = (perf_counter() - started) * 1000
                poll.start()
                loop.exec()
            finally:
                if profiler is not None:
                    profiler.disable()
                    profiler.dump_stats(str(a.profile / f'{scenario}-{cycle}.prof'))
                heartbeat.stop()
                poll.stop()
                deadline.stop()
                module.InteractivePlotWidget = original
            assert 'end' in finished, (scenario, 'Rendering timed out')
            ticks.append(finished['end'])
            expected = page.page_fits()
            assert len(page.plot_widgets) == len(expected) == a.page_size
            digest = hashlib.sha256()
            for fit, widget in zip(expected, page.plot_widgets):
                points, line = widget.listDataItems()
                values = fit.sources[0].fit
                x, y = points.getData()
                np.testing.assert_array_equal(x, values.x)
                np.testing.assert_array_equal(y, values.y)
                order = np.argsort(values.x)
                np.testing.assert_array_equal(line.yData, values.predicted[order])
                for data in (x, y, line.xData, line.yData):
                    digest.update(data.tobytes())
            sample = {'cycle': cycle, 'scenario': scenario,
                      'dispatch_ms': dispatch_ms, 'complete_ms': (finished['end'] - started) * 1000,
                      'max_qt_gap_ms': max(b - b0 for b0, b in zip(ticks, ticks[1:])) * 1000,
                      'max_render_callback_ms': max(item['ms'] for item in callback_costs),
                      'render_callbacks': list(callback_costs),
                      'heartbeat_ticks': len(ticks), 'created': len(built),
                      'events_after_created_counts': construction_events,
                      'memory_before': before, 'memory_after': memory_info(),
                      'plot_data_sha256': digest.hexdigest(), 'all_plot_arrays_exact': True}
            samples.append(sample)
            if a.capture and cycle == 0:
                from metrology_app.appearance import widget_to_qimage
                controls = [(page._panel_cache[key]['swap_button'],
                             page._panel_cache[key]['swap_button'].isHidden())
                            for key in page._visible_panel_keys]
                try:
                    for control, _hidden in controls:
                        control.hide()
                    image, _scale = widget_to_qimage(page.plot_host, 1)
                    target = a.output.with_name(a.output.stem + '-' + scenario + '.png')
                    assert image.save(str(target))
                    sample['capture'] = {'path': str(target), 'width': image.width(),
                                         'height': image.height(),
                                         'png_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
                finally:
                    for control, hidden in controls:
                        control.setHidden(hidden)
            print(json.dumps({k: v for k, v in sample.items()
                              if k not in ('memory_before', 'memory_after', 'events_after_created_counts')}), flush=True)
            a.output.write_text(json.dumps({'samples': samples}, indent=2), encoding='utf-8')
        page.stop_background_draw()
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert sip.isdeleted(page)
        cleanup = {'cycle': cycle, 'memory_after_qt_delete': memory_info(),
                   'live_qwidgets_after_qt_delete': len(app.allWidgets())}
        if a.collect_between_cycles:
            import gc
            built.clear()
            del page
            cleanup['collected_objects'] = gc.collect()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            cleanup['memory_after_gc'] = memory_info()
            cleanup['live_qwidgets_after_gc'] = len(app.allWidgets())
        cleanup_samples.append(cleanup)
    report = {'rows': a.rows, 'parameters': a.parameters, 'fits': len(fits[0]),
              'page_size': a.page_size, 'cycles': a.cycles, 'platform': a.platform,
              'baseline_tag': a.baseline_tag, 'batch_size': getattr(module, 'RENDER_BATCH_SIZE', None),
              'baseline_source': str(a.baseline_source) if a.baseline_source else None,
              'baseline_curve_source': str(a.baseline_curve_source) if a.baseline_curve_source else None,
              'profiled': bool(a.profile),
              'collect_between_cycles': a.collect_between_cycles,
              'cleanup_samples': cleanup_samples,
              'source_sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
              'scope': 'Rendering precomputed fits through current viewport paint; no fitting or Workbook refresh',
              'samples': samples, 'p50_ms': {scenario: {field: statistics.median(s[field] for s in samples if s['scenario'] == scenario)
                  for field in ('dispatch_ms', 'complete_ms', 'max_qt_gap_ms', 'max_render_callback_ms')}
                  for scenario in ('initial', 'retained_refresh', 'ranked_refresh')}}
    a.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if a.max_retained_callback_ms is not None:
        maximum = max(sample['max_render_callback_ms'] for sample in samples
                      if sample['scenario'] == 'retained_refresh')
        assert maximum < a.max_retained_callback_ms, (maximum, a.max_retained_callback_ms)


if __name__ == '__main__':
    main()

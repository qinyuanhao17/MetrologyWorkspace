"""Read-only control latency probe; run against frozen and current source alike.

python -m benchmarks.benchmark_controls --wkb FILE --iterations 30
Uses isolated settings/recovery; reports callbacks and settled GUI gaps separately.
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
    parser.add_argument('--wkb', required=True, type=Path)
    parser.add_argument('--iterations', type=int, default=30)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--budget-ms', type=float)
    parser.add_argument('--scratch-root', type=Path)
    parser.add_argument('--operations', nargs='+', default=['select', 'single', 'stage', 'group'])
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='metrology-controls-', dir=args.scratch_root) as scratch:
        os.environ['METROLOGY_SETTINGS_PATH'] = str(Path(scratch) / 'settings.yaml')
        os.environ['METROLOGY_RECOVERY_DIR'] = str(Path(scratch) / 'recovery')
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.resize(1500, 950)
        start = perf_counter()
        window.load_workbook(args.wkb)
        loaded = perf_counter()
        window.show()
        QTest.qWait(600)
        print(json.dumps({'open_call_ms': (loaded - start) * 1000,
                          'open_settled_ms': (perf_counter() - start) * 1000,
                          'file_sha256': source_hash}), flush=True)
        timer = QTimer(interval=10)
        ticks = []
        timer.timeout.connect(lambda: ticks.append(perf_counter()))
        timer.start()
        profiler = cProfile.Profile()
        try:
            for operation in args.operations:
                plot = None
                if operation in ('wheel', 'scroll', 'trend-wheel', 'trend-scroll'):
                    window.group_controls.enabled.setChecked(True)
                    window.group_controls.apply_button.click()
                    if operation.startswith('trend-'):
                        child = window.open_correlation_workspace()
                        page = child.sequence_page
                        child.tabs.setCurrentWidget(page)
                        page.selector.selectAll()
                        page.draw_plot()
                        plot = page.plot_widgets[0]
                    else:
                        window.results_tabs.setCurrentIndex(0)
                        plot = next(iter(window.plot_groups.values()))['plots']['trend']
                        window.setup_scroll.ensureWidgetVisible(plot)
                    QTest.qWait(600)
                if args.profile:
                    profiler.enable()
                samples = []
                for _ in range(args.iterations):
                    view = window.raw_view
                    if operation == 'single':
                        view.selectAll()
                        QTest.qWait(30)
                    if operation == 'group':
                        window.group_controls.order.setCurrentIndex(1 - window.group_controls.order.currentIndex())
                        QTest.qWait(30)
                    ticks[:] = [perf_counter()]
                    start = perf_counter()
                    if operation == 'select':
                        view.clearSelection()
                        ticks[:] = [perf_counter()]
                        start = perf_counter()
                        QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                    elif operation == 'single':
                        cell = view.model().index(2, 2)
                        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                                         pos=view.visualRect(cell).center())
                        assert view.selectionModel().selection().count() == 1
                    elif operation == 'stage':
                        window.mode_tabs.setCurrentIndex(1 - window.mode_tabs.currentIndex())
                        assert window.result.result_mode == window.result_mode.currentText().lower()
                    elif operation == 'group':
                        window.group_controls.apply_button.click()
                        assert not window.group_controls.pending
                    elif plot is not None:
                        point = plot.viewport().rect().center()
                        event = QWheelEvent(QPointF(point), QPointF(plot.viewport().mapToGlobal(point)),
                                            QPoint(), QPoint(0, 120 if len(samples) % 2 else -120),
                                            Qt.MouseButton.NoButton,
                                            Qt.KeyboardModifier.NoModifier if 'scroll' in operation else Qt.KeyboardModifier.ControlModifier,
                                            Qt.ScrollPhase.NoScrollPhase, False)
                        app.sendEvent(plot.viewport(), event)
                    else:
                        raise ValueError(operation)
                    callback = (perf_counter() - start) * 1000
                    render_ready = None
                    if plot is not None:
                        # Process the actual paint, then wait only for this
                        # visible plot's full-data image; not hidden pages.
                        app.processEvents()
                        assert plot.isVisible(), 'Trend completion requires a visible target'
                        plot.viewport().repaint()
                        deadline = perf_counter() + 15
                        while any(getattr(item, 'render_pending', False)
                                  for item in plot.listDataItems()):
                            if perf_counter() >= deadline:
                                raise AssertionError('Visible full-data curve did not finish')
                            QTest.qWait(5)
                        render_ready = (perf_counter() - start) * 1000
                    # Includes deferred layout, dirty-title and plot callbacks.
                    QTest.qWait(400)
                    samples.append({'callback_ms': callback, 'render_ready_ms': render_ready,
                                    'gap_ms': max((b-a for a,b in zip(ticks,ticks[1:])), default=0) * 1000})
                summary = {}
                for key in ('callback_ms', 'gap_ms', *(['render_ready_ms'] if plot is not None else [])):
                    values = sorted(sample[key] for sample in samples)
                    summary[key] = {'p50': statistics.median(values),
                                    'p95': values[min(len(values)-1, int(len(values)*.95))],
                                    'max': max(values)}
                print(json.dumps({'operation': operation, 'samples': samples, **summary}), flush=True)
                if args.budget_ms is not None and summary['gap_ms']['max'] > args.budget_ms:
                    raise AssertionError(f"{operation}: GUI gap {summary['gap_ms']['max']:.1f} ms > {args.budget_ms} ms")
        finally:
            profiler.disable()
            timer.stop()
            if args.profile:
                import pstats
                pstats.Stats(profiler).strip_dirs().sort_stats('cumtime').print_stats(40)
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()
            assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == source_hash


if __name__ == '__main__':
    main()

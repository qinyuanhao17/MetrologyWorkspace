"""Actual Ctrl+V / Ctrl+Z on a fixed, read-only NOVA workbook.

Run in independent processes with --code-root pointing to frozen/current source.
Settings, recovery and font caches stay inside --scratch. Timings distinguish
key return, current numerical results and full visible viewport repaint.
Offscreen rendering is not native display frame-rate verification.
"""
import argparse
import cProfile
import csv
import hashlib
import json
from io import StringIO
import os
from pathlib import Path
import pstats
import sys
import tempfile
from time import perf_counter

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-root', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--wkb', type=Path, required=True)
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--kind', choices=('cell', 'column'), default='cell')
    parser.add_argument('--burst', action='store_true')
    args = parser.parse_args()
    if args.count < 1:
        parser.error('--count must be positive')
    sys.path.insert(0, str(args.code_root))
    args.scratch.mkdir(parents=True, exist_ok=True)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['METROLOGY_SETTINGS_PATH'] = str(args.scratch / 'settings.yaml')
    os.environ['METROLOGY_RECOVERY_DIR'] = str(args.scratch / 'recovery')
    os.environ['MPLCONFIGDIR'] = str(args.scratch / 'matplotlib')
    tempfile.tempdir = str(args.scratch)

    import pandas as pd
    import pyqtgraph as pg
    import metrology_app
    implementation = Path(metrology_app.__file__).resolve().parent
    assert implementation == (args.code_root / 'metrology_app').resolve(), implementation
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from metrology_app.appearance import configure_fonts
    from metrology_app.matching_window import MatchingWindow

    app = QApplication.instance() or QApplication([])
    configure_fonts(app)
    sha = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    window = MatchingWindow()
    window.resize(1500, 950)
    window.load_workbook(args.wkb)
    window.result_mode.setCurrentText('Preview')
    window.document.timer.stop()
    window.show()
    ticks = []
    timer = QTimer(interval=10)
    timer.timeout.connect(lambda: ticks.append(perf_counter()))
    timer.start()

    def settle():
        deadline = perf_counter() + 30
        while not window._analysis_current or window._auto_run_pending:
            assert perf_counter() < deadline
            QTest.qWait(5)
        app.processEvents()
        targets = [window]
        plots = [p for target in targets for p in target.findChildren(pg.PlotWidget) if p.isVisible()]
        for plot in plots:
            plot.viewport().repaint()
        while any(getattr(item, 'render_pending', False) for plot in plots for item in plot.listDataItems()):
            assert perf_counter() < deadline
            QTest.qWait(5)
        app.processEvents()
        for target in targets:
            target.repaint()
        return perf_counter()

    def measure(name, action):
        ticks[:] = [perf_counter()]
        start = perf_counter()
        action()
        callback = perf_counter()
        deadline = start + 30
        while not window._analysis_current or window._auto_run_pending:
            assert perf_counter() < deadline
            QTest.qWait(5)
        numerical = perf_counter()
        visible = settle()
        QTest.qWait(35)
        print(json.dumps({'operation': name, 'callback_ms': (callback-start)*1000,
                          'numerical_ms': (numerical-start)*1000, 'visible_ms': (visible-start)*1000,
                          'max_gap_ms': max((b-a for a,b in zip(ticks,ticks[1:])), default=0)*1000}), flush=True)

    settle()
    raw = window.raw_model.document_frame()
    baseline_summary = window.result.summary.copy()
    mapping = window.selected_mappings()[0]
    name = mapping.raw_column
    column = raw.columns.get_loc(name)
    original = raw.iat[0, column]
    output = StringIO()
    changed = raw.copy()
    changed[name] = [str(float(value) + .25) for value in raw[name]]
    csv.writer(output, delimiter='\t', lineterminator='\n').writerows([list(raw.columns)] + changed.values.tolist())
    whole_clipboard = output.getvalue()
    print(json.dumps({'implementation': str(implementation),
                      'rows': len(raw), 'columns': len(raw.columns), 'column': name,
                      'sha256': sha, 'scope': 'main_workbook_only',
                      'results_tab': window.results_tabs.tabText(window.results_tabs.currentIndex()),
                      'visible_plot_count': sum(p.isVisible() for p in window.findChildren(pg.PlotWidget))}), flush=True)
    view = window.raw_view
    for repeat in range(args.count):
        view.scrollTo(view.model().index(1, column))
        view.setCurrentIndex(view.model().index(1, column))
        view.setFocus()
        QTest.qWait(20)
        value = str(float(original) + .25 + repeat / 100)
        view.setCurrentIndex(view.model().index(0, 0) if args.kind == 'column' else view.model().index(1, column))
        app.clipboard().setText(whole_clipboard if args.kind == 'column' else value)
        measure('paste', lambda: QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier))
        value = changed.iat[0, column] if args.kind == 'column' else value
        assert window.raw_model.cells[(1, column)] == value
        assert window.result.series(mapping.name)['Raw'].iloc[0] == float(value)
        measure('undo', lambda: QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
        assert window.raw_model.cells[(1, column)] == original
        assert window.result.series(mapping.name)['Raw'].iloc[0] == float(original)
        pd.testing.assert_frame_equal(window.result.summary, baseline_summary)

    if args.burst:
        for row in range(1, 6):
            view.setCurrentIndex(view.model().index(row, column))
            app.clipboard().setText(str(float(raw.iat[row-1, column]) + .5))
            QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        settle()
        def undo_burst():
            for row in range(5, 0, -1):
                QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                assert window.raw_model.cells[(row, column)] == raw.iat[row-1, column]
                QTest.qWait(10)
        measure('five_undo_burst', undo_burst)

    if args.profile:
        view.setCurrentIndex(view.model().index(0, 0))
        app.clipboard().setText(whole_clipboard)
        profile = cProfile.Profile()
        profile.enable()
        measure('profile_paste', lambda: QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier))
        profile.disable()
        pstats.Stats(profile).strip_dirs().sort_stats('cumtime').print_stats(55)
        profile = cProfile.Profile()
        profile.enable()
        measure('profile_undo', lambda: QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
        profile.disable()
        pstats.Stats(profile).strip_dirs().sort_stats('cumtime').print_stats(55)

    pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)
    pd.testing.assert_frame_equal(window.result.summary, baseline_summary)
    timer.stop()
    for target in [window]:
        target.document.force_close = True
        target.document.timer.stop()
        target.document.identity_timer.stop()
        target.close()
        target.deleteLater()
    app.processEvents()
    assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == sha
    print(json.dumps({'equivalence': 'pass', 'source_hash_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()

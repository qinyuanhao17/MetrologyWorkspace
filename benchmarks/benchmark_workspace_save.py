"""Measure complete Save stages and GUI heartbeat on an owned literal workbook."""
import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='workspace-save-probe-') as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts
        from metrology_app.correlation_window import CorrelationWindow
        from metrology_app import workspace_document
        from metrology_app.workspace_store import load_workspace
        app = QApplication.instance() or QApplication([])
        configure_fonts(app)
        window = CorrelationWindow()
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 6000, 'Die Seq': list(map(str, range(1, 6001))),
                            **{f'P{i}': [f'{row+i}.000000000001' for row in range(6000)] for i in range(31)}})
        window.set_table(raw, 'Synthetic literal Save fixture')
        window.set_reference_table(raw)
        window.show()
        app.processEvents()
        path = Path(scratch) / 'owned.wct'
        reports = []
        profile = cProfile.Profile()
        for label in ('first-save', 'overwrite'):
            stages, ticks = {}, []
            def instrument(name, call):
                def timed(*a, **kw):
                    start = time.perf_counter()
                    try:
                        return call(*a, **kw)
                    finally:
                        stages[name] = stages.get(name, 0) + time.perf_counter() - start
                return timed
            timer = QTimer(interval=10)
            timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
            start = time.perf_counter()
            ticks.append(start)
            timer.start()
            with patch.object(window, 'workspace_snapshot', instrument('snapshot', window.workspace_snapshot)), \
                 patch.object(workspace_document, 'save_workspace', instrument('sqlite_write_and_protection', workspace_document.save_workspace)), \
                 patch.object(window.document, 'mark_clean', instrument('accept_baseline', window.document.mark_clean)):
                profile.enable()
                window.document.save(path)
                profile.disable()
            end = time.perf_counter()
            timer.stop()
            ticks.append(end)
            reopened = load_workspace(path, expected_type='correlation_trend')
            pd.testing.assert_frame_equal(reopened.frames['raw_data'], raw)
            pd.testing.assert_frame_equal(reopened.frames['reference_data'], raw)
            reports.append({'operation': label, 'total_seconds': end-start,
                            'heartbeat_ticks': len(ticks)-2,
                            'max_heartbeat_gap_seconds': max(b-a for a,b in zip(ticks,ticks[1:])),
                            'stages': stages, 'bytes': path.stat().st_size, 'literal_roundtrip_equal': True})
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(25)
        args.output.write_text(json.dumps({'fixture': 'synthetic 6000 × 33 literal rows in each source',
            'source_module': workspace_document.__file__,
            'samples': reports, 'profile': stream.getvalue()}, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(reports, indent=2), flush=True)
        window.document.force_close = True
        window.close()


if __name__ == '__main__':
    main()

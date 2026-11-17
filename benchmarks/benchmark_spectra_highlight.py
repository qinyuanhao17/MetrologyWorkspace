"""Repeatable selection latency, scene growth and cached/native pixel probe."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import numpy as np
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--groups', type=int, default=64)
    parser.add_argument('--points', type=int, default=5001)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    with tempfile.TemporaryDirectory(prefix='spectra-highlight-') as scratch:
        isolate_settings(scratch)
        from PyQt6.QtGui import QColor
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.spectra_plots import CurveGroup, CurveSegment, MuellerPanel
        from metrology_app.sme_spectra import M_COLS
        app = QApplication.instance() or QApplication([])
        from metrology_app.appearance import configure_fonts, set_theme_palette
        configure_fonts(app)
        set_theme_palette('light')
        matrix = MuellerPanel()
        matrix.resize(1600, 1000)
        matrix.apply_theme(matrix.palette())
        matrix.show()
        x = np.linspace(200, 900, args.points)
        groups = {}
        for metric, name in enumerate(M_COLS):
            groups[name] = []
            for index in range(args.groups):
                y = np.sin(x / (43 + metric * 2) + index / 90) * .008 + index / 12000
                y[args.points // 3:args.points // 3 + 4] = np.nan
                groups[name].append(CurveGroup(f'file-{index}', QColor('#E377C2'),
                    (CurveSegment(f'file-{index}', x, y),)))
        matrix.set_curves(groups, set())

        def settle():
            deadline = time.monotonic() + 90
            QTest.qWait(30)
            while any(p.render_pending for p in matrix.mij_plots.values()):
                if time.monotonic() > deadline:
                    raise TimeoutError('Selection raster did not settle')
                QTest.qWait(5)
            app.processEvents()

        settle()
        panels = tuple(matrix.mij_plots.values())
        source_buffers = [(item, item.xData, item.yData, item.screen_cache._revision)
                          for panel in panels for item in panel._curve_items]
        initial_scene = len(panels[0].plot.scene().items())
        samples = []
        for label, keys in (('single', {'file-3'}), ('multi', {'file-3', 'file-19', 'file-41'}),
                            ('clear', set()), ('single-repeat', {'file-3'})):
            start = time.perf_counter()
            for panel in panels:
                panel.set_emphasized_keys(keys)
            submit = time.perf_counter() - start
            immediate = bool(keys) and all(item.opacity() > 0 for panel in panels
                                           for item in panel._emphasis_items)
            settle()
            samples.append({'selection': label, 'submit_seconds': submit,
                            'settled_seconds': time.perf_counter() - start,
                            'native_highlight_visible_before_cache': immediate})
            matrix.grab().save(str(args.output.with_suffix(f'.{label}.png')))
        panel = panels[0]
        cached = panel.plot.grab().toImage()
        for item in panel.plot.listDataItems():
            item.setExportMode(True, {'antialias': True})
        native = panel.plot.grab().toImage()
        a = np.frombuffer(cached.constBits().asstring(cached.sizeInBytes()), dtype=np.uint8).astype(int)
        b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
        pixel_error = {'mean': float(np.abs(a - b).mean()), 'max': int(np.abs(a - b).max())}
        for item in panel.plot.listDataItems():
            item.setExportMode(False)
        for _ in range(30):
            for keys in ({'file-3', 'file-19'}, set()):
                for target in panels:
                    target.set_emphasized_keys(keys)
        settle()
        selection_samples = []
        for keys in ({'file-3'}, {'file-3', 'file-19', 'file-41'}, set()):
            start = time.perf_counter()
            for target in panels:
                target.set_selected_keys(keys)
            submitted = time.perf_counter() - start
            settle()
            selection_samples.append({'files': len(keys), 'submit_seconds': submitted})
        report = {'operation': 'persistent Highlight; ordinary selection is unchanged',
                  'source_module': sys.modules[MuellerPanel.__module__].__file__,
                  'fixture': 'synthetic overlapping Mueller residual-like stress data; not measured SME',
                  'groups_per_axis': args.groups, 'points_per_curve': args.points,
                  'panels': len(panels), 'selections': samples, 'pixel_error': pixel_error,
                  'ordinary_selection': selection_samples,
                  'base_arrays_retained': all(item.xData is x and item.yData is y for item, x, y, _ in source_buffers),
                  'base_cache_revisions_unchanged': all(item.screen_cache._revision == revision for item, _, _, revision in source_buffers),
                  'scene_items_before': initial_scene, 'scene_items_after_clear': len(panel.plot.scene().items())}
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
        for target in panels:
            target.cancel_rendering()
        matrix.close()


if __name__ == '__main__':
    main()

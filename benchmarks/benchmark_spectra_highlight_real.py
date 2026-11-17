"""Read-only real SME Residual/Highlight validation in both source-color modes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from run_tests import isolate_settings


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--mode', choices=('wafer', 'sme'), default='wafer')
    parser.add_argument('--pink-stress', action='store_true', help='Visual fixture only: use pink for all source colors.')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    with tempfile.TemporaryDirectory(prefix='real-spectra-highlight-') as scratch:
        isolate_settings(scratch)
        import numpy as np
        from PyQt6.QtGui import QColor
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.settings import save_settings
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_viewer import SpectraViewerWindow
        app = QApplication.instance() or QApplication([])
        configure_fonts(app)
        save_settings({'theme': 'light'})
        set_theme_palette('light')
        loaded = load_folder(args.folder)
        assert loaded.spectra and not loaded.cancelled
        input_hashes = {str(source.path): digest(source.path) for source in loaded.spectra}
        def numeric_digest():
            value = hashlib.sha256()
            for source in loaded.spectra:
                for channel in source.channels:
                    value.update(channel.wavelength.tobytes())
                    value.update(channel.numeric.tobytes())
            return value.hexdigest()
        original_numeric = numeric_digest()
        viewer = SpectraViewerWindow()
        viewer.resize(2100, 1250)
        for key, action in viewer.view_actions.items():
            action.setChecked(key == 'mueller')
        viewer.show()
        viewer.apply_load_result(loaded, replace=True)
        viewer.check_all_spectra()
        def settle():
            deadline = time.monotonic() + 90
            QTest.qWait(30)
            while viewer.plot_render_pending or (viewer.map_window is not None and viewer.map_window._pending_page_wafers):
                if time.monotonic() > deadline:
                    raise TimeoutError('Real SME rendering did not settle')
                QTest.qWait(5)
            app.processEvents()
        settle()
        baseline = next(s for s in loaded.spectra if any(c.spectrum_type == 'mueller' for c in s.channels))
        viewer.set_baseline(baseline.key)
        viewer.set_color_mode(args.mode)
        settle()
        if args.pink_stress:
            for color in viewer._channel_colors.values():
                color.setNamedColor('#E377C2')
            viewer._plot_revision += 1
            viewer._refresh_plots()
            settle()
        panels = tuple(viewer.mueller_panel.mij_plots.values())
        assert len(panels) == 16 and all(panel.groups for panel in panels)
        rendered = sorted({segment.spectrum_key for group in panels[0].groups for segment in group.segments})
        chosen = [key for key in rendered if key != baseline.key]
        assert len(chosen) >= 3
        single = {chosen[len(chosen) // 3]}
        multi = {chosen[len(chosen) // 5], chosen[len(chosen) // 2], chosen[-1]}
        original_buffers = [(item, item.xData, item.yData) for panel in panels for item in panel._curve_items]
        mapping = viewer.open_wafer_map()
        mapping.resize(720, 760)
        settle()
        def point_geometry():
            return [(p.pos().x(), p.pos().y(), p.size(), p.pen().widthF())
                    for plot in mapping.wafer_plots.values() for p in plot.scatter.points()]
        geometry = point_geometry()
        def capture(label):
            viewer.mueller_panel.grab().save(str(args.output.with_suffix(f'.{label}.png')))
        capture('unhighlighted')
        samples = []
        ranges = [panel.plot.getViewBox().viewRange() for panel in panels]
        for label, keys in (('single', single), ('multi', multi), ('clear', set())):
            if label == 'multi':
                viewer._apply_highlights(set())
                settle()
            viewer.select_spectrum_keys(keys)
            start = time.perf_counter()
            if keys:
                viewer.highlight_selected_spectra(True)
            elif hasattr(viewer, 'clear_highlights'):
                viewer.clear_highlights()
            else:
                viewer._apply_highlights(set())
            viewer.select_spectrum_keys(set())
            submit = time.perf_counter() - start
            settle()
            samples.append({'operation': label, 'submit_seconds': submit,
                            'settled_seconds': time.perf_counter() - start,
                            'highlighted_files': len(viewer.highlighted_keys)})
            assert [panel.plot.getViewBox().viewRange() for panel in panels] == ranges
            capture(label)
            if label == 'multi':
                assert point_geometry() == geometry, 'Highlight changed point size, border or position'
                mapping.grab().save(str(args.output.with_suffix('.die-map.png')))
                target = next(panel for panel in panels if panel.title == 'M12')
                screen = target.plot.grab().toImage()
                for item in target.plot.listDataItems():
                    item.setExportMode(True, {'antialias': True})
                native = target.plot.grab().toImage()
                screen.save(str(args.output.with_suffix('.screen-M12.png')))
                native.save(str(args.output.with_suffix('.native-M12.png')))
                a = np.frombuffer(screen.constBits().asstring(screen.sizeInBytes()), dtype=np.uint8).astype(int)
                b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
                pixel_error = {'max': int(np.abs(a-b).max()), 'mean': float(np.abs(a-b).mean())}
                for item in target.plot.listDataItems():
                    item.setExportMode(False)
                settle()
        assert numeric_digest() == original_numeric
        source_files_unchanged = all(digest(Path(path)) == value for path, value in input_hashes.items())
        assert source_files_unchanged
        report = {'folder': str(args.folder), 'mode': args.mode, 'pink_visual_fixture': args.pink_stress,
            'source_module': sys.modules[SpectraViewerWindow.__module__].__file__,
            'loaded_sme': len(loaded.spectra), 'issues': dict(Counter(issue.status for issue in loaded.issues)),
            'channel_types': dict(Counter(c.spectrum_type for s in loaded.spectra for c in s.channels)),
            'baseline_sme': str(baseline.path), 'residual_files_plotted': len(rendered),
            'panels': [panel.title for panel in panels], 'groups_per_panel': [len(panel.groups) for panel in panels],
            'selections': samples, 'pixel_error_M12': pixel_error, 'die_points': len(geometry),
            'point_geometry_unchanged': True, 'original_numeric_sha256': original_numeric,
            'axis_ranges_unchanged': True,
            'numeric_arrays_unchanged': True, 'input_files_unchanged': source_files_unchanged,
            'base_buffers_retained': all(item.xData is x and item.yData is y for item, x, y in original_buffers),
            'input_sha256': input_hashes}
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key:value for key,value in report.items() if key != 'input_sha256'}, indent=2), flush=True)
        # The archived baseline installs its unpinned map as a global filter.
        # Remove that listener before QObject teardown, after all measurements.
        app.removeEventFilter(mapping.window_pin)
        viewer.document.force_close = True
        viewer.close()
        viewer.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    main()

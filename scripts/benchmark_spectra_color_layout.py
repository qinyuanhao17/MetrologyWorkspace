"""Measure Color By modes and verify resizable Spectra layout on real SME files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--verify-pixels", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-colors-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import LoadResult, load_folder
        from metrology_app.spectra_viewer import SpectraViewerWindow

        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        result = load_folder(args.folder)
        if args.limit:
            result = LoadResult(result.spectra[:args.limit], result.issues)
        window = SpectraViewerWindow()
        window.resize(2000, 1100)
        window.show()
        window.apply_load_result(result, replace=True)
        def source_hash():
            digest = hashlib.sha256()
            for spectrum in result.spectra:
                for channel in spectrum.channels:
                    digest.update(channel.numeric.tobytes())
            return digest.hexdigest()
        original_hash = source_hash()
        ticks = []
        heartbeat = QTimer(interval=10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        heartbeat.start()
        report = {"spectra": len(result.spectra), "actions": {}, "platform": app.platformName(),
                  "device_pixel_ratio": window.devicePixelRatioF()}

        def settle():
            deadline = time.monotonic() + 120
            QTest.qWait(30)
            while window.plot_render_pending and time.monotonic() < deadline:
                QTest.qWait(5)
            assert not window.plot_render_pending

        def timed(name, action):
            ticks[:] = [time.perf_counter()]
            start = ticks[0]
            action()
            submit = time.perf_counter() - start
            settle()
            end = time.perf_counter()
            ticks.append(end)
            groups = window.plot_panels["S"].groups
            report["actions"][name] = {"submit_seconds": submit, "complete_seconds": end - start,
                "max_heartbeat_gap_seconds": max(b-a for a, b in zip(ticks, ticks[1:])),
                "S_groups": len(groups), "S_distinct_colors": len({g.color.name() for g in groups}),
                "S_scene_curves": len(window.plot_panels["S"].plot.listDataItems())}
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(name, report["actions"][name], flush=True)

        timed("check_wafer", window.check_all_spectra)
        report["main_tree_fraction"] = window.main_splitter.sizes()[0] / sum(window.main_splitter.sizes())
        assert abs(report["main_tree_fraction"] - .25) < .03
        panel = window.plot_panels["S"]
        wafer_colors = {g.key: g.color.name() for g in panel.groups}
        timed("sme", lambda: window.color_by_combo.setCurrentIndex(1))
        sme_colors = {g.key: g.color.name() for g in panel.groups}
        assert len(set(sme_colors.values())) == len(sme_colors)
        window.grab().save("qa_spectra_color_sme.png")
        window.select_spectrum_keys({result.spectra[0].key})
        timed("uncheck_one_sme", window.uncheck_selected_spectra)
        timed("recheck_one_sme", window.check_selected_spectra)
        assert {g.key: g.color.name() for g in panel.groups} == sme_colors
        timed("wafer", lambda: window.color_by_combo.setCurrentIndex(0))
        assert {g.key: g.color.name() for g in panel.groups} == wafer_colors
        window.grab().save("qa_spectra_color_wafer.png")
        splitters = [window.main_splitter, window.legend_splitter, window.plot_splitter,
                     window.left_plot_splitter, window.mueller_panel.plot_splitter,
                     *window.mueller_panel.row_splitters]
        for splitter in splitters:
            splitter.setSizes([0] + [500] * (splitter.count()-1))
            app.processEvents()
            assert splitter.sizes()[0] == 0
            handle = splitter.handle(1)
            QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
            app.processEvents()
            assert all(size > 0 for size in splitter.sizes())
        report["splitters_collapsed_and_restored"] = len(splitters)
        if args.verify_pixels:
            window.color_by_combo.setCurrentIndex(1)
            window.select_spectrum_keys({s.key for s in result.spectra[:2]})
            settle()
            panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
            report["pixel_byte_differences"] = {}
            for name, limits in (("full", None), ("zoom", (520, 540)), ("phase", (390, 420))):
                for target in panels:
                    if limits is None:
                        target._auto_range_all()
                    else:
                        target.plot.setXRange(*limits, padding=0)
                settle()
                cached = [target.plot.grab().toImage() for target in panels]
                curves = [curve for target in panels for curve in (*target._curve_items, *target._highlight_items)]
                for curve in curves:
                    curve.setExportMode(True, {"antialias": False})
                native = [target.plot.grab().toImage() for target in panels]
                differences = []
                for i, (left, right) in enumerate(zip(cached, native)):
                    a = bytes(left.constBits().asstring(left.sizeInBytes()))
                    b = bytes(right.constBits().asstring(right.sizeInBytes()))
                    differences.append(sum(x != y for x, y in zip(a, b)))
                    if differences[-1]:
                        left.save(f"qa_spectra_sme_{name}_{i}_cached.png")
                        right.save(f"qa_spectra_sme_{name}_{i}_native.png")
                report["pixel_byte_differences"][name] = differences
                for curve in curves:
                    curve.setExportMode(False)
            assert all(not any(d) for d in report["pixel_byte_differences"].values()), report["pixel_byte_differences"]
        report["source_arrays_sha256"] = source_hash()
        report["source_arrays_unchanged"] = report["source_arrays_sha256"] == original_hash
        assert report["source_arrays_unchanged"]
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        heartbeat.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

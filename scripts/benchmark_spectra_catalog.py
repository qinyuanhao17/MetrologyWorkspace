"""Profile loading and full-spectrum drawing on a supplied real catalog."""
import argparse
from collections import Counter
import cProfile
import json
from pathlib import Path
import pstats
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify-pixels", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-catalog-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtTest import QTest
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import load_folder, scan_sme_files
        from metrology_app.spectra_viewer import SpectraViewerWindow

        report = {"folder": str(args.folder), "sme_count": len(scan_sme_files(args.folder))}
        profile = cProfile.Profile()
        start = time.perf_counter()
        profile.enable()
        result = load_folder(args.folder)
        profile.disable()
        report["load_seconds"] = time.perf_counter() - start
        report["readable"] = len(result.spectra)
        report["issues"] = [{"path": str(issue.path.relative_to(args.folder)),
                              "message": issue.message, "status": issue.status} for issue in result.issues]
        report["issue_counts"] = dict(Counter(issue.message for issue in result.issues))
        report["channels"] = sum(len(s.channels) for s in result.spectra)
        report["channel_identities"] = len({c.key for s in result.spectra for c in s.channels})
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "issues"}), flush=True)
        with args.output.with_suffix(".profile.log").open("w", encoding="utf-8") as stream:
            pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(25)
        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        window = SpectraViewerWindow()
        window.resize(2200, 1150)
        window.show()
        app.processEvents()
        def timed(name, action):
            start = time.perf_counter()
            profile.enable()
            action()
            report[name + "_submit"] = time.perf_counter() - start
            app.processEvents()
            app.processEvents()
            event_slices = []
            while window.plot_render_pending:
                tick = time.perf_counter()
                app.processEvents()
                event_slices.append(time.perf_counter() - tick)
                QTest.qWait(2)
            app.processEvents()
            profile.disable()
            report[name] = time.perf_counter() - start
            if event_slices:
                report[name + "_max_paint_slice"] = max(event_slices)
            print(name, report[name], flush=True)
        timed("apply_seconds", lambda: window.apply_load_result(result, replace=True))
        timed("check_all_seconds", window.check_all_spectra)
        panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
        def curve_items(widget):
            return [item for item in widget.plot.listDataItems() +
                    (list(widget.secondary.childGroup.childItems()) if widget.secondary is not None else [])
                    if hasattr(item, "setExportMode")]

        def settle():
            deadline = time.perf_counter() + 60
            app.processEvents()
            while window.plot_render_pending and time.perf_counter() < deadline:
                QTest.qWait(2)
            assert not window.plot_render_pending

        def repaints():
            frames = []
            for _ in range(3):
                start = time.perf_counter()
                for widget in panels:
                    widget.plot.viewport().update()
                app.processEvents()
                frames.append(time.perf_counter() - start)
            return frames

        report["repeat_repaint_seconds"] = repaints()
        for widget in panels:
            for item in curve_items(widget):
                item.setExportMode(True, {"antialias": False})
        app.processEvents()
        report["uncached_repeat_repaint_seconds"] = repaints()
        for widget in panels:
            for item in curve_items(widget):
                item.setExportMode(False)
        settle()
        # Flush the deliberate cache-disable experiment before timing selection.
        report["cache_rewarm_seconds"] = repaints()
        timed("select_one_seconds", lambda: window.select_spectrum_keys({result.spectra[0].key}))
        timed("select_all_seconds", lambda: window.select_spectrum_keys({s.key for s in result.spectra}))
        timed("clear_selection_seconds", lambda: window.select_spectrum_keys(set()))
        timed("add_same_seconds", lambda: window.apply_load_result(result, replace=False))
        panel = window.plot_panels["S"]
        timed("zoom_seconds", lambda: panel.plot.setXRange(520, 540, padding=0))
        timed("unfold_seconds", window.unfold_tree)
        while window._unfold_timer.isActive():
            app.processEvents()
        report["tree_leaves"] = len(window.spectrum_items)
        start = time.perf_counter()
        window.start_loading(args.folder, replace=False)
        progress_messages = []
        window._loader.progress.connect(lambda *values: progress_messages.append(values))
        max_event = 0.0
        while window._loader is not None:
            tick = time.perf_counter()
            app.processEvents()
            max_event = max(max_event, time.perf_counter() - tick)
            QTest.qWait(1)
        report["thread_add_seconds"] = time.perf_counter() - start
        report["thread_add_max_event_seconds"] = max_event
        report["progress_messages"] = len(progress_messages)
        if args.verify_pixels:
            window.select_spectrum_keys({s.key for s in result.spectra[:2]})
            settle()
            report["cache_image_differences"] = {}
            for name, x_range in (("all", None), ("zoom", (520, 540))):
                for widget in panels:
                    if x_range is None:
                        widget.plot.getPlotItem().autoBtn.clicked.emit(None)
                    else:
                        widget.plot.setXRange(*x_range, padding=0)
                frames = []
                for native in (False, True):
                    for widget in panels:
                        for item in curve_items(widget):
                            item.setExportMode(native, {"antialias": False} if native else None)
                    settle()
                    images = []
                    for widget in panels:
                        image = widget.plot.grab().toImage()
                        images.append(bytes(image.constBits().asstring(image.sizeInBytes())))
                    frames.append(images)
                differences = [sum(a != b for a, b in zip(left, right))
                               for left, right in zip(*frames)]
                report["cache_image_differences"][name] = differences
                assert not any(differences), (name, differences)
                for widget in panels:
                    for item in curve_items(widget):
                        item.setExportMode(False)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        with args.output.with_suffix(".profile.log").open("w", encoding="utf-8") as stream:
            pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(45)
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

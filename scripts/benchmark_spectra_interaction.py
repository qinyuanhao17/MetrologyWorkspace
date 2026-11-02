"""Measure real checkbox, window resize and splitter input latency on SME data."""
import argparse
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
    with tempfile.TemporaryDirectory(prefix="spectra-input-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QPoint, Qt, QTimer
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_viewer import SpectraViewerWindow

        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        result = load_folder(args.folder)
        window = SpectraViewerWindow()
        window.resize(1800, 1000)
        window.show()
        window.apply_load_result(result, replace=True)
        tree = window.tree
        wafer = tree.topLevelItem(0)
        lot = wafer.child(0)
        pad = lot.child(0)
        wafer.setExpanded(True)
        lot.setExpanded(True)
        pad.setExpanded(True)
        app.processEvents()
        report = {"folder": str(args.folder), "readable": len(result.spectra),
                  "qt_platform": app.platformName(), "device_pixel_ratio": window.devicePixelRatioF(),
                  "initial_window_size": [window.width(), window.height()], "actions": {}}
        profile = cProfile.Profile()
        ticks = []
        heartbeat = QTimer(interval=10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        heartbeat.start()

        def settle():
            deadline = time.perf_counter() + 60
            # Native window/layout events may enqueue painting on a later turn.
            for _ in range(4):
                app.processEvents()
                QTest.qWait(2)
            while window.plot_render_pending and time.perf_counter() < deadline:
                app.processEvents()
                QTest.qWait(2)
            assert not window.plot_render_pending, "drawing did not settle"
            app.processEvents()

        def timed(name, action):
            ticks.clear()
            start = time.perf_counter()
            ticks.append(start)
            profile.enable()
            action()
            submit = time.perf_counter() - start
            settle()
            profile.disable()
            end = time.perf_counter()
            ticks.append(end)
            report["actions"][name] = {"submit_seconds": submit, "complete_seconds": end - start,
                "max_heartbeat_gap_seconds": max(b - a for a, b in zip(ticks, ticks[1:])),
                "checked": len(window.checked_spectra()), "selected": len(window._selected_keys)}
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(name, report["actions"][name], flush=True)

        def click_check(item):
            tree.scrollToItem(item)
            app.processEvents()
            rect = tree.visualItemRect(item)
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(rect.left() + 8, rect.center().y()))

        timed("check_pad", lambda: click_check(pad))
        assert len(window.checked_spectra()) == pad.childCount()
        timed("uncheck_one", lambda: click_check(pad.child(0)))
        timed("recheck_one", lambda: click_check(pad.child(0)))
        timed("resize_larger", lambda: window.resize(2200, 1150))
        timed("resize_smaller", lambda: window.resize(1500, 850))
        timed("fullscreen", window.showFullScreen)
        timed("normal", window.showNormal)

        def drag(splitter):
            handle = splitter.handle(1)
            center = handle.rect().center()
            origin = handle.mapToGlobal(center)
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
            moves = []
            for offset in (10, 20, 30, 40, 50, 60, 50, 40):
                start = time.perf_counter()
                QTest.mouseMove(handle, handle.mapFromGlobal(origin + QPoint(offset, 0)))
                app.processEvents()
                moves.append(time.perf_counter() - start)
            start = time.perf_counter()
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton,
                               pos=handle.mapFromGlobal(origin + QPoint(40, 0)))
            app.processEvents()
            report.setdefault("drag_samples", []).append({"move_seconds": moves,
                "release_seconds": time.perf_counter() - start})

        timed("drag_plot_boundary", lambda: drag(window.plot_splitter))
        timed("drag_mueller_boundary", lambda: drag(window.mueller_panel.row_splitters[0]))
        if args.verify_pixels:
            window.resize(1800, 1000)
            window.select_spectrum_keys({s.key for s in result.spectra[:2]})
            settle()
            panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
            report["pixel_byte_differences"] = {}
            for name, limits in (("all", None), ("zoom", (520, 540)), ("phase", (390, 420))):
                for panel in panels:
                    if limits is None:
                        panel.plot.getPlotItem().autoBtn.clicked.emit(None)
                    else:
                        panel.plot.setXRange(*limits, padding=0)
                settle()
                cached = [panel.plot.grab().toImage() for panel in panels]
                curves = [item for panel in panels for item in (*panel._curve_items, *panel._highlight_items)]
                report["background_cache_failures"] = sum(item.screen_cache._failed for item in curves)
                for item in curves:
                    item.setExportMode(True, {"antialias": False})
                native = [panel.plot.grab().toImage() for panel in panels]
                differences = []
                for index, (left, right) in enumerate(zip(cached, native)):
                    a = bytes(left.constBits().asstring(left.sizeInBytes()))
                    b = bytes(right.constBits().asstring(right.sizeInBytes()))
                    differences.append(sum(x != y for x, y in zip(a, b)))
                    if differences[-1]:
                        left.save(f"qa_spectra_{name}_{index}_cached.png")
                        right.save(f"qa_spectra_{name}_{index}_native.png")
                report["pixel_byte_differences"][name] = differences
                for item in curves:
                    item.setExportMode(False)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            assert not report["background_cache_failures"]
            assert all(not any(values) for values in report["pixel_byte_differences"].values()), report["pixel_byte_differences"]
        with args.output.with_suffix(".profile.log").open("w", encoding="utf-8") as stream:
            pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(35)
        window.close()
        window.deleteLater()
        heartbeat.stop()
        app.processEvents()


if __name__ == "__main__":
    main()

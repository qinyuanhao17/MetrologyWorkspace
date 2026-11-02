"""Repeatable real-folder loading, input-latency and screen-quality probe."""
import argparse
import cProfile
import hashlib
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
    with tempfile.TemporaryDirectory(prefix="spectra-quality-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QTimer
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.spectra_viewer import SpectraViewerWindow
        import numpy as np

        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        window = SpectraViewerWindow()
        window.resize(2000, 1100)
        window.show()
        for action in window.view_actions.values():
            action.setChecked(True)
        QTest.qWait(30)
        report = {"folder": str(args.folder), "window_size": [2000, 1100],
                  "device_pixel_ratio": window.devicePixelRatioF(), "platform": app.platformName(), "actions": {}}
        ticks = []
        timer = QTimer(interval=10)
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start()

        def settle():
            deadline = time.monotonic() + 180
            QTest.qWait(30)
            while (window._loader is not None or window.plot_render_pending) and time.monotonic() < deadline:
                QTest.qWait(5)
            assert window._loader is None and not window.plot_render_pending, "operation did not settle"

        def measured(name, action):
            ticks[:] = [time.perf_counter()]
            start = ticks[0]
            profile = cProfile.Profile()
            profile.enable()
            action()
            submit = time.perf_counter() - start
            settle()
            profile.disable()
            ticks.append(time.perf_counter())
            report["actions"][name] = {"submit_seconds": submit, "complete_seconds": ticks[-1] - start,
                "max_heartbeat_gap_seconds": max(b-a for a, b in zip(ticks, ticks[1:]))}
            with args.output.with_suffix(f".{name}.profile.log").open("w", encoding="utf-8") as stream:
                pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(40)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(name, report["actions"][name], flush=True)

        measured("load", lambda: window.start_loading(args.folder, replace=True))
        spectra = window.catalog.spectra
        report["spectra"] = len(spectra)
        report["issues"] = len(window.catalog.issues)
        def source_hash():
            digest = hashlib.sha256()
            for spectrum in spectra:
                for channel in spectrum.channels:
                    digest.update(channel.numeric.tobytes())
            return digest.hexdigest()
        before_hash = source_hash()
        measured("check_all", window.check_all_spectra)
        matrix = window.mueller_panel.mij_plots["M01"]
        report["color_groups"] = len(matrix.groups)
        report["base_antialias"] = [c.opts["antialias"] for c in matrix._curve_items]
        matrix.plot.grab().save(str(args.output.with_suffix(".M01.png")))
        window.grab().save(str(args.output.with_suffix(".window.png")))
        measured("select_one", lambda: window.select_spectrum_keys({spectra[0].key}))
        measured("uncheck_one", window.uncheck_selected_spectra)
        measured("recheck_one", window.check_selected_spectra)
        key = matrix.groups[0].key
        measured("hide_legend", lambda: window.toggle_channel(key))
        measured("restore_legend", lambda: window.toggle_channel(key))
        measured("resize", lambda: window.resize(2200, 1200))
        measured("restore_size", lambda: window.resize(2000, 1100))
        measured("zoom_M01", lambda: matrix.plot.setXRange(390, 430, padding=0))
        measured("view_all_M01", matrix._auto_range_all)
        report["source_arrays_unchanged"] = before_hash == source_hash()
        assert report["source_arrays_unchanged"]
        if args.verify_pixels:
            report["native_reference"] = {}
            for name, panel in (("M01", matrix), ("M23", window.mueller_panel.mij_plots["M23"]),
                                ("PsiDelta", window.plot_panels["psi_delta"])):
                for mode, limits in (("full", None), ("zoom", (390, 430))):
                    panel._auto_range_all() if limits is None else panel.plot.setXRange(*limits, padding=0)
                    settle()
                    cached = panel.plot.grab().toImage()
                    curves = panel.plot.listDataItems()
                    for curve in curves:
                        curve.setExportMode(True, {"antialias": True})
                    native = panel.plot.grab().toImage()
                    a = np.frombuffer(cached.constBits().asstring(cached.sizeInBytes()), dtype=np.uint8).astype(int)
                    b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
                    error = np.abs(a-b)
                    report["native_reference"][f"{name}_{mode}"] = {"max_byte_error": int(error.max()),
                        "mean_byte_error": float(error.mean()), "fraction_bytes_over_16": float(np.mean(error > 16))}
                    cached.save(str(args.output.with_suffix(f".{name}_{mode}_screen.png")))
                    native.save(str(args.output.with_suffix(f".{name}_{mode}_native.png")))
                    for curve in curves:
                        curve.setExportMode(False)
                    assert error.mean() < .8 and np.mean(error > 16) < .01, report["native_reference"]
                    if mode == "zoom":
                        assert error.max() <= 3, report["native_reference"]
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        timer.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

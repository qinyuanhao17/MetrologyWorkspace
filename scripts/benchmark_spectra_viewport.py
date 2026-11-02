"""Measure full-view and zoomed spectral rendering on the real SME batch."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-data", action="store_true", help="Draw the full arrays as the reference renderer")
    parser.add_argument("--verify-pixels", action="store_true", help="Compare all plots against full-data rendering in three views")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-viewport-") as scratch:
        isolate_settings(scratch)
        import numpy as np
        import pyqtgraph as pg
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtTest import QTest
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_viewer import SpectraViewerWindow

        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        window = SpectraViewerWindow()
        result = load_folder(Path(r"C:\Users\Yuanhao Qin\OneDrive\Desktop\all_uploaded_SME_spectra_42_files"))
        window.apply_load_result(result, replace=True)
        window.check_all_spectra()
        window.resize(2200, 1150)
        window.show()
        def settle():
            deadline = time.perf_counter() + 60
            app.processEvents()
            while window.plot_render_pending and time.perf_counter() < deadline:
                QTest.qWait(2)
            assert not window.plot_render_pending

        settle()
        panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
        items = []
        for panel in panels:
            items.extend(panel.plot.getPlotItem().listDataItems())
            if panel.secondary is not None:
                items.extend(panel.secondary.childGroup.childItems())
        curves = [item for item in items if isinstance(item, pg.PlotCurveItem)]
        if args.full_data:
            for item in curves:
                if hasattr(item, "setClipToView"):
                    item.setClipToView(False)
        all_points = sum(len(item.getData()[0]) for item in curves)
        zoom_ms = []
        zoom_points = []
        for center in (520, 530, 540, 550, 560, 570):
            start = time.perf_counter()
            for panel in panels:
                panel.plot.setXRange(center - 10, center + 10, padding=0)
            settle()
            zoom_ms.append(round((time.perf_counter() - start) * 1000, 2))
            zoom_points.append(sum(len(item.getData()[0]) for item in curves))
        start = time.perf_counter()
        for panel in panels:
            panel.plot.getPlotItem().autoBtn.clicked.emit(None)
        settle()
        restore_ms = round((time.perf_counter() - start) * 1000, 2)
        restored_points = sum(len(item.getData()[0]) for item in curves)
        pixel_differences = {}
        if args.verify_pixels:
            window.select_spectrum_keys({spectrum.key for spectrum in result.spectra[:2]})
            settle()
            comparison_curves = []
            for panel in panels:
                comparison_curves.extend(panel.plot.getPlotItem().listDataItems())
                if panel.secondary is not None:
                    comparison_curves.extend(item for item in panel.secondary.childGroup.childItems()
                                             if isinstance(item, pg.PlotCurveItem))
            for name, x_range in (("all", None), ("zoom", (520, 540)), ("phase", (390, 420))):
                for panel in panels:
                    if x_range is None:
                        panel.plot.getPlotItem().autoBtn.clicked.emit(None)
                    else:
                        panel.plot.setXRange(*x_range, padding=0)
                images = []
                for enabled in (False, True):
                    for item in comparison_curves:
                        item.setClipToView(enabled)
                    settle()
                    frame = []
                    for panel in panels:
                        image = panel.plot.grab().toImage()
                        frame.append(bytes(image.constBits().asstring(image.sizeInBytes())))
                    images.append(frame)
                pixel_differences[name] = [sum(a != b for a, b in zip(left, right))
                                          for left, right in zip(*images)]
            assert all(not any(differences) for differences in pixel_differences.values())
        print(json.dumps({
            "pyqtgraph": pg.__version__, "files": len(result.spectra),
            "channels": window.catalog.channel_count, "plots": len(panels),
            "full_data_reference": args.full_data, "all_points": all_points,
            "zoom_ms": zoom_ms, "zoom_points": zoom_points,
            "zoom_median_ms": round(float(np.median(zoom_ms)), 2),
            "restore_all_ms": restore_ms, "restored_points": restored_points,
            "pixel_byte_differences": pixel_differences,
        }))
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

"""Repeatable splitter drag probe using the supplied 42-file SME fixture."""
import json
import argparse
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default=r"C:\Users\Yuanhao Qin\OneDrive\Desktop\all_uploaded_SME_spectra_42_files")
    parser.add_argument("--opaque", action="store_true", help="Reproduce continuous layout updates during dragging")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-resize-") as scratch:
        isolate_settings(scratch)
        from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QSplitter
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import load_folder
        from metrology_app.spectra_viewer import SpectraViewerWindow

        class ResizeCounter(QObject):
            count = 0

            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Resize:
                    self.count += 1
                return False

        app = QApplication.instance() or QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        window = SpectraViewerWindow()
        root = Path(args.folder)
        result = load_folder(root)
        window.apply_load_result(result, replace=True)
        window.check_all_spectra()
        window.resize(1800, 1000)
        window.show()
        if args.opaque:
            for splitter in window.findChildren(QSplitter):
                splitter.setOpaqueResize(True)
        def settle():
            deadline = time.perf_counter() + 60
            app.processEvents()
            while window.plot_render_pending and time.perf_counter() < deadline:
                QTest.qWait(2)
            assert not window.plot_render_pending

        settle()
        counter = ResizeCounter()
        panels = (*window.plot_panels.values(), *window.mueller_panel.mij_plots.values())
        for panel in panels:
            panel.plot.installEventFilter(counter)
        handle = window.plot_splitter.handle(1)
        timings = []
        resize_counts = []
        during_drag_counts = []
        completion_timings = []
        for _ in range(3):
            window.plot_splitter.setSizes([500, 800])
            settle()
            center = handle.rect().center()
            origin = handle.mapToGlobal(center)
            initial = counter.count
            start = time.perf_counter()
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
            for offset in (10, 20, 30, 40, 50, 60, 70, 80, 70, 60, 50, 40):
                QTest.mouseMove(handle, handle.mapFromGlobal(origin + QPoint(offset, 0)))
                app.processEvents()
            during_drag_counts.append(counter.count - initial)
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton,
                               pos=handle.mapFromGlobal(origin + QPoint(40, 0)))
            app.processEvents()
            timings.append(round((time.perf_counter() - start) * 1000, 2))
            settle()
            completion_timings.append(round((time.perf_counter() - start) * 1000, 2))
            resize_counts.append(counter.count - initial)
        print(json.dumps({
            "files": len(result.spectra), "channels": window.catalog.channel_count,
            "plots": len(panels), "drag_steps": 12,
            "drag_ms": timings, "plot_resize_events": resize_counts,
            "drag_complete_ms": completion_timings,
            "during_drag_resize_events": during_drag_counts,
            "opaque_resize": window.plot_splitter.opaqueResize(),
        }))
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

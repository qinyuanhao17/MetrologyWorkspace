"""Launch the application shell with no analysis windows open."""
import os
import sys
import multiprocessing
import tempfile
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()

# PyInstaller's Matplotlib hook normally creates a disposable font cache on
# every launch. A stable per-user cache makes repeated module opens much faster.
_cache_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MetrologyWorkspace" / "matplotlib"
try:
    _cache_root.mkdir(parents=True, exist_ok=True)
except OSError:
    _cache_root = Path(tempfile.gettempdir()) / "MetrologyWorkspace" / "matplotlib"
    _cache_root.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(_cache_root)

from PyQt6.QtWidgets import QApplication

from metrology_app.shell import MainWindow
from metrology_app.appearance import configure_fonts, set_theme_palette, style_titlebar
from metrology_app.settings import load_settings


def main():
    if '--vendor' in sys.argv:
        import argparse
        import json
        from dataclasses import asdict
        from metrology_app.reference_summary_window import ReferenceSummaryRequest, run_reference_summary
        parser = argparse.ArgumentParser(description='Reference Summary batch processing')
        parser.add_argument('--vendor',type=str.upper,choices=('NOVA','PMISH','KLA','CDSEM1'),required=True)
        parser.add_argument('--files',type=Path,nargs='+',required=True)
        parser.add_argument('--output-parent',type=Path)
        args = parser.parse_args(sys.argv[1:])
        try:
            report = run_reference_summary(ReferenceSummaryRequest(
                args.vendor,tuple(args.files),args.output_parent or args.files[0].resolve().parent))
        except Exception as error:
            parser.exit(2,f'Reference Summary failed: {error}\n')
        print(json.dumps(asdict(report.result),ensure_ascii=False,default=str))
        return 1 if report.result.error_count else 0
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    configure_fonts(app)
    settings = load_settings()
    set_theme_palette(settings["theme"])
    window = MainWindow()
    window.show()
    style_titlebar(window, settings["theme"])
    if "--spectra-smoke-test" in sys.argv:
        from metrology_app.spectra_smoke import run_spectra_smoke
        index = sys.argv.index("--spectra-smoke-test")
        if len(sys.argv) <= index + 2:
            return 2
        return run_spectra_smoke(window, app, sys.argv[index + 1], sys.argv[index + 2])
    if "--self-test" in sys.argv:
        # Release smoke test: prove that lazily imported components and all
        # bundled Qt/Matplotlib resources can be created by the frozen app.
        wafer = window.open_component("wafer_map")
        correlation = window.open_component("correlation_analysis")
        matching = window.open_component("card_matching")
        dynamic = window.open_component("dynamic_analysis")
        writer = window.open_component("auto_weighting_writer")
        spectra = window.open_component("spectra_viewer")
        reference = window.open_component("reference_summary")
        app.processEvents()
        from metrology_app.auto_weighting_ocr import local_self_test
        valid = (wafer.tabs.count() == 3 and correlation.tabs.count() == 4
                 and matching.mode_tabs.count() == 2 and dynamic.tabs.count() == 3
                 and writer.tabs.count() == 2 and spectra.tree.columnCount() > 0
                 and reference.vendor.count() == 4 and local_self_test())
        window.unload_all_components()
        window.close()
        app.processEvents()
        return 0 if valid else 2
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

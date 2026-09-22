"""Launch the component shell with every module initially unloaded."""
import os
import sys
import tempfile
from pathlib import Path

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

from wafermap.shell import MainWindow
from wafermap.appearance import configure_fonts, set_theme_palette, style_titlebar
from wafermap.settings import load_settings


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    configure_fonts(app)
    settings = load_settings()
    set_theme_palette(settings["theme"])
    window = MainWindow()
    window.show()
    style_titlebar(window, settings["theme"])
    if "--self-test" in sys.argv:
        # Release smoke test: prove that both lazily imported components and all
        # bundled Qt/Matplotlib resources can be created by the frozen app.
        wafer = window.open_component("wafer_map")
        correlation = window.open_component("correlation_analysis")
        app.processEvents()
        valid = wafer.tabs.count() == 3 and correlation.tabs.count() == 3
        window.unload_all_components()
        window.close()
        app.processEvents()
        return 0 if valid else 2
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

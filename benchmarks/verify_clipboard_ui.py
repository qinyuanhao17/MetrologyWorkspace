"""Save real Qt clipboard/filter/metadata UI for visual review in isolated settings."""
import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["METROLOGY_SETTINGS_PATH"] = str(args.scratch / "settings.yaml")
    os.environ["METROLOGY_RECOVERY_DIR"] = str(args.scratch / "recovery")
    os.environ["MPLCONFIGDIR"] = str(args.scratch / "mpl")
    tempfile.tempdir = str(args.scratch)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import pandas as pd
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from metrology_app.appearance import configure_fonts
    from metrology_app.correlation_window import CorrelationWindow
    from metrology_app.settings import apply_theme, save_settings
    from metrology_app.sheet import selection_bounds

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    frame = pd.DataFrame({"Wafer ID": ["LP200001.10"] * 5, "Lot ID": ["LP200001"] * 5,
                          "PAD Name": ["ARRAY"] * 5, "Die Seq": ["002", "036", "050", "066", "085"],
                          "X(mm)": ["-1.000", "1.000", "-1.000", "1.000", "0.000"],
                          "Y(mm)": ["-1.000", "-1.000", "1.000", "1.000", "0.000"],
                          "DP": ["63.000", "64.000", "65.000", "66.000", "67.000"],
                          "TG": ["4.500", "5.000", "5.700", "6.000", "6.500"],
                          "EW": ["30.000", "30.100", "30.300", "30.500", "30.800"]})
    window = CorrelationWindow()
    window.resize(1460, 950)
    window.set_table(frame, "Visual fixture")
    window.document.timer.stop()
    window.document.identity_timer.stop()
    window.show()
    app.processEvents()
    for theme in ("light", "dark"):
        save_settings({"theme": theme})
        apply_theme(window, theme)
        window.tabs.setCurrentIndex(1)
        window.sheet.setCurrentIndex(window.model.index(0, 0))
        app.clipboard().setText(frame.to_csv(sep="\t", index=False))
        window.sheet.paste()
        app.processEvents()
        assert selection_bounds(window.sheet) == (0, 0, 5, 8)
        assert window.sheet.clipboard_outline.bounds is None
        window.grab().save(str(args.scratch / f"{theme}-paste.png"))
        window.sheet.copy()
        app.processEvents()
        first = window.sheet.viewport().grab().toImage()
        first.save(str(args.scratch / f"{theme}-copy-a.png"))
        deadline = 500
        while deadline > 0 and window.sheet.viewport().grab().toImage() == first:
            QTest.qWait(10)
            deadline -= 10
        second = window.sheet.viewport().grab().toImage()
        assert second != first, "copy perimeter did not animate"
        second.save(str(args.scratch / f"{theme}-copy-b.png"))
        window.metadata_locks_panel.checks["X(mm)"].setChecked(True)
        window.metadata_locks_panel.checks["Y(mm)"].setChecked(True)
        window.grab().save(str(args.scratch / f"{theme}-locks.png"))
    page = window.correlation_page
    page.selector.selectAll()
    page.start_draw()
    window.tabs.setCurrentWidget(page)
    app.processEvents()
    page.parameter_filter.buttons["DP"].click()
    app.processEvents()
    window.grab().save(str(args.scratch / "parameter-filter.png"))
    print(f"verified paste, copy animation, metadata and parameter UI: {args.scratch}")
    window.document.timer.stop()
    window.document.identity_timer.stop()
    window.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()

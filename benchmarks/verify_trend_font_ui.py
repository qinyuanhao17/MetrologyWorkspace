"""Capture Trend font changes on real Qt panels with a linked secondary axis."""
import argparse
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metrology-trend-font-ui-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        import numpy as np
        import pandas as pd
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.correlation_window import CorrelationWindow
        from metrology_app.settings import save_settings

        app = QApplication([])
        configure_fonts(app)
        die = np.tile(np.arange(1, 21), 3)
        frame = pd.DataFrame({"Wafer ID": np.repeat(["W001", "W002", "W003"], 20),
                              "Lot ID": ["L001"] * 60, "PAD Name": ["ARRAY"] * 60,
                              "Die Seq": die, "DP [nm]": 80 + 10 * np.sin(die / 3),
                              "EW [V]": 1.2 + .2 * np.cos(die / 4)})
        for theme in ("light", "dark"):
            save_settings({"theme": theme})
            set_theme_palette(theme)
            window = CorrelationWindow()
            try:
                window.set_table(frame, "Independent Trend font fixture")
                for index in range(window.parameter_list.topLevelItemCount()):
                    item = window.parameter_list.topLevelItem(index)
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        name = item.data(0, Qt.ItemDataRole.UserRole)
                        item.setCheckState(0, Qt.CheckState.Checked if name in {"DP [nm]", "EW [V]"}
                                           else Qt.CheckState.Unchecked)
                page = window.sequence_page
                page.selector.selectAll()
                page.draw_plot()
                assert page.set_overlay("DP [nm]", "EW [V]")
                window.tabs.setCurrentWidget(page)
                window.resize(1500, 950)
                window.show()
                app.processEvents()
                primary = page.plot_widgets[0]
                assert len(primary.secondary_views) == 1
                primary.getViewBox().setRange(xRange=(8, 45), yRange=(65, 95), padding=0)
                app.processEvents()
                zoom = primary.getViewBox().viewRange()
                secondary = primary.secondary_views[0]
                secondary_zoom = secondary.viewRange()
                items = [item for plot in page.plot_widgets for item in plot.getPlotItem().listDataItems()]
                items.extend(item for plot in page.plot_widgets for view in plot.secondary_views
                             for item in view.addedItems if hasattr(item, "xData"))
                curves = [(item, item.xData.copy(), item.yData.copy()) for item in items]
                page.font_size.setCurrentText("16")
                app.processEvents()
                assert primary is page.plot_widgets[0] and secondary is primary.secondary_views[0]
                np.testing.assert_allclose(primary.getViewBox().viewRange(), zoom)
                np.testing.assert_allclose(secondary.viewRange(), secondary_zoom)
                for item, x, y in curves:
                    np.testing.assert_equal(item.xData, x)
                    np.testing.assert_equal(item.yData, y)
                for width in (1500, 1180):
                    window.resize(width, 950)
                    app.processEvents()
                    page.grab().save(str(args.output / f"trend-font16-{theme}-{width}.png"))
                page.ensure_export_figure()
                assert page.figure.axes[0].title.get_fontsize() == 17
                page.figure.savefig(args.output / f"trend-font16-export-{theme}.png", dpi=100)
            finally:
                window.document.force_close = True
                window.document.identity_timer.stop()
                window.document.timer.stop()
                window.close()
                window.deleteLater()
                app.processEvents()
        print("Trend font screenshots/export rendered; curves, zoom and secondary axes retained.")


if __name__ == "__main__":
    main()

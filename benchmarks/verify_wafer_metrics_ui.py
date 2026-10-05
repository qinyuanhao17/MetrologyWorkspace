"""Render dense single-wafer tables in both themes using scratch settings."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metrology-wafer-ui-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        import numpy as np
        import pandas as pd
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.settings import save_settings

        app = QApplication([])
        configure_fonts(app)
        die = np.tile(np.arange(1, 21), 240)
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"AH06593.00-{i:03}" for i in range(240)], 20),
                            "Lot ID": ["AH06593.00"] * len(die), "PAD Name": ["ARRAY"] * len(die),
                            "Die Seq": die, "CD": 850 + 8 * np.sin(die / 3) + np.repeat(np.arange(240) / 100, 20)})
        reference = pd.DataFrame({"CD Reference": raw["CD"] * (.97 + np.repeat(np.arange(240) / 4000, 20))
                                  + 2 + np.repeat(.1 + np.arange(240) / 300, 20) * np.cos(die)})
        for theme in ("light", "dark"):
            save_settings({"theme": theme})
            set_theme_palette(theme)
            window = MatchingWindow()
            window.set_reference_frame(reference)
            window.set_raw_frame(raw)
            window.run_analysis()
            window.resize(2000, 980)
            window.results_tabs.setCurrentIndex(1)
            window.show()
            app.processEvents()
            group = window.plot_groups["CD"]
            view, model, card = group["wafer_view"], group["wafer_model"], group["wafer_card"]
            cell = model.index(0, model.frame.columns.get_loc("Draw"))
            view.scrollTo(cell)
            app.processEvents()
            baseline = (card.height(), view.mapTo(card, QPoint()).y(), window.results_panel.minimumHeight())
            for _ in range(3):
                QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(cell).center())
                app.processEvents()
                assert len(group["wafer_details"]) == 1
                detail = next(iter(group["wafer_details"].values()))
                detail["plot_area"].moveDock(detail["plot_area"].docks["bias"], "bottom", detail["plot_area"].docks["trend"])
                app.processEvents()
                group["wafer_uncheck_all"].click()
                QTest.qWait(30)
                assert not group["wafer_details"]
                assert baseline == (card.height(), view.mapTo(card, QPoint()).y(), window.results_panel.minimumHeight())
            # Capture unchecked/checked indicators on a selected and an ordinary row.
            view.selectRow(0)
            view.setFocus()
            view.scrollTo(cell)
            app.processEvents()
            card.grab().save(str(args.output / f"wafer-metrics-unchecked-{theme}.png"))
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(cell).center())
            app.processEvents()
            view.selectRow(0)
            view.setFocus()
            view.scrollTo(cell)
            app.processEvents()
            header = view.horizontalHeader()
            button = group["wafer_uncheck_all"]
            assert button.isVisible() and button.width() == button.height() == 20
            assert header.logicalIndexAt(button.mapTo(header.viewport(), button.rect().center())) == cell.column()
            card.grab().save(str(args.output / f"wafer-metrics-checked-{theme}.png"))
            header.grab().save(str(args.output / f"wafer-draw-header-{theme}.png"))
            curve = group["wafer_r2"].listDataItems()[0]
            point = curve.scatter.points()[10]
            plot = group["wafer_r2"]
            position = plot.mapFromScene(curve.scatter.mapToScene(point.pos()))
            QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
            QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
            assert view.selectionModel().selectedRows() == []
            assert all(len(h.points()) == 0 for h in group["wafer_highlights"].values())
            group["wafer_uncheck_all"].click()
            app.processEvents()
            card.grab().save(str(args.output / f"wafer-metrics-cleared-{theme}.png"))
            print(f"{theme}: 240 wafer rows; repeated Draw/dock/Uncheck all restored {baseline}; highlight cancelled")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()

"""Render real Qt screens and verify linked-tool participation without user settings."""
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
    with tempfile.TemporaryDirectory(prefix="metrology-group-ui-") as scratch:
        os.environ["METROLOGY_SETTINGS_PATH"] = str(Path(scratch) / "settings.yaml")
        os.environ["METROLOGY_RECOVERY_DIR"] = str(Path(scratch) / "recovery")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        import numpy as np
        import pandas as pd
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QMessageBox, QPushButton
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.data_selection import DataSelectionDialog
        from metrology_app.match_group_ui import CombinedGroupDialog
        from metrology_app.match_groups import row_ids
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.settings import apply_theme, save_settings

        app = QApplication([])
        configure_fonts(app)
        die = np.tile(np.arange(1, 21), 6)
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"AH06593.00-{i:02}" for i in range(1, 7)], 20),
                            "Lot ID": ["AH06593.00"] * 120, "PAD Name": ["ARRAY"] * 120,
                            "Cur SME File Path": ["measurement-a.csv"] * 120,
                            "Die Seq": die, "CD": 850 + 8 * np.sin(die / 3) + np.repeat(np.arange(6), 20)})
        raw["Thickness"] = 120 + 3 * np.cos(die / 4) + np.repeat(np.arange(6), 20)
        reference = pd.DataFrame({"CD Reference": raw["CD"] * .998 + 2 + .15 * np.cos(die)})
        reference["Thickness Reference"] = raw["Thickness"] * 1.002 + .1
        window = MatchingWindow()
        window.set_reference_frame(reference)
        window.set_raw_frame(raw)
        window.group_controls.restore({"enabled": True, "mark_enabled": True,
            "head_names": {"0": "Optical A", "1": "Optical B"}, "new_rows": row_ids(raw)[80:],
            "data_selection": {"records": [], "excluded": []}},
            pd.DataFrame({"TestFlag": np.repeat([0, 0, 1, 1, 0, 1], 20)}))
        window.run_analysis()
        editor = CombinedGroupDialog(window.result.group_plan, window)
        editor.add_group()
        editor.combined_list.currentItem().setText(0, "Old + New Optical A")
        for i in range(editor.members.topLevelItemCount()):
            item = editor.members.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) in ("Old:0", "New:0"):
                item.setCheckState(0, Qt.CheckState.Checked)
        editor.accept()
        for state in (window.group_controls.state, window.group_controls.state["applied"]):
            state["combined_groups"] = editor.groups
        window.group_controls.refresh()
        window.run_analysis(apply_groups=False)
        page = window.group_plot_page
        page.use_group_card.setChecked(True)
        window.results_tabs.setCurrentWidget(page)
        window.resize(1720, 980)
        window.show()
        window.setup_splitter.setSizes([150, 140, 720])
        for theme in ("light", "dark"):
            snapshot = window.workspace_snapshot()
            size = window.size()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                window.close()
            window.deleteLater()
            app.processEvents()
            save_settings({"theme": theme})
            set_theme_palette(theme)
            window = MatchingWindow()
            window.restore_workspace(snapshot)
            window.resize(size)
            window.show()
            page = window.group_plot_page
            window.results_tabs.setCurrentWidget(page)
            app.processEvents()
            def capture_metric_settings():
                dialog = app.activeModalWidget()
                app.processEvents()
                assert len(dialog.findChildren(QDoubleSpinBox)) == 3
                buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
                assert buttons["Apply"].x() > buttons["Cancel"].x()
                for spin in dialog.findChildren(QDoubleSpinBox):
                    assert spin.width() >= spin.minimumSizeHint().width()
                dialog.grab().save(str(args.output / f"metric-highlighting-{theme}.png"))
                dialog.reject()
            QTimer.singleShot(0, capture_metric_settings)
            window.metric_highlighting_action.trigger()
            window.group_settings_action.trigger()
            settings = window.group_settings_dialog
            app.processEvents()
            controls = window.group_controls
            assert settings.width() < 650 and settings.height() < 520
            assert "Import combined…" not in [button.text() for button in settings.findChildren(QPushButton)]
            assert "Clear filters / sort" not in [button.text() for button in settings.findChildren(QPushButton)]
            settings.grab().save(str(args.output / f"group-settings-{theme}.png"))
            style = settings.styleSheet()
            settings.setStyleSheet("* { font-size: 19px; } QLabel#hint { font-size: 16px; }")
            settings.resize(560, 450)
            app.processEvents()
            for control in (controls.names_button, controls.new_button, controls.order, controls.group_order_button):
                assert control.width() >= control.minimumSizeHint().width()
            settings.grab().save(str(args.output / f"group-settings-large-font-{theme}.png"))
            settings.setStyleSheet(style)
            settings.resize(520, 360)
            settings.reject()
            page.grab().save(str(args.output / f"group-plots-{theme}.png"))
            page.page_image().save(str(args.output / f"group-plots-content-{theme}.png"))
            assert "Select group plots…" not in [action.text() for action in window.groups_menu.actions()]
            assert "Include single-wafer plots" not in [check.text() for check in page.findChildren(QCheckBox)]
            assert "Manage groups…" not in [button.text() for button in page.findChildren(QPushButton)]
            def capture_manager():
                manager = app.activeModalWidget()
                assert not manager.findChildren(QComboBox)
                manager.add_group()
                manager.combined_list.currentItem().setText(0, "Optical A + B")
                manager.combined_list.setCurrentItem(manager.combined_list.topLevelItem(0))
                manager.combined_list.topLevelItem(0).setCheckState(1, Qt.CheckState.Checked)
                app.processEvents()
                manager.grab().save(str(args.output / f"combined-groups-{theme}.png"))
                manager.reject()
            QTimer.singleShot(0, capture_manager)
            window.manage_groups_action.trigger()
            app.processEvents()
            assert len(page.plot_groups) == 10 and page.scroll.verticalScrollBar().maximum() > 0
            assert page.plots.count() == 2
            for (key, parameter), block in page.plot_groups.items():
                assert page.parameter_sections[parameter].isAncestorOf(block["card"])
            page.grab().save(str(args.output / f"group-plots-scroll-{theme}.png"))
            page.parameter_sections["CD"].grab().save(str(args.output / f"group-parameter-section-{theme}.png"))
            window.results_tabs.setCurrentIndex(1)
            app.processEvents()
            window.plot_groups["CD"]["wafer_card"].grab().save(str(args.output / f"wafer-parameter-section-{theme}.png"))
            window.results_tabs.setCurrentWidget(page)
            def set_wafer_labels(checked):
                def apply():
                    manager = app.activeModalWidget()
                    for tree in (manager.members, manager.combined_list):
                        for i in range(tree.topLevelItemCount()):
                            item = tree.topLevelItem(i)
                            key = item.data(0, Qt.ItemDataRole.UserRole)
                            if key == "Old:0" or key.startswith("combined:"):
                                item.setCheckState(1, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                    manager.accept()
                QTimer.singleShot(0, apply)
                window.manage_groups_action.trigger()
                app.processEvents()
            set_wafer_labels(True)
            page.grab().save(str(args.output / f"group-plots-show-wafer-{theme}.png"))
            combined = next(block for (key, _), block in page.plot_groups.items() if key.startswith("combined:"))
            combined["card"].grab().save(str(args.output / f"combined-group-show-wafer-{theme}.png"))
            window.resize(1180, 900)
            app.processEvents()
            combined["card"].grab().save(str(args.output / f"combined-group-show-wafer-narrow-{theme}.png"))
            for (key, _), block in page.plot_groups.items():
                for name in ("trend", "bias"):
                    plot = block["plots"][name]
                    plot._refresh_group_axis()
                    tooltip = plot._wafer_axis.toolTip()
                    assert ("Wafer ID:" in tooltip) == (key == "Old:0" or key.startswith("combined:"))
                    if "Wafer ID:" in tooltip:
                        assert "Lot ID: AH06593.00" in tooltip and "PAD Name: ARRAY" in tooltip
                    width = plot.getViewBox().sceneBoundingRect().width()
                    low, high = plot.getViewBox().viewRange()[0]
                    for axis in (plot._group_axis, plot._wafer_axis):
                        edge = -1000
                        for position, label in axis._tickLevels[0]:
                            assert ":" not in label
                            half = max(QFontMetrics(plot.font()).horizontalAdvance(line) for line in label.splitlines()) / 2
                            pixel = (position - low) * width / (high - low)
                            assert pixel - half >= max(0, edge + 8) and pixel + half <= width
                            edge = pixel + half
                    if plot._wafer_axis.isVisible():
                        assert plot._wafer_axis.sceneBoundingRect().top() < plot._group_axis.sceneBoundingRect().top()
                        assert plot._wafer_axis.boundary_width == 1
            window.resize(size)
            app.processEvents()
            set_wafer_labels(False)
            for order in ("original",):
                window.group_settings_action.trigger()
                assert settings.isVisible()
                controls.order.setCurrentIndex(controls.order.findData(order))
                controls.apply_button.click()
                app.processEvents()
                assert not settings.isVisible()
                for block in page.plot_groups.values():
                    for name in ("trend", "bias"):
                        plot = block["plots"][name]
                        assert plot.getAxis("bottom").labelText == "Die Seq"
                        assert not plot._group_axis.isVisible()
                        assert not plot._wafer_axis.isVisible()
                        assert all(line.pen.widthF() == 1 and line.pen.color().name() == "#929292"
                                   for line in plot._group_boundaries)
                page.grab().save(str(args.output / f"group-plots-{order}-{theme}.png"))
            controls.order.setCurrentIndex(controls.order.findData("groups"))
            controls.apply_button.click()
            app.processEvents()
            dialog = DataSelectionDialog(window.result.group_plan, window)
            apply_theme(dialog, theme)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(args.output / f"data-selection-{theme}.png"))
            dialog.reject()
            dialog.deleteLater()
        snapshot = window.workspace_snapshot()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            window.close()
        window.deleteLater()
        app.processEvents()
        save_settings({"theme": "light"})
        set_theme_palette("light")
        window = MatchingWindow()
        window.restore_workspace(snapshot)
        window.show()
        page = window.group_plot_page
        window.results_tabs.setCurrentWidget(page)
        window.resize(1180, 900)
        app.processEvents()
        page.grab().save(str(args.output / "group-plots-narrow.png"))

        # Dynamic is independent: apply only traceable source exclusions, never
        # replace its table or exclude another file with the same Wafer IDs.
        child = window.open_dynamic_workspace("preview")
        child.set_table(raw.copy(), "Independent Dynamic table")
        def exclude_first():
            dialog = app.activeModalWidget()
            dialog.search.setText("AH06593.00-01")
            next(b for b in dialog.findChildren(QPushButton) if b.text() == "Uncheck Visible").click()
            dialog.accept()
        QTimer.singleShot(0, exclude_first)
        window.data_selection_action.trigger()
        assert len(child.model.frame()) == 120
        assert sum(map(len, child.selection["groups"].values())) == 100
        other = raw.copy()
        other["Cur SME File Path"] = "measurement-b.csv"
        child.set_table(other, "Different source file")
        assert sum(map(len, child.selection["groups"].values())) == 120
        assert len(window.raw_frame) == len(window.reference_frame) == 120
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            window.close()
        print("UI screenshots rendered; per-Group wafer labels, non-overlapping ticks and retained sources verified.")


if __name__ == "__main__":
    main()

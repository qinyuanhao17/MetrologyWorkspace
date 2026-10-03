"""User-visible Card Matching workflow tests."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHeaderView, QLabel, QMessageBox,
    QScrollArea, QSplitter, QTabBar, QTableView, QTabWidget,
)

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import MatchWorkbook
from metrology_app.matching_window import DataFrameModel, MatchingWindow
from metrology_app.module_registry import create_default_registry
from metrology_app.sheet import SheetModel, SheetView


APP = QApplication.instance() or QApplication([])


class MatchingWindowTests(unittest.TestCase):
    def setUp(self):
        self._recent_patchers = (
            patch(
                "metrology_app.matching_window.recent_wkb_paths",
                return_value=(),
            ),
            patch(
                "metrology_app.matching_window.remember_recent_wkb",
                side_effect=lambda path: (Path(path).resolve(),),
            ),
            patch(
                "metrology_app.matching_window.forget_recent_wkb",
                return_value=(),
            ),
        )
        for patcher in self._recent_patchers:
            patcher.start()
        self.window = MatchingWindow()
        self._documents = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        for patcher in reversed(self._recent_patchers):
            patcher.stop()
        self._documents.cleanup()

    def save_child_and_close(self, child):
        """An explicit Save decision replaces the old silent close-and-save."""
        if self.window.workbook_path is None:
            self.window.save_workbook(Path(self._documents.name) / "workspace.wkb")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(child.close())

    def reference(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W3"],
            "CD_Bot Reference": [12.0, 22.0, 32.0],
            "SPA Reference": [5.0, 7.0, 9.0],
        })

    def raw(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W3"],
            "CD_Bot": [1.0, 2.0, 3.0],
            "SPA": [2.0, 3.0, 4.0],
        })

    def test_reference_and_raw_inputs_are_editable_spreadsheet_grids(self):
        self.assertIsInstance(self.window.reference_model, SheetModel)
        self.assertIsInstance(self.window.raw_model, SheetModel)
        self.assertIsInstance(self.window.reference_view, SheetView)
        self.assertIsInstance(self.window.raw_view, SheetView)
        self.assertGreaterEqual(self.window.reference_model.rowCount(), 100)
        self.assertGreaterEqual(self.window.reference_model.columnCount(), 26)
        self.assertGreaterEqual(self.window.raw_model.rowCount(), 100)
        self.assertGreaterEqual(self.window.raw_model.columnCount(), 26)

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.reference_model.setData(
            self.window.reference_model.index(1, 1),
            "14.5",
        )
        self.window.raw_model.setData(
            self.window.raw_model.index(1, 1),
            "1.5",
        )

        self.assertEqual(self.window.reference_frame.iloc[0, 1], "14.5")
        self.assertEqual(self.window.raw_frame.iloc[0, 1], "1.5")
        self.assertIsNone(self.window.result)

        self.window.raw_model.undo.undo()
        self.assertEqual(self.window.raw_frame.iloc[0, 1], "1.0")

    def test_editable_match_tables_offer_auto_rename_for_duplicate_headers(self):
        duplicate = pd.DataFrame(
            [["W1", "1", "2"], ["W2", "3", "4"]],
            columns=["Wafer ID", "DP", "DP"],
        )
        self.window.reference_model.load(duplicate)
        self.window.raw_model.load(duplicate)
        APP.processEvents()

        for banner in (
            self.window.reference_duplicate_banner,
            self.window.raw_duplicate_banner,
        ):
            self.assertFalse(banner.isHidden())
            self.assertGreaterEqual(banner.minimumHeight(), 44)
            self.assertEqual(banner.button.text(), "Auto rename")

        before = {
            key: value for key, value in self.window.reference_model.cells.items()
            if key[0] > 0
        }
        self.window.reference_duplicate_banner.button.click()
        APP.processEvents()
        self.assertEqual(
            self.window.reference_model.headers(), ["Wafer ID", "DP", "DP_2"]
        )
        self.assertEqual(
            {key: value for key, value in self.window.reference_model.cells.items()
             if key[0] > 0},
            before,
        )
        self.assertTrue(self.window.reference_duplicate_banner.isHidden())

        self.window.result_mode.setCurrentText("Final")
        self.window.final_raw_model.load(duplicate)
        APP.processEvents()
        self.assertFalse(self.window.raw_duplicate_banner.isHidden())
        self.window.raw_duplicate_banner.button.click()
        APP.processEvents()
        self.assertEqual(
            self.window.final_raw_model.headers(), ["Wafer ID", "DP", "DP_2"]
        )
        self.assertTrue(self.window.raw_duplicate_banner.isHidden())

    def test_correlation_button_opens_active_reference_and_raw_sources(self):
        class FakeCorrelationWorkspace:
            def __init__(self):
                self.inputs = None
                self.shown = False
                self.title = ""

            def set_sources(self, reference, raw, mappings, mode):
                self.inputs = (
                    reference.copy(), raw.copy(), tuple(mappings), mode
                )

            def setWindowTitle(self, title):
                self.title = title

            def show(self):
                self.shown = True

        opened = []
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.window = MatchingWindow(
            correlation_window_factory=lambda: opened.append(
                FakeCorrelationWorkspace()
            ) or opened[-1]
        )
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")

        workspace = self.window.open_correlation_workspace()

        self.assertFalse(self.window.correlation_button.isHidden())
        self.assertTrue(self.window.correlation_button.isEnabled())
        self.assertTrue(workspace.shown)
        restored_reference, restored_raw, mappings, mode = workspace.inputs
        pd.testing.assert_frame_equal(restored_reference, self.reference())
        pd.testing.assert_frame_equal(restored_raw, self.raw())
        self.assertEqual(
            [mapping.name for mapping in mappings], ["CD_Bot", "SPA"]
        )
        self.assertEqual(mode, "Preview")
        self.assertIn("Preview", workspace.title)

    def test_default_correlation_button_reuses_the_standard_tool(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")

        workspace = self.window.open_correlation_workspace()
        try:
            self.assertIsInstance(workspace, CorrelationWindow)
            self.assertEqual(
                [
                    workspace.tabs.tabText(index)
                    for index in range(workspace.tabs.count())
                ],
                ["1. Ref Data", "2. Raw Data", "3. Correlation", "4. Trend"],
            )
            self.assertEqual(list(workspace.raw_model.frame().columns),
                             list(self.raw().columns))
            self.assertEqual(workspace.reference_model.frame()["Wafer ID"].tolist(),
                             self.raw()["Wafer ID"].tolist())
        finally:
            workspace.close()
            workspace.deleteLater()
            APP.processEvents()

    def test_drawn_correlation_and_trend_restore_after_window_and_wkb_reopen(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drawn-correlation-state.wkb"
            self.window.save_workbook(path)
            first = self.window.open_correlation_workspace()
            raw_spa = next(
                first.parameter_list.topLevelItem(index)
                for index in range(first.parameter_list.topLevelItemCount())
                if first.parameter_list.topLevelItem(index).text(0) == "SPA"
            )
            raw_spa.setCheckState(0, Qt.CheckState.Unchecked)
            reference_keys = [
                key for key in first.correlation_page.selector.wafers
                if key[0] == "Reference"
            ]
            trend_key = next(
                key for key in first.sequence_page.selector.wafers
                if key[0] == "Reference"
            )
            correlation_cells = {
                (key, metric)
                for key in reference_keys for metric in ("CD_Bot", "SPA")
            }
            trend_cells = {(trend_key, "CD_Bot")}
            first.correlation_page.selector.set_selected_cells(
                correlation_cells
            )
            first.correlation_page.draw_plot()
            first.sequence_page.selector.set_selected_cells(trend_cells)
            first.sequence_page.draw_plot()
            self.assertTrue(first.correlation_page.ready)
            self.assertTrue(first.sequence_page.ready)
            self.save_child_and_close(first)
            first.deleteLater()
            APP.processEvents()

            second = self.window.open_correlation_workspace()
            try:
                self.assertEqual(second.selected(second.parameter_list), ["CD_Bot"])
                self.assertEqual(
                    second.correlation_page.selector.selected_cells(),
                    correlation_cells,
                )
                self.assertEqual(
                    second.sequence_page.selector.selected_cells(), trend_cells
                )
                self.assertTrue(second.correlation_page.ready)
                self.assertTrue(second.sequence_page.ready)
            finally:
                second.close()
                second.deleteLater()
                APP.processEvents()

            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                restored = reopened.open_correlation_workspace()
                self.assertEqual(
                    restored.selected(restored.parameter_list), ["CD_Bot"]
                )
                self.assertEqual(
                    restored.correlation_page.selector.selected_cells(),
                    correlation_cells,
                )
                self.assertEqual(
                    restored.sequence_page.selector.selected_cells(), trend_cells
                )
                self.assertTrue(restored.correlation_page.ready)
                self.assertTrue(restored.sequence_page.ready)
                restored.close()
                restored.deleteLater()
                APP.processEvents()
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_keyboard_undo_restores_replaced_reference_and_raw_tables(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()

        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        self.window.raw_view.setFocus()
        APP.clipboard().setText(
            "Wafer ID\tCD_Bot\tSPA\nW1\t101\t201\nW2\t102\t202\nW3\t103\t203"
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(
            self.window.raw_frame[["CD_Bot", "SPA"]].astype(float).values.tolist(),
            [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]],
        )

        self.window.reference_view.setCurrentIndex(
            self.window.reference_model.index(0, 0)
        )
        self.window.reference_view.setFocus()
        APP.clipboard().setText(
            "Wafer ID\tCD_Bot Reference\tSPA Reference\n"
            "W1\t112\t205\nW2\t122\t207\nW3\t132\t209"
        )
        QTest.keyClick(
            self.window.reference_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(
            self.window.reference_view,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(
            self.window.reference_frame[
                ["CD_Bot Reference", "SPA Reference"]
            ].astype(float).values.tolist(),
            [[12.0, 5.0], [22.0, 7.0], [32.0, 9.0]],
        )
        self.assertEqual(self.window.mapping_table.rowCount(), 2)

    def test_keyboard_undo_restores_deleted_reference_and_raw_tables(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()

        for view, frame_name in (
            (self.window.raw_view, "raw_frame"),
            (self.window.reference_view, "reference_frame"),
        ):
            view.setFocus()
            QTest.keyClick(
                view,
                Qt.Key.Key_A,
                Qt.KeyboardModifier.ControlModifier,
            )
            QTest.keyClick(view, Qt.Key.Key_Delete)
            self.assertTrue(getattr(self.window, frame_name).empty)
            QTest.keyClick(
                view,
                Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier,
            )
            self.assertFalse(getattr(self.window, frame_name).empty)

        self.assertEqual(self.window.mapping_table.rowCount(), 2)

    def test_reference_is_loaded_before_raw_data_and_enables_analysis(self):
        self.assertFalse(self.window.raw_view.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.assertTrue(self.window.raw_view.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.assertEqual(self.window.mapping_table.rowCount(), 2)
        self.assertTrue(self.window.analyze_button.isEnabled())

        result = self.window.run_analysis()
        self.assertEqual(result.parameter_names, ("CD_Bot", "SPA"))
        self.assertEqual(self.window.summary_model.rowCount(), 2)

    def test_save_again_overwrites_current_wkb_without_asking_for_a_path(self):
        self.assertEqual(self.window.save_action.shortcut().toString(), "Ctrl+S")
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "current.wkb"
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                return_value=(str(path), "Matching Workbook (*.wkb)"),
            ) as first_prompt:
                self.window.save_action.trigger()

            first_prompt.assert_called_once()
            self.assertEqual(self.window.workbook_path, path.resolve())

            self.window.match_type.setCurrentText("TEM")
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                side_effect=AssertionError("Save again must not ask for a path"),
            ) as repeated_prompt:
                self.window.save_action.trigger()

            repeated_prompt.assert_not_called()
            self.assertEqual(MatchWorkbook.load(path).match_type, "TEM")

    def test_opened_wkb_becomes_the_target_for_save(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "opened.wkb"
            self.window.save_workbook(path)

            reopened = MatchingWindow()
            self.addCleanup(reopened.deleteLater)
            reopened.load_workbook(path)
            reopened.match_type.setCurrentText("TEM")
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                side_effect=AssertionError("An opened WKB already has a path"),
            ) as prompt:
                reopened.save_action.trigger()

            prompt.assert_not_called()
            self.assertEqual(reopened.workbook_path, path.resolve())
            self.assertEqual(MatchWorkbook.load(path).match_type, "TEM")
            reopened.close()

    def test_save_as_selects_a_new_current_wkb_for_later_saves(self):
        self.assertEqual(
            self.window.save_as_action.shortcut().toString(),
            "Ctrl+Shift+S",
        )
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "original.wkb"
            renamed = Path(folder) / "renamed.wkb"
            self.window.save_workbook(original)

            self.window.match_type.setCurrentText("TEM")
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                return_value=(str(renamed), "Matching Workbook (*.wkb)"),
            ):
                self.window.save_as_action.trigger()

            self.assertEqual(self.window.workbook_path, renamed.resolve())
            self.assertEqual(MatchWorkbook.load(original).match_type, "KLA")
            self.assertEqual(MatchWorkbook.load(renamed).match_type, "TEM")

            self.window.match_type.setCurrentText("NOVA")
            with patch.object(
                QFileDialog,
                "getSaveFileName",
                side_effect=AssertionError("Save must reuse the Save As path"),
            ) as repeated_prompt:
                self.window.save_action.trigger()

            repeated_prompt.assert_not_called()
            self.assertEqual(MatchWorkbook.load(renamed).match_type, "NOVA")

    def test_select_all_mappings_checks_every_candidate(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")

        self.assertFalse(self.window.select_all_mappings.isChecked())
        self.window.select_all_mappings.click()

        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertTrue(self.window.select_all_mappings.isChecked())

    def test_raw_column_picker_ignores_the_mouse_wheel(self):
        """A wheel over the mapping table must not remap the parameter."""
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()
        APP.processEvents()
        picker = self.window.mapping_table.cellWidget(0, 3)
        picker.setFocus()
        APP.processEvents()
        self.assertTrue(picker.hasFocus())
        chosen = picker.currentText()
        index = picker.currentIndex()
        center = picker.rect().center()

        for delta in (-120, 120):
            event = QWheelEvent(
                QPointF(center), QPointF(picker.mapToGlobal(center)),
                QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            APP.sendEvent(picker, event)
            APP.processEvents()
            # Checked after each notch: a plain combo box would step the index.
            self.assertEqual(picker.currentIndex(), index)
            self.assertEqual(picker.currentText(), chosen)

    def test_clearing_raw_data_keeps_mappings_and_prompts_for_columns(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()
        self.window.raw_view.setFocus()
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(self.window.raw_view, Qt.Key.Key_Delete)

        self.assertTrue(self.window.raw_frame.empty)
        self.assertEqual(self.window.mapping_table.rowCount(), 2)
        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))

        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        APP.clipboard().setText(
            "Wafer ID\tDifferent\nW1\t1\nW2\t2\nW3\t3"
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )

        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertTrue(all(
            not self.window.mapping_table.cellWidget(row, 3).currentText()
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertIn("Choose a Raw Data column", self.window.status.text())
        self.assertEqual(self.window.status.objectName(), "warning")
        self.assertTrue(self.window.status.wordWrap())
        self.assertFalse(self.window.analyze_button.isEnabled())

    def test_single_wafer_plots_use_the_table_row_numbers_as_ticks(self):
        """Full wafer names would collide, so the axis uses the table index."""
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3 + ["W3"] * 3,
            "CD Reference": [3.0, 5.0, 7.0, 1.0, 4.0, 7.0, 2.0, 4.0, 6.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3 + ["W3"] * 3,
            "CD": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.match_type.setCurrentText("NOVA")
        self.window.run_analysis()
        APP.processEvents()

        group = self.window.plot_groups["CD"]
        expected = [[(0.0, "1"), (1.0, "2"), (2.0, "3")]]
        for name in ("wafer_r2", "wafer_slope"):
            self.assertEqual(group[name].getAxis("bottom")._tickLevels, expected)

    def test_single_wafer_ticks_thin_out_when_the_rows_do_not_fit(self):
        """Dense plots show every nth row number instead of overlapping."""
        wafers = [f"W{index:03d}" for index in range(1, 151)]
        reference = pd.DataFrame({
            "Wafer ID": [wafer for wafer in wafers for _ in range(2)],
            "CD Reference": [12.0, 22.0] * len(wafers),
        })
        raw = pd.DataFrame({
            "Wafer ID": [wafer for wafer in wafers for _ in range(2)],
            "CD": [1.0, 2.0] * len(wafers),
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.match_type.setCurrentText("NOVA")
        self.window.run_analysis()
        APP.processEvents()

        group = self.window.plot_groups["CD"]
        levels = group["wafer_r2"].getAxis("bottom")._tickLevels[0]
        labels = [int(text) for _position, text in levels]
        step = labels[1] - labels[0]
        self.assertGreater(step, 1)
        self.assertLess(len(labels), len(wafers))
        self.assertEqual(labels, list(range(1, len(wafers) + 1, step)))
        self.assertEqual(
            group["wafer_slope"].getAxis("bottom")._tickLevels[0],
            levels,
        )

    def test_single_wafer_tick_step_scales_with_the_plot_width(self):
        """A narrower plot keeps fewer row-number labels than a wide one."""

        class _Box:
            def __init__(self, width):
                self._width = width

            def width(self):
                return self._width

        class _Item:
            def __init__(self, width):
                self._box = _Box(width)

            def getViewBox(self):
                return self._box

        class _Plot:
            def __init__(self, width):
                self._item = _Item(width)

            def font(self):
                return APP.font()

            def getPlotItem(self):
                return self._item

        narrow = MatchingWindow._wafer_row_tick_levels(
            {"wafer_r2": _Plot(320)}, 121
        )
        wide = MatchingWindow._wafer_row_tick_levels(
            {"wafer_r2": _Plot(1400)}, 121
        )
        narrow_step = int(narrow[1][1]) - int(narrow[0][1])
        wide_step = int(wide[1][1]) - int(wide[0][1])
        self.assertGreaterEqual(wide_step, 1)
        self.assertGreater(narrow_step, wide_step)

    def test_single_wafer_table_gives_the_wafer_column_the_free_width(self):
        """Long wafer names must not be elided while the table has room."""
        self.window.set_reference_frame(pd.DataFrame({
            "Wafer ID": ["AH06836.00-01", "AH06836.00-02", "AH06836.00-03"],
            "CD_Bot Reference": [12.0, 22.0, 32.0],
        }), "Clipboard")
        self.window.set_raw_frame(pd.DataFrame({
            "Wafer ID": ["AH06836.00-01", "AH06836.00-02", "AH06836.00-03"],
            "CD_Bot": [1.0, 2.0, 3.0],
        }), "Clipboard")
        self.window.run_analysis()
        APP.processEvents()

        card = self.window.plot_groups["CD_Bot"]["wafer_card"]
        view = card.findChild(QTableView)
        header = view.horizontalHeader()
        self.assertEqual(
            header.sectionResizeMode(0), QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, view.model().columnCount()):
            self.assertEqual(
                header.sectionResizeMode(column),
                QHeaderView.ResizeMode.Fixed,
            )
        view.resize(900, 200)
        APP.processEvents()
        self.assertGreater(header.sectionSize(0), header.sectionSize(1))

    def test_single_wafer_table_joins_the_identity_lines_with_slashes(self):
        """The Wafer cell shows the whole a/b/c identity instead of eliding."""
        self.window.set_reference_frame(pd.DataFrame({
            "CD Reference": [12.0, 22.0, 32.0, 42.0],
        }), "Clipboard")
        self.window.set_raw_frame(pd.DataFrame({
            "Wafer ID": ["AH06836.00-01"] * 4,
            "Lot ID": ["L1", "L1", "L2", "L2"],
            "PAD Name": ["ARRAY", "ARRAY", "CELL", "CELL"],
            "Die Seq": [1, 2, 1, 2],
            "CD": [1.0, 2.0, 3.0, 4.0],
        }), "Clipboard")
        self.window.match_type.setCurrentText("NOVA")
        self.window.run_analysis()
        APP.processEvents()

        view = self.window.plot_groups["CD"]["wafer_view"]
        model = view.model()
        texts = [
            model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole)
            for row in range(model.rowCount())
        ]
        self.assertEqual(texts, [
            "AH06836.00-01/PAD: ARRAY/Lot: L1",
            "AH06836.00-01/PAD: CELL/Lot: L2",
        ])
        self.assertTrue(all("\n" not in text for text in texts))

    def test_dynamic_windows_start_empty_until_the_workbook_has_its_own_table(self):
        """Dynamic never copies Raw/Map data; Preview and Final open blank."""
        for match_type in ("KLA", "NOVA", "TEM"):
            with self.subTest(match_type=match_type):
                self.window.match_type.setCurrentText(match_type)
                self.window.set_reference_frame(self.reference(), "Clipboard")
                self.window.set_raw_frame(self.raw(), "Clipboard")
                self.window.run_analysis()
                for stage in ("preview", "final"):
                    workspace = self.window.open_dynamic_workspace(stage)
                    self.assertEqual(
                        len(workspace.model.frame().columns), 0,
                        f"{match_type} {stage} copied workbook data",
                    )
                self.window._close_stage_windows()
                APP.processEvents()

    def test_unchecking_every_bias_view_hides_its_plots(self):
        """Unchecking Bias or Bias % removes exactly that plot."""
        # The window asks about its unsaved draft on close; this test only
        # checks the plot layout, so answer it up front.
        self.window.document.confirm_close = lambda: True
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()
        APP.processEvents()

        plots = lambda: tuple(self.window.plot_groups["CD_Bot"]["plots"])
        self.assertEqual(plots(), ("match", "trend", "bias", "bias-percent"))

        self.window.percent_bias.setChecked(False)
        APP.processEvents()
        self.assertEqual(plots(), ("match", "trend", "bias"))

        self.window.absolute_bias.setChecked(False)
        APP.processEvents()
        self.assertEqual(plots(), ("match", "trend"))
        self.assertFalse(self.window.absolute_bias.isChecked())

        # The workbook still has a primary Bias mode, so analysis keeps working.
        self.window.run_analysis()
        APP.processEvents()
        self.assertEqual(plots(), ("match", "trend"))
        self.assertTrue(self.window.mapping_table.item(0, 7).text())

    def test_analysis_results_share_the_scrollable_setup_workspace(self):
        self.assertIn("Match Workbook", self.window.windowTitle())
        self.assertIn("Untitled", self.window.windowTitle())
        self.assertFalse(any(
            label.text() == "Match Workbook"
            for label in self.window.findChildren(QLabel)
        ))
        self.assertEqual(
            [action.text() for action in self.window.menuBar().actions()],
            ["File", "Analysis"],
        )
        self.assertEqual(
            [action.text() for action in self.window.file_menu.actions()],
            [
                "New Workbook…",
                "Open Workbook…",
                "Open Recent WKB",
                "Reveal Workbook in Folder",
                "Save Workbook",
                "Save Workbook As…",
                "Export Excel",
                "Save images",
                "Recover Workbook Draft…",
            ],
        )
        self.assertFalse(self.window.reveal_wkb_action.isEnabled())
        self.assertEqual(
            [action.text() for action in self.window.match_type_menu.actions()],
            ["KLA", "NOVA", "TEM"],
        )
        self.assertEqual(
            [action.text() for action in self.window.bias_menu.actions()],
            ["Bias", "Bias %"],
        )
        self.assertIsInstance(self.window.mode_tabs, QTabBar)
        self.assertEqual(self.window.mode_tabs.count(), 2)
        self.assertEqual(self.window.mode_tabs.tabText(0), "Preview")
        self.assertEqual(self.window.mode_tabs.tabText(1), "Final")
        self.assertFalse(hasattr(self.window, "reference_paste_button"))
        self.assertFalse(hasattr(self.window, "raw_paste_button"))
        self.assertFalse(hasattr(self.window, "fullmap_page"))
        self.assertFalse(self.window.preview_open_button.isHidden())
        self.assertTrue(self.window.final_open_button.isHidden())
        self.assertFalse(self.window.preview_dynamic_button.isHidden())
        self.assertTrue(self.window.final_dynamic_button.isHidden())
        self.assertNotIn(
            "Paste a Reference table to begin.",
            [label.text() for label in self.window.findChildren(QLabel)],
        )
        self.assertTrue(self.window.status.isHidden())
        self.assertFalse(hasattr(self.window, "reset_order_button"))
        self.assertIsInstance(self.window.setup_scroll, QScrollArea)
        self.assertIsInstance(self.window.setup_splitter, QSplitter)
        self.assertEqual(
            self.window.setup_splitter.orientation(), Qt.Orientation.Vertical
        )
        self.assertFalse(hasattr(self.window, "parameter_picker"))
        self.assertFalse(hasattr(self.window, "primary_plot_splitter"))
        self.assertFalse(hasattr(self.window, "plot_scroll"))
        self.assertFalse(hasattr(self.window, "result_plots"))
        self.assertFalse(hasattr(self.window, "linear_fit"))
        self.assertTrue(self.window.absolute_bias.isChecked())
        self.assertFalse(self.window.percent_bias.isChecked())
        self.window.absolute_bias.setChecked(False)
        # Bias plots are optional; the checkbox no longer springs back.
        self.assertFalse(self.window.absolute_bias.isChecked())
        self.window.absolute_bias.setChecked(True)
        self.assertTrue(self.window.absolute_bias.isChecked())

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

        headers = [
            self.window.mapping_table.horizontalHeaderItem(column).text()
            for column in range(self.window.mapping_table.columnCount())
        ]
        self.assertEqual(headers, [
            "Use", "Parameter", "Reference column", "Raw Data column",
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode",
        ])
        self.assertEqual(self.window.mapping_table.item(0, 7).text(), "3")
        self.assertEqual(self.window.mapping_table.item(0, 8).text(), "KLA")
        self.assertEqual(self.window.mapping_table.item(0, 9).text(), "Preview")
        self.assertEqual(tuple(self.window.plot_groups), ("CD_Bot", "SPA"))
        cd_plots = self.window.plot_groups["CD_Bot"]["plots"]
        spa_plots = self.window.plot_groups["SPA"]["plots"]
        self.assertEqual(
            tuple(cd_plots), ("match", "trend", "bias", "bias-percent")
        )
        self.assertIn(
            "Linear fit",
            [item.name() for item in cd_plots["match"].listDataItems()],
        )
        self.assertTrue(all(plot.minimumHeight() == 330 for plot in cd_plots.values()))
        self.assertEqual(cd_plots["match"].minimumWidth(), 340)
        self.assertEqual(cd_plots["match"].maximumWidth(), 340)
        self.assertTrue(cd_plots["bias"].listDataItems())
        self.assertTrue(cd_plots["bias-percent"].listDataItems())
        self.assertTrue(spa_plots["match"].listDataItems())

        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.assertGreater(self.window.setup_scroll.verticalScrollBar().maximum(), 0)
        first_card = self.window.plot_groups["CD_Bot"]["card"]
        second_card = self.window.plot_groups["SPA"]["card"]
        self.assertLessEqual(first_card.geometry().bottom(), second_card.geometry().top())
        self.assertTrue(
            cd_plots["match"].geometry().intersected(
                cd_plots["trend"].geometry()
            ).isEmpty()
        )
        self.assertTrue(
            cd_plots["match"].geometry().intersected(
                cd_plots["bias"].geometry()
            ).isEmpty()
        )
        self.assertEqual(
            {plot.geometry().top() for plot in cd_plots.values()},
            {cd_plots["match"].geometry().top()},
        )
        plot_container_rect = cd_plots["match"].parentWidget().contentsRect()
        self.assertTrue(all(
            plot_container_rect.contains(plot.geometry())
            for plot in cd_plots.values()
        ))

        self.window.mode_tabs.setCurrentIndex(1)
        self.assertEqual(self.window.result_mode.currentText(), "Final")
        self.assertTrue(self.window.preview_open_button.isHidden())
        self.assertFalse(self.window.final_open_button.isHidden())
        self.assertTrue(self.window.preview_dynamic_button.isHidden())
        self.assertFalse(self.window.final_dynamic_button.isHidden())

    def test_section_guidance_is_available_from_titles_not_inline_comments(self):
        labels = self.window.findChildren(QLabel)
        titles = {label.text(): label for label in labels}
        expected_help = {
            "Reference": (
                "Paste the prepared table first.\n"
                "Row 1 = headers · Ctrl+V paste · Ctrl+Z undo."
            ),
            "Raw Data": (
                "Rows are matched to Reference from top to bottom.\n"
                "Row 1 = headers · Ctrl+V paste · Ctrl+Z undo."
            ),
            "Parameter mapping": (
                "Numeric Reference columns are listed; “Reference” suffix "
                "columns pair by name."
            ),
        }

        for title, help_text in expected_help.items():
            self.assertIn(title, titles)
            self.assertEqual(titles[title].toolTip(), help_text)

        visible_text = {label.text() for label in labels}
        for help_text in expected_help.values():
            for line in help_text.splitlines():
                self.assertNotIn(line, visible_text)

    def test_raw_table_paste_auto_runs_after_first_manual_run(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")

        self.window.analyze_button.click()
        self.assertIsNotNone(self.window.result)

        APP.clipboard().setText(
            "Wafer ID\tCD_Bot\tSPA\nW1\t2\t3\nW2\t3\t4\nW3\t4\t5"
        )
        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        self.window.raw_view.paste()
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(
            self.window.result.series("CD_Bot")["Raw"].tolist(),
            [2.0, 3.0, 4.0],
        )

    def test_raw_mapping_change_auto_runs_and_preserves_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window._run_analysis_clicked()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([500, 260, 900])
        APP.processEvents()
        sizes = tuple(self.window.setup_splitter.sizes()[:2])

        self.window.mapping_table.cellWidget(0, 3).setCurrentText("SPA")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(
            self.window.result.summary.loc[0, "Raw column"],
            "SPA",
        )
        self.assertEqual(tuple(self.window.setup_splitter.sizes()[:2]), sizes)

    def test_reference_raw_and_mapping_edits_auto_refresh_without_clearing_results(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window._run_analysis_clicked()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([510, 250, 900])
        APP.processEvents()
        sizes = tuple(self.window.setup_splitter.sizes()[:2])

        self.window.reference_model.setData(
            self.window.reference_model.index(1, 1), "14"
        )
        self.assertIsNotNone(self.window.result)
        APP.processEvents()
        self.assertEqual(
            self.window.result.series("CD_Bot")["Reference"].iloc[0], 14.0
        )

        self.window.raw_model.setData(self.window.raw_model.index(1, 1), "1.5")
        self.assertIsNotNone(self.window.result)
        APP.processEvents()
        self.assertEqual(
            self.window.result.series("CD_Bot")["Raw"].iloc[0], 1.5
        )

        self.window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertIsNotNone(self.window.result)
        APP.processEvents()
        QTest.qWait(1)
        APP.processEvents()
        self.assertEqual(self.window.result.parameter_names, ("SPA",))
        self.assertEqual(tuple(self.window.setup_splitter.sizes()[:2]), sizes)

    def test_selected_primary_plots_share_one_horizontal_row(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        self.assertEqual(tuple(plots), ("match", "trend", "bias"))
        self.assertEqual(
            {plots[name].geometry().top() for name in plots},
            {plots["match"].geometry().top()},
        )
        self.assertLess(plots["match"].geometry().right(), plots["trend"].geometry().left())
        self.assertLess(plots["trend"].geometry().right(), plots["bias"].geometry().left())
        self.assertEqual(plots["match"].width(), 340)
        self.assertAlmostEqual(
            plots["trend"].width(), plots["bias"].width(), delta=1
        )

    def test_four_primary_plots_fit_without_horizontal_scrolling(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        self.assertEqual(
            tuple(plots), ("match", "trend", "bias", "bias-percent")
        )
        self.assertEqual(
            self.window.setup_scroll.horizontalScrollBar().maximum(), 0
        )
        self.assertEqual(
            {plot.geometry().top() for plot in plots.values()},
            {plots["match"].geometry().top()},
        )
        flexible_widths = [
            plots[name].width() for name in ("trend", "bias", "bias-percent")
        ]
        self.assertLessEqual(max(flexible_widths) - min(flexible_widths), 1)
        plot_container = plots["match"].parentWidget().contentsRect()
        self.assertTrue(all(
            plot_container.contains(plot.geometry()) for plot in plots.values()
        ))

    def test_a_single_parameter_plot_card_stays_at_the_top_of_results(self):
        self.window.set_reference_frame(
            self.reference()[["Wafer ID", "CD_Bot Reference"]], "Clipboard"
        )
        self.window.set_raw_frame(
            self.raw()[["Wafer ID", "CD_Bot"]], "Clipboard"
        )
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        card = self.window.plot_groups["CD_Bot"]["card"]
        self.assertLessEqual(card.geometry().top(), 4)

    def test_primary_plot_height_is_fixed_for_single_and_multiple_parameters(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        multiple_heights = {
            plot.height()
            for group in self.window.plot_groups.values()
            for plot in group["plots"].values()
        }

        single = MatchingWindow()
        try:
            single.set_reference_frame(
                self.reference()[["Wafer ID", "CD_Bot Reference"]], "Clipboard"
            )
            single.set_raw_frame(
                self.raw()[["Wafer ID", "CD_Bot"]], "Clipboard"
            )
            single.run_analysis()
            single.resize(1600, 900)
            single.show()
            APP.processEvents()
            single_heights = {
                plot.height()
                for group in single.plot_groups.values()
                for plot in group["plots"].values()
            }
        finally:
            single.close()

        self.assertEqual(multiple_heights, {330})
        self.assertEqual(single_heights, {330})
        self.assertEqual(
            self.window.plot_groups["CD_Bot"]["plots"]["match"].width(), 340
        )
        self.assertEqual(self.window.plot_groups_layout.spacing(), 8)

    def test_match_plot_shows_fit_equation_to_the_right_of_its_title(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        group = self.window.plot_groups["CD_Bot"]
        match_widget = group["plots"]["match"]
        match = match_widget.getPlotItem()
        annotations = [item for item in match.items if isinstance(item, pg.TextItem)]
        self.assertEqual(annotations, [])
        self.assertEqual(group["match_title"].text(), "CD_Bot")
        self.assertEqual(group["match_formula"].text(), "y = 10x + 2\nR² = 1")
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        title_rect = group["match_title"].geometry()
        formula_rect = group["match_formula"].geometry()
        self.assertLessEqual(title_rect.right(), formula_rect.left())
        self.assertLessEqual(formula_rect.right(), match_widget.width())
        view_top = match_widget.mapFromScene(
            match.getViewBox().sceneBoundingRect().topLeft()
        ).y()
        self.assertLessEqual(formula_rect.bottom(), view_top)

    def test_result_plots_show_four_sided_frames_and_use_box_zoom_mode(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        for plot_widget in plots.values():
            plot = plot_widget.getPlotItem()
            view = plot.getViewBox()
            self.assertEqual(view.state["mouseMode"], pg.ViewBox.RectMode)
            self.assertEqual(view.border.style(), Qt.PenStyle.NoPen)
            widths = []
            for axis_name in ("top", "right", "bottom", "left"):
                axis = plot.getAxis(axis_name)
                self.assertTrue(axis.isVisible())
                widths.append(axis.pen().widthF())
            self.assertEqual(len(set(widths)), 1)
            self.assertGreater(plot.getAxis("top").geometry().height(), 0)
            self.assertGreater(plot.getAxis("right").geometry().width(), 0)

    def test_primary_plot_frames_align_and_omit_the_wafer_axis_title(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        view_rects = []
        for widget in plots.values():
            scene_rect = widget.getPlotItem().getViewBox().sceneBoundingRect()
            top_left = widget.mapFromScene(scene_rect.topLeft())
            bottom_right = widget.mapFromScene(scene_rect.bottomRight())
            view_rects.append((top_left.y(), bottom_right.y()))
        self.assertLessEqual(max(top for top, _ in view_rects) - min(
            top for top, _ in view_rects
        ), 1)
        self.assertLessEqual(max(bottom for _, bottom in view_rects) - min(
            bottom for _, bottom in view_rects
        ), 1)
        for name in ("trend", "bias"):
            self.assertEqual(plots[name].getAxis("bottom").labelText.strip(), "")

    def test_mapping_results_flag_out_of_range_slope_and_r_squared(self):
        reference = pd.DataFrame({
            "Slope Reference": [2.0, 4.0, 6.0, 8.0],
            "RSQ Reference": [2.0, 1.0, 2.0, 5.0],
        })
        raw = pd.DataFrame({
            "Slope": [1.0, 2.0, 3.0, 4.0],
            "RSQ": [1.0, 2.0, 3.0, 4.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.run_analysis()

        slope_bad = self.window.mapping_table.item(0, 4)
        r_squared_good = self.window.mapping_table.item(0, 6)
        slope_good = self.window.mapping_table.item(1, 4)
        r_squared_bad = self.window.mapping_table.item(1, 6)

        self.assertNotEqual(
            slope_bad.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertIn("0.9–1.1", slope_bad.toolTip())
        self.assertEqual(
            r_squared_good.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertEqual(
            slope_good.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertNotEqual(
            r_squared_bad.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertIn("below 0.9", r_squared_bad.toolTip())

    def test_single_wafer_table_flags_the_same_quality_thresholds(self):
        model = DataFrameModel(pd.DataFrame({
            "Slope": [0.89, 1.0],
            "R²": [0.95, 0.89],
        }))

        self.assertIsNotNone(model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNone(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNone(model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNotNone(model.data(model.index(1, 1), Qt.ItemDataRole.BackgroundRole))

    def test_trend_and_bias_use_visible_point_lines(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.match_type.setCurrentText("TEM")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        trend_items = {
            item.name(): item for item in plots["trend"].listDataItems()
        }
        self.assertEqual(set(trend_items), {"PMISH", "TEM"})
        self.assertEqual(
            trend_items["TEM"].opts["pen"].color().name(),
            "#ed7d31",
        )
        self.assertEqual(
            trend_items["PMISH"].opts["pen"].color().name(),
            "#5b9bd5",
        )
        for item in trend_items.values():
            self.assertEqual(item.opts["pen"].style(), Qt.PenStyle.SolidLine)
            self.assertGreaterEqual(item.opts["pen"].widthF(), 2.0)
            self.assertEqual(item.opts["symbol"], "o")

        bias_item = plots["bias"].listDataItems()[0]
        self.assertEqual(bias_item.opts["symbol"], "o")
        bias_percent_item = plots["bias-percent"].listDataItems()[0]
        self.assertEqual(bias_percent_item.opts["symbol"], "o")
        self.assertEqual(plots["match"].getAxis("bottom").labelText, "PMISH")
        self.assertEqual(plots["match"].getAxis("left").labelText, "TEM")
        self.assertEqual(plots["trend"].getAxis("left").labelText, "")
        self.assertEqual(plots["bias"].getAxis("left").labelText, "Bias (nm)")
        self.assertEqual(
            plots["bias-percent"].getAxis("left").labelText,
            "Bias (%)",
        )
        self.assertFalse(plots["bias"].getAxis("left").autoSIPrefix)
        self.assertFalse(plots["bias-percent"].getAxis("left").autoSIPrefix)
        self.assertEqual(
            plots["trend"].getAxis("bottom")._tickLevels,
            [[(1.0, "W1"), (2.0, "W2"), (3.0, "W3")]],
        )

    def test_final_bias_axes_fit_measurements_not_the_zero_reference_line(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.result_mode.setCurrentText("Final")
        raw = self.raw()
        raw["CD_Bot"] = [9, 19.1, 29.2]
        raw["SPA"] = [8, 10.1, 12.2]
        self.window.set_raw_frame(raw, "Final Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()
        self.window.resize(1500, 900)
        self.window.show()
        APP.processEvents()
        for parameter, negative in (("CD_Bot", True), ("SPA", False)):
            for name in ("bias", "bias-percent"):
                with self.subTest(parameter=parameter, plot=name):
                    plot = self.window.plot_groups[parameter]["plots"][name]
                    view = plot.getViewBox()
                    values = plot.listDataItems()[0].getData()[1]
                    lines = [item for item in plot.getPlotItem().items if isinstance(item, pg.InfiniteLine)]
                    self.assertEqual(len(lines), 1)
                    self.assertEqual(lines[0].value(), 0)
                    # Check both first draw and the native Auto Scale path after zoom.
                    for reset in (False, True):
                        if reset:
                            view.setYRange(-100, 100, padding=0)
                            view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
                            APP.processEvents()
                        low, high = view.viewRange()[1]
                        self.assertLess(low, min(values))
                        self.assertGreater(high, max(values))
                        if negative:
                            self.assertLess(high, 0)
                        else:
                            self.assertGreater(low, 0)

    def test_bias_auto_range_keeps_zero_crossings_and_constant_values_visible(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.result_mode.setCurrentText("Final")
        raw = self.raw()
        raw["CD_Bot"] = [11, 22, 33]
        raw["SPA"] = [5, 7, 9]
        self.window.set_raw_frame(raw, "Final Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()
        for parameter in ("CD_Bot", "SPA"):
            for name in ("bias", "bias-percent"):
                with self.subTest(parameter=parameter, plot=name):
                    plot = self.window.plot_groups[parameter]["plots"][name]
                    plot.getViewBox().autoRange()
                    low, high = plot.getViewBox().viewRange()[1]
                    values = plot.listDataItems()[0].getData()[1]
                    self.assertLess(low, min(values))
                    self.assertGreater(high, max(values))
                    self.assertLess(low, 0)
                    self.assertGreater(high, 0)

    def test_trend_card_checkbox_switches_between_raw_and_carded_values(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        group = self.window.plot_groups["CD_Bot"]
        checkbox = group["plots"]["trend"].findChild(
            QCheckBox, "trendCardToggle"
        )
        self.assertIsNotNone(checkbox)
        self.assertTrue(checkbox.isChecked())
        pmish = {
            item.name(): item for item in group["plots"]["trend"].listDataItems()
        }["PMISH"]
        self.assertEqual(pmish.yData.tolist(), [12.0, 22.0, 32.0])

        checkbox.setChecked(False)
        APP.processEvents()

        pmish = {
            item.name(): item for item in group["plots"]["trend"].listDataItems()
        }["PMISH"]
        self.assertEqual(pmish.yData.tolist(), [1.0, 2.0, 3.0])

    def test_run_analysis_preserves_the_setup_scroll_position(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        scroll_bar = self.window.setup_scroll.verticalScrollBar()
        scroll_bar.setValue(0)

        self.window.analyze_button.click()
        APP.processEvents()

        self.assertEqual(scroll_bar.value(), 0)

    def test_run_analysis_preserves_the_dragged_setup_splitter_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([520, 280, 760])
        APP.processEvents()
        dragged_sizes = self.window.setup_splitter.sizes()

        self.window.run_analysis()
        APP.processEvents()

        self.assertEqual(
            self.window.setup_splitter.sizes()[:2],
            dragged_sizes[:2],
        )

    def test_wkb_restores_the_saved_setup_splitter_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([320, 520, 1600])
        APP.processEvents()
        saved_sizes = tuple(self.window.setup_splitter.sizes())

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "layout.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.resize(1600, 900)
                reopened.show()
                APP.processEvents()
                reopened.load_workbook(path)
                APP.processEvents()
                self.assertEqual(
                    tuple(reopened.setup_splitter.sizes()[:2]),
                    saved_sizes[:2],
                )
                self.assertEqual(
                    reopened.setup_scroll.verticalScrollBar().value(), 0
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_wkb_paths_are_sent_to_the_diagnostic_log(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "diagnostic.wkb"
            with self.assertLogs("metrology_workspace", level="INFO") as captured:
                self.window.save_workbook(path)
                self.window.load_workbook(path)

        messages = "\n".join(captured.output)
        self.assertIn(f"WKB saved: {path.resolve()}", messages)
        self.assertIn(f"WKB opened: {path.resolve()}", messages)

    def test_recent_wkb_menu_reopens_a_persisted_workbook(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recent-analysis.wkb"
            self.window.save_workbook(path)
            with (
                patch(
                    "metrology_app.matching_window.recent_wkb_paths",
                    create=True,
                    return_value=(path.resolve(),),
                ),
                patch(
                    "metrology_app.matching_window.remember_recent_wkb",
                    create=True,
                    return_value=(path.resolve(),),
                ),
            ):
                reopened = MatchingWindow()
                try:
                    recent_action = reopened.open_recent_menu.actions()[0]
                    self.assertIn(path.name, recent_action.text())
                    self.assertEqual(recent_action.toolTip(), str(path.resolve()))

                    recent_action.trigger()

                    self.assertEqual(reopened.workbook_path, path.resolve())
                finally:
                    reopened.close()
                    reopened.deleteLater()
                    APP.processEvents()

    def test_opening_a_wkb_remembers_it_in_the_recent_menu(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remember-opened.wkb"
            self.window.save_workbook(path)
            with (
                patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(path), "Matching Workbook (*.wkb)"),
                ),
                patch(
                    "metrology_app.matching_window.remember_recent_wkb",
                    return_value=(path.resolve(),),
                ) as remember,
            ):
                self.window.open_wkb_dialog()

            remember.assert_called_once_with(path.resolve())
            self.assertEqual(
                self.window.open_recent_menu.actions()[0].toolTip(),
                str(path.resolve()),
            )

    def test_unavailable_recent_settings_do_not_fail_wkb_save(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "still-saved.wkb"
            self.window.save_workbook(path)
            with (
                patch(
                    "metrology_app.matching_window.remember_recent_wkb",
                    side_effect=PermissionError("settings unavailable"),
                ),
                patch.object(QMessageBox, "warning") as warning,
            ):
                saved = self.window.save_wkb()

            self.assertEqual(saved, path.resolve())
            self.assertTrue(path.is_file())
            warning.assert_not_called()

    def test_reveal_wkb_action_selects_the_current_workbook(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "locate-this.wkb"
            self.window.save_workbook(path)
            self.assertTrue(self.window.reveal_wkb_action.isEnabled())

            with patch(
                "metrology_app.matching_window.reveal_path_in_folder",
                create=True,
            ) as reveal:
                self.window.reveal_wkb_action.trigger()

            reveal.assert_called_once_with(path.resolve())

    def test_parameter_plot_order_survives_run_and_wkb(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        card = self.window.plot_groups["CD_Bot"]["card"]
        self.assertTrue(card.acceptDrops())
        self.assertIsNotNone(card.findChild(QLabel, "parameterDragHandle"))
        self.window.move_parameter("SPA", "CD_Bot", before=True)

        self.assertEqual(self.window.parameter_order(), ("SPA", "CD_Bot"))
        self.window.run_analysis()
        self.assertEqual(self.window.parameter_order(), ("SPA", "CD_Bot"))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "order.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                self.assertEqual(reopened.parameter_order(), ("SPA", "CD_Bot"))
                self.assertFalse(hasattr(reopened, "reset_order_button"))
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_numeric_reference_columns_without_suffix_can_be_mapped_manually(self):
        reference = pd.DataFrame({
            "Wafer ID": ["slot16", "", "slot17"],
            "Die Seq": ["2", "36", "2"],
            "PMISH": ["1.1", "2.1", "3.1"],
            "TEM": ["2.0", "4.0", "6.0"],
            "BIAS": ["0.9", "1.9", "2.9"],
        })
        raw = pd.DataFrame({
            "Cur SME File Path": ["a", "b", "c"],
            "Wafer ID": ["W1", "W1", "W2"],
            "Lot ID": ["L1", "L1", "L1"],
            "Tool SN": ["T1", "T1", "T1"],
            "PAD Name": ["P1", "P1", "P1"],
            "OCD CD": ["1.0", "2.0", "3.0"],
        })

        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")

        reference_columns = [
            self.window.mapping_table.item(row, 2).text()
            for row in range(self.window.mapping_table.rowCount())
        ]
        self.assertEqual(reference_columns, ["PMISH", "TEM", "BIAS"])
        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
            for row in range(self.window.mapping_table.rowCount())
        ))

        tem_row = reference_columns.index("TEM")
        self.window.mapping_table.cellWidget(tem_row, 3).setCurrentText("OCD CD")
        self.window.mapping_table.item(tem_row, 0).setCheckState(Qt.CheckState.Checked)

        self.assertTrue(self.window.analyze_button.isEnabled())
        result = self.window.run_analysis()
        self.assertEqual(result.parameter_names, ("TEM",))
        self.assertEqual(result.card("TEM").slope, 2.0)

    def test_final_mode_keeps_evaluated_values_equal_to_raw_data(self):
        reference = pd.DataFrame({"CD Reference": [10.0, 20.0, 30.0]})
        raw = pd.DataFrame({"CD": [11.0, 19.0, 31.0]})
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(raw, "Final clipboard")

        result = self.window.run_analysis()

        self.assertEqual(result.series("CD")["Evaluated Value"].tolist(), [11.0, 19.0, 31.0])

    def test_preview_and_final_fullmap_open_in_the_existing_wafer_workspace(self):
        opened = []

        class FakeWaferWorkspace:
            def __init__(self):
                self.cards = {}

            def set_parameter_cards(self, cards):
                self.cards = dict(cards)

            def set_table(self, frame, source):
                self.frame = frame
                self.source = source

            def show(self):
                opened.append(self)

        self.window.close()
        self.window.deleteLater()
        self.window = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.set_preview_frame(pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "X": [-1.0, 1.0],
            "Y": [0.0, 0.0],
            "CD_Bot": [4.0, 5.0],
            "SPA": [5.0, 6.0],
        }), "Preview clipboard")
        final = pd.DataFrame({
            "Wafer ID": ["F1", "F1"],
            "X": [-1.0, 1.0],
            "Y": [0.0, 0.0],
            "CD_Bot": [41.0, 51.0],
            "SPA": [11.0, 13.0],
        })
        self.window.set_final_frame(final, "Final clipboard")
        self.window.run_analysis()

        preview_workspace = self.window.open_stage_workspace("preview")
        final_workspace = self.window.open_stage_workspace("final")

        self.assertEqual(len(opened), 2)
        self.assertIn("Preview", preview_workspace.source)
        self.assertIn("Final", final_workspace.source)
        # The workspace gets the pasted values plus the Cards; applying them is
        # the workspace's own Card option, so nothing is carded up front.
        self.assertEqual(preview_workspace.frame["CD_Bot"].tolist(), [4.0, 5.0])
        self.assertEqual(
            sorted(preview_workspace.cards), ["CD_Bot", "SPA"]
        )
        pd.testing.assert_frame_equal(final_workspace.frame, final)

    def test_kla_map_edits_are_saved_in_wkb_and_not_regenerated(self):
        opened = []

        class FakeWaferWorkspace:
            def __init__(self):
                self.model = SheetModel()

            def set_table(self, frame, source):
                self.source = source
                self.model.load(frame)

            def show(self):
                opened.append(self)

        self.window.close()
        self.window.deleteLater()
        self.window = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        workspace = self.window.open_stage_workspace("preview")
        generated = workspace.model.frame()
        # Preview hands over the raw values; the Card is an opt-in in the
        # workspace Data tab, so the saved snapshot keeps the raw numbers.
        self.assertEqual(generated["CD_Bot"].astype(float).tolist(), [1.0, 2.0, 3.0])
        edited = generated.copy()
        edited.loc[0, "CD_Bot"] = 999.0
        workspace.model.load(edited)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "edited-map.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
            try:
                reopened.load_workbook(path)
                restored_workspace = reopened.open_stage_workspace("preview")
                restored = restored_workspace.model.frame()
                self.assertEqual(float(restored.loc[0, "CD_Bot"]), 999.0)
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_preview_and_final_dynamic_edits_are_saved_independently_in_wkb(self):
        opened = []

        class FakeDynamicWorkspace:
            def __init__(self):
                self.model = SheetModel()

            def set_table(self, frame, source):
                self.source = source
                self.model.load(frame)

            def setWindowTitle(self, title):
                self.title = title

            def show(self):
                opened.append(self)

        self.window.close()
        self.window.deleteLater()
        self.window = MatchingWindow(
            dynamic_window_factory=FakeDynamicWorkspace
        )
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        preview_workspace = self.window.open_dynamic_workspace("preview")
        final_workspace = self.window.open_dynamic_workspace("final")
        preview_dynamic = pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "Die Seq": [1, 2],
            "Cycle": [1, 1],
            "CD_Bot": [12.1, 12.2],
        })
        final_dynamic = pd.DataFrame({
            "Wafer ID": ["F1", "F1"],
            "Die Seq": [1, 2],
            "Cycle": [1, 1],
            "CD_Bot": [11.8, 11.9],
        })
        preview_workspace.model.load(preview_dynamic)
        final_workspace.model.load(final_dynamic)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dynamic-edits.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow(
                dynamic_window_factory=FakeDynamicWorkspace
            )
            try:
                reopened.load_workbook(path)
                restored_preview = reopened.open_dynamic_workspace(
                    "preview"
                ).model.frame()
                restored_final = reopened.open_dynamic_workspace(
                    "final"
                ).model.frame()
                pd.testing.assert_frame_equal(
                    restored_preview.astype(str), preview_dynamic.astype(str)
                )
                pd.testing.assert_frame_equal(
                    restored_final.astype(str), final_dynamic.astype(str)
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_closing_managed_wafer_map_saves_after_explicit_save_decision(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "managed-map.wkb"
            self.window.save_workbook(path)
            workspace = self.window.open_stage_workspace("preview")
            try:
                column = workspace.model.frame().columns.get_loc("CD_Bot")
                workspace.model.edit({(1, column): "999"})
                with patch.object(
                    QMessageBox,
                    "question",
                    return_value=QMessageBox.StandardButton.Save,
                ) as discard_prompt:
                    closed = workspace.close()

                self.assertTrue(closed)
                discard_prompt.assert_called_once()
                saved = MatchWorkbook.load(path)
                self.assertEqual(float(saved.preview_map.loc[0, "CD_Bot"]), 999.0)
            finally:
                workspace.model.undo.setClean()
                workspace.close()
                workspace.deleteLater()
                APP.processEvents()

    def test_closing_managed_dynamic_saves_after_explicit_save_decision(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_dynamic_frame = pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W1", "W1"],
            "Die Seq": [1, 2, 1, 2],
            "Cycle": [1, 1, 2, 2],
            "CD_Bot": [10.0, 20.0, 11.0, 22.0],
        })

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "managed-dynamic.wkb"
            self.window.save_workbook(path)
            workspace = self.window.open_dynamic_workspace("preview")
            try:
                column = workspace.model.frame().columns.get_loc("CD_Bot")
                workspace.model.edit({(1, column): "777"})
                with patch.object(
                    QMessageBox,
                    "question",
                    return_value=QMessageBox.StandardButton.Save,
                ) as discard_prompt:
                    closed = workspace.close()

                self.assertTrue(closed)
                discard_prompt.assert_called_once()
                saved = MatchWorkbook.load(path)
                self.assertEqual(
                    float(saved.preview_dynamic.loc[0, "CD_Bot"]), 777.0
                )
            finally:
                workspace.model.undo.setClean()
                workspace.close()
                workspace.deleteLater()
                APP.processEvents()

    def test_kla_refresh_keeps_each_windows_plot_view(self):
        """A data refresh repaints plots in place: zoom, scroll and page stay."""
        parameters = [f"P{i}" for i in range(6)]
        xs = [-2.0, -1.0, 0.0, 1.0, 2.0, 0.0]
        ys = [0.0, 1.0, 2.0, 0.0, -1.0, -2.0]
        reference_rows, raw_rows = [], []
        for wafer in range(4):
            for die in range(6):
                value = float(wafer * 6 + die)
                reference_rows.append({
                    "Wafer ID": f"W{wafer}",
                    "Die Seq": die + 1,
                    "FIELD X": xs[die],
                    "FIELD Y": ys[die],
                    **{
                        f"{name} Reference": value + offset
                        for offset, name in enumerate(parameters)
                    },
                })
                raw_rows.append({
                    "Wafer ID": f"W{wafer}",
                    "Die Seq": die + 1,
                    "FIELD X": xs[die],
                    "FIELD Y": ys[die],
                    **{
                        name: value + offset - 1.0
                        for offset, name in enumerate(parameters)
                    },
                })
        self.window.set_reference_frame(
            pd.DataFrame(reference_rows), "Clipboard"
        )
        self.window.set_raw_frame(pd.DataFrame(raw_rows), "Clipboard")
        self.window.run_analysis()
        map_window = self.window.open_stage_workspace("preview")
        correlation_window = self.window.open_correlation_workspace()

        try:
            map_page = map_window.plot_page
            map_window.tabs.setCurrentIndex(1)
            map_window.check_all(map_window.wafer_list, True)
            map_window.check_all(map_window.parameter_list, True)
            map_page.selector.selectAll()
            map_page.draw_maps()
            QTest.qWait(600)
            APP.processEvents()
            self.assertIsNotNone(map_page.result)
            map_page.zoom.setCurrentText("150%")
            APP.processEvents()
            map_page.scroll.horizontalScrollBar().setValue(70)
            map_page.scroll.verticalScrollBar().setValue(90)
            map_page.show_selector()

            correlation_page = correlation_window.correlation_page
            correlation_window.tabs.setCurrentIndex(2)
            correlation_page.selector.selectAll()
            correlation_page.draw_plot()
            APP.processEvents()
            self.assertTrue(correlation_page.ready)
            self.assertGreater(correlation_page.page_count(), 1)
            correlation_page.set_page(1)
            correlation_page.show_selector()

            trend_page = correlation_window.sequence_page
            correlation_window.tabs.setCurrentIndex(3)
            trend_page.selector.selectAll()
            trend_page.draw_plot()
            APP.processEvents()
            trend_page.show_selector()

            replacement = self.window.raw_model.frame().copy()
            column = replacement.columns.get_loc("P0")
            replacement.iloc[0, column] = "400"
            self.window.raw_model.edit({(1, column): "400"})
            APP.processEvents()
            self.window.run_analysis()
            QTest.qWait(800)
            APP.processEvents()

            self.assertIs(map_page.stack.currentWidget(), map_page.selector_panel)
            self.assertEqual(map_page.zoom.currentText(), "150%")
            # The new canvas may clamp an offset by a pixel or two; what matters
            # is that the view did not snap back to the top-left corner.
            self.assertAlmostEqual(
                map_page.scroll.horizontalScrollBar().value(), 70, delta=3
            )
            self.assertAlmostEqual(
                map_page.scroll.verticalScrollBar().value(), 90, delta=3
            )
            self.assertIs(
                correlation_page.stack.currentWidget(),
                correlation_page.selector_panel,
            )
            self.assertEqual(correlation_page.page_index, 1)
            self.assertIs(
                trend_page.stack.currentWidget(), trend_page.selector_panel
            )
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_analysis_menu_owns_the_trend_axis_mode(self):
        """The menu supplies a decimal threshold and two force modes."""
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        self.assertEqual(self.window.trend_axis_mode, "auto")
        self.assertEqual(self.window.second_axis_ratio, 10.0)
        self.assertEqual(
            [self.window.second_axis_actions[mode].text()
             for mode in ("auto", "dual", "single")],
            ["● Auto (median ratio)", "○ Always two Y axes",
             "○ Always one Y axis"],
        )
        self.assertFalse(any(action.isCheckable()
                             for action in self.window.second_axis_actions.values()))
        self.assertEqual(self.window.second_axis_spin.decimals(), 3)

        workspace = self.window.open_correlation_workspace()
        try:
            page = workspace.sequence_page
            # The menu owns the option, so the in-page control is hidden.
            self.assertTrue(page.axis_mode.isHidden())
            self.assertTrue(page.axis_ratio.isHidden())
            self.assertEqual(page.axis_mode_value(), "auto")

            self.window.second_axis_spin.setValue(2.75)
            self.window.second_axis_actions["dual"].trigger()
            APP.processEvents()
            self.assertEqual(page.axis_ratio_limit(), 2.75)
            self.assertEqual(page.axis_mode_value(), "dual")
            self.assertEqual(
                self.window.second_axis_actions["dual"].text(),
                "● Always two Y axes",
            )
            self.window.second_axis_actions["single"].trigger()
            APP.processEvents()

            # The menu is saved once, separate from per-stage plotting choices.
            state = self.window._correlation_selection_states["preview"]
            self.assertNotIn("trend_axis_mode", state)
            self.assertNotIn("trend_axis_ratio", state)
            self.assertEqual(
                self.window.current_workbook().trend_axis_settings,
                {"mode": "single", "ratio": 2.75},
            )

            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "second-axis.wkb"
                self.window.save_workbook(path)
                self.window._close_stage_windows()
                reopened = MatchingWindow()
                try:
                    reopened.load_workbook(path)
                    self.assertEqual(reopened.trend_axis_mode, "single")
                    self.assertEqual(reopened.second_axis_spin.value(), 2.75)
                    restored = reopened.open_correlation_workspace()
                    self.assertEqual(
                        restored.sequence_page.axis_mode_value(), "single"
                    )
                    self.assertEqual(restored.sequence_page.axis_ratio_limit(), 2.75)
                    # The menu shows the value the workbook carries.
                    self.assertEqual(
                        reopened.second_axis_actions["single"].text(),
                        "● Always one Y axis",
                    )
                    reopened._close_stage_windows()
                finally:
                    reopened.close()
                    reopened.deleteLater()
                    APP.processEvents()
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_standalone_correlation_window_keeps_its_own_axis_mode_control(self):
        """Without a Match Workbook the page keeps the control it always had."""
        from metrology_app.correlation_window import CorrelationWindow

        workspace = CorrelationWindow()
        try:
            self.assertFalse(workspace.sequence_page.axis_mode.isHidden())
            self.assertFalse(workspace.sequence_page.axis_ratio.isHidden())
            self.assertEqual(workspace.sequence_page.axis_mode_value(), "auto")
            workspace.set_second_axis_ratio(2.75, show_control=True)
            workspace.set_trend_axis_mode("dual", show_control=True)
            self.assertEqual(workspace.sequence_page.axis_mode_value(), "dual")
            self.assertEqual(workspace.sequence_page.axis_ratio_limit(), 2.75)
            self.assertFalse(workspace.sequence_page.axis_mode.isHidden())
        finally:
            workspace.close()
            workspace.deleteLater()
            APP.processEvents()

    def test_stage_selection_cannot_override_shared_axis_settings(self):
        """Opening a stage cannot overwrite the workbook menu's policy."""
        workspace = CorrelationWindow()
        try:
            self.window.set_trend_axis_mode("dual")
            self.window._correlation_selection_states["preview"] = {
                "trend_axis_ratio": 2.75,
            }
            self.window._offer_second_axis_settings(workspace)
            self.assertEqual(self.window.trend_axis_mode, "dual")
            self.assertEqual(workspace.sequence_page.axis_mode_value(), "dual")
            self.assertEqual(workspace.sequence_page.axis_ratio_limit(), 10.0)
        finally:
            workspace.close()
            workspace.deleteLater()
            APP.processEvents()

    def test_axis_settings_are_shared_between_preview_and_final(self):
        """Both open windows and later openings use the same saved policy."""
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Preview clipboard")
        self.window.run_analysis()
        self.window.second_axis_spin.setValue(2.75)
        self.window.set_trend_axis_mode("dual")
        preview = self.window.open_correlation_workspace()
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(self.raw(), "Final clipboard")
        final = self.window.open_correlation_workspace()
        for workspace in (preview, final):
            self.assertEqual(workspace.sequence_page.axis_ratio_limit(), 2.75)
            self.assertEqual(workspace.sequence_page.axis_mode_value(), "dual")
        self.window.set_trend_axis_mode("single")
        self.window.result_mode.setCurrentText("Preview")
        for workspace in (preview, final):
            self.assertEqual(workspace.sequence_page.axis_mode_value(), "single")
        self.window._close_stage_windows()

        # Save a later menu edit without any child window to capture it.
        self.window.set_second_axis_ratio(4.125)
        self.window.set_trend_axis_mode("auto")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared-axis.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                for stage in ("Final", "Preview"):
                    reopened.result_mode.setCurrentText(stage)
                    workspace = reopened.open_correlation_workspace()
                    self.assertEqual(workspace.sequence_page.axis_ratio_limit(), 4.125)
                    self.assertEqual(workspace.sequence_page.axis_mode_value(), "auto")
                    self.assertEqual(reopened.second_axis_spin.value(), 4.125)
                reopened._close_stage_windows()
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_workspace_card_checkbox_applies_the_parameter_cards(self):
        """The Data tab offers the workbook Card; off until the engineer asks."""
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        workspace = self.window.open_stage_workspace("preview")
        try:
            self.assertTrue(workspace.card_check.isEnabled())
            self.assertFalse(workspace.card_check.isChecked())
            plotted = lambda: pd.to_numeric(
                workspace.plot_page.frame["CD_Bot"], errors="coerce"
            ).tolist()
            self.assertEqual(plotted(), [1.0, 2.0, 3.0])

            workspace.card_check.setChecked(True)
            APP.processEvents()
            self.assertEqual(plotted(), [12.0, 22.0, 32.0])
            # The table keeps the loaded values; only the plots use the Card.
            self.assertEqual(
                pd.to_numeric(
                    workspace.model.frame()["CD_Bot"], errors="coerce"
                ).tolist(),
                [1.0, 2.0, 3.0],
            )

            workspace.card_check.setChecked(False)
            APP.processEvents()
            self.assertEqual(plotted(), [1.0, 2.0, 3.0])
        finally:
            workspace.close()
            workspace.deleteLater()
            APP.processEvents()

    def test_dynamic_workspace_card_checkbox_applies_the_parameter_cards(self):
        self.window.set_reference_frame(pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot Reference": [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
        }), "Clipboard")
        self.window.set_raw_frame(pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }), "Clipboard")
        self.window.run_analysis()
        # Dynamic only opens with the table the workbook saved for it.
        self.window.preview_dynamic_frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })
        workspace = self.window.open_dynamic_workspace("preview")
        try:
            self.assertTrue(workspace.card_check.isEnabled())
            self.assertFalse(workspace.card_check.isChecked())
            self.assertEqual(
                pd.to_numeric(
                    workspace.dynamic_page.frame["CD_Bot"], errors="coerce"
                ).tolist(),
                [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            )

            workspace.card_check.setChecked(True)
            APP.processEvents()
            self.assertEqual(
                pd.to_numeric(
                    workspace.dynamic_page.frame["CD_Bot"], errors="coerce"
                ).tolist(),
                [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
            )
        finally:
            workspace.model.undo.setClean()
            workspace.close()
            workspace.deleteLater()
            APP.processEvents()

    def test_refreshing_analysis_windows_keeps_their_active_tab(self):
        """Raw, Reference and mapping edits refresh data without moving views."""
        self.window.set_reference_frame(pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot Reference": [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
            "SPA Reference": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }), "Clipboard")
        self.window.set_raw_frame(pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "SPA": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0],
        }), "Clipboard")
        self.window.run_analysis()
        map_window = self.window.open_stage_workspace("preview")
        dynamic_window = self.window.open_dynamic_workspace("preview")
        correlation_window = self.window.open_correlation_workspace()

        def assert_views_kept():
            self.assertEqual(map_window.tabs.currentIndex(), 2)
            self.assertEqual(dynamic_window.tabs.currentIndex(), 2)
            self.assertEqual(correlation_window.tabs.currentIndex(), 3)
            self.assertEqual(
                (
                    map_window.sheet.currentIndex().row(),
                    map_window.sheet.currentIndex().column(),
                ),
                (3, 1),
            )
            self.assertIs(
                correlation_window.sequence_page.stack.currentWidget(),
                correlation_window.sequence_page.selector_panel,
            )

        try:
            map_window.tabs.setCurrentIndex(2)          # Radius Plot
            dynamic_window.tabs.setCurrentIndex(2)      # Trend
            correlation_window.tabs.setCurrentIndex(3)  # Trend
            map_window.sheet.setCurrentIndex(
                map_window.sheet.model().index(3, 1)
            )
            # Draw once, then go back to the curve boxes: a later refresh must
            # not yank the engineer out of the selector.
            trend = correlation_window.sequence_page
            trend.selector.selectAll()
            trend.draw_plot()
            trend.show_selector()
            APP.processEvents()

            replacement = pd.DataFrame({
                "Wafer ID": ["W1"] * 6,
                "Die Seq": [1, 2, 1, 2, 1, 2],
                "CD_Bot": [40.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "SPA": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0],
            })
            self.window.set_raw_frame(replacement, "Clipboard")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            assert_views_kept()
            self.assertEqual(
                pd.to_numeric(
                    correlation_window.raw_model.frame()["CD_Bot"],
                    errors="coerce",
                ).tolist(),
                replacement["CD_Bot"].tolist(),
            )

            # A Reference edit refreshes the derived values the same way.
            reference = pd.DataFrame({
                "Wafer ID": ["W1"] * 6,
                "Die Seq": [1, 2, 1, 2, 1, 2],
                "CD_Bot Reference": [15.0, 25.0, 35.0, 45.0, 55.0, 65.0],
                "SPA Reference": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            })
            self.window.set_reference_frame(reference, "Clipboard")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            assert_views_kept()
            self.assertEqual(
                pd.to_numeric(
                    correlation_window.reference_model.frame()["CD_Bot"],
                    errors="coerce",
                ).tolist(),
                reference["CD_Bot Reference"].tolist(),
            )

            # Changing a parameter mapping must not rebuild the windows either.
            self.window.mapping_table.cellWidget(0, 3).setCurrentText("SPA")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            assert_views_kept()
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_tem_keeps_one_analysis_window_per_button(self):
        """TEM opens each of the three windows once, not one window in total."""
        self.window.match_type.setCurrentText("TEM")
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        correlation = self.window.open_correlation_workspace()
        map_window = self.window.open_stage_workspace("preview")
        dynamic_window = self.window.open_dynamic_workspace("preview")
        try:
            self.assertEqual(
                self.window._stage_windows,
                [correlation, map_window, dynamic_window],
            )
            self.assertTrue(correlation.isVisible())
            self.assertEqual(
                self.window._stage_window_context[map_window],
                ("map", "preview"),
            )

            # Each button reuses its own window instead of opening a second one.
            repeated = self.window.open_stage_workspace("preview")
            self.assertIs(repeated, map_window)
            self.assertEqual(len(self.window._stage_windows), 3)
            self.assertEqual(
                self.window._stage_windows.count(map_window), 1
            )
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_kla_and_nova_keep_all_three_analysis_windows_open(self):
        for match_type in ("KLA", "NOVA"):
            with self.subTest(match_type=match_type):
                self.window.match_type.setCurrentText(match_type)
                self.window.set_reference_frame(self.reference(), "Clipboard")
                self.window.set_raw_frame(self.raw(), "Clipboard")
                self.window.run_analysis()
                windows = [
                    self.window.open_stage_workspace("preview"),
                    self.window.open_dynamic_workspace("preview"),
                    self.window.open_correlation_workspace(),
                ]
                try:
                    self.assertEqual(len(self.window._stage_windows), 3)
                    self.assertTrue(
                        all(window.isVisible() for window in windows)
                    )
                finally:
                    self.window._close_stage_windows()
                    APP.processEvents()

    def test_kla_raw_edits_refresh_every_analysis_window(self):
        """KLA/NOVA refresh Map and Correlation; Dynamic keeps its own table."""
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot Reference": [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "CD_Bot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }), "Clipboard")
        self.window.run_analysis()
        map_window = self.window.open_stage_workspace("preview")
        dynamic_window = self.window.open_dynamic_workspace("preview")
        correlation_window = self.window.open_correlation_workspace()
        try:
            column = "CD_Bot"
            before_map = pd.to_numeric(
                map_window.model.frame()[column], errors="coerce"
            ).tolist()
            # Dynamic never copies the workbook: it starts empty and stays so.
            self.assertEqual(len(dynamic_window.model.frame().columns), 0)

            replacement = pd.DataFrame({
                "Wafer ID": ["W1"] * 6,
                "Die Seq": [1, 2, 1, 2, 1, 2],
                # A non-affine change: a plain offset would be absorbed by the
                # refitted Card and the derived Map/Dynamic tables would look
                # unchanged even though they did follow the workbook.
                "CD_Bot": [40.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            })
            self.window.set_raw_frame(replacement, "Clipboard")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            self.assertEqual(
                pd.to_numeric(
                    correlation_window.raw_model.frame()[column], errors="coerce"
                ).tolist(),
                replacement[column].tolist(),
            )
            self.assertNotEqual(
                pd.to_numeric(
                    map_window.model.frame()[column], errors="coerce"
                ).tolist(),
                before_map,
            )
            self.assertEqual(len(dynamic_window.model.frame().columns), 0)
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_tem_correlation_window_follows_raw_edits(self):
        self.window.match_type.setCurrentText("TEM")
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        correlation_window = self.window.open_correlation_workspace()
        try:
            replacement = self.raw().copy()
            replacement["CD_Bot"] = replacement["CD_Bot"] + 5
            self.window.set_raw_frame(replacement, "Clipboard")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            self.assertEqual(
                pd.to_numeric(
                    correlation_window.raw_model.frame()["CD_Bot"],
                    errors="coerce",
                ).tolist(),
                replacement["CD_Bot"].tolist(),
            )
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_tem_map_data_stays_independent_of_raw_edits(self):
        self.window.match_type.setCurrentText("TEM")
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        independent = pd.DataFrame({
            "Wafer ID": ["W1", "W1"],
            "PAD Name": ["P1", "P1"],
            "Die Seq": [1, 2],
            "CD_Bot": [42.0, 43.0],
        })
        self.window.preview_map_frame = independent.copy()
        map_window = self.window.open_stage_workspace("preview")
        try:
            self.assertEqual(
                pd.to_numeric(
                    map_window.model.frame()["CD_Bot"], errors="coerce"
                ).tolist(),
                [42.0, 43.0],
            )

            replacement = self.raw().copy()
            replacement["CD_Bot"] = replacement["CD_Bot"] + 5
            self.window.set_raw_frame(replacement, "Clipboard")
            APP.processEvents()
            self.window.run_analysis()
            APP.processEvents()

            self.assertEqual(
                pd.to_numeric(
                    map_window.model.frame()["CD_Bot"], errors="coerce"
                ).tolist(),
                [42.0, 43.0],
            )
        finally:
            self.window._close_stage_windows()
            APP.processEvents()

    def test_closing_match_workbook_saves_and_closes_all_analysis_workspaces(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_dynamic_frame = pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W1", "W1"],
            "Die Seq": [1, 2, 1, 2],
            "Cycle": [1, 1, 2, 2],
            "CD_Bot": [10.0, 20.0, 11.0, 22.0],
        })

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "close-with-analysis-windows.wkb"
            self.window.save_workbook(path)
            map_workspace = self.window.open_stage_workspace("preview")
            dynamic_workspace = self.window.open_dynamic_workspace("preview")
            correlation_workspace = self.window.open_correlation_workspace()
            try:
                map_column = map_workspace.model.frame().columns.get_loc("CD_Bot")
                dynamic_column = (
                    dynamic_workspace.model.frame().columns.get_loc("CD_Bot")
                )
                map_workspace.model.edit({(1, map_column): "999"})
                dynamic_workspace.model.edit({(1, dynamic_column): "777"})
                APP.processEvents()

                with patch.object(QMessageBox, "warning") as warning, patch.object(
                    QMessageBox, "question", return_value=QMessageBox.StandardButton.Save
                ):
                    self.assertTrue(self.window.close())
                    APP.processEvents()

                warning.assert_not_called()
                for workspace in (
                    map_workspace, dynamic_workspace, correlation_workspace
                ):
                    try:
                        visible = workspace.isVisible()
                    except RuntimeError as error:
                        self.assertIn("has been deleted", str(error))
                        visible = False
                    self.assertFalse(visible)
                saved = MatchWorkbook.load(path)
                self.assertEqual(float(saved.preview_map.loc[0, "CD_Bot"]), 999.0)
                self.assertEqual(
                    float(saved.preview_dynamic.loc[0, "CD_Bot"]), 777.0
                )
            finally:
                for workspace in (
                    map_workspace, dynamic_workspace, correlation_workspace
                ):
                    try:
                        workspace.close()
                        workspace.deleteLater()
                    except RuntimeError as error:
                        self.assertIn("has been deleted", str(error))
                APP.processEvents()

    def test_reopening_preview_dynamic_restores_its_parameter_selection(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_dynamic_frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 6,
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "Cycle": [1, 1, 2, 2, 3, 3],
            "CD_Bot": [10.0, 20.0, 11.0, 22.0, 12.0, 24.0],
            "SPA": [5.0, 7.0, 6.0, 9.0, 7.0, 11.0],
        })

        first = self.window.open_dynamic_workspace("preview")
        for index in range(first.parameter_list.topLevelItemCount()):
            item = first.parameter_list.topLevelItem(index)
            if item.text(0) in {"CD_Bot", "SPA"}:
                item.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(first.selection["metrics"], ["CD_Bot", "SPA"])
        self.save_child_and_close(first)
        first.deleteLater()
        APP.processEvents()

        second = self.window.open_dynamic_workspace("preview")
        try:
            self.assertEqual(second.selection["metrics"], ["CD_Bot", "SPA"])
            self.assertEqual(
                list(second.dynamic_page.parameter_models), ["CD_Bot", "SPA"]
            )
        finally:
            second.close()
            second.deleteLater()
            APP.processEvents()

    def test_preview_and_final_wafer_quality_metrics_survive_wkb_reopen(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W1"], "X": [-1, 1], "Y": [0, 0],
            "CD_Bot": [4, 5], "SPA": [5, 6],
            "MSE": [0.1, 0.2], "GOF": [0.9, 0.8], "NGOF": [0.8, 0.7],
            "LBH": [1, 2], "CINDEX": [3, 4], "fitTime": [10, 11],
            "regIter": [5, 6],
        })
        self.window.set_preview_frame(frame, "Preview FullMap")
        self.window.set_final_frame(frame, "Final FullMap")
        self.window.run_analysis()
        quality = ["MSE", "GOF", "NGOF", "LBH", "CINDEX"]
        for stage in ("preview", "final"):
            workspace = self.window.open_stage_workspace(stage)
            items = {workspace.parameter_list.topLevelItem(i).text(0):
                     workspace.parameter_list.topLevelItem(i)
                     for i in range(workspace.parameter_list.topLevelItemCount())}
            for column in quality:
                with self.subTest(stage=stage, column=column):
                    self.assertEqual(items[column].text(1), "NUMERIC")
                    self.assertTrue(items[column].flags() & Qt.ItemFlag.ItemIsUserCheckable)
                    self.assertEqual(items[column].checkState(0), Qt.CheckState.Unchecked)
                    items[column].setCheckState(0, Qt.CheckState.Checked)
            self.assertEqual(workspace.plot_page.selection["metrics"], quality)
            for column in ("fitTime", "regIter"):
                self.assertEqual(items[column].text(1), "METADATA")
            self.save_child_and_close(workspace)
            workspace.deleteLater()
            APP.processEvents()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quality.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                for stage in ("preview", "final"):
                    workspace = reopened.open_stage_workspace(stage)
                    self.assertEqual(workspace.selection["metrics"], quality)
                    self.assertEqual(workspace.plot_page.selection["metrics"], quality)
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_reopening_preview_wafer_map_restores_its_parameter_selection(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        first = self.window.open_stage_workspace("preview")
        parameter = next(
            first.parameter_list.topLevelItem(index)
            for index in range(first.parameter_list.topLevelItemCount())
            if first.parameter_list.topLevelItem(index).text(0) == "CD_Bot"
        )
        parameter.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(first.selection["metrics"], ["CD_Bot"])
        self.save_child_and_close(first)
        first.deleteLater()
        APP.processEvents()

        second = self.window.open_stage_workspace("preview")
        try:
            self.assertEqual(second.selection["metrics"], ["CD_Bot"])
            self.assertEqual(second.plot_page.selection["metrics"], ["CD_Bot"])
        finally:
            second.close()
            second.deleteLater()
            APP.processEvents()

    def test_drawn_wafer_map_auto_restores_after_window_and_wkb_reopen(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_map_frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 4,
            "FIELD X": [0, 1, 0, 1],
            "FIELD Y": [0, 0, 1, 1],
            "CD_Bot": [10.0, 11.0, 12.0, 13.0],
        })

        def wait_for_plot(workspace):
            deadline = time.monotonic() + 25
            page = workspace.plot_page
            while time.monotonic() < deadline:
                QTest.qWait(20)
                if (
                    page.worker is None
                    and not page.input_refresh_timer.isActive()
                    and page.result is not None
                ):
                    return
            self.fail(f"Wafer Map did not render: {page.status.text()}")

        first = self.window.open_stage_workspace("preview")
        parameter = next(
            first.parameter_list.topLevelItem(index)
            for index in range(first.parameter_list.topLevelItemCount())
            if first.parameter_list.topLevelItem(index).text(0) == "CD_Bot"
        )
        parameter.setCheckState(0, Qt.CheckState.Checked)
        selected_cell = (first.plot_page.selector.wafers[0], "CD_Bot")
        first.plot_page.selector.set_selected_cells({selected_cell})
        first.plot_page.draw_maps()
        wait_for_plot(first)
        self.save_child_and_close(first)
        first.deleteLater()
        APP.processEvents()

        second = self.window.open_stage_workspace("preview")
        try:
            wait_for_plot(second)
            self.assertEqual(second.plot_page.drawn_cells, {selected_cell})
        finally:
            second.close()
            second.deleteLater()
            APP.processEvents()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drawn-map-state.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                restored = reopened.open_stage_workspace("preview")
                wait_for_plot(restored)
                self.assertEqual(
                    restored.plot_page.drawn_cells, {selected_cell}
                )
                restored.close()
                restored.deleteLater()
                APP.processEvents()
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_drawn_radius_plot_auto_restores_after_window_and_wkb_reopen(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_map_frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 4,
            "FIELD X": [0, 1, 0, 1],
            "FIELD Y": [0, 0, 1, 1],
            "CD_Bot": [10.0, 11.0, 12.0, 13.0],
        })

        def wait_for_radius(workspace):
            deadline = time.monotonic() + 5
            page = workspace.radius_page
            while time.monotonic() < deadline:
                QTest.qWait(20)
                if not page.input_refresh_timer.isActive() and page.ready:
                    return
            self.fail(f"Radius Plot did not render: {page.status.text()}")

        first = self.window.open_stage_workspace("preview")
        parameter = next(
            first.parameter_list.topLevelItem(index)
            for index in range(first.parameter_list.topLevelItemCount())
            if first.parameter_list.topLevelItem(index).text(0) == "CD_Bot"
        )
        parameter.setCheckState(0, Qt.CheckState.Checked)
        selected_cell = (first.radius_page.selector.wafers[0], "CD_Bot")
        first.radius_page.selector.set_selected_cells({selected_cell})
        first.radius_page.draw_plot()
        self.assertTrue(first.radius_page.ready, first.radius_page.status.text())
        self.save_child_and_close(first)
        first.deleteLater()
        APP.processEvents()

        second = self.window.open_stage_workspace("preview")
        try:
            wait_for_radius(second)
            self.assertEqual(second.radius_page.drawn_cells, {selected_cell})
        finally:
            second.close()
            second.deleteLater()
            APP.processEvents()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drawn-radius-state.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                restored = reopened.open_stage_workspace("preview")
                wait_for_radius(restored)
                self.assertEqual(
                    restored.radius_page.drawn_cells, {selected_cell}
                )
                restored.close()
                restored.deleteLater()
                APP.processEvents()
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_reopened_wkb_restores_map_and_dynamic_sidebar_selections(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.preview_dynamic_frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 4 + ["W2"] * 4,
            "Die Seq": [1, 2, 1, 2] * 2,
            "Cycle": [1, 1, 2, 2] * 2,
            "CD_Bot": [10, 20, 11, 22, 30, 40, 31, 42],
            "SPA": [5, 7, 6, 9, 15, 17, 16, 19],
        })

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sidebar-selections.wkb"
            self.window.save_workbook(path)
            map_workspace = self.window.open_stage_workspace("preview")
            dynamic_workspace = self.window.open_dynamic_workspace("preview")

            for index in range(map_workspace.wafer_list.topLevelItemCount()):
                item = map_workspace.wafer_list.topLevelItem(index)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if "W2" in item.text(0)
                    else Qt.CheckState.Unchecked,
                )
            for index in range(map_workspace.parameter_list.topLevelItemCount()):
                item = map_workspace.parameter_list.topLevelItem(index)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if item.text(0) == "CD_Bot"
                        else Qt.CheckState.Unchecked,
                    )

            for index in range(dynamic_workspace.wafer_list.topLevelItemCount()):
                item = dynamic_workspace.wafer_list.topLevelItem(index)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if "W2" in item.text(0)
                    else Qt.CheckState.Unchecked,
                )
            for index in range(
                dynamic_workspace.parameter_list.topLevelItemCount()
            ):
                item = dynamic_workspace.parameter_list.topLevelItem(index)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if item.text(0) == "SPA"
                        else Qt.CheckState.Unchecked,
                    )
            APP.processEvents()

            self.save_child_and_close(map_workspace)
            self.save_child_and_close(dynamic_workspace)
            map_workspace.deleteLater()
            dynamic_workspace.deleteLater()
            APP.processEvents()

            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                restored_map = reopened.open_stage_workspace("preview")
                restored_dynamic = reopened.open_dynamic_workspace("preview")

                self.assertEqual(restored_map.selection["metrics"], ["CD_Bot"])
                self.assertEqual(len(restored_map.selection["wafers"]), 1)
                self.assertIn("W2", restored_map.selection["wafers"][0])
                self.assertEqual(restored_dynamic.selection["metrics"], ["SPA"])
                self.assertEqual(len(restored_dynamic.selection["wafers"]), 1)
                self.assertIn("W2", restored_dynamic.selection["wafers"][0])
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_tem_map_starts_empty_and_saved_map_is_restored(self):
        class FakeWaferWorkspace:
            def __init__(self):
                self.model = SheetModel()

            def set_table(self, frame, source):
                self.model.load(frame)

            def show(self):
                pass

        self.window.close()
        self.window.deleteLater()
        self.window = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.match_type.setCurrentText("TEM")
        self.window.run_analysis()

        workspace = self.window.open_stage_workspace("preview")
        self.assertTrue(workspace.model.frame().empty)
        tem_map = pd.DataFrame({
            "Wafer ID": ["TEM-MAP", "TEM-MAP"],
            "FIELD X": [-1, 1],
            "FIELD Y": [0, 0],
            "CD_Bot": [201.0, 202.0],
            "SPA": [31.0, 32.0],
        })
        workspace.model.load(tem_map)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tem-map.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
            try:
                reopened.load_workbook(path)
                restored = reopened.open_stage_workspace("preview").model.frame()
                pd.testing.assert_frame_equal(
                    restored.astype(str), tem_map.astype(str)
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_pasting_fullmap_after_analysis_keeps_match_results_interactive(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        self.window.set_preview_frame(pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "CD_Bot": [4.0, 5.0],
            "SPA": [5.0, 6.0],
        }), "Preview clipboard")

        self.assertIsNotNone(self.window.workbook)
        self.assertIsNotNone(self.window.result)
        self.assertIn("SPA", self.window.plot_groups)
        self.assertTrue(
            self.window.plot_groups["SPA"]["plots"]["trend"].listDataItems()
        )

    def test_replacing_reference_keeps_raw_data_and_refreshes_mappings(self):
        self.window.set_reference_frame(self.reference(), "First Reference")
        self.window.set_raw_frame(self.raw(), "First Raw")
        self.assertTrue(self.window.analyze_button.isEnabled())

        replacement = self.reference().assign(**{"CD_Bot Reference": [13.0, 23.0, 33.0]})
        self.window.set_reference_frame(replacement, "Replacement Reference")

        pd.testing.assert_frame_equal(self.window.raw_frame, self.raw())
        self.assertTrue(self.window.raw_model.cells)
        self.assertTrue(self.window.analyze_button.isEnabled())

    def test_switching_preview_and_final_keeps_results_and_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window._run_analysis_clicked()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([480, 260, 900])
        APP.processEvents()
        sizes = tuple(self.window.setup_splitter.sizes()[:2])
        self.assertTrue(self.window.export_button.isEnabled())

        self.window.result_mode.setCurrentText("Final")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        # The last valid Preview stays visible until independent Final data arrives.
        self.assertEqual(self.window.result.result_mode, "preview")
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertEqual(self.window.summary_model.rowCount(), 2)
        self.assertEqual(tuple(self.window.setup_splitter.sizes()[:2]), sizes)
        self.assertFalse(self.window.reference_card.isHidden())
        self.assertFalse(self.window.raw_card.isHidden())
        self.assertFalse(self.window.raw_view.model().cells)
        self.assertFalse(self.window.mapping_card.isHidden())

        final_raw = self.raw().assign(CD_Bot=[11.0, 19.0, 31.0])
        self.window.set_raw_frame(final_raw, "Final clipboard")
        APP.processEvents()
        self.assertEqual(self.window.result.result_mode, "final")
        self.assertEqual(
            self.window.result.series("CD_Bot")["Raw"].tolist(),
            [11.0, 19.0, 31.0],
        )

        self.window.result_mode.setCurrentText("Preview")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(self.window.result.result_mode, "preview")
        self.assertFalse(self.window.raw_card.isHidden())
        self.assertEqual(
            self.window.raw_model.frame()["CD_Bot"].astype(float).tolist(),
            [1.0, 2.0, 3.0],
        )

        self.window.result_mode.setCurrentText("Final")
        APP.processEvents()
        self.assertEqual(
            self.window.final_raw_model.frame()["CD_Bot"].astype(float).tolist(),
            [11.0, 19.0, 31.0],
        )

    def test_results_panel_omits_the_mode_parameter_status_line(self):
        self.assertTrue(self.window.result_status.isHidden())

    def test_wkb_restores_independent_preview_and_final_raw_data(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Preview clipboard")
        self.window.result_mode.setCurrentText("Final")
        final_raw = self.raw().assign(CD_Bot=[11.0, 19.0, 31.0])
        self.window.set_raw_frame(final_raw, "Final clipboard")
        self.window.run_analysis()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "independent-modes.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                self.assertEqual(reopened.result_mode.currentText(), "Final")
                self.assertEqual(
                    reopened.raw_view.model().frame()["CD_Bot"].astype(float).tolist(),
                    [11.0, 19.0, 31.0],
                )
                reopened.result_mode.setCurrentText("Preview")
                APP.processEvents()
                self.assertEqual(
                    reopened.raw_view.model().frame()["CD_Bot"].astype(float).tolist(),
                    [1.0, 2.0, 3.0],
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_nova_shows_single_wafer_slope_and_r_squared_but_tem_does_not(self):
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD Reference": [3.0, 5.0, 7.0, 1.0, 4.0, 7.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.match_type.setCurrentText("NOVA")
        self.window.run_analysis()

        self.assertIsInstance(self.window.results_tabs, QTabWidget)
        self.assertEqual(self.window.results_tabs.count(), 2)
        self.assertEqual(self.window.results_tabs.tabText(0), "All parameter plots")
        self.assertEqual(self.window.results_tabs.tabText(1), "Single-wafer metrics")
        group = self.window.plot_groups["CD"]
        self.assertFalse(group["wafer_card"].isHidden())
        self.assertEqual(group["wafer_model"].rowCount(), 2)

        self.window.match_type.setCurrentText("TEM")
        self.window.run_analysis()
        self.assertTrue(self.window.plot_groups["CD"]["wafer_card"].isHidden())
    def test_exports_excel_and_separate_plot_images_after_analysis(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.set_preview_frame(self.raw().assign(**{
            "Wafer ID": ["P1", "P2", "P3"],
        }), "Preview clipboard")
        final = pd.DataFrame({
            "Wafer ID": ["F1", "F2", "F3"],
            "CD_Bot": [12.0, 22.0, 32.0],
            "SPA": [5.0, 7.0, 9.0],
        })
        self.window.set_final_frame(final, "Final clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            excel_path = Path(folder) / "result.xlsx"
            image_folder = Path(folder) / "images"
            self.window.export_excel(excel_path)
            images = self.window.save_plot_images(image_folder)

            with pd.ExcelFile(excel_path, engine="openpyxl") as book:
                self.assertEqual(book.sheet_names, [
                    "Summary", "Reference", "Raw Data", "Preview",
                    "Preview FullMap", "Final FullMap",
                ])
            preview = pd.read_excel(excel_path, sheet_name="Preview", engine="openpyxl")
            preview_fullmap = pd.read_excel(
                excel_path, sheet_name="Preview FullMap", engine="openpyxl"
            )
            final_fullmap = pd.read_excel(
                excel_path, sheet_name="Final FullMap", engine="openpyxl"
            )
            self.assertIn("CD_Bot | Evaluated Value", preview.columns)
            self.assertIn("SPA | Bias", preview.columns)
            self.assertEqual(preview_fullmap["CD_Bot"].tolist(), [12, 22, 32])
            pd.testing.assert_frame_equal(final_fullmap, final, check_dtype=False)
            self.assertTrue(images)
            self.assertTrue(all(path.exists() and path.suffix == ".png" for path in images))
            names = {path.name for path in images}
            self.assertIn("CD_Bot-bias.png", names)
            self.assertIn("CD_Bot-bias-percent.png", names)

    def test_match_image_export_captures_the_complete_widget_header(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.show()
        APP.processEvents()
        match_plot = self.window.plot_groups["CD_Bot"]["plots"]["match"]

        with tempfile.TemporaryDirectory() as folder:
            images = self.window.save_plot_images(folder)
            match_image = QImage(str(next(
                path for path in images if path.name == "CD_Bot-match.png"
            )))

        self.assertFalse(match_image.isNull())
        self.assertEqual(match_image.size(), match_plot.size())

    def test_default_registry_exposes_a_multi_instance_matching_tool(self):
        registry = create_default_registry()
        spec = registry.get("card_matching")
        first = registry.create("card_matching")
        second = registry.create("card_matching")
        try:
            self.assertEqual(spec.title, "Match Workbook")
            self.assertIsInstance(first, MatchingWindow)
            self.assertIsNot(first, second)
        finally:
            first.close()
            second.close()
            first.deleteLater()
            second.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()

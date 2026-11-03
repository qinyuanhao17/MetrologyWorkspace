"""Spectra Info pairs measured files to original Workbook source rows."""
from dataclasses import replace
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from tests.test_spectra_viewer import make_spectrum
from metrology_app.spectra_info import build_spectra_info
from tests.test_spectra_viewer import APP
from metrology_app.spectra_viewer import SpectraViewerWindow
from metrology_app.sme_spectra import LoadResult
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QTimer


class SpectraInfoTests(unittest.TestCase):
    def sources(self):
        a, b = make_spectrum(1), make_spectrum(2)
        a = replace(a, identity=replace(a.identity, timestamp="2026-04-08 11:32:09.026"))
        b = replace(b, identity=replace(b.identity, timestamp="2026-04-08 11:32:11.126"))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 2, "Lot ID": ["L1"] * 2, "PAD Name": ["P1"] * 2,
                            "Die Seq": [2, 1], "FIELD X": [-1, -1], "FIELD Y": [5, 5],
                            "Cur SME File Path": ["C:/old/b_20260408113211126.sme", "C:/old/a_20260408113209026.sme"]})
        return raw, (a, b)

    def test_original_row_order_sme_metadata_reference_columns_and_flag_position(self):
        raw, spectra = self.sources()
        result = build_spectra_info(raw, pd.DataFrame({"Ref A": ["8.100", "9.200"], "Ref B": ["3.400", "4.500"]}),
                                    spectra, checked_keys={s.key for s in spectra}, flags={spectra[0].key: -1})
        self.assertEqual(result.issues, ())
        self.assertEqual(result.source_rows, (0, 1))
        self.assertEqual(result.with_flags.columns.tolist(), ["Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq",
                         "Relative Column", "Relative Row", "Time", "Type", "Ref A", "Ref B", "Test Flag"])
        self.assertEqual(result.with_flags["Die Seq"].tolist(), [2, 1])
        self.assertEqual(result.with_flags["Relative Column"].tolist(), [-1, -1])
        self.assertEqual(result.with_flags["Relative Row"].tolist(), [5, 5])
        self.assertEqual(result.with_flags["Time"].tolist(), ["20260408113211126", "20260408113209026"])
        self.assertEqual(result.with_flags["Ref A"].tolist(), ["8.100", "9.200"])
        self.assertEqual(result.with_flags["Ref B"].tolist(), ["3.400", "4.500"])
        self.assertEqual(result.with_flags["Test Flag"].tolist(), [0, -1])
        self.assertEqual(result.with_flags["Type"].tolist(), ["Accuracy", "Accuracy"])
        self.assertNotIn("Test Flag", result.without_flags)

    def test_extra_or_ambiguous_checked_sources_and_timestamp_mismatches_are_reported(self):
        raw, spectra = self.sources()
        extra = make_spectrum(3, wafer="Extra")
        result = build_spectra_info(raw, pd.DataFrame(), (*spectra, extra), checked_keys={extra.key}, visible_keys={extra.key})
        self.assertTrue(any("Extra" in issue for issue in result.issues))
        raw.loc[0, "Cur SME File Path"] = "renamed_20260408113211127.sme"
        result = build_spectra_info(raw, pd.DataFrame(), spectra, checked_keys={s.key for s in spectra})
        self.assertTrue(any("timestamp" in issue.lower() for issue in result.issues))
        result = build_spectra_info(raw, pd.DataFrame(), spectra, checked_keys={s.key for s in spectra}, verify_timestamp=False)
        self.assertEqual(result.issues, ())
        duplicated = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
        result = build_spectra_info(duplicated, pd.DataFrame(), spectra, checked_keys={s.key for s in spectra}, verify_timestamp=False)
        self.assertTrue(any("ambiguous" in issue.lower() for issue in result.issues))

    def test_hidden_rows_never_enter_tables_but_hidden_checked_extras_still_report(self):
        raw, spectra = self.sources()
        extra = make_spectrum(3, wafer="Extra")
        result = build_spectra_info(raw, pd.DataFrame(), (*spectra, extra),
                                    checked_keys={s.key for s in spectra}, visible_keys={spectra[1].key})
        self.assertEqual(result.issues, ())
        self.assertEqual(result.with_flags["Die Seq"].tolist(), [2])
        self.assertEqual(result.source_rows, (0,))
        result = build_spectra_info(raw, pd.DataFrame(), (*spectra, extra),
                                    checked_keys={extra.key}, visible_keys=set())
        self.assertTrue(result.issues)


class SpectraInfoWorkflowTests(unittest.TestCase):
    def test_copy_wkb_editor_filters_do_not_hide_participating_info_rows(self):
        from metrology_app.selection_script import export_script
        from metrology_app.sme_spectra import file_metadata_dataframe
        raw, sources = SpectraInfoTests().sources()
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.set_spectra_info_source(lambda: (raw, pd.DataFrame()))
        frame = file_metadata_dataframe(sources).rename(columns=lambda c: f"Raw Data / {c}")
        view = {"filters": [[{"column": "Raw Data / Die Seq", "values": ["1"]}]],
                "row_bools": [[]], "show": "filtered", "hide_excluded": True, "search": "Die1"}
        viewer.set_workbook_selection_source(lambda: export_script(frame, {"checked": [1], **view}))
        self.assertTrue(viewer.copy_wkb_selection())
        result = viewer.spectra_info()
        self.assertEqual(result.with_flags["Die Seq"].tolist(), [2])
        self.assertEqual(result.source_rows, (0,))
        self.assertEqual(viewer._data_selection_view["filters"], view["filters"])
        self.assertEqual(viewer.spectra_info_button.objectName(), "primary")

    def test_similar_wafer_check_and_flag_actions_are_independent(self):
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        sources = tuple(replace(make_spectrum(die, wafer=wafer), x_mm=float(die) + (.399 if wafer == "Near" else .4 if wafer == "Edge" else 0))
                        for wafer in ("W1", "Near", "Edge") for die in (1, 2))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.set_spectrum_checks({s.key: True for s in sources})
        viewer.set_spectrum_checks({sources[1].key: False})
        viewer.set_test_flags({sources[0].key: 1, sources[3].key: -1, sources[4].key: -1})
        maps = viewer.open_wafer_map()
        actions = {a.text(): a for a in maps.build_selection_menu(("W1", "L1", "P1")).actions()}
        before = viewer.checked_spectra()
        actions["Apply Flag to Similar Wafer"].trigger()
        self.assertEqual(viewer.checked_spectra(), before)
        self.assertEqual(viewer.test_flags, {sources[0].key: 1, sources[2].key: 1, sources[4].key: -1})
        flags = dict(viewer.test_flags)
        actions["Apply Check To Similar Wafer"].trigger()
        self.assertEqual(viewer.test_flags, flags)
        self.assertEqual({s.key for s in viewer.checked_spectra()}, {sources[i].key for i in (0, 2, 4, 5)})

    def test_flag_editor_supports_values_grouping_and_safe_wheel_without_changing_live_state(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        from metrology_app.spectra_info_ui import TestFlagDialog
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        sources = (make_spectrum(1), make_spectrum(2, wafer="W2"))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        flags = TestFlagDialog(viewer)
        self.addCleanup(flags.close)
        flags.show()
        APP.processEvents()
        flags.add_flag_button.click()
        self.assertEqual(flags.flag_values(), [0, 1, -1, 2])
        next(a for a in flags.group_menu.actions() if a.text() == "Wafer ID").setChecked(False)
        self.assertEqual(flags.tree.topLevelItemCount(), 1)
        flags.batch_value.setCurrentIndex(flags.batch_value.findData(2))
        flags.assign_visible()
        combo = flags.combos[0][1]
        combo.setFocus()
        event = QWheelEvent(QPointF(combo.rect().center()), QPointF(combo.mapToGlobal(combo.rect().center())),
                            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(combo, event)
        self.assertEqual(combo.currentData(), 2)
        self.assertEqual(viewer.test_flags, {})
        flags.accept()
        viewer.set_test_flags(flags.assignments)
        self.assertEqual(viewer.test_flags, {s.key: 2 for s in sources})
        flags.values.setCurrentItem(flags.values.topLevelItem(3))
        flags.delete_flag_button.click()
        self.assertEqual(flags.flag_values(), [0, 1, -1])
        self.assertEqual(set(flags.assignments.values()), {0})

    def test_workbook_info_filters_copy_export_flags_and_spec_restore(self):
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.selection_script import export_script
        from metrology_app.sme_spectra import file_metadata_dataframe
        owner = MatchingWindow()
        owner.document.force_close = True
        self.addCleanup(owner.close)
        raw, sources = SpectraInfoTests().sources()
        owner.set_raw_frame(raw)
        owner.set_reference_frame(pd.DataFrame({"First": ["8.100", "9.200"], "Second": ["3.400", "4.500"]}))
        viewer = owner.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        self.assertTrue(viewer.spectra_info_button.isEnabled())
        self.assertTrue(viewer.verify_spectra_time_action.isChecked())
        self.assertIn(viewer.verify_spectra_time_action, viewer.options_menu.actions())
        frame = file_metadata_dataframe(sources).rename(columns=lambda c: f"Raw Data / {c}")
        script = export_script(frame, {"checked": [1], "filters": [[{"column": "Raw Data / Die Seq", "values": ["2"]}]],
                                       "row_bools": [[]], "show": "filtered", "hide_excluded": True})
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                dialog.apply_selection_script(script)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        viewer.data_selection_action.trigger()
        self.assertEqual(errors, [])
        info = viewer.open_spectra_info()
        self.assertFalse(info.problems)
        self.assertEqual(info.tabs.count(), 2)
        self.assertNotIn("Test Flag", info.table_frame())
        self.assertEqual(info.table_frame()["Die Seq"].tolist(), [2])
        self.assertEqual(info.result.source_rows, (0,))
        viewer.set_test_flags({sources[1].key: 1})
        QTest.qWait(20)
        def configure_flags():
            dialog = APP.activeModalWidget()
            try:
                dialog.add_flag_button.click()
                next(a for a in dialog.group_menu.actions() if a.text() == "Tool SN").setChecked(True)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, configure_flags)
        viewer.test_flag_action.trigger()
        self.assertEqual(errors, [])
        info.tabs.setCurrentIndex(1)
        self.assertEqual(info.table_frame()["Test Flag"].tolist(), [1])
        info.copy_button.click()
        copied = pd.read_csv(StringIO(APP.clipboard().text()), sep="\t", dtype=str)
        self.assertEqual(copied["Die Seq"].tolist(), ["2"])
        self.assertEqual(copied["Second"].tolist(), ["3.400"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "info.csv"
            info.export_csv(path)
            exported = pd.read_csv(path, dtype=str)
            self.assertEqual(exported["Time"].tolist(), ["\t20260408113211126"])
            self.assertEqual(exported["Test Flag"].tolist(), ["1"])
            viewer.verify_spectra_time_action.setChecked(False)
            saved = viewer.save_spec(Path(directory) / "flags.spec")
            restored = SpectraViewerWindow()
            restored.document.force_close = True
            self.addCleanup(restored.close)
            restored.load_workspace(saved)
            self.assertEqual(restored.test_flags, {sources[1].key: 1})
            self.assertEqual(restored.test_flag_values, [0, 1, -1, 2])
            self.assertEqual(restored.test_flag_grouping, ["wafer", "lot", "tool_sn", "pad"])
            self.assertFalse(restored.verify_spectra_time_action.isChecked())

    def test_info_blocks_export_for_extra_checked_spectra_and_flag_dialog_has_local_cancel(self):
        from metrology_app.spectra_info_ui import SpectraInfoWindow, TestFlagDialog
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        raw, sources = SpectraInfoTests().sources()
        extra = make_spectrum(3, wafer="Extra")
        viewer.apply_load_result(LoadResult((*sources, extra), ()), replace=True)
        viewer.check_all_spectra()
        viewer.set_spectra_info_source(lambda: (raw, pd.DataFrame()))
        info = SpectraInfoWindow(viewer)
        self.addCleanup(info.close)
        self.assertTrue(info.problems)
        self.assertFalse(info.export_button.isEnabled())
        self.assertFalse(info.copy_button.isEnabled())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.csv"
            with self.assertRaises(ValueError):
                info.export_csv(path)
            self.assertFalse(path.exists())
        flags = TestFlagDialog(viewer)
        self.addCleanup(flags.close)
        flags.batch_value.setCurrentIndex(flags.batch_value.findData(-1))
        flags.search.setText("W1")
        flags.assign_visible()
        flags.reject()
        self.assertEqual(viewer.test_flags, {})
        self.assertEqual(flags.assignments[sources[0].key], -1)
        self.assertNotIn(extra.key, flags.assignments)

    def test_die_map_sets_flags_without_replacing_maps_or_changing_checks(self):
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        sources = (make_spectrum(1), make_spectrum(2))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.set_spectrum_checks({sources[0].key: True})
        maps = viewer.open_wafer_map()
        QTest.qWait(100)
        plot = next(iter(maps.wafer_plots.values()))
        ranges = plot.plot.getViewBox().viewRange()
        viewer.select_spectrum_keys({sources[1].key})
        menu = maps.build_selection_menu(("W1", "L1", "P1"))
        flags = next(a.menu() for a in menu.actions() if a.text() == "Set Test Flag")
        next(a for a in flags.actions() if a.text() == "1").trigger()
        self.assertEqual(viewer.test_flags, {sources[1].key: 1})
        self.assertEqual(len(plot.flag_markers.points()), 1)
        self.assertEqual(plot.flag_markers.points()[0].brush().color().name(), "#15803d")
        viewer.select_spectrum_keys({sources[0].key})
        next(a for a in flags.actions() if a.text() == "-1").trigger()
        self.assertEqual(len(plot.flag_markers.points()), 2)
        self.assertEqual({p.brush().color().name() for p in plot.flag_markers.points()}, {"#15803d", "#dc2626"})
        from PyQt6.QtGui import QImage
        import numpy as np
        image = plot.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), dtype=np.uint8).reshape(image.height(), -1, 4)
        self.assertTrue(np.any(np.all(pixels[:, :, :3] == [21, 128, 61], axis=2)), "Green flag must be painted")
        self.assertTrue(np.any(np.all(pixels[:, :, :3] == [220, 38, 38], axis=2)), "Red flag must be painted")
        self.assertIs(next(iter(maps.wafer_plots.values())), plot)
        self.assertEqual(plot.plot.getViewBox().viewRange(), ranges)
        self.assertEqual(viewer.checked_spectra(), (sources[0],))
        next(a for a in flags.actions() if a.text() == "0 (Fallback)").trigger()
        self.assertEqual(viewer.test_flags, {sources[1].key: 1})


if __name__ == "__main__":
    unittest.main()

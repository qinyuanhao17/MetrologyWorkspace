"""Portable Match Workbook Spectra workflows, independent of source SME paths."""
from pathlib import Path
from dataclasses import replace
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from metrology_app.matching_window import MatchingWindow
from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_workbook import snapshot, restore
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests.test_spectra_viewer import APP, make_spectrum
from tests.test_sme_spectra import SAMPLE_ROOT, copy_verified_samples


class SpectraWorkbookTests(unittest.TestCase):
    def test_workbook_path_mode_and_missing_references_survive_save_without_embedding(self):
        from metrology_app.sme_spectra import load_folder
        from metrology_app.workspace_store import load_workspace
        owner, reopened = MatchingWindow(), MatchingWindow()
        owner.document.force_close = reopened.document.force_close = True
        self.addCleanup(owner.close)
        self.addCleanup(reopened.close)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_verified_samples(root / "sources")
            child = owner.open_spectra_workspace()
            child.apply_load_result(load_folder(root / "sources"), replace=True)
            child.check_all_spectra()
            flagged_key = child.catalog.spectra[0].key
            child.set_test_flags({flagged_key: -1})
            path = owner.save_workbook(root / "reference.mwkb")
            previous_size = path.stat().st_size
            child.spec_save_actions["paths"].trigger()
            self.assertTrue(child.spec_save_actions["paths"].isChecked())
            self.assertFalse(child.spec_save_actions["embedded"].isChecked())
            owner.save_workbook(path)
            self.assertLess(path.stat().st_size, previous_size)
            self.assertTrue(load_workspace(path).frames["spectra.preview.spectra"]["samples"].eq("").all())
            missing = child.catalog.spectra[0].path
            missing.rename(missing.with_suffix(".unavailable"))
            reopened.load_workbook(path)
            restored = reopened.open_spectra_workspace()
            self.assertEqual(len(restored.catalog.spectra), 41)
            self.assertEqual(len(restored._unavailable_paths), 1)
            self.assertTrue(any("unavailable" in issue.message for issue in restored.catalog.issues))
            draft = restored.workspace_snapshot()
            self.assertEqual(len(draft.frames["spectra"]), 42)
            self.assertEqual(len(draft.states["ui"]["checked"]), 42)
            self.assertEqual(restored.test_flags[flagged_key], -1)
            missing.with_suffix(".unavailable").rename(missing)
            restored.apply_load_result(load_folder(root / "sources"), replace=False)
            self.assertFalse(restored._unavailable_paths)
            self.assertEqual(len(restored.workspace_snapshot().frames["spectra"]), 42)
            self.assertEqual(len(restored.checked_spectra()), 42)

    def test_document_storage_work_keeps_gui_timers_running(self):
        from PyQt6.QtCore import QTimer
        from metrology_app.workspace_document import document_io
        window = SpectraViewerWindow()
        window.document.force_close = True
        self.addCleanup(window.close)
        ticks = []
        timer = QTimer(window, interval=10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        self.assertEqual(document_io(window, lambda: (time.sleep(.12), 42)[1], "Saving…"), 42)
        timer.stop()
        self.assertGreaterEqual(len(ticks), 3)

    def test_path_save_type_removes_embedded_samples_and_reloads_original_files(self):
        from metrology_app.sme_spectra import load_folder
        from metrology_app.workspace_store import load_workspace
        viewer, reopened = SpectraViewerWindow(), SpectraViewerWindow()
        viewer.document.force_close = reopened.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(reopened.close)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_verified_samples(root / "sources")
            viewer.apply_load_result(load_folder(root / "sources"), replace=True)
            viewer.check_all_spectra()
            expected = viewer.catalog.spectra
            path = viewer.save_spec(root / "reference.spec")
            embedded_size = path.stat().st_size
            viewer.set_spec_save_type("paths")
            viewer.save_spec(path)
            stored = load_workspace(path)
            self.assertTrue(stored.frames["spectra"]["samples"].eq("").all())
            self.assertLess(path.stat().st_size, embedded_size)
            reopened.load_workspace(path)
            self.assertEqual(reopened.spec_save_type, "paths")
            self.assertEqual([s.key for s in reopened.checked_spectra()], [s.key for s in expected])
            for original, loaded in zip(expected, reopened.catalog.spectra):
                np.testing.assert_array_equal(original.channels[0].numeric, loaded.channels[0].numeric)
            reopened.set_spec_save_type("embedded")
            reopened.save_spec(path)
            self.assertTrue(load_workspace(path).frames["spectra"]["samples"].str.len().gt(0).all())

    def test_data_selection_row_modes_follow_manual_spectrum_checks_outside_saved_filters(self):
        from PyQt6.QtCore import QTimer
        from metrology_app.selection_script import export_script
        from metrology_app.sme_spectra import file_metadata_dataframe
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        sources = (make_spectrum(1), make_spectrum(2, wafer="W2"), make_spectrum(3, wafer="W2"))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        filters = [[{"column": "Raw Data / Wafer ID", "values": ["W1"]}]]
        script = export_script(file_metadata_dataframe(sources).rename(columns=lambda c: f"Raw Data / {c}"),
                               {"checked": [0, 1, 2], "filters": filters, "row_bools": [[]],
                                "show": "filtered", "hide_excluded": True})
        errors = []

        def configure():
            dialog = APP.activeModalWidget()
            try:
                dialog.apply_selection_script(script)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, configure)
        viewer.data_selection_action.trigger()
        self.assertEqual(errors, [])
        viewer.unfold_tree()
        QTest.qWait(30)
        viewer.spectrum_items[sources[1].key].setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual([s.key for s in viewer.checked_spectra()], [sources[0].key, sources[2].key])

        def inspect():
            dialog = APP.activeModalWidget()
            try:
                for mode, rows in (("all", [0, 1, 2]), ("filtered", [0]),
                                   ("checked", [0, 2]), ("unchecked", [1])):
                    dialog.show_rows.setCurrentIndex(dialog.show_rows.findData(mode))
                    self.assertEqual(dialog.model.rows, rows, mode)
                self.assertEqual(dialog.filter_groups, filters)
                self.assertTrue(dialog.hide_excluded.isChecked())
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, inspect)
        viewer.data_selection_action.trigger()
        self.assertEqual(errors, [])
        self.assertEqual([s.key for s in viewer.checked_spectra()], [sources[0].key, sources[2].key])

    def test_managed_titles_follow_workbook_save_as_and_standalone_spec_names(self):
        owner = MatchingWindow()
        owner.document.force_close = True
        try:
            child = owner.open_spectra_workspace()
            child.apply_load_result(LoadResult((make_spectrum(1),), ()), replace=True)
            child.document.refresh_identity()
            self.assertNotIn("Untitled", child.windowTitle())
            self.assertIn("Unsaved Match Workbook", child.windowTitle())
            with tempfile.TemporaryDirectory() as folder:
                for name in ("first.mwkb", "renamed.mwkb"):
                    owner.save_workbook(Path(folder) / name)
                    self.assertIn(name, child.windowTitle())
                    self.assertNotIn("Untitled", child.windowTitle())
                    self.assertFalse(child.isWindowModified())
                    child.check_all_spectra()
                    child.document.refresh_identity()
                child.save_spec(Path(folder) / "independent.spec")
                self.assertIn("independent.spec", child.windowTitle())
                self.assertFalse(child.isWindowModified())
                child.uncheck_all_spectra()
                child.document.refresh_identity()
                self.assertTrue(child.isWindowModified())
                owner.save_workbook(Path(folder) / "renamed.mwkb")
                self.assertIn("independent.spec", child.windowTitle())
                self.assertTrue(child.isWindowModified())
        finally:
            owner.close()

    def test_copy_wkb_selection_updates_script_view_once_without_changing_parent(self):
        from copy import deepcopy
        from metrology_app.match_groups import row_ids
        owner, standalone = MatchingWindow(), SpectraViewerWindow()
        owner.document.force_close = standalone.document.force_close = True
        try:
            raw = pd.DataFrame({"Wafer ID": ["W1", "W1"], "Lot ID": ["L1"] * 2,
                                "PAD Name": ["P1"] * 2, "Die Seq": ["001", "002"],
                                "Cur SME File Path": ["C:/old/one.sme", "C:/old/two.sme"]})
            owner.set_raw_frame(raw)
            owner.set_reference_frame(pd.DataFrame({"CD Reference": ["1.200", "2.300"]}))
            selection = {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(owner.raw_frame))],
                         "excluded": ["1"],
                         "view_filter_groups": [[{"column": "Reference / CD Reference", "minimum": 2}],
                                                [{"column": "Raw Data / Wafer ID", "values": ["W1"]}]],
                         "view_filter_row_bools": [[], []], "view_filter_group_bools": ["or"],
                         "view_show": "filtered", "view_search": "W", "hide_excluded": True}
            for state in (owner.group_controls.state, owner.group_controls.state["applied"]):
                state["data_selection"] = deepcopy(selection)
            child = owner.open_spectra_workspace()
            first, second, other = make_spectrum(1), make_spectrum(2), make_spectrum(1, wafer="Other")
            child.apply_load_result(LoadResult((second, other, first), ()), replace=True)
            child.check_all_spectra()
            child.select_spectrum_keys({second.key})
            self.assertFalse(standalone.copy_wkb_selection_action.isEnabled())
            action = next(a for a in child.data_menu.actions() if a.text() == "Copy WKB Selection")
            self.assertTrue(action.isEnabled())
            action.trigger()
            self.assertEqual({s.key for s in child.checked_spectra()}, {first.key, other.key})
            self.assertEqual(child._selected_keys, {second.key})
            from metrology_app.selection_script import selection_view
            for key, value in selection_view(selection).items():
                self.assertEqual(child._data_selection_view[key], value)
            self.assertTrue(child._data_selection_view["context"])
            self.assertEqual(owner.group_controls.state["data_selection"], selection)
            for state in (owner.group_controls.state, owner.group_controls.state["applied"]):
                state["data_selection"]["excluded"] = []
            APP.processEvents()
            self.assertEqual({s.key for s in child.checked_spectra()}, {first.key, other.key})
            action.trigger()
            self.assertEqual({s.key for s in child.checked_spectra()}, {first.key, second.key, other.key})
            child.uncheck_all_spectra()
            self.assertEqual(owner.group_controls.state["data_selection"]["excluded"], [])
            with tempfile.TemporaryDirectory() as folder:
                saved = child.save_spec(Path(folder) / "copied-filter.spec")
                standalone.load_workspace(saved)
                self.assertEqual(standalone._data_selection_view, child._data_selection_view)
        finally:
            owner.close()
            standalone.close()

    def test_escape_from_export_recovery_cancels_without_leaving_a_waiting_worker(self):
        viewer = SpectraViewerWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                source = replace(make_spectrum(1), path=root / "missing.sme")
                viewer.apply_load_result(LoadResult((source,), ()), replace=True)
                viewer.check_all_spectra()
                viewer.export_checked_spectra(root / "output")
                dialog = viewer.export_dialog
                deadline = time.monotonic() + 3
                while not dialog.retry_button.isVisible() and time.monotonic() < deadline:
                    QTest.qWait(10)
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
                while viewer._exporter is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(viewer._exporter)
                self.assertTrue(dialog.report["cancelled"])
                self.assertIn("Export Failed×", dialog.summary.toPlainText())
        finally:
            viewer.document.force_close = True
            viewer.close()

    def test_export_dialog_retries_and_skips_missing_originals_then_lists_unexported_paths(self):
        viewer = SpectraViewerWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                available, retry, skip = (root / name for name in ("available.sme", "retry.sme", "skip.sme"))
                available.write_bytes(b"original SME bytes")
                spectra = tuple(replace(make_spectrum(i), path=path, key=str(path))
                                for i, path in enumerate((available, retry, skip), 1))
                viewer.apply_load_result(LoadResult(spectra, ()), replace=True)
                viewer.check_all_spectra()
                viewer.export_checked_spectra(root / "output")
                dialog = viewer.export_dialog
                deadline = time.monotonic() + 5
                while not dialog.retry_button.isVisible() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertTrue(dialog.isVisible())
                self.assertIn("retry.sme", dialog.issue_label.text())
                retry.write_bytes(available.read_bytes())
                QTest.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
                while "skip.sme" not in dialog.issue_label.text() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIn("skip.sme", dialog.issue_label.text())
                QTest.mouseClick(dialog.skip_button, Qt.MouseButton.LeftButton)
                while viewer._exporter is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(viewer._exporter)
                self.assertEqual(len(list((root / "output").rglob("*.sme"))), 2)
                self.assertEqual([issue[0] for issue in dialog.report["skipped"]], [str(skip)])
                self.assertIn(str(skip), dialog.summary.toPlainText())
                self.assertIn("Exported 2", viewer.status.text())
                self.assertIn("Export Failed×", dialog.status_label.text())
                self.assertIn("Export Failed×", dialog.summary.toPlainText())
        finally:
            viewer.document.force_close = True
            viewer.close()

    def test_context_export_copies_only_checked_sme_in_original_folders(self):
        from metrology_app.sme_spectra import load_folder
        viewer = SpectraViewerWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = copy_verified_samples(Path(folder) / "source").resolve()
                result = load_folder(root)
                viewer.apply_load_result(result, replace=True)
                viewer.select_spectrum_keys({result.spectra[0].key, result.spectra[-1].key})
                viewer.check_selected_spectra()
                target = Path(folder) / "exported"
                action = next(a for a in viewer.build_tree_menu().actions() if a.text() == "Export Checked Spectra…")
                with patch("metrology_app.spectra_viewer.QFileDialog.getExistingDirectory", return_value=str(target)):
                    action.trigger()
                deadline = time.monotonic() + 10
                while viewer._exporter is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(viewer._exporter)
                files = list(target.rglob("*.sme"))
                self.assertEqual(len(files), 2)
                for source in (result.spectra[0], result.spectra[-1]):
                    output = target / root.name / source.path.relative_to(root)
                    self.assertEqual(output.read_bytes(), source.path.read_bytes())
                self.assertEqual(len(load_folder(target).spectra), 2)
                self.assertIn("Export Succeeded√", viewer.export_dialog.status_label.text())
                self.assertIn("Export Succeeded√", viewer.export_dialog.summary.toPlainText())
        finally:
            viewer.document.force_close = True
            viewer.close()

    def test_export_collision_reports_failure_and_preserves_the_original_export(self):
        viewer = SpectraViewerWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                source = root / "measured.sme"
                source.write_bytes(b"original SME bytes")
                viewer.apply_load_result(LoadResult((replace(make_spectrum(1), path=source),), ()), replace=True)
                viewer.check_all_spectra()
                for outcome in ("Export Succeeded√", "Export Failed×"):
                    viewer.export_checked_spectra(root / "export")
                    deadline = time.monotonic() + 3
                    while viewer._exporter is not None and time.monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertIsNone(viewer._exporter)
                    self.assertIn(outcome, viewer.export_dialog.status_label.text())
                    self.assertIn(outcome, viewer.export_dialog.summary.toPlainText())
                    self.assertIn(outcome, viewer.status.text())
                    marker = viewer.export_dialog.summary.document().find(outcome).charFormat()
                    self.assertGreaterEqual(marker.fontWeight(), QFont.Weight.Bold)
                    color = marker.foreground().color()
                    self.assertTrue(color.green() > color.red() if "Succeeded" in outcome else color.red() > color.green())
                copied = list((root / "export").rglob("*.sme"))
                self.assertEqual(len(copied), 1)
                self.assertEqual(copied[0].read_bytes(), source.read_bytes())
        finally:
            viewer.document.force_close = True
            viewer.close()

    def test_spectra_data_selection_updates_checks_and_survives_spec_save(self):
        viewer = SpectraViewerWindow()
        reopened = SpectraViewerWindow()
        try:
            sources = (make_spectrum(1), make_spectrum(2))
            viewer.apply_load_result(LoadResult(sources, ()), replace=True)
            viewer.check_all_spectra()
            viewer.unfold_tree()
            QTest.qWait(30)
            errors = []
            def choose():
                dialog = APP.activeModalWidget()
                try:
                    self.assertEqual(len(dialog.model.frame), 2)
                    dialog.search.setText("Die1.sme")
                    dialog.check_visible(False)
                    dialog.hide_excluded.setChecked(True)
                    dialog.accept()
                except Exception as error:
                    errors.append(error)
                    dialog.reject()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, choose)
            viewer.data_selection_action.trigger()
            self.assertEqual(errors, [])
            self.assertEqual(viewer.checked_spectra(), (sources[1],))
            self.assertTrue(viewer.spectrum_items[sources[0].key].isHidden())
            self.assertFalse(viewer.spectrum_items[sources[1].key].isHidden())
            with tempfile.TemporaryDirectory() as folder:
                path = viewer.save_spec(Path(folder) / "selection.spec")
                reopened.load_workspace(path)
            self.assertEqual([s.key for s in reopened.checked_spectra()], [sources[1].key])
            self.assertEqual(reopened.workspace_snapshot().states["ui"]["data_selection"]["search"], "Die1.sme")
        finally:
            viewer.document.force_close = reopened.document.force_close = True
            viewer.close()
            reopened.close()

    def test_workbook_and_shell_viewers_use_the_same_light_and_dark_styles(self):
        from metrology_app.shell import MainWindow
        from metrology_app.settings import get_settings, save_settings, theme_stylesheet
        from metrology_app.appearance import set_theme_palette
        original_palette = APP.palette()
        original_settings = get_settings()
        try:
            for theme in ("light", "dark"):
                with self.subTest(theme=theme):
                    save_settings({"theme": theme})
                    set_theme_palette(theme)
                    shell = MainWindow()
                    try:
                        standalone = shell.open_component("spectra_viewer")
                        owner = shell.open_component("card_matching")
                        child = owner.open_spectra_workspace()
                        QTest.qWait(20)
                        self.assertEqual(child.styleSheet(), theme_stylesheet(theme))
                        self.assertEqual(child.styleSheet(), standalone.styleSheet())
                        self.assertEqual(child.open_map_button.sizeHint(), standalone.open_map_button.sizeHint())
                        self.assertEqual(child.group_by_combo.font(), standalone.group_by_combo.font())
                        self.assertTrue(child.save_spec_action.shortcut().isEmpty())
                        switched = "dark" if theme == "light" else "light"
                        save_settings({"theme": switched})
                        shell.apply_settings()
                        QTest.qWait(20)
                        self.assertEqual(child.styleSheet(), theme_stylesheet(switched))
                        self.assertEqual(child.styleSheet(), standalone.styleSheet())
                    finally:
                        for instances in shell.loaded_components.values():
                            for window in instances:
                                window.document.force_close = True
                        shell.close()
                        APP.processEvents()
        finally:
            save_settings(original_settings)
            APP.setPalette(original_palette)

    def test_managed_save_shortcuts_target_workbook_and_standalone_targets_spec(self):
        owner, standalone = MatchingWindow(), SpectraViewerWindow()
        try:
            child = owner.open_spectra_workspace()
            self.assertTrue(child.save_spec_action.shortcut().isEmpty())
            self.assertTrue(child.save_spec_as_action.shortcut().isEmpty())
            self.assertEqual(standalone.save_spec_action.shortcut().toString(), "Ctrl+S")
            self.assertEqual(standalone.save_spec_as_action.shortcut().toString(), "Ctrl+Shift+S")
            child.show()
            child.activateWindow()
            child.setFocus()
            QTest.qWait(30)
            with patch.object(owner, "save_wkb") as save, patch.object(owner, "save_wkb_dialog") as save_as:
                QTest.keyClick(child, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
                QTest.keyClick(child, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(save.call_count, 1)
                self.assertEqual(save_as.call_count, 1)
        finally:
            owner.document.force_close = standalone.document.force_close = True
            owner.close()
            standalone.close()
            APP.processEvents()

    def test_showing_an_empty_viewer_does_not_create_unsaved_changes(self):
        viewer = SpectraViewerWindow()
        try:
            viewer.show()
            QTest.qWait(30)
            self.assertFalse(viewer.document.is_dirty())
        finally:
            viewer.document.force_close = True
            viewer.close()

    def test_spec_uses_standard_shell_routing_and_revision_protection(self):
        from metrology_app.shell import MainWindow
        shell = MainWindow()
        first = SpectraViewerWindow()
        try:
            first.apply_load_result(LoadResult((make_spectrum(1),), ()), replace=True)
            with tempfile.TemporaryDirectory() as directory:
                path = first.save_spec(Path(directory) / "independent.spec")
                second = shell.load_path(path)
                self.assertIsInstance(second, SpectraViewerWindow)
                first.check_all_spectra()
                first.save_spec()
                second.check_all_spectra()
                with self.assertRaisesRegex(ValueError, "changed in another"):
                    second.save_spec()
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                    self.assertFalse(second.close())
                second.document.force_close = True
        finally:
            first.document.force_close = True
            first.close()
            shell.close()
            APP.processEvents()

    def test_invalid_spec_settings_do_not_replace_current_spectra(self):
        from metrology_app.workspace_store import save_workspace
        viewer, other = SpectraViewerWindow(), SpectraViewerWindow()
        try:
            original = make_spectrum(1)
            viewer.apply_load_result(LoadResult((original,), ()), replace=True)
            other.apply_load_result(LoadResult((make_spectrum(2, wafer="Other"),), ()), replace=True)
            invalid = snapshot(other)
            invalid.states["ui"]["analysis"] = "invalid-mode"
            with tempfile.TemporaryDirectory() as directory:
                path = save_workspace(Path(directory) / "invalid.spec", invalid)
                with self.assertRaises(ValueError):
                    viewer.load_workspace(path)
                self.assertEqual(viewer.catalog.spectra[0].key, original.key)
        finally:
            viewer.close()
            other.close()

    def test_child_can_save_and_open_spec_without_saving_its_parent(self):
        owner, restored = MatchingWindow(), SpectraViewerWindow()
        try:
            child = owner.open_spectra_workspace()
            source = make_spectrum(1)
            child.apply_load_result(LoadResult((source,), ()), replace=True)
            child.check_all_spectra()
            child.set_baseline(source.key)
            with tempfile.TemporaryDirectory() as directory:
                saved = child.save_spec(Path(directory) / "spectra")
                self.assertEqual(saved.suffix, ".spec")
                self.assertIsNone(owner.document.path)
                self.assertTrue(owner.document.is_dirty())
                restored.load_workspace(saved)
                self.assertEqual(restored._checked_keys, {source.key})
                self.assertEqual(restored._baseline_key, source.key)
                self.assertEqual(restored.analysis_mode, "residual")
                np.testing.assert_array_equal(restored.catalog.spectra[0].channels[0].numeric, source.channels[0].numeric)
                self.assertFalse(restored.document.is_dirty())
        finally:
            owner.document.force_close = True
            owner.close()
            restored.close()
            APP.processEvents()

    @unittest.skipUnless(SAMPLE_ROOT.is_dir(), "Original mixed-instrument samples unavailable")
    def test_managed_loading_embeds_all_instruments_and_survives_source_removal(self):
        owner, reopened = MatchingWindow(), MatchingWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child = owner.open_spectra_workspace()
                child.start_loading(copy_verified_samples(root / "inputs"), replace=True)
                deadline = time.monotonic() + 20
                while child._loader is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(child._loader)
                self.assertEqual(len(child.catalog.spectra), 42)
                expected = {s.key: s for s in child.catalog.spectra}
                path = root / "all-instruments.mwkb"
                owner.save_workbook(path)
                import shutil
                temporary_inputs = (root / "inputs").resolve()
                self.assertTrue(temporary_inputs.is_relative_to(root.resolve()))
                shutil.rmtree(temporary_inputs)
                reopened.load_workbook(path)
                restored = reopened.open_spectra_workspace()
                self.assertEqual(len(restored.catalog.spectra), 42)
                for actual in restored.catalog.spectra:
                    source = expected[actual.key]
                    self.assertEqual(actual.identity, source.identity)
                    self.assertEqual(len(actual.channels), len(source.channels))
                    for a, b in zip(actual.channels, source.channels):
                        np.testing.assert_array_equal(a.numeric, b.numeric)
                        self.assertEqual(a.key, b.key)
        finally:
            owner.document.force_close = reopened.document.force_close = True
            owner.close()
            reopened.close()
            APP.processEvents()

    def test_embedded_spectra_round_trip_preserves_samples_and_view_choices(self):
        viewer, restored = SpectraViewerWindow(), SpectraViewerWindow()
        try:
            sources = (make_spectrum(1), make_spectrum(2, wafer="W2"))
            viewer.apply_load_result(LoadResult(sources, ()), replace=True)
            viewer.check_all_spectra()
            viewer.set_color_mode("sme")
            viewer.set_baseline(sources[0].key)
            viewer.select_spectrum_keys({sources[1].key})
            key = viewer.plot_panels["S"].groups[0].key
            viewer.toggle_channel(key)
            viewer.plot_panels["psi_delta"].secondary.setYRange(-50, 75, padding=0)
            draft = snapshot(viewer)
            restore(restored, draft)
            self.assertEqual(restored._checked_keys, viewer._checked_keys)
            self.assertEqual(restored._selected_keys, viewer._selected_keys)
            self.assertEqual(restored._baseline_key, viewer._baseline_key)
            self.assertEqual(restored.analysis_mode, "residual")
            self.assertEqual(restored.color_mode, "sme")
            self.assertEqual(restored._hidden_channel_keys, viewer._hidden_channel_keys)
            self.assertEqual(restored.plot_panels["psi_delta"].secondary.viewRange()[1], [-50, 75])
            for a, b in zip(viewer.catalog.spectra, restored.catalog.spectra):
                self.assertEqual(a.identity, b.identity)
                self.assertEqual(a.key, b.key)
                np.testing.assert_array_equal(a.channels[0].numeric, b.channels[0].numeric)
                np.testing.assert_array_equal(a.channels[0].wavelength, b.channels[0].wavelength)
        finally:
            viewer.close()
            restored.close()

    def test_match_save_reopen_and_closed_child_restore_without_sme_files(self):
        owner, reopened = MatchingWindow(), MatchingWindow()
        try:
            child = owner.open_spectra_workspace()
            source = make_spectrum(1)  # fixture's original SME path does not exist
            child.apply_load_result(LoadResult((source,), ()), replace=True)
            child.check_all_spectra()
            child.close()
            APP.processEvents()
            child = owner.open_spectra_workspace()
            self.assertEqual(len(child.catalog.spectra), 1)
            self.assertEqual(child._checked_keys, {source.key})
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "spectra.mwkb"
                owner.save_workbook(path)
                self.assertFalse(owner.document.is_dirty())
                reopened.load_workbook(path)
                restored = reopened.open_spectra_workspace()
                self.assertEqual(restored.catalog.spectra[0].identity, source.identity)
                np.testing.assert_array_equal(restored.catalog.spectra[0].channels[0].numeric, source.channels[0].numeric)
                self.assertEqual(restored._checked_keys, {source.key})
                self.assertTrue(reopened.spectra_button.isEnabled())
                QTest.qWait(40)
                self.assertFalse(reopened.document.is_dirty())
                restored.uncheck_all_spectra()
                self.assertTrue(reopened.document.is_dirty())
        finally:
            owner.document.force_close = reopened.document.force_close = True
            owner.close()
            reopened.close()
            APP.processEvents()

    def test_delete_spectra_window_keeps_other_child_and_dynamic_selections(self):
        owner = MatchingWindow()
        try:
            a = owner.open_spectra_workspace()
            scope = "spectra." + "a" * 32 + ".preview"
            owner._workspace_states[scope] = {"window": {"name": "Second", "checked": True}}
            b = owner.open_spectra_workspace(scope=scope)
            owner._dynamic_selection_states["preview"] = {"sentinel": True}
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                owner._delete_analysis_window("spectra.preview")
            self.assertNotIn("spectra.preview", owner._spectra_windows)
            self.assertIs(owner._spectra_windows[scope], b)
            self.assertEqual(owner._dynamic_selection_states["preview"], {"sentinel": True})
        finally:
            owner.document.force_close = True
            owner.close()
            APP.processEvents()

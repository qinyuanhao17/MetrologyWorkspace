"""Portable Match Workbook Spectra workflows, independent of source SME paths."""
from pathlib import Path
from dataclasses import replace
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from metrology_app.matching_window import MatchingWindow
from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_workbook import snapshot, restore
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests.test_spectra_viewer import APP, make_spectrum
from tests.test_sme_spectra import SAMPLE_ROOT, copy_verified_samples


class SpectraWorkbookTests(unittest.TestCase):
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

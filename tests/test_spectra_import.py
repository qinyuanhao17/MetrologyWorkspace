"""Compression preferences and all-or-nothing background spectrum imports."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, current_thread, enumerate as threads
from time import monotonic
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from metrology_app import spectra_workbook
from metrology_app.settings import SETTINGS_PATH, load_settings, save_settings
from metrology_app.sme_spectra import EncryptedSME, LoadResult, load_folders
from metrology_app.spectra_viewer import SpectraLoadThread, SpectraViewerWindow
from tests.test_spectra_viewer import make_spectrum


class SpectraImportTests(unittest.TestCase):
    def viewer(self):
        window = SpectraViewerWindow()
        window.document.force_close = True
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        return window

    def wait_for_load(self, viewer):
        deadline = monotonic() + 10
        while viewer._loader is not None and monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(viewer._loader)
        self.assertFalse(any(thread.name.startswith("sme-embed") for thread in threads()))

    def test_limits_and_preferences_follow_current_cpu_count(self):
        choose = spectra_workbook.import_compression_threads
        for cpus, automatic, ceiling in ((None, 1, 0), (1, 1, 0), (2, 2, 2),
                                         (15, 14, 14), (16, 16, 16), (24, 24, 24)):
            with self.subTest(cpus=cpus):
                self.assertEqual(choose(cpus), ("auto", automatic, tuple(range(2, ceiling + 1, 2))))
                for invalid in (3, 26, True, "4"):
                    self.assertEqual(choose(cpus, invalid), choose(cpus))
        self.assertEqual(choose(15, 12)[:2], (12, 12))
        self.assertEqual([spectra_workbook.compression_workers(6, count) for count in range(8)],
                         [0, 1, 2, 2, 4, 4, 6, 6])
        self.assertEqual(spectra_workbook.compression_workers(1, 7), 1)

    def test_manual_option_is_saved_and_restored_with_fallback(self):
        self.addCleanup(load_settings, SETTINGS_PATH)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "prefs.yaml"
            load_settings(path)
            with patch("metrology_app.spectra_viewer.os.cpu_count", return_value=24), \
                    patch("metrology_app.spectra_viewer.save_settings", side_effect=lambda data: save_settings(data, path)):
                viewer = self.viewer()
                combo = viewer.compression_threads_combo
                self.assertEqual(combo.currentText(), "Auto (24 threads)")
                self.assertEqual([combo.itemData(i) for i in range(1, combo.count())], list(range(2, 25, 2)))
                combo.activated.emit(combo.findData(20))
                first_import = SpectraLoadThread(folder, viewer)
                load_settings(path)
                self.assertEqual(self.viewer().compression_threads_combo.currentData(), 20)
                combo.activated.emit(combo.findData("auto"))
                self.assertEqual(first_import.compression_threads, 20)
                self.assertEqual(SpectraLoadThread(folder, viewer).compression_threads, 24)
                combo.activated.emit(combo.findData(20))
            with patch("metrology_app.spectra_viewer.os.cpu_count", return_value=15):
                self.assertEqual(self.viewer().compression_threads_combo.currentText(), "Auto (14 threads)")
            with patch("metrology_app.spectra_viewer.os.cpu_count", return_value=None):
                combo = self.viewer().compression_threads_combo
                self.assertEqual((combo.count(), combo.currentText()), (1, "Auto (1 thread)"))

    def test_serial_parallel_records_and_saved_spectrum_tables_are_identical(self):
        samples = tuple(make_spectrum(index) for index in range(1, 7))
        expected = spectra_workbook.encode_sources(samples)
        progressed = []
        parallel = spectra_workbook.encode_sources(samples, workers=4, progress=lambda *args: progressed.append(args))
        self.assertEqual(list(parallel.items()), list(expected.items()))
        self.assertEqual(progressed, [(index, len(samples)) for index in range(len(samples) + 1)])
        for count in (0, 1):
            with patch.object(spectra_workbook, "ThreadPoolExecutor") as pool:
                self.assertEqual(spectra_workbook.encode_sources(samples[:count], workers=4),
                                 dict(list(expected.items())[:count]))
                pool.assert_not_called()
        window, reopened = self.viewer(), self.viewer()
        with TemporaryDirectory() as folder:
            with patch("metrology_app.spectra_viewer.load_folders", return_value=LoadResult(samples, ())):
                window.start_loading(folder, replace=True)
                self.wait_for_load(window)
            path = window.save_spec(Path(folder) / "embedded.spec")
            reopened.load_workspace(path)
            pd.testing.assert_frame_equal(window.workspace_snapshot().frames["spectra"],
                                          reopened.workspace_snapshot().frames["spectra"])
        from metrology_app.matching_window import MatchingWindow
        owner, restored_owner = MatchingWindow(), MatchingWindow()
        for book in (owner, restored_owner):
            book.document.force_close = True
            self.addCleanup(book.deleteLater)
            self.addCleanup(book.close)
        with TemporaryDirectory() as folder:
            managed = owner.open_spectra_workspace()
            with patch("metrology_app.spectra_viewer.load_folders", return_value=LoadResult(samples, ())):
                managed.start_loading(folder, replace=True)
                self.wait_for_load(managed)
            saved = owner.save_workbook(Path(folder) / "embedded.mwkb")
            restored_owner.load_workbook(saved)
            restored_managed = restored_owner.open_spectra_workspace()
            pd.testing.assert_frame_equal(managed.workspace_snapshot().frames["spectra"],
                                          restored_managed.workspace_snapshot().frames["spectra"])

    def test_paths_only_and_distinct_preparation_progress(self):
        window = self.viewer()
        sources = (make_spectrum(1), make_spectrum(2))

        def read(_folders, *, progress, cancelled, workers):
            progress(0, 2, "Scanning")
            progress(2, 2, "Read files")
            return LoadResult(sources, ())

        with TemporaryDirectory() as folder, patch("metrology_app.spectra_viewer.load_folders", side_effect=read):
            window.set_spec_save_type("paths")
            with patch.object(spectra_workbook, "encode_sources", wraps=spectra_workbook.encode_sources) as encode:
                window.start_loading(folder, replace=True)
                self.wait_for_load(window)
                encode.assert_not_called()
            self.assertEqual(len(window.catalog.spectra), 2)
            window.set_spec_save_type("embedded")
            with patch.object(window, "_show_progress", wraps=window._show_progress) as reading, \
                    patch.object(window, "_show_preparation_progress", wraps=window._show_preparation_progress) as preparing:
                window.start_loading(folder, replace=False)
                self.wait_for_load(window)
                self.assertEqual(reading.call_args_list[-1].args, (2, 2, "Read files"))
                self.assertEqual([call.args for call in preparing.call_args_list], [(0, 2), (2, 2)])

    def test_parallel_reads_preserve_order_and_stop_submitting_on_cancel(self):
        stopped = Event()
        started = []
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for number in range(1, 9):
                (root / f"{number}.sme").touch()

            def read(path):
                number = int(path.stem)
                started.append(number)
                if number == 3:
                    raise EncryptedSME("encrypted")
                return make_spectrum(number)

            with patch("metrology_app.sme_spectra.parse_sme_file", side_effect=read):
                sequential = load_folders((root,))
                parallel = load_folders((root,), workers=4)
                self.assertEqual([item.key for item in parallel.spectra],
                                 [item.key for item in sequential.spectra])
                self.assertEqual(parallel.issues, sequential.issues)
                started.clear()
                def stop_after_first(done, *_):
                    if done == 1:
                        stopped.set()

                result = load_folders((root,), workers=4, cancelled=stopped.is_set,
                                      progress=stop_after_first)
            self.assertTrue(result.cancelled)
            self.assertLessEqual(len(started), 4)
            self.assertFalse(any(thread.name.startswith("sme-read") for thread in threads()))

    def test_cancel_stops_submission_and_drains_in_flight_jobs(self):
        sources = tuple(make_spectrum(index) for index in range(12))
        cancelled = Event()
        started = []
        original = spectra_workbook._encode_source

        def measured(source):
            started.append((source.key, current_thread().name))
            return original(source)

        with patch.object(spectra_workbook, "_encode_source", side_effect=measured):
            result = spectra_workbook.encode_sources(
                sources, workers=2, cancelled=cancelled.is_set,
                progress=lambda done, _total: cancelled.set() if done == 1 else None)
        self.assertEqual(result, {})
        self.assertLessEqual(len(started), 2)
        self.assertTrue(all(name.startswith("sme-embed") for _, name in started))
        self.assertFalse(any(thread.name.startswith("sme-embed") for thread in threads()))

    def test_failure_and_cancellation_leave_existing_viewer_batch_untouched(self):
        window = self.viewer()
        window.apply_load_result(LoadResult((make_spectrum(1),), ()), replace=True)
        previous = window.catalog.spectra
        cache = window.workspace_snapshot().frames["spectra"]
        incoming = LoadResult(tuple(make_spectrum(index) for index in range(2, 8)), ())
        with TemporaryDirectory() as folder, \
                patch("metrology_app.spectra_viewer.load_folders", return_value=LoadResult((), ())), \
                patch.object(spectra_workbook, "_encode_source", wraps=spectra_workbook._encode_source) as encode:
            window.start_loading(folder, replace=False)
            self.wait_for_load(window)
            encode.assert_not_called()
            self.assertEqual(window.catalog.spectra, previous)
            self.assertIn("No readable spectra", window.status.text())
        with TemporaryDirectory() as folder, \
                patch("metrology_app.spectra_viewer.load_folders", return_value=incoming), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            with patch.object(spectra_workbook, "_encode_source", side_effect=ValueError("encoding failed")):
                window.start_loading(folder, replace=True)
                self.wait_for_load(window)
            self.assertIn("encoding failed", window.status.text())
            self.assertEqual(window.catalog.spectra, previous)
            pd.testing.assert_frame_equal(window.workspace_snapshot().frames["spectra"], cache)

            release = Event()
            original = spectra_workbook._encode_source

            def wait_then_encode(source):
                if not release.wait(5):
                    raise TimeoutError("test did not release encoder")
                return original(source)

            with patch.object(spectra_workbook, "_encode_source", side_effect=wait_then_encode):
                window.start_loading(folder, replace=True)
                window.cancel_loading()
                release.set()
                self.wait_for_load(window)
            self.assertIn("cancelled", window.status.text())
            self.assertEqual(window.catalog.spectra, previous)
            pd.testing.assert_frame_equal(window.workspace_snapshot().frames["spectra"], cache)

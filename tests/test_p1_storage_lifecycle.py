"""Repeated public persistence lifecycles; every file is test-owned."""
import gc
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import weakref
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QApplication

from benchmarks.benchmark_memory_storage import fixture, trend
from metrology_app import recovery, settings
from metrology_app.settings_dialog import SettingsDialog


APP = QApplication.instance() or QApplication([])


class P1StorageLifecycleTests(unittest.TestCase):
    def setUp(self):
        isolation = patch.multiple(settings, _current=deepcopy(settings.DEFAULTS),
            _loaded_path=None, _loaded_contents=None, _load_error=None)
        isolation.start()
        self.addCleanup(isolation.stop)

    def test_trend_reports_retention_without_turning_rss_growth_into_a_leak(self):
        result = trend([{'rss': value} for value in (100, 200, 300, 400, 500, 600)], 'rss')
        self.assertEqual(result['slope_per_cycle'], 100)
        self.assertEqual(result['late_minus_early'], 400)
        self.assertIsNone(trend([{'rss': None}], 'rss'))
        self.assertEqual(trend([{'rss': 7}], 'rss')['slope_per_cycle'], 0)

    def test_fixture_keeps_exact_width_literal_precision_and_both_stages(self):
        book = fixture(200, 30)
        self.assertEqual(book.raw.shape, (200, 30))
        self.assertEqual(book.raw.iloc[0]['Die Seq'], '001')
        self.assertEqual(book.raw.iloc[0]['P0'], '10.000000000000')
        pd.testing.assert_frame_equal(book.raw, book.final_match_raw)
        book.final_match_raw.iat[0, 6] = 'changed'
        self.assertEqual(book.raw.iloc[0]['P0'], '10.000000000000')

    def test_benchmark_refuses_a_settings_file_as_its_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.yaml'
            path.write_bytes(b'theme: light\n')
            result = subprocess.run([sys.executable, '-m', 'benchmarks.benchmark_memory_storage',
                                     '--output', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('dedicated .json', result.stderr)
            self.assertEqual(path.read_bytes(), b'theme: light\n')

    def test_mixed_benchmark_really_draws_each_tool_with_multiple_wafers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mixed.json'
            result = subprocess.run([sys.executable, '-X', 'utf8', '-m',
                'benchmarks.benchmark_memory_storage', '--cycles', '1', '--rows', '2000',
                '--columns', '8', '--scenario', 'mixed', '--populate-dynamic',
                '--platform', 'offscreen', '--output', str(path)],
                capture_output=True, text=True, encoding='utf-8', timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            report = json.loads(path.read_text(encoding='utf-8'))
            rendered = report['samples'][0]['opened']['verified_rendering']
            self.assertEqual(set(rendered[0]), {'trend_panels', 'correlation_fits'})
            self.assertEqual(set(rendered[1]), {'map_scenes', 'radius_series'})
            self.assertEqual(set(rendered[2]), {'dynamic_pivots'})
            self.assertTrue(all(count > 0 for tool in rendered for count in tool.values()))
            self.assertEqual(report['samples'][0]['window_wrappers_alive_after_gc'], 0)
            self.assertTrue(report['settings_unchanged'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process counter metadata')
    def test_memory_sampling_does_not_retain_new_pointer_types_on_each_call(self):
        import ctypes
        from benchmarks.benchmark_correlation_restore import memory_info
        # This registry keeps its keys alive. A new counter type per call is
        # an observer leak, even when the sampled process has no new windows.
        memory_info()
        count = len(ctypes._pointer_type_cache)
        for _ in range(25):
            value = memory_info()
            self.assertGreater(value['private'], 0)
            self.assertGreater(value['rss'], 0)
        self.assertEqual(len(ctypes._pointer_type_cache), count,
                         'Sampler retains a fresh ctypes counter/pointer class per observation')

    def test_two_persistent_processes_alternate_saves_and_reject_stale_state(self):
        worker = """
import json, sys
from metrology_app.settings import load_settings, save_settings, get_settings
path = sys.argv[1]
for line in sys.stdin:
    command = json.loads(line)
    try:
        result = load_settings(path) if command['op'] == 'load' else save_settings(command['data'], path)
        answer = {'ok': True, 'state': result}
    except OSError as error:
        answer = {'ok': False, 'error': type(error).__name__, 'state': get_settings()}
    print(json.dumps(answer), flush=True)
"""
        def ask(process, **command):
            process.stdin.write(json.dumps(command) + '\n')
            process.stdin.flush()
            answer = process.stdout.readline()
            self.assertTrue(answer, 'Persistent settings worker stopped unexpectedly')
            return json.loads(answer)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.yaml'
            settings.save_settings({'theme': 'light', 'recent_wkbs': ['sentinel.mwkb']}, path)
            processes = [subprocess.Popen([sys.executable, '-X', 'utf8', '-c', worker, str(path)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding='utf-8') for _ in range(2)]
            try:
                first, second = processes
                for iteration in range(8):
                    ask(first, op='load')
                    accepted = ask(second, op='load')['state']
                    self.assertTrue(ask(first, op='save', data={'font_size': 11 + iteration})['ok'])
                    stale = ask(second, op='save', data={'theme': 'dark'})
                    self.assertFalse(stale['ok'])
                    self.assertEqual(stale['error'], 'SettingsConflictError')
                    self.assertEqual(stale['state'], accepted)
                    ask(second, op='load')
                    result = ask(second, op='save', data={'opacity': 90 if iteration % 2 else 80})
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['state']['font_size'], 11 + iteration)
                    self.assertEqual(result['state']['recent_wkbs'], ['sentinel.mwkb'])
                self.assertFalse(Path(str(path) + '.lock').exists())
                self.assertEqual(list(Path(directory).glob('*.tmp')), [])
            finally:
                for process in processes:
                    process.stdin.close()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process.stdout.close()
                    process.stderr.close()

    def test_repeated_settings_dialog_cancel_changes_neither_memory_nor_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.yaml'
            settings.save_settings({'font_size': 10, 'theme': 'light'}, path)
            before = path.read_bytes()
            active = settings.get_settings()
            for iteration in range(8):
                dialog = SettingsDialog()
                try:
                    dialog.font_size.setCurrentText('16')
                    dialog.theme.setCurrentIndex(dialog.theme.findData('dark'))
                    dialog.reject()
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(settings.get_settings(), active)
                finally:
                    dialog.deleteLater()
                    APP.processEvents()

    def test_shell_releases_each_settings_dialog_after_real_modal_cancel(self):
        from metrology_app.shell import MainWindow
        shell = MainWindow()
        try:
            for _ in range(12):
                QTimer.singleShot(0, lambda: shell.findChildren(SettingsDialog)[-1].reject())
                shell.open_settings()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                gc.collect()
                self.assertEqual(len(shell.findChildren(SettingsDialog)), 0,
                                 'Closed Settings dialog remains owned by the long-lived Shell')
        finally:
            shell.close()
            shell.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_cancelled_queued_recovery_releases_frames_before_writer_drains(self):
        entered, release = threading.Event(), threading.Event()
        def hold_writer():
            entered.set()
            if not release.wait(15):
                raise TimeoutError('Writer blocker was not released')
        blocker = recovery._WRITER.submit(hold_writer)
        self.assertTrue(entered.wait(5))
        try:
            with tempfile.TemporaryDirectory() as directory:
                for iteration in range(20):
                    frame = pd.DataFrame({'CD': ['001.234567890123'] * 10000})
                    snapshot = recovery.WorkspaceSnapshot('wafer_map', {'input_data': frame})
                    reference = weakref.ref(frame)
                    future = recovery.submit_recovery(Path(directory) / f'{iteration}.wmap',
                        snapshot, None, {}, True, '', None, None)
                    self.assertTrue(future.cancel())
                    del frame, snapshot
                    gc.collect()
                    self.assertIsNone(reference(), 'Cancelled queued payload retained its full frame')
                self.assertEqual(list(Path(directory).iterdir()), [])
        finally:
            release.set()
            blocker.result(timeout=10)


if __name__ == '__main__':
    unittest.main()

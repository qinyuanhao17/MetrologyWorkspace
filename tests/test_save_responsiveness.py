"""Large first saves stay responsive without weakening file/pref protection."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QTimer

from metrology_app import settings
from metrology_app.workspace_document import large_spectra_payload
from metrology_app.workspace_store import WorkspaceSnapshot, load_workspace, save_workspace
from metrology_app.window import MainWindow
from tests.test_spectra_viewer import APP


class SaveResponsivenessTests(unittest.TestCase):
    def setUp(self):
        isolation = patch.multiple(settings, _current=deepcopy(settings._current),
            _loaded_path=settings._loaded_path, _loaded_contents=settings._loaded_contents,
            _load_error=settings._load_error)
        isolation.start()
        self.addCleanup(isolation.stop)

    def test_large_first_save_routes_plain_frames_to_responsive_io(self):
        frame = pd.DataFrame({'CD': ['1.000000000001'], 'Note': ['x' * 8_100_000]})
        snapshot = WorkspaceSnapshot('wafer_map', {'input_data': frame})
        self.assertTrue(large_spectra_payload(snapshot))
        self.assertFalse(large_spectra_payload(WorkspaceSnapshot('wafer_map',
            {'input_data': pd.DataFrame({'CD': ['1.00']})})))
        window = MainWindow()
        window.document.force_close = True
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        ticks, workers = [], []
        timer = QTimer(interval=10)
        timer.timeout.connect(lambda: ticks.append(True))
        main_thread = threading.get_ident()
        def slow_write(*args, **kwargs):
            workers.append(threading.get_ident())
            time.sleep(.12)
            return save_workspace(*args, **kwargs)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(window, 'workspace_snapshot', return_value=snapshot), \
             patch.object(window.document, 'remember_recent'), \
             patch('metrology_app.workspace_document.save_workspace', side_effect=slow_write):
            timer.start()
            try:
                path = window.document.save(Path(folder) / 'first.wmap')
            finally:
                timer.stop()
            self.assertTrue(workers and all(worker != main_thread for worker in workers))
            self.assertGreaterEqual(len(ticks), 2)
            pd.testing.assert_frame_equal(load_workspace(path).frames['input_data'], frame)

    def test_repeated_save_does_not_rewrite_an_unchanged_recent_list(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.yaml'
            document = Path(folder) / 'owned.wct'
            settings.save_settings({'theme': 'light'}, path)
            settings.remember_recent_wkb(document, settings_path=path)
            before = path.read_bytes()
            with patch('metrology_app.settings.save_settings', side_effect=AssertionError('Unneeded preferences write')):
                recent = settings.remember_recent_wkb(document, settings_path=path)
            self.assertEqual(recent[0], document.resolve())
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(settings.get_settings()['theme'], 'light')

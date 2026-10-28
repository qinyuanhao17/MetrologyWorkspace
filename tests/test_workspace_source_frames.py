"""Source-only reads must not traverse unrelated plot controls."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.sheet import SheetModel, prepare_sheet_version
from metrology_app.table_version import LiteralTableVersion
from metrology_app.window import MainWindow


APP = QApplication.instance() or QApplication([])


class WorkspaceSourceFrameTests(unittest.TestCase):
    def model(self, frame, *, versioned=False):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        if versioned:
            model._load_prepared_frame(prepare_sheet_version(
                frame, LiteralTableVersion.from_frame(frame)))
        else:
            model.load(frame)
        return model

    def test_source_guard_reads_both_literal_tables_without_collecting_ui(self):
        raw = pd.DataFrame({'Die Seq': ['001', '001', '03'],
                            'CD': ['1.00000000000001', 'bad', 'NA']})
        raw.attrs['source_rows'] = [4, 2, 2]
        reference = pd.DataFrame({'Reference': ['2.0000', '', '3']})
        window = SimpleNamespace(workspace_type='correlation_trend',
                                 model=self.model(raw, versioned=True),
                                 reference_model=self.model(reference))
        with patch('metrology_app.window.analysis_state',
                   side_effect=AssertionError('A source check traversed plot controls')):
            frames = MainWindow._workspace_source_frames(window, readonly=True)
        self.assertEqual(set(frames), {'raw_data', 'reference_data'})
        pd.testing.assert_frame_equal(frames['raw_data'], raw)
        pd.testing.assert_frame_equal(frames['reference_data'], reference)
        frames['raw_data'].attrs['source_rows'].append(99)
        self.assertEqual(window.model.document_frame().attrs['source_rows'], [4, 2, 2])
        window.model.edit({(1, 1): '9.99999999999999'})
        self.assertEqual(frames['raw_data'].iloc[0, 1], '1.00000000000001')
        self.assertEqual(window.model.document_frame().iloc[0, 1], '9.99999999999999')

    def test_detached_source_reads_are_mutable_and_keep_the_owner_unchanged(self):
        frame = pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['1.0000', '2']})
        for kind in ('wafer_map', 'dynamic'):
            with self.subTest(kind=kind):
                window = SimpleNamespace(workspace_type=kind,
                                         model=self.model(frame, versioned=True))
                frames = MainWindow._workspace_source_frames(window)
                self.assertEqual(set(frames), {'input_data'})
                frames['input_data'].iloc[0, 1] = 'external edit'
                pd.testing.assert_frame_equal(window.model.document_frame(), frame)

    def test_missing_reference_keeps_the_existing_empty_source_contract(self):
        frame = pd.DataFrame({'CD': ['1.00', '2.00']})
        window = SimpleNamespace(workspace_type='correlation_trend', model=self.model(frame))
        frames = MainWindow._workspace_source_frames(window, readonly=True)
        self.assertTrue(frames['reference_data'].empty)
        pd.testing.assert_frame_equal(frames['raw_data'], frame)

    def test_formal_snapshot_still_collects_ui_and_detaches_source_data(self):
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        def close():
            window.document.force_close = True
            window.close()
        self.addCleanup(close)
        frame = pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['1.0000', 'NA']})
        window.model.load(frame)
        ui = {'selection': {'metrics': ['CD']}, 'tab': 2}
        with patch('metrology_app.window.analysis_state', return_value=ui) as capture:
            snapshot = window.workspace_snapshot()
        capture.assert_called_once_with(window)
        self.assertEqual(snapshot.states['ui'], ui)
        pd.testing.assert_frame_equal(snapshot.frames['input_data'], frame)
        snapshot.frames['input_data'].iloc[0, 1] = 'external edit'
        pd.testing.assert_frame_equal(window.model.document_frame(), frame)

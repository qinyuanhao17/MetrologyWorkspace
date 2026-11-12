"""Spectra coordinate tables retain measured values and participation identity."""
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from metrology_app.spectra_info import build_spectra_info
from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests import test_spectra_info as fixtures
from tests.test_spectra_viewer import make_spectrum


class SpectraXYTests(unittest.TestCase):
    def test_xy_uses_sme_coordinates_in_original_raw_row_order(self):
        raw, sources = fixtures.SpectraInfoTests().sources()
        a = replace(sources[0], x_mm=-12.3456, y_mm=45.6789)
        b = replace(sources[1], x_mm=23.4567, y_mm=-56.7891)
        raw['X(mm)'], raw['Y(mm)'] = '999', '-999'
        result = build_spectra_info(raw, pd.DataFrame(), (a, b),
                                    checked_keys={a.key, b.key})
        self.assertEqual(result.issues, ())
        self.assertEqual(result.xy.columns.tolist(),
                         ['Wafer ID', 'Lot ID', 'PAD Name', 'Die Seq', 'FIELD X', 'FIELD Y', 'X(mm)', 'Y(mm)'])
        self.assertEqual(result.xy.to_dict('records'), [
            {'Wafer ID':'W1', 'Lot ID':'L1', 'PAD Name':'P1', 'Die Seq':2,
             'FIELD X':-1, 'FIELD Y':5, 'X(mm)':23.4567, 'Y(mm)':-56.7891},
            {'Wafer ID':'W1', 'Lot ID':'L1', 'PAD Name':'P1', 'Die Seq':1,
             'FIELD X':-1, 'FIELD Y':5, 'X(mm)':-12.3456, 'Y(mm)':45.6789}])
        self.assertEqual(result.source_rows, (0, 1))

    def test_without_raw_natural_identity_die_time_order_and_missing_xy(self):
        sources = [make_spectrum(1, wafer='W10'), make_spectrum(1, wafer='W2', pad='P10'),
                   make_spectrum(10, wafer='W2', pad='P2'), make_spectrum(2, wafer='W2', pad='P2'),
                   make_spectrum(1, wafer='W2', lot='L2')]
        later = replace(sources[3], key='repeat', path=sources[3].path.with_name('repeat.sme'),
                        identity=replace(sources[3].identity, timestamp='2026-10-31 11:00:02'))
        sources.insert(0, later)
        sources[4] = replace(sources[4], x_mm=None, y_mm=None)
        result = build_spectra_info(None, pd.DataFrame(), sources,
                                    checked_keys={s.key for s in sources})
        self.assertEqual(result.issues, ())
        self.assertFalse(result.raw_order)
        self.assertEqual(result.xy[['Wafer ID','Lot ID','PAD Name','Die Seq']].values.tolist(), [
            ['W2','L1','P2',2], ['W2','L1','P2',2], ['W2','L1','P2',10],
            ['W2','L1','P10',1], ['W2','L2','P1',1], ['W10','L1','P1',1]])
        self.assertEqual(result.source_rows, (4, 0, 3, 2, 5, 1))
        self.assertTrue(pd.isna(result.xy.iloc[0]['X(mm)']))
        self.assertTrue(pd.isna(result.xy.iloc[0]['Y(mm)']))
        # Empty Workbook Raw Data uses the same fallback, with no fabricated Reference pairing.
        empty = build_spectra_info(pd.DataFrame(), pd.DataFrame({'Depth':['9.9']}), sources,
                                   checked_keys={s.key for s in sources})
        pd.testing.assert_frame_equal(empty.xy, result.xy)


class SpectraXYWorkflowTests(unittest.TestCase):
    def test_standalone_xy_tab_copy_export_and_live_checks(self):
        from PyQt6.QtTest import QTest
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        sources = (replace(make_spectrum(10), x_mm=12.3456, y_mm=-9.87),
                   replace(make_spectrum(2), x_mm=-2.34, y_mm=None))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        self.assertTrue(viewer.spectra_info_button.isEnabled())
        info = viewer.open_spectra_info()
        self.assertEqual([info.tabs.tabText(i) for i in range(info.tabs.count())],
                         ['Spectra Info', 'With Test Flag', 'XY'])
        info.tabs.setCurrentIndex(2)
        self.assertEqual(info.table_frame()['Die Seq'].tolist(), [2, 10])
        info.copy_button.click()
        copied = pd.read_csv(StringIO(fixtures.APP.clipboard().text()), sep='\t')
        self.assertEqual(copied['X(mm)'].tolist(), [-2.34, 12.3456])
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'xy.csv'
            info.export_csv(path)
            exported = pd.read_csv(path)
            self.assertTrue(pd.isna(exported.iloc[0]['Y(mm)']))
            self.assertEqual(exported.iloc[1]['Y(mm)'], -9.87)
        viewer.set_spectrum_checks({sources[1].key:False})
        for _ in range(20):
            if len(info.models[2].frame) == 1:
                break
            QTest.qWait(10)
        self.assertEqual(info.models[2].frame['Die Seq'].tolist(), [10])
        self.assertIn('natural', info.status.text().lower())

    def test_xy_data_selection_filter_apply_changes_info_participation(self):
        from PyQt6.QtCore import QTimer
        from metrology_app.sme_spectra import file_metadata_dataframe
        from metrology_app.selection_script import export_script
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        raw, original = fixtures.SpectraInfoTests().sources()
        sources = (replace(original[0], x_mm=-12.3456, y_mm=45.6789),
                   replace(original[1], x_mm=23.4567, y_mm=-56.7891))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        viewer.set_spectra_info_source(lambda:(raw, pd.DataFrame()))
        frame = file_metadata_dataframe(viewer.catalog.spectra).rename(columns=lambda c:f'Raw Data / {c}')
        self.assertEqual(frame['Raw Data / X(mm)'].tolist(), [-12.3456, 23.4567])
        condition = {'column':'Raw Data / X(mm)', 'values':['-12.3456']}
        script = export_script(frame, {'checked':[0,1], 'filters':[[condition]],
                                       'row_bools':[[]], 'show':'filtered', 'hide_excluded':True})
        errors = []
        def choose():
            dialog = fixtures.APP.activeModalWidget()
            try:
                dialog.apply_selection_script(script)
                self.assertEqual(dialog.model.rows, [0])
                dialog.check_visible(False)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        viewer.data_selection_action.trigger()
        self.assertEqual(errors, [])
        self.assertEqual([s.identity.die_seq for s in viewer.checked_spectra()], [2])
        result = viewer.spectra_info()
        self.assertEqual(result.xy['Die Seq'].tolist(), [2])
        self.assertEqual(result.xy['X(mm)'].tolist(), [23.4567])
        with TemporaryDirectory() as directory:
            saved = viewer.save_spec(Path(directory) / 'coordinates.spec')
            restored = SpectraViewerWindow()
            restored.document.force_close = True
            self.addCleanup(restored.close)
            self.addCleanup(restored.deleteLater)
            restored.load_workspace(saved)
            self.assertEqual(restored.spectra_info().xy['X(mm)'].tolist(), [23.4567])
            def inspect():
                import json
                dialog = fixtures.APP.activeModalWidget()
                try:
                    state = json.loads(dialog.selection_script())
                    self.assertEqual(state['filters'], [[condition]])
                    self.assertTrue(state['hide_excluded'])
                    self.assertEqual(dialog.model.rows, [0])
                except Exception as error:
                    errors.append(error)
                dialog.reject()
            QTimer.singleShot(0, inspect)
            restored.data_selection_action.trigger()
            self.assertEqual(errors, [])

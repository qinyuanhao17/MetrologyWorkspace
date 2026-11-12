"""Unopened Spectra drafts remain portable through Save/Save As and recovery."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import sqlite3
from contextlib import closing
import pandas as pd
from metrology_app.workspace_store import WorkspaceSnapshot, load_workspace, save_workspace


class DeferredWorkspaceFramesTests(unittest.TestCase):
    def test_backing_bytes_live_through_shared_snapshots_then_release_without_resource_warnings(self):
        import gc,warnings
        source=WorkspaceSnapshot('match_workbook',{'reference':pd.DataFrame(), 'raw':pd.DataFrame(),
            'spectra.preview.spectra':pd.DataFrame({'source':['one'],'metadata':['a'],'samples':['A']})},{'match':{}})
        with TemporaryDirectory() as directory:
            path=save_workspace(Path(directory)/'source.mwkb',source)
            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter('always',ResourceWarning)
                saved=load_workspace(path,defer_spectra=True)
                backing=saved.frames['spectra.preview.spectra'].source.path
                shared=deepcopy(saved)
                del saved;gc.collect()
                self.assertTrue(backing.is_file())
                del shared;gc.collect()
                self.assertFalse(backing.exists())
            self.assertFalse([warning for warning in observed if warning.category is ResourceWarning])

    def test_recovery_of_changed_raw_does_not_materialize_unopened_spectra(self):
        from metrology_app.workspace_frames import StoredFrame
        from metrology_app.workspace_document import pack_snapshot
        original=WorkspaceSnapshot('match_workbook',{'reference':pd.DataFrame({'Ref':['1']}),
            'raw':pd.DataFrame({'Raw':['2']}),'spectra.preview.spectra':pd.DataFrame(
                {'source':['one'],'metadata':['literal'],'samples':['A'*20000]})},{'match':{}})
        with TemporaryDirectory() as directory:
            path=save_workspace(Path(directory)/'original.mwkb',original)
            baseline=load_workspace(path,defer_spectra=True)
            current=deepcopy(baseline)
            current.frames['raw'].iat[0,0]='3'
            with patch.object(StoredFrame,'load',side_effect=AssertionError('Unopened samples materialized')):
                description=pack_snapshot(current,'baseline',baseline)
            self.assertEqual(len(description['frames']),3)

    def test_native_fetch_keeps_literal_cells_dtypes_and_catalog_row_order(self):
        frame=pd.DataFrame({'ID':['001','NA',' 2 '],'Value':[1.25,float('nan'),-0.0]})
        with TemporaryDirectory() as directory:
            path=save_workspace(Path(directory)/'literal.wmap',WorkspaceSnapshot('wafer_map',{'input_data':frame}))
            with closing(sqlite3.connect(path)) as connection,connection:
                connection.execute('CREATE TABLE reordered AS SELECT * FROM frame_0 ORDER BY row_order DESC')
                connection.execute('DELETE FROM frame_0')
                connection.execute('INSERT INTO frame_0 SELECT * FROM reordered')
                connection.execute('DROP TABLE reordered')
            pd.testing.assert_frame_equal(load_workspace(path).frames['input_data'],frame)

    def test_metadata_listing_excludes_recovery_and_deferred_loading_rejects_incomplete_rows(self):
        from metrology_app.workspace_store import workspace_kind
        source=WorkspaceSnapshot('match_workbook',{'reference':pd.DataFrame(), 'raw':pd.DataFrame(),
            'spectra.preview.spectra':pd.DataFrame({'source':['one','two'],'metadata':['a','b'],'samples':['A','B']})},
            {'match':{},'recovery':{}})
        with TemporaryDirectory() as directory:
            path=save_workspace(Path(directory)/'draft.mwkb',source)
            self.assertEqual(workspace_kind(path),'match_workbook')
            with self.assertRaisesRegex(ValueError,'Recover'):
                workspace_kind(path,allow_recovery=False)
            with closing(sqlite3.connect(path)) as connection,connection:
                table=connection.execute("SELECT table_name FROM frame_catalog WHERE name='spectra.preview.spectra'").fetchone()[0]
                connection.execute(f'UPDATE "{table}" SET row_order=0')
            with self.assertRaisesRegex(ValueError,'row order'):
                load_workspace(path,defer_spectra=True)

    def test_unopened_spectra_survive_source_replacement_save_as_and_recovery(self):
        samples = pd.DataFrame({'source':['one'],'metadata':['literal metadata'],'samples':['A'*20000]})
        original = WorkspaceSnapshot('match_workbook',{'reference':pd.DataFrame({'Ref':['1.00']}),
            'raw':pd.DataFrame({'Raw':['2.000']}),'spectra.preview.spectra':samples},{'match':{}})
        with TemporaryDirectory() as directory:
            path=save_workspace(Path(directory)/'original.mwkb',original)
            lazy=load_workspace(path,defer_spectra=True)
            deferred=lazy.frames['spectra.preview.spectra']
            self.assertNotIsInstance(deferred,pd.DataFrame)
            self.assertIs(deepcopy(deferred),deferred)
            # An already-open document owns its old draft even if another window replaces the file.
            replacement=deepcopy(original); replacement.frames['spectra.preview.spectra'].iat[0,2]='new'
            save_workspace(path,replacement)
            target=save_workspace(Path(directory)/'copy.mwkb',lazy)
            pd.testing.assert_frame_equal(load_workspace(target).frames['spectra.preview.spectra'],samples)
            from metrology_app.workspace_document import pack_snapshot,unpack_snapshot,same_snapshot
            recovery=deepcopy(lazy)
            description=pack_snapshot(recovery,'baseline',lazy)
            recovery.states['recovery']={'payload_version':2}
            saved=save_workspace(Path(directory)/'recovery.mwkb',recovery)
            restored=load_workspace(saved,defer_spectra=True)
            self.assertTrue(same_snapshot(unpack_snapshot(restored,description),lazy))
            pd.testing.assert_frame_equal(deferred.load(),samples)

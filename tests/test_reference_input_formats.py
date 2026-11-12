"""Vendor parsing is identical for CSV and first-sheet Excel transport."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from metrology_app.reference_merge import parse_file
from tests.test_cdsem1_compatibility import workbook


class ReferenceInputFormatTests(unittest.TestCase):
    def test_each_vendor_accepts_csv_xlsx_xlsm_without_changing_values_or_channels(self):
        fixtures={
            'NOVA':[['WaferID','LotID','CD','Note','A_LBH'],['W1','L1','30.100','quoted, note\nnext line','NO_LBH']],
            'PMISH':[['WaferID:','W1','LotID:','L1'],
                     ['Num','Seq','Pad name','RefDieCol','RefDieRow','X(mm)','Y(mm)','Recipe','Metrology unit','AzimuthAngle','P'],
                     ['1','1','P','0','0','1.00','2.00','R','UVSE','45°','30.100']],
            'KLA':[['Head 1','WaferID:','W1','LotID:','L1','Slot:','P','TestID:','1','TestLabel:','CD'],
                   ['Site #','X (mm)','Y (mm)','CD'],['1','1.00','2.00','30.100']],
        }
        with TemporaryDirectory() as folder:
            root=Path(folder)
            for vendor,rows in fixtures.items():
                source=root/f'{vendor}.csv'
                with source.open('w',encoding='utf-8-sig',newline='') as stream:
                    csv.writer(stream).writerows(rows)
                expected=parse_file(source,vendor)
                self.assertEqual(len(expected.records),1,vendor)
                for extension in ('.xlsx','.xlsm'):
                    with self.subTest(vendor=vendor,extension=extension):
                        path=root/(vendor+extension);workbook(path,rows)
                        before=path.read_bytes()
                        actual=parse_file(path,vendor)
                        self.assertEqual([r['data'] for r in actual.records],[r['data'] for r in expected.records])
                        self.assertEqual([r['channel'] for r in actual.records],[r['channel'] for r in expected.records])
                        self.assertEqual(actual.records[0]['line'],len(rows))
                        self.assertEqual(path.read_bytes(),before)
                from metrology_app.reference_summary_window import ReferenceSummaryRequest,run_reference_summary
                report=run_reference_summary(ReferenceSummaryRequest(vendor,tuple(root/(vendor+extension) for extension in ('.csv','.xlsx','.xlsm')),root))
                self.assertEqual((report.result.input_rows,report.result.kept_rows,report.result.duplicates),(3,1,2))
                self.assertEqual(report.result.error_count,0)

    def test_workbook_cancellation_and_sparse_row_provenance(self):
        from metrology_app.reference_input import iter_source_rows
        from metrology_app.cdsem1 import _write_workbook
        with TemporaryDirectory() as folder:
            path=Path(folder)/'source.xlsx'
            rows=[['WaferID','CD','Note'],['','',''],['W1','30.100','two\nlines']]
            workbook(path,rows)
            with self.assertRaises(InterruptedError):
                list(iter_source_rows(path,cancelled=lambda:True))
            parsed=parse_file(path,'NOVA')
            self.assertEqual(parsed.records[0]['line'],3)
            self.assertEqual(parsed.records[0]['data']['Note'],'two\nlines')

"""Vendor parsing is identical for CSV and first-sheet Excel transport."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from metrology_app.reference_merge import parse_file
from tests.test_cdsem1_compatibility import workbook


class ReferenceInputFormatTests(unittest.TestCase):
    def test_ref_summary_accepts_optional_channel_fields_and_changing_measurements(self):
        from metrology_app.reference_summary_window import ReferenceSummaryRequest, run_reference_summary

        fixtures = {
            'NOVA': [[['WaferID', 'CD'], ['W1', '30.100']],
                     [['WaferID', 'SWA'], ['W2', '84.200']]],
            'PMISH': [[['Num', 'Seq', 'CD'], ['1', '1', '30.100']],
                      [['Seq', 'SWA'], ['1', '84.200']]],
            'KLA': [[['Head', 'WaferID:', 'W1', 'TestID:', '7'], ['Site #', 'CD'], ['1', '30.100']],
                    [['Head', 'WaferID:', 'W2', 'TestID:', '7'], ['Site #', 'SWA'], ['1', '84.200']]],
        }
        absent_from_batch = {
            'NOVA': {'LotID'},
            'PMISH': {'Recipe', 'Metrology unit', 'AzimuthAngle'},
            'KLA': {'TestLabel'},
        }
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for vendor, files in fixtures.items():
                with self.subTest(vendor=vendor):
                    paths = []
                    for index, rows in enumerate(files):
                        path = root / f'{vendor}_{index}.csv'
                        with path.open('w', encoding='utf-8', newline='') as stream:
                            csv.writer(stream).writerows(rows)
                        paths.append(path)
                    report = run_reference_summary(ReferenceSummaryRequest(vendor, tuple(paths), root))
                    self.assertEqual((report.result.kept_rows, report.result.error_count), (2, 0))
                    output, = (path for path in report.result.output_dir.glob('*.csv') if not path.name.startswith('_'))
                    with output.open(encoding='utf-8-sig', newline='') as stream:
                        reader = csv.DictReader(stream)
                        self.assertTrue(absent_from_batch[vendor].isdisjoint(reader.fieldnames))
                        self.assertEqual([(row['CD'], row['SWA']) for row in reader],
                                         [('30.100', ''), ('', '84.200')])

    def test_kla_retains_blocks_with_any_missing_channel_fields(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'partial-channels.csv'
            heads = [
                ['Head', 'TestID:', '1', 'TestLabel:', 'Top'],
                ['Head', 'TestID:', 'TestLabel:', 'Bottom'],
                ['Head', 'TestLabel:', 'TestID: 3'],
                ['Head'],
            ]
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                for index, head in enumerate(heads, 1):
                    writer.writerows([head, ['Site #', 'CD'], ['1', str(index)]])
            parsed = parse_file(path, 'KLA')
            self.assertEqual(parsed.issues, [])
            self.assertEqual([row['channel'] for row in parsed.records],
                             [('1', 'Top'), ('', 'Bottom'), ('3', ''), ('', '')])
            self.assertEqual([row['data']['CD'] for row in parsed.records], ['1', '2', '3', '4'])

    def test_kla_batch_keeps_channels_when_every_file_lacks_test_id(self):
        from metrology_app.reference_merge import merge

        with TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / 'first.csv', root / 'second.xlsx'
            with first.open('w', encoding='utf-8', newline='') as stream:
                csv.writer(stream).writerows([['Head', 'TestLabel:', 'Top'], ['Site #', 'CD'], ['1', '30.1000']])
            workbook(second, [['Head', 'TestLabel:', 'Bottom'], ['Site #', 'SWA'], ['1', '84.2000']])

            result = merge('KLA', [first, second], root)
            self.assertEqual((result.channel_count, result.kept_rows, result.error_count), (2, 2, 0))
            measurements = {}
            for output in result.output_dir.glob('KLA_*.csv'):
                with output.open(encoding='utf-8-sig', newline='') as stream:
                    row, = csv.DictReader(stream)
                    self.assertNotIn('TestID', row)
                    measurements[row['TestLabel']] = (row.get('CD'), row.get('SWA'))
            self.assertEqual(measurements, {'Top': ('30.1000', None), 'Bottom': (None, '84.2000')})

    def test_kla_long_per_channel_settings_are_not_rejected_measurement_headers(self):
        import csv
        from metrology_app.reference_merge import parse_file
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.csv'
            rows = []
            for channel in (1, 2):
                rows.append(['Head', 'WaferID:', 'W1', 'LotID:', 'L1', 'Slot:', '01',
                             'TestID:', str(channel), 'TestLabel:', f'Channel {channel}'])
                rows.append(['Site #', 'Pass Settings', '', 'Pass Settings'])
                rows.extend([f'Display setting {i}', 'on'] for i in range(220))
                rows.extend([['Site #', 'X (mm)', 'Y (mm)', 'CD'],
                             ['1', '1.2500', '-2.5000', f'{channel}.123400']])
            with path.open('w', newline='', encoding='utf-8') as stream:
                csv.writer(stream).writerows(rows)
            parsed = parse_file(path, 'KLA')
            self.assertEqual(parsed.issues, [])
            self.assertEqual(parsed.blocks, 2)
            self.assertEqual([row['channel'] for row in parsed.records],
                             [('1', 'Channel 1'), ('2', 'Channel 2')])
            self.assertEqual([row['data']['CD'] for row in parsed.records], ['1.123400', '2.123400'])
            self.assertEqual([row['data']['X (mm)'] for row in parsed.records], ['1.2500'] * 2)

    def test_kla_actual_duplicate_data_header_is_still_rejected(self):
        from metrology_app.reference_merge import parse_file
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.csv'
            for first_row in ('', 'bad-site,30,31\n'):
                with self.subTest(first_row=first_row):
                    path.write_text('Head,TestID:,1,TestLabel:,CD\nSite #,CD,CD\n' +
                                    first_row + '1,30,31\nHead,TestID:,2,TestLabel:,Good\nSite #,CD\n1,32\n',
                                    encoding='utf-8')
                    parsed = parse_file(path, 'KLA')
                    self.assertEqual(len(parsed.records), 1)
                    self.assertTrue(any(issue['Kind'] == 'HEADER' and 'Duplicate or empty' in issue['Detail']
                                        for issue in parsed.issues))

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

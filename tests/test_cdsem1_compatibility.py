"""CDSEM single/multi-wafer identities, conflict safety and portable inputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest
import pandas as pd

from metrology_app.cdsem1 import COMMON, LOCAL, _write_workbook, read_cd_rows, pivot_cd_rows, merge_cdsem1


def workbook(path, rows):
    _write_workbook(path,[('Raw',iter((row,['']*len(row)) for row in rows),1,len(rows[0]),[],0),
                          ('Ignored',iter([(['Do not read'],[''])]),1,1,[],0)])


class CDSEMCompatibilityTests(unittest.TestCase):
    def test_optional_ids_are_independent_and_blank_coordinates_fail_in_both_formats(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            for identity in ('Wafer_ID','Lot_ID'):
                path=root/(identity+'.xlsx')
                workbook(path,[['ACD_No','MP_Name','Chip_X','Chip_Y','Result',identity],
                               [' cd ','MP1','0','0','30.1','literal-ID']])
                _,_,rows=read_cd_rows(path)
                self.assertEqual(rows[0][identity],'literal-ID')
                other='Lot_ID' if identity=='Wafer_ID' else 'Wafer_ID'
                self.assertEqual(rows[0][other],'')
                self.assertEqual(len(pivot_cd_rows(rows,'Raw',path.name)['sites']),1)
            for extension in ('.csv','.xlsx'):
                for field in ('MP_Name','Chip_X','Chip_Y'):
                    header=['ACD_No','MP_Name','Chip_X','Chip_Y','Result']
                    values=['CD','MP1','0','0','30.1'];values[header.index(field)]=' '
                    path=root/('invalid-'+field+extension)
                    if extension=='.csv':
                        with path.open('w',encoding='utf-8-sig',newline='') as stream:
                            csv.writer(stream).writerows([header,values])
                    else:
                        workbook(path,[header,values])
                    with self.assertRaisesRegex(ValueError,field):
                        read_cd_rows(path)

    def test_main_vendor_command_uses_the_existing_summary_engine(self):
        import subprocess,sys,json
        with TemporaryDirectory() as folder:
            root=Path(folder);source=root/'single.xlsx'
            workbook(source,[['ACD_No','MP_Name','Chip_X','Chip_Y','Result'],['CD','MP1','0','0','30.10']])
            result=subprocess.run([sys.executable,'main.py','--vendor','CDSEM1','--files',str(source),
                                   '--output-parent',str(root)],capture_output=True,text=True,encoding='utf-8',timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertEqual((report['site_count'],report['mp_count']),(1,1))
            self.assertEqual(len(list(Path(report['output_dir']).glob('*_Results.csv'))),1)

    def test_single_wafer_without_ids_preserves_names_and_output_shape(self):
        header=['ACD_No','MP_Name','Chip_X','Chip_Y','Result','No','Wafer_X','Wafer_Y']
        records=[header,['CD','mp-A','0','0','30.10','1','100','200'],
                 ['CD','MP-b','0','0','31.20','2','110','210'],
                 ['ACD01','','','','99','','',''],
                 ['CD','mp-A','0','0','30.10','1','100','200']]
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'no-ids.xlsx';workbook(source,records)
            before=source.read_bytes()
            sheet,total,rows=read_cd_rows(source)
            self.assertEqual((sheet,total,len(rows)),('Raw',4,3))
            self.assertTrue(all(row['Wafer_ID']==row['Lot_ID']=='' for row in rows))
            book=pivot_cd_rows(rows,sheet,source.name)
            self.assertEqual(book['mps'],['mp-A','MP-b'])
            self.assertEqual((len(book['sites']),book['duplicates'],book['missing']),(1,1,0))
            result=merge_cdsem1([source],root)
            output=next(result.output_dir.glob('*_Results.csv'))
            frame=pd.read_csv(output,dtype=str,keep_default_na=False,encoding='utf-8-sig')
            self.assertEqual(list(frame.columns),COMMON+['mp-A','MP-b'])
            self.assertEqual(frame[['Lot_ID','Wafer_ID']].values.tolist(),[['','']])
            self.assertEqual(frame[['mp-A','MP-b']].values.tolist(),[['30.10','31.20']])
            from metrology_app.reference_alignment import load_alignment_output
            wide=load_alignment_output(next(result.output_dir.glob('*.xlsx')))
            self.assertEqual(wide.shape,(1,79))
            self.assertEqual(list(wide.columns),COMMON+[f'{name} / {field}' for name in ['mp-A','MP-b'] for field in LOCAL])
            self.assertEqual(wide['mp-A / Wafer_X'].tolist(),['100'])
            self.assertEqual(source.read_bytes(),before)

    def test_pivot_requires_coordinates_but_not_wafer_or_lot(self):
        row={'ACD_No':'CD','MP_Name':'MP1','Chip_X':'0','Chip_Y':'0','Result':'30.1','SourceRow':'2'}
        self.assertEqual(len(pivot_cd_rows([row],'Raw','source')['sites']),1)
        for field in ('MP_Name','Chip_X','Chip_Y'):
            for value in ('', '   '):
                with self.subTest(field=field,value=value),self.assertRaisesRegex(ValueError,field):
                    pivot_cd_rows([{**row,field:value}],'Raw','source')

    def test_conflicts_multi_wafer_and_per_file_isolation(self):
        row={'ACD_No':'CD','MP_Name':'mP1','Chip_X':'0','Chip_Y':'0','Result':'30.10','SourceRow':'2'}
        same={**row,'SourceRow':'3'}
        self.assertEqual(pivot_cd_rows([row,same],'Raw','source')['duplicates'],1)
        with self.assertRaisesRegex(ValueError,'conflicting'):
            pivot_cd_rows([row,{**same,'Result':'31.10'}],'Raw','source')
        book=pivot_cd_rows([{**row,'Lot_ID':'L1','Wafer_ID':'W1'},
                           {**same,'Lot_ID':'L1','Wafer_ID':'W2','Result':'31.10'}],'Raw','source')
        self.assertEqual(len(book['sites']),2)
        with TemporaryDirectory() as folder:
            root=Path(folder)
            for name,result in [('first','30.10'),('second','31.10')]:
                with (root/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                    writer=csv.writer(stream)
                    writer.writerows([['ACD_No','MP_Name','Chip_X','Chip_Y','Result'],['CD','mP1','0','0',result]])
            result=merge_cdsem1([root/'first.csv',root/'second.csv'],root)
            self.assertEqual((result.parsed_files,result.site_count),(2,2))
            outputs=list(result.output_dir.glob('*_Results.csv'))
            self.assertEqual(len(outputs),2)
            self.assertEqual(sorted(pd.read_csv(path,dtype=str,keep_default_na=False)['mP1'][0] for path in outputs),['30.10','31.10'])

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import pandas as pd

from metrology_app.reference_alignment import (AlignmentColumns, infer_alignment_columns, wafer_groups,
    wafer_row_order, coordinate_row_order, coordinate_bias, load_alignment_output)


class ReferenceAlignmentTests(unittest.TestCase):
    def test_bias_converts_reference_into_raw_units(self):
        ref = pd.DataFrame({'Wafer ID':['R'],'X(mm)':['1.00'],'Y(mm)':['-2.00']})
        raw = pd.DataFrame({'Wafer ID':['D'],'X(µm)':['1200'],'Y(µm)':['-2300']})
        result = coordinate_bias(ref,raw,infer_alignment_columns(ref),infer_alignment_columns(raw),{('R','',''):('D','','')})[0][2]
        self.assertAlmostEqual(result['Bias X (µm)'].iloc[0],200)
        self.assertAlmostEqual(result['Bias Y (µm)'].iloc[0],-300)
        self.assertEqual(result.attrs['unit'],'µm')

    def test_pasted_raw_table_keeps_na_identity_and_sorts_fields_without_faking_xy(self):
        from PyQt6.QtWidgets import QApplication, QPushButton
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence
        from PyQt6.QtTest import QTest
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(lambda app=app: page.close())
        text = ('Cur SME File Path\tWafer ID\tLot ID\tTool SN\tPAD Name\tDie Seq\tFIELD X\tFIELD Y\tSeq\tX(mm)\tY(mm)\tLogical ID\tMSE\n'
                'C:/test/b.sme\tLP200001.10\tLP200001\tNA\tNA\t17\t4\t3\tNA\tNA\tNA\t\t16.455\n'
                'C:/test/a.sme\tLP200001.10\tLP200001\tNA\tNA\t10\t7\t2\tNA\tNA\tNA\t\t16.049\n')
        app.clipboard().setText(text)
        QTest.keySequence(page.raw.view,QKeySequence.StandardKey.Paste)
        raw = page.raw.frame()
        self.assertEqual(len(raw),2)
        self.assertEqual(raw['PAD Name'].tolist(),['NA','NA'])
        self.assertEqual(raw['X(mm)'].tolist(),['NA','NA'])
        self.assertEqual(coordinate_row_order(raw,page.raw.columns()),[0,1])
        self.assertFalse(any(b.text()=='Paste Raw Data' for b in page.findChildren(QPushButton)))
        ref = pd.DataFrame({'Wafer ID':['R','R'],'X(mm)':[1,2],'Y(mm)':[3,4]})
        with self.assertRaisesRegex(ValueError,'missing/non-finite'):
            coordinate_bias(ref,raw,infer_alignment_columns(ref),page.raw.columns(),{('R','',''):('LP200001.10','LP200001','NA')})

    def test_trends_default_two_columns_scroll_without_zoom_and_ctrl_zoom(self):
        from PyQt6.QtCore import Qt, QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtWidgets import QApplication, QPushButton
        from metrology_app.reference_alignment_ui import CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = CoordinateTrendPage()
        self.addCleanup(lambda app=app: page.close())
        page.resize(1000, 500)
        frame = pd.DataFrame({'Point':[1,2,3], 'Bias X (mm)':[.1,.2,.1], 'Bias Y (mm)':[-.1,0,.1]})
        page.show_results([(('Ref',str(i),''),('Raw',str(i),''),frame) for i in range(6)])
        page.show(); app.processEvents()
        self.assertEqual(page.columns.currentText(),'2')
        first, second = page.plots[:2]
        self.assertEqual(first.mapTo(page, first.rect().topLeft()).y(),second.mapTo(page,second.rect().topLeft()).y())
        self.assertGreater(second.mapTo(page,second.rect().topLeft()).x(),first.mapTo(page,first.rect().topLeft()).x())
        self.assertFalse(any('Compare' in b.text() for b in page.findChildren(QPushButton)))
        first.grab(); app.processEvents()
        view = first.getViewBox()
        initial = view.viewRange()
        scroll = page.scroll.verticalScrollBar()
        self.assertGreater(scroll.maximum(),0)
        center = first.rect().center()
        def wheel(modifiers, delta):
            event = QWheelEvent(QPointF(center),QPointF(first.mapToGlobal(center)),QPoint(),QPoint(0,delta),
                Qt.MouseButton.NoButton,modifiers,Qt.ScrollPhase.NoScrollPhase,False)
            app.sendEvent(first.viewport(),event); app.processEvents()
        wheel(Qt.KeyboardModifier.NoModifier,-120)
        self.assertEqual(view.viewRange(),initial)
        self.assertGreater(scroll.value(),0)
        scroll.setValue(0); app.processEvents()
        wheel(Qt.KeyboardModifier.ControlModifier,120)
        self.assertNotEqual(view.viewRange(),initial)
        self.assertEqual(scroll.value(),0)
        page.reset_views(); app.processEvents()
        import numpy as np
        np.testing.assert_allclose(view.viewRange(),initial,rtol=0,atol=1e-14)
        curves = first.listDataItems()
        page.columns.setCurrentText('1'); app.processEvents()
        self.assertIs(page.plots[0],first)
        self.assertEqual(first.listDataItems(),curves)

    def test_tab1_transfer_clipboard_drag_sort_and_linked_only_trends(self):
        from PyQt6.QtCore import QModelIndex
        from PyQt6.QtWidgets import QApplication, QAbstractItemView
        from metrology_app.reference_summary_window import ReferenceSummaryWindow, ReferenceSummaryRequest, run_reference_summary
        app = QApplication.instance() or QApplication([])
        window = ReferenceSummaryWindow()
        self.addCleanup(window.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'ref.csv'
            source.write_text('WaferID,LotID,SiteName,Col/X,Row/Y,MpointX,MpointY\n'
                'R1,L,P,1,0,2000,4000\nR1,L,P,0,0,1000,3000\n'
                'R2,L,P,0,0,5000,1000\nR2,L,P,1,0,6000,2000\n')
            window._completed(run_reference_summary(ReferenceSummaryRequest('NOVA',(source,),root)))
            page = window.alignment
            self.assertEqual(window.tabs.count(),3)
            self.assertEqual(len(page.ref.frame()),4)
            self.assertEqual(page.ref.columns().unit,'')
            page.ref.pickers['unit'].setCurrentIndex(page.ref.pickers['unit'].findData('µm'))
            raw = pd.DataFrame({'Wafer ID':['D1','D1','D2','D2','D3','D3'], 'Lot ID':['L']*6,
                'PAD Name':['P']*6,'FIELD X':[0,1,0,1,0,1],'FIELD Y':[0]*6,
                'X (mm)':[5.1,6.2,1.2,2.3,100,200], 'Y (mm)':[1,2,2.9,4.4,10,20]})
            app.clipboard().setText(raw.to_csv(sep='\t',index=False))
            page.paste_raw()
            self.assertEqual(page.raw_wafers.dragDropMode(),QAbstractItemView.DragDropMode.NoDragDrop)
            self.assertEqual(page.links,{})
            raw_before = page.raw.frame().copy()
            self.assertTrue(page.ref_wafers.model().moveRows(QModelIndex(),0,1,QModelIndex(),2))
            self.assertEqual(page.ref.frame()['WaferID'].tolist(),['R2','R2','R1','R1'])
            self.assertEqual(page.links,{('R1','L','P'):('D2','L','P')})
            pd.testing.assert_frame_equal(page.raw.frame(),raw_before)
            page.set_link(('R2','L','P'),('D1','L','P'))
            with self.assertRaisesRegex(ValueError,'one-to-one'):
                page.set_link(('R2','L','P'),('D2','L','P'))
            page.apply_sort()
            self.assertEqual(page.ref.frame()['MpointX'].tolist(),['5000','6000','1000','2000'])
            page.draw()
            self.assertEqual(window.tabs.currentIndex(),2)
            self.assertEqual(len(page.results),2)
            self.assertEqual(len(window.trend_page.plots),2)
            result = next(frame for ref,raw,frame in page.results if ref[0]=='R1')
            self.assertAlmostEqual(result['Bias X (mm)'].iloc[0],.2)
            self.assertAlmostEqual(result['Bias Y (mm)'].iloc[0],-.1)
            self.assertEqual(result['Ref source row'].tolist(),[3,2])
            self.assertEqual(result['Raw source row'].tolist(),[4,5])
            page.raw.set_frame(raw.iloc[[0,2,3,4,5]])
            page.draw()
            self.assertIn('Counts must match',page.status.text())
            self.assertFalse(page.results)
            self.assertFalse(window.trend_page.plots)

    def test_cdsem_pivot_transfer_retains_mp_coordinate_names(self):
        from tests.test_reference_summary import synthetic_cdsem
        from metrology_app.reference_summary_window import ReferenceSummaryRequest, run_reference_summary
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'cd.xlsx'
            synthetic_cdsem(path)
            report = run_reference_summary(ReferenceSummaryRequest('CDSEM1',(path,),Path(folder)))
            output = next(path for path in report.output_files if path.suffix=='.xlsx')
            frame = load_alignment_output(output)
            self.assertEqual(frame['Wafer_ID'].tolist(),['W01'])
            self.assertEqual(frame['MP-A / Wafer_X'].tolist(),['100'])
            self.assertEqual(frame['MP-B / Wafer_X'].tolist(),['111'])
            self.assertEqual(infer_alignment_columns(frame,'CDSEM1').unit,'')
            from PyQt6.QtWidgets import QApplication
            from metrology_app.reference_alignment_ui import AlignmentSheet
            app = QApplication.instance() or QApplication([])
            sheet = AlignmentSheet('Ref')
            self.addCleanup(lambda app=app: sheet.close())
            sheet.set_frame(frame,'CDSEM1')
            sheet.coordinate_pair.setCurrentIndex(sheet.coordinate_pair.findData('MP-B'))
            self.assertEqual((sheet.columns().x,sheet.columns().y),('MP-B / Wafer_X','MP-B / Wafer_Y'))
            self.assertEqual(sheet.columns().unit,'')

    def test_vendor_aliases_and_units_are_explicit(self):
        nova = infer_alignment_columns(pd.DataFrame(columns=['WaferID','LotID','SiteName','Col/X','Row/Y','MpointX','MpointY']), 'NOVA')
        self.assertEqual((nova.pad, nova.field_x, nova.x, nova.unit), ('SiteName','Col/X','MpointX',''))
        kla = infer_alignment_columns(pd.DataFrame(columns=['WaferID','LotID','Slot','X (mm)','Y (mm)']), 'KLA')
        self.assertEqual((kla.pad, kla.unit), ('Slot','mm'))
        micron = infer_alignment_columns(pd.DataFrame(columns=['WaferID','X (µm)','Y (µm)']))
        self.assertEqual(micron.unit,'µm')
        cd = infer_alignment_columns(pd.DataFrame(columns=['Wafer_ID','Lot_ID','Chip_X','Chip_Y','MP1 / Wafer_X','MP1 / Wafer_Y']), 'CDSEM1')
        self.assertEqual((cd.wafer, cd.field_x, cd.x, cd.unit), ('Wafer_ID','Chip_X',None,''))

    def test_sort_and_wafer_move_preserve_literal_rows_and_stable_duplicates(self):
        f = pd.DataFrame({'Wafer ID':['B','A','B','A'], 'Lot ID':['L']*4, 'PAD Name':['P']*4,
                          'FIELD X':['2','-1','1','-1'], 'FIELD Y':['0','2','0','1'], 'value':['1.00','2.00','3.00','4.00']})
        c = infer_alignment_columns(f)
        self.assertEqual(wafer_row_order(f,c,[('A','L','P'),('B','L','P')]), [1,3,0,2])
        order = coordinate_row_order(f,c)
        self.assertEqual(order,[2,0,3,1])
        indexed = f.copy(); indexed.index = [10,20,30,40]
        self.assertEqual(coordinate_row_order(indexed,c),order)
        self.assertEqual(f.iloc[order]['value'].tolist(),['3.00','1.00','4.00','2.00'])
        self.assertEqual(f['value'].tolist(),['1.00','2.00','3.00','4.00'])

    def test_only_linked_wafers_are_compared_in_mm_and_mismatch_is_an_error(self):
        ref = pd.DataFrame({'WaferID':['R']*2,'MpointX':['1000','2000'],'MpointY':['3000','4000']})
        raw = pd.DataFrame({'Wafer ID':['D','D','Unlinked'],'X (mm)':['1.2','2.3','99'],'Y (mm)':['2.9','4.4','99']})
        rc = replace(infer_alignment_columns(ref,'NOVA'),unit='µm')
        dc = infer_alignment_columns(raw)
        links = {('R','',''):('D','','')}
        result = coordinate_bias(ref,raw,rc,dc,links)[0][2]
        self.assertEqual(len(result),2)
        self.assertAlmostEqual(result['Bias X (mm)'].iloc[0],.2)
        self.assertAlmostEqual(result['Bias Y (mm)'].iloc[0],-.1)
        with self.assertRaisesRegex(ValueError,'Counts must match'):
            coordinate_bias(ref.iloc[:1],raw,rc,dc,links)
        with self.assertRaisesRegex(ValueError,'choose the coordinate unit'):
            coordinate_bias(ref,raw,replace(rc,unit=''),dc,links)
        with self.assertRaisesRegex(ValueError,'one-to-one'):
            coordinate_bias(ref,raw,rc,dc,{('R','',''):('D','',''),('Other','',''):('D','','')})

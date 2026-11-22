from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import pandas as pd

from metrology_app.reference_alignment import (AlignmentColumns, infer_alignment_columns, wafer_groups,
    wafer_row_order, coordinate_row_order, coordinate_bias, load_alignment_output)


class ReferenceAlignmentTests(unittest.TestCase):
    def test_wafer_alignment_tables_share_excel_selection_rows_and_ctrl_scroll(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_alignment_ui import CoordinateTrendPage, ReferenceAlignmentPage

        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        rows = 120
        frame = pd.DataFrame({
            "Wafer ID": [f"W{row // 3:03d}" for row in range(rows)],
            "Die Seq": [row % 3 + 1 for row in range(rows)],
            "X(mm)": [row / 10 for row in range(rows)],
            "Y(mm)": [row / 20 for row in range(rows)],
        })
        page.ref.set_frame(frame)
        page.raw.set_frame(frame)
        page.resize(1400, 900)
        page.show()
        app.processEvents()

        ref, raw = page.ref.view, page.raw.view
        ref.setCurrentIndex(ref.model().index(10, 0))
        QTest.keyClick(
            ref,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        ranges = ref.selectionModel().selection()
        self.assertEqual(len(ranges), 1)
        self.assertEqual(
            (ranges[0].top(), ranges[0].left(), ranges[0].bottom(), ranges[0].right()),
            (10, 0, 10, 3),
        )

        raw.verticalHeader().sectionDoubleClicked.emit(70)
        app.processEvents()
        self.assertEqual(ref.currentIndex().row(), 70)
        self.assertEqual(raw.currentIndex().row(), 70)
        self.assertEqual([index.row() for index in ref.selectionModel().selectedRows()], [70])
        self.assertEqual([index.row() for index in raw.selectionModel().selectedRows()], [70])
        self.assertEqual(
            ref.verticalHeader().sectionViewportPosition(70),
            raw.verticalHeader().sectionViewportPosition(70),
        )
        self.assertTrue(ref.visualRect(ref.model().index(70, 0)).intersects(ref.viewport().rect()))
        self.assertTrue(raw.visualRect(raw.model().index(70, 0)).intersects(raw.viewport().rect()))

        assert ref.verticalScrollBar().maximum() > 0
        assert raw.verticalScrollBar().maximum() > 0
        point = ref.viewport().rect().center()
        event = QWheelEvent(
            QPointF(point),
            QPointF(ref.viewport().mapToGlobal(point)),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        app.sendEvent(ref.viewport(), event)
        app.processEvents()
        self.assertGreater(ref.verticalScrollBar().value(), 0)
        self.assertEqual(raw.verticalScrollBar().value(), ref.verticalScrollBar().value())

        ref.verticalScrollBar().setValue(0)
        raw.verticalScrollBar().setValue(0)
        point = raw.viewport().rect().center()
        event = QWheelEvent(
            QPointF(point),
            QPointF(raw.viewport().mapToGlobal(point)),
            QPoint(),
            QPoint(0, -240),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        app.sendEvent(raw.viewport(), event)
        app.processEvents()
        self.assertGreater(raw.verticalScrollBar().value(), 0)
        self.assertEqual(ref.verticalScrollBar().value(), raw.verticalScrollBar().value())
        page.close()
        page.deleteLater()
        app.processEvents()

    def test_ctrl_wheel_syncs_ref_and_raw_wafer_list_progress(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage

        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(page.close)
        page.resize(1100, 700)
        page.ref.set_frame(pd.DataFrame({'Wafer ID': [f'R{i}' for i in range(24)]}))
        page.raw.set_frame(pd.DataFrame({'Wafer ID': [f'D{i}' for i in range(40)]}))
        page.show()
        app.processEvents()
        ref, raw = page.ref_wafers, page.raw_wafers
        left, right = ref.verticalScrollBar(), raw.verticalScrollBar()
        self.assertGreater(left.maximum(), 0)
        self.assertEqual(left.maximum(), right.maximum())

        def wheel(view, delta, modifiers):
            viewport = view.viewport()
            point = viewport.rect().center()
            event = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                                modifiers, Qt.ScrollPhase.NoScrollPhase, False)
            app.sendEvent(viewport, event)

        wheel(ref, -120, Qt.KeyboardModifier.NoModifier)
        self.assertGreater(left.value(), 0)
        self.assertEqual(right.value(), 0)
        control = Qt.KeyboardModifier.ControlModifier
        previous = left.value()
        wheel(ref, -120, control)
        self.assertGreater(left.value(), previous)
        self.assertEqual(right.value(), left.value())
        previous = left.value(), right.value()
        wheel(raw, 120, control)
        self.assertLess(left.value(), previous[0])
        self.assertLess(right.value(), previous[1])
        self.assertEqual(left.value(), right.value())

    def test_bias_converts_reference_into_raw_units(self):
        ref = pd.DataFrame({'Wafer ID':['R'],'X(mm)':['1.00'],'Y(mm)':['-2.00']})
        raw = pd.DataFrame({'Wafer ID':['D'],'X(µm)':['1200'],'Y(µm)':['-2300']})
        result = coordinate_bias(ref,raw,infer_alignment_columns(ref),infer_alignment_columns(raw),{('R','',''):('D','','')})[0][2]
        self.assertAlmostEqual(result['Bias X (µm)'].iloc[0],200)
        self.assertAlmostEqual(result['Bias Y (µm)'].iloc[0],-300)
        self.assertEqual(result.attrs['unit'],'µm')

    def test_combined_xy_field_supplies_both_bias_axes_with_the_labelled_unit(self):
        ref = pd.DataFrame({'WaferID': ['R'], 'XY(mm)': ['X0.15 Y-0.16']})
        raw = pd.DataFrame({'WaferID': ['D'], 'XY(mm)': ['X0.18 Y-0.10']})
        ref_columns, raw_columns = infer_alignment_columns(ref), infer_alignment_columns(raw)
        self.assertEqual((ref_columns.x, ref_columns.y, ref_columns.unit), ('XY(mm)', 'XY(mm)', 'mm'))
        result = coordinate_bias(ref, raw, ref_columns, raw_columns, {('R', '', ''): ('D', '', '')})[0][2]
        self.assertAlmostEqual(result['Bias X (mm)'].iloc[0], .03)
        self.assertAlmostEqual(result['Bias Y (mm)'].iloc[0], .06)
        self.assertEqual(ref.loc[0, 'XY(mm)'], 'X0.15 Y-0.16')

    def test_pasted_raw_table_keeps_na_identity_and_sorts_fields_without_faking_xy(self):
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
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

    def test_trends_default_three_columns_scroll_without_zoom_and_ctrl_zoom(self):
        from PyQt6.QtCore import Qt, QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
        from metrology_app.reference_alignment_ui import CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = CoordinateTrendPage()
        self.addCleanup(lambda app=app: page.close())
        page.resize(1000, 500)
        frame = pd.DataFrame({'Point':[1,2,3], 'Bias X (mm)':[.1,.2,.1], 'Bias Y (mm)':[-.1,0,.1]})
        page.show_results([(('Ref',str(i),''),('Raw',f'D{i}',''),frame) for i in range(6)])
        page.show(); app.processEvents()
        self.assertEqual(page.columns.currentText(),'3')
        first_title = page.panels[0].findChild(QLabel).text()
        self.assertIn('Raw · D0', first_title)
        self.assertNotIn('Ref', first_title)
        self.assertNotIn('↔', first_title)
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
        width = first.width()
        page.columns.setCurrentText('1'); app.processEvents()
        self.assertIs(page.plots[0],first)
        self.assertEqual(first.listDataItems(),curves)
        self.assertEqual(first.width(), width)

    def test_xy_bias_shared_point_preview_updates_synchronously_by_source_row(self):
        from unittest.mock import Mock
        from PyQt6.QtWidgets import QApplication
        from metrology_app.plotting.selection import DataPointEdits
        from metrology_app.reference_alignment_ui import CoordinateTrendPage

        app = QApplication.instance() or QApplication([])
        page = CoordinateTrendPage()
        self.addCleanup(page.close)
        records = Mock(return_value=("first", "second"))
        edits = DataPointEdits(lambda rows, _checked: rows, records=records)
        page.data_point_edits = edits
        frame = pd.DataFrame({
            "Point": [1, 2],
            "Raw source row": [2, 3],
            "Bias X (mm)": [0.1, 0.2],
            "Bias Y (mm)": [-0.1, 0.1],
        })
        page.show_results([
            (("Ref", "R1", ""), ("Raw", "D1", ""), frame),
            (("Ref", "R2", ""), ("Raw", "D2", ""), frame.copy()),
        ])
        page.show()
        app.processEvents()
        edits.highlight({"first"}, None, rows={0})
        self.assertEqual([len(plot.point_selection.preview.data) for plot in page.plots], [2, 2])
        records.assert_not_called()

    def test_sparse_trend_layout_keeps_panels_left_aligned_and_fixed_size(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_alignment_ui import CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = CoordinateTrendPage()
        self.addCleanup(page.close)
        page.resize(1300, 850)
        page.show()
        frame = pd.DataFrame({'Point':[1], 'Bias X (mm)':[.1], 'Bias Y (mm)':[.2]})
        results = [(('Ref', str(i), ''), ('Raw', str(i), ''), frame) for i in range(4)]
        page.show_results(results)
        app.processEvents()
        for columns in ('3', '2', '1'):
            page.columns.setCurrentText(columns)
            app.processEvents()
            first, last = page.panels[0], page.panels[-1]
            self.assertEqual(last.size(), first.size())
            self.assertEqual(last.x(), 0 if columns != '2' else first.width() + 6)
        page.show_results(results[:1])
        app.processEvents()
        self.assertLess(page.panels[0].width(), page.scroll.viewport().width() // 2)
        self.assertLess(page.panels[0].height(), page.scroll.viewport().height())

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
            self.assertEqual(window.tabs.count(), 9)
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
            self.assertEqual(len(page.results), 2)
            self.assertEqual(len(window.trend_page.plots), 2)
            self.assertIn('Comparing 1 uniquely matched Field X/Y points', page.status.toolTip())
            d1 = next(frame for _, raw_key, frame in page.results if raw_key[0] == 'D1')
            self.assertEqual(d1['Ref source row'].tolist(), [4])

    def test_analysis_data_waits_for_plot_and_copies_reference_in_raw_input_order(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import clipboard_frame
        from metrology_app.reference_summary_window import ReferenceSummaryWindow
        from tests.test_wafer_static import finish_graphics

        app = QApplication.instance() or QApplication([])
        window = ReferenceSummaryWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        alignment = window.alignment
        alignment.ref.set_frame(pd.DataFrame({
            'WaferID': ['R1', 'R1', 'R1', 'R2'],
            'FIELD X': [2, 0, 1, 0], 'FIELD Y': [0] * 4,
            'X(mm)': [20, 0, 10, 99], 'Y(mm)': [0] * 4,
            'CD': ['002.00', '000.00', '001.00', '999.00'],
            'Depth': ['12', '10', '11', '99'],
        }))
        alignment.raw.set_frame(pd.DataFrame({
            'Wafer ID': ['D1', 'D2', 'D1', 'D1'],
            'Lot ID': ['L'] * 4, 'Tool SN': ['T'] * 4, 'PAD Name': ['P'] * 4,
            'Seq': ['02', '01', '03', '01'],
            'FIELD X': [1, 0, 2, 0], 'FIELD Y': [0] * 4,
            'X(mm)': ['X12', 'X99', 'X23', 'X1'], 'Y(mm)': ['Y1', 'Y99', 'Y2', 'Y3'],
            'CD': ['7.10', '999', '8.20', '6.00'], 'Width': ['21', '99', '22', '20'],
        }))
        alignment.set_link(('R1', '', ''), ('D1', 'L', 'P'))
        alignment.apply_sort()
        self.assertFalse(window.data_selection_action.isEnabled())
        self.assertTrue(window.analysis.model.document_frame().empty)
        self.assertTrue(window.analysis.reference_model.document_frame().empty)
        alignment.draw()

        for order, expected in (('raw', [2, 3, 1]), ('ref', [3, 1, 2]), ('sorted', [1, 2, 3])):
            window.trend_page.order_buttons[order].click()
            curve = window.trend_page.plots[0].listDataItems()[0]
            self.assertEqual(list(curve.yData), expected)

        analysis = window.analysis
        self.assertEqual([window.tabs.tabText(index) for index in range(3, 9)],
                         ['4. Ref Data', '5. Raw Data', '6. Correlation', '7. Trend', '8. Ref WaferMap', '9. Ref Radius Plot'])
        data = analysis.reference_model.document_frame()
        raw_data = analysis.raw_model.document_frame()
        self.assertEqual(list(data.columns[:9]), ['Wafer ID', 'Lot ID', 'Tool SN', 'PAD Name',
                         'Die Seq', 'FIELD X', 'FIELD Y', 'X(mm)', 'Y(mm)'])
        self.assertEqual(data['Wafer ID'].tolist(), ['D1'] * 3)
        self.assertEqual(data['CD'].tolist(), ['001.00', '002.00', '000.00'])
        self.assertEqual(data['Die Seq'].tolist(), ['02', '03', '01'])
        self.assertEqual(data['X(mm)'].tolist(), ['X12', 'X23', 'X1'])
        self.assertEqual(raw_data['Wafer ID'].tolist(), ['D1'] * 3)
        self.assertEqual(raw_data['CD'].tolist(), ['7.10', '8.20', '6.00'])
        for page in (analysis.correlation_page, analysis.sequence_page):
            self.assertEqual(page.frame['CD'].tolist(), data['CD'].tolist() + raw_data['CD'].tolist())
            self.assertIn('CD', page.selection['metrics'])
            self.assertEqual({key[0] for key, metric in page.selection['available_cells'] if metric == 'CD'},
                             {'Reference', 'Raw Data'})
        for page in (analysis.plot_page, analysis.radius_page):
            pd.testing.assert_frame_equal(page.frame, data)
            self.assertNotIn('Width', page.selection['metrics'])
            self.assertEqual({key[0] for key, _ in page.selection['available_cells']}, {'Reference'})
        self.assertEqual(analysis.plot_page.x_column.currentData(), 'X(mm)')
        self.assertEqual(analysis.radius_page.y_column.currentData(), 'Y(mm)')
        for page in (analysis.correlation_page, analysis.sequence_page, analysis.plot_page, analysis.radius_page):
            window.tabs.setCurrentWidget(page)
            page.selector.selectAll()
            if page is analysis.plot_page:
                page.draw_maps()
                finish_graphics(page)
                self.assertIsNotNone(page.result, page.empty.text() or page.status.text())
                self.assertEqual(page.result['scenes'][0]['layer']['x'].tolist(), [12, 23, 1])
                self.assertEqual({scene['wafer'][0] for scene in page.result['scenes'] if not scene.get('skip')},
                                 {'Reference'})
            else:
                page.draw_plot()
                self.assertTrue(page.ready, page.status.text())
                if page is analysis.sequence_page:
                    self.assertEqual({group['source']['name'] for group in page.groups}, {'Reference', 'Raw Data'})
                elif page is analysis.radius_page:
                    self.assertEqual({plot['wafer'][0] for plot in page.plot_sources if not plot.get('skip')},
                                     {'Reference'})
        for requested in (['CD'], ['CD', 'Depth']):
            window.analysis.copy_reference(requested)
            copied = clipboard_frame(app.clipboard().text())
            self.assertEqual(list(copied.columns), requested)
            self.assertEqual(copied['CD'].tolist(), ['001.00', '', '002.00', '000.00'])
        alignment.clear_links()
        self.assertFalse(window.data_selection_action.isEnabled())
        self.assertTrue(window.analysis.model.document_frame().empty)
        self.assertTrue(window.analysis.reference_model.document_frame().empty)

    def test_reference_trend_y_axes_menu_updates_plot_and_survives_reopen(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_summary_window import ReferenceSummaryWindow

        app = QApplication.instance() or QApplication([])
        self.addCleanup(app.processEvents)
        window, reopened = ReferenceSummaryWindow(), ReferenceSummaryWindow()
        for item in (window, reopened):
            item.document.force_close = True
            self.addCleanup(item.deleteLater)
            self.addCleanup(item.close)
        window.show()
        plot = window.analysis.sequence_page
        alignment = window.alignment
        xy = {'X(mm)': [0, 1, 2], 'Y(mm)': [0, 0, 0]}
        measures = {'CD [nm]': [90, 100, 110], 'Depth [nm]': [19, 20, 21]}
        alignment.ref.set_frame(pd.DataFrame({'WaferID': ['R'] * 3, **xy, **measures}))
        alignment.raw.set_frame(pd.DataFrame({'WaferID': ['D'] * 3, 'Die Seq': [1, 2, 3], **xy, **measures}))
        alignment.set_link(('R', '', ''), ('D', '', ''))
        alignment.draw()
        window.tabs.setCurrentWidget(plot)
        app.processEvents()
        plot.selector.selectAll()
        plot.draw_plot()
        self.assertTrue(plot.ready, plot.status.text())
        self.assertTrue(plot.set_overlay('CD [nm]', 'Depth [nm]', 'Reference'), plot.status.text())

        self.assertIn(window.analysis_menu.menuAction(), window.menuBar().actions())
        menu = window.analysis_menu.actions()[0].menu()
        self.assertEqual(menu.title(), 'Trend Y Axes')
        actions = {action.text(): action for action in menu.actions() if action.isCheckable()}
        self.assertTrue(actions['Auto (median ratio)'].isChecked())
        self.assertEqual(plot.axis_ratio_limit(), 1.0)
        self.assertTrue(any(widget.secondary_views for widget in plot.plot_widgets))
        plot.axis_ratio.setValue(10)
        self.assertFalse(any(widget.secondary_views for widget in plot.plot_widgets))
        plot.axis_ratio.setValue(2.75)
        self.assertTrue(any(widget.secondary_views for widget in plot.plot_widgets))

        actions['Always one Y axis'].trigger()
        self.assertFalse(any(widget.secondary_views for widget in plot.plot_widgets))
        actions['Always two Y axes'].trigger()
        self.assertTrue(any(widget.secondary_views for widget in plot.plot_widgets))
        actions['Always one Y axis'].trigger()
        self.assertFalse(plot.axis_ratio.isEnabled())

        with tempfile.TemporaryDirectory() as folder:
            path = window.save_reference(Path(folder) / 'trend.ref')
            reopened.load_workspace(path)
            restored = reopened.analysis.sequence_page
            self.assertEqual((restored.axis_mode_value(), restored.axis_ratio_limit()), ('single', 2.75))
            menu = reopened.analysis_menu.actions()[0].menu()
            self.assertTrue(next(action for action in menu.actions() if action.text() == 'Always one Y axis').isChecked())

    def test_reference_group_settings_survive_workspace_reopen(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_summary_window import ReferenceSummaryWindow

        app = QApplication.instance() or QApplication([])
        window, reopened = ReferenceSummaryWindow(), ReferenceSummaryWindow()
        for item in (window, reopened):
            item.document.force_close = True
        xy = {'X(mm)': [0, 1, 2, 3], 'Y(mm)': [0, 0, 0, 0]}
        values = {'CD [nm]': [90, 100, 110, 120]}
        page = window.alignment
        page.ref.set_frame(pd.DataFrame({
            'WaferID': ['R'] * 4, 'PAD Name': ['P'] * 4, **xy, **values,
        }))
        page.raw.set_frame(pd.DataFrame({
            'WaferID': ['D'] * 4, 'PAD Name': ['P'] * 4, 'Die Seq': [1, 2, 3, 4],
            'TestFlag': [0, 0, 1, 1], **xy, **values,
        }))
        page.link_aligned()
        page.draw()
        controls = window.analysis.display_options.controls
        controls.enabled.setChecked(True)
        self.assertTrue(window.analysis.display_options.apply_groups())
        plan = window.analysis._group_plan
        self.assertEqual(plan.group_keys, ('All:0', 'All:1'))
        shown = plan.group_keys[0]
        controls.set_display_groups([], [shown])
        window.analysis.display_options._context_cache = None
        window.analysis.display_options.refresh()

        with tempfile.TemporaryDirectory() as folder:
            path = window.save_reference(Path(folder) / 'groups.ref')
            reopened.load_workspace(path)
        restored = reopened.analysis._group_plan
        self.assertIsNotNone(restored)
        self.assertTrue(restored.enabled)
        self.assertEqual(restored.state['show_wafer_groups'], [shown])
        app.processEvents()
        window.close()
        reopened.close()
        app.processEvents()

    def test_data_menu_applies_match_workbook_selection_to_analysis_and_xy_bias(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication, QDialog
        from metrology_app.data_selection import DataSelectionDialog
        from metrology_app.reference_summary_window import ReferenceSummaryWindow

        app = QApplication.instance() or QApplication([])
        window, reopened = ReferenceSummaryWindow(), ReferenceSummaryWindow()
        for item in (window, reopened):
            item.document.force_close = True
            self.addCleanup(item.deleteLater)
            self.addCleanup(item.close)
        xy = {'X(mm)': [0, 1, 2], 'Y(mm)': [0, 0, 0]}
        page = window.alignment
        page.ref.set_frame(pd.DataFrame({'WaferID': ['R'] * 3, 'CD': [1, 2, 3], **xy}))
        page.raw.set_frame(pd.DataFrame({'WaferID': ['D'] * 3, 'Die Seq': [1, 2, 3], 'CD': [4, 5, 6], **xy}))
        page.link_aligned()
        page.draw()
        self.assertIn(window.data_menu.menuAction(), window.menuBar().actions())

        def exclude_middle(dialog):
            self.assertEqual(len(dialog.plan.raw), 3)
            self.assertIn('CD', dialog.plan.reference)
            dialog.model.checked.remove(dialog.model.ids[1])
            dialog.hide_excluded.setChecked(True)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch.object(DataSelectionDialog, 'exec', new=exclude_middle):
            window.data_selection_action.trigger()
        analysis = window.analysis
        self.assertEqual(analysis.participating_positions(analysis.raw_model.document_frame()), {0, 2})
        self.assertEqual(analysis.sheet.model().rowCount(), 3)  # header and two participating rows
        self.assertEqual(analysis.reference_sheet.model().rowCount(), 3)
        rows = {row for positions in analysis.selection['groups'].values() for row in positions}
        self.assertEqual(rows, {0, 2, 3, 5})
        for plot in (analysis.plot_page, analysis.radius_page):
            self.assertEqual({row for positions in plot.selection['groups'].values() for row in positions}, {0, 2})
        self.assertTrue(pd.isna(window.trend_page.plots[0].listDataItems()[0].yData[1]))
        self.assertEqual(len(page.raw.source_rows), 3)

        with tempfile.TemporaryDirectory() as folder:
            reopened.load_workspace(window.save_reference(Path(folder) / 'selection.ref'))
            restored = reopened.analysis
            self.assertEqual(restored.participating_positions(restored.raw_model.document_frame()), {0, 2})

    def test_loaded_outputs_preserve_raw_edits_and_trends_when_either_tab_switches(self):
        from PyQt6.QtWidgets import QApplication, QLabel
        from metrology_app.reference_summary_window import ReferenceSummaryWindow
        app = QApplication.instance() or QApplication([])
        window = ReferenceSummaryWindow()
        self.addCleanup(lambda app=app: window.close())
        page, trend = window.alignment, window.trend_page
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = []
            for name, wafer in [('A', 'R1'), ('B', 'R2')]:
                target = root / name
                target.mkdir()
                path = target / 'NOVA_merged.csv'
                path.write_text(f'WaferID,X(mm),Y(mm)\n{wafer},1.000,2.500\n')
                paths.append(path.resolve())
            page.add_output_files(paths)
            self.assertEqual(trend.output_picker.count(), 2)
            self.assertEqual([page.output_picker.itemText(i) for i in range(2)], list(map(str, paths)))
            common = {'X(mm)': ['1.100'], 'Y(mm)': ['2.550']}
            page.raw.set_frame(pd.DataFrame({'Wafer ID': ['D1'], **common}))
            page.raw.model.edit({(1, 1): '1.3000'})
            page.link_aligned()
            page.draw()
            self.assertIn('D1', trend.panels[0].findChild(QLabel).text())
            self.assertEqual(window.analysis.model.document_frame()['Wafer ID'].tolist(), ['D1'])
            first_raw = page.raw
            page.output_picker.setCurrentIndex(1)
            self.assertEqual(trend.output_picker.currentData(), str(paths[1]))
            self.assertEqual(page.ref.frame().WaferID.tolist(), ['R2'])
            self.assertTrue(page.raw.frame().empty)
            self.assertEqual(trend.plots, [])
            self.assertTrue(window.analysis.model.document_frame().empty)
            page.raw.set_frame(pd.DataFrame({'Wafer ID': ['D2'], **common}))
            page.link_aligned()
            page.draw()
            trend.output_picker.setCurrentIndex(0)
            self.assertEqual(page.output_picker.currentData(), str(paths[0]))
            self.assertIs(page.raw, first_raw)
            self.assertEqual(page.raw.frame()['X(mm)'].tolist(), ['1.3000'])
            self.assertIn('D1', trend.panels[0].findChild(QLabel).text())
            self.assertEqual(window.analysis.model.document_frame()['Wafer ID'].tolist(), ['D1'])
            page.raw.model.undo.undo()
            self.assertEqual(page.raw.frame()['X(mm)'].tolist(), ['1.100'])
            self.assertEqual(trend.plots, [])
            trend.output_picker.setCurrentIndex(1)
            self.assertEqual(page.raw.frame()['Wafer ID'].tolist(), ['D2'])
            self.assertIn('D2', trend.panels[0].findChild(QLabel).text())
            self.assertEqual(window.analysis.model.document_frame()['Wafer ID'].tolist(), ['D2'])

    def test_sqlite_session_reopens_plot_state_mappings_and_cached_outputs(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.reference_summary_window import ReferenceSummaryWindow
        from metrology_app.workspace_store import save_workspace, workspace_kind

        app = QApplication.instance() or QApplication([])
        original, restored = ReferenceSummaryWindow(), ReferenceSummaryWindow()
        for window in (original, restored):
            window.document.force_close = True
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / f'NOVA_{number}.csv' for number in (1, 2, 3)]
            for index, path in enumerate(paths, 1):
                path.write_text(f'WaferID,X(mm),Y(mm),Field X,Field Y,CD\nR{index},2,0,2,0,002.50\nR{index},1,0,1,0,001.50\n')
            original.set_source_files(paths[:2])
            from PyQt6.QtCore import Qt
            original.source_list.item(1).setCheckState(Qt.CheckState.Unchecked)
            page = original.alignment
            page.add_output_files(paths)
            page.raw.set_frame(pd.DataFrame({'Wafer ID': ['D1', 'D1'], 'X(mm)': ['1.50', '2.50'],
                                           'Y(mm)': ['0', '1'], 'Field X': ['1', '2'], 'Field Y': ['0', '0']}))
            page.primary.setCurrentIndex(page.primary.findData('y'))
            page.x_order.setCurrentIndex(page.x_order.findData(False))
            page.apply_sort()
            page.link_aligned()
            page.draw()
            original.trend_page.set_order('ref')
            original.trend_page.columns.setCurrentText('2')
            original.tabs.setCurrentWidget(original.analysis.raw_page)
            expected = original.analysis.reference_model.document_frame()
            page.output_picker.setCurrentIndex(1)
            page.raw.set_frame(pd.DataFrame({'Wafer ID': ['D2'], 'X(mm)': ['2.00'], 'Y(mm)': ['0']}))
            page.link_aligned()
            page.output_picker.setCurrentIndex(0)
            paths[2].unlink()  # Unvisited output is already in the import snapshot.
            saved = original.save_reference(root / 'alignment')
            old_snapshot = original.workspace_snapshot()
            old_snapshot.states['ui'].update(version=1, tab=5)
            legacy = save_workspace(root / 'legacy.ref', old_snapshot)
            self.assertEqual(saved.suffix, '.ref')
            self.assertEqual(workspace_kind(saved), 'reference_summary')
            for path in paths[:2]:
                path.unlink()
            restored.load_workspace(saved)
            restored_page = restored.alignment
            self.assertEqual(restored.selected_source_files(), (paths[0],))
            self.assertIs(restored.tabs.currentWidget(), restored.analysis.raw_page)
            self.assertEqual(restored.trend_page.columns.currentText(), '2')
            self.assertEqual(restored.trend_page._order, 'ref')
            self.assertEqual(restored_page.raw.source_rows, page.raw.source_rows)
            self.assertEqual(restored_page.links, page.links)
            self.assertEqual(restored_page.primary.currentData(), 'y')
            self.assertEqual(restored_page.x_order.currentData(), False)
            pd.testing.assert_frame_equal(restored.analysis.reference_model.document_frame(), expected)
            self.assertFalse(restored.document.is_dirty())
            restored.trend_page.output_picker.setCurrentIndex(1)
            self.assertEqual(restored_page.raw.frame()['Wafer ID'].tolist(), ['D2'])
            self.assertTrue(restored.analysis.model.document_frame().empty)
            restored_page.output_picker.setCurrentIndex(2)
            self.assertEqual(restored_page.ref.frame()['WaferID'].tolist(), ['R3', 'R3'])
            restored_page.output_picker.setCurrentIndex(0)
            pd.testing.assert_frame_equal(restored.analysis.reference_model.document_frame(), expected)
            self.assertEqual(restored_page.raw.source_rows, [3, 2])
            links = restored_page.links.copy()
            restored_page.recover_sort()
            self.assertEqual(restored_page.links, links)
            self.assertEqual(restored_page.raw.source_rows, [2, 3])
            self.assertEqual(restored_page.raw.frame()['X(mm)'].tolist(), ['1.50', '2.50'])
            self.assertFalse(restored_page.results)
            restored.load_workspace(legacy)
            self.assertIs(restored.tabs.currentWidget(), restored.analysis.sequence_page)

    def test_loading_output_folders_adds_only_checked_summary_csvs(self):
        from unittest.mock import patch
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QDialog, QListWidget
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(lambda app=app: page.close())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'NOVA_batch'
            output.mkdir()
            for name in ('NOVA_merged.csv', 'NOVA_other.csv', '_issues.csv'):
                (output / name).write_text('WaferID,X(mm),Y(mm)\nR,1.00,2.00\n')

            def accept_checked(dialog):
                choices = dialog.findChild(QListWidget)
                self.assertEqual(choices.count(), 2)
                choices.item(1).setCheckState(Qt.CheckState.Unchecked)
                return QDialog.DialogCode.Accepted

            with patch('metrology_app.reference_alignment_ui.choose_folders', return_value=(root, output)), \
                    patch.object(QDialog, 'exec', new=accept_checked):
                page.choose_output_folders()
            self.assertEqual(page.output_picker.count(), 1)
            self.assertEqual(page.output_picker.currentData(), str(output.resolve() / 'NOVA_merged.csv'))
            self.assertEqual(page.ref.frame()['X(mm)'].tolist(), ['1.00'])

    def test_axis_sort_directions_keep_their_labels_when_y_is_primary(self):
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage
        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(lambda app=app: page.close())
        frame = pd.DataFrame({'Wafer ID': ['W'] * 4, 'Field X': [1, 2, 2, 1],
                              'Field Y': [0, 0, 1, 1], 'tag': ['A', 'B', 'C', 'D']})
        self.assertEqual(page.status.text(), '')
        self.assertFalse(any(button.text() == 'Reset views' for button in page.trend_page.findChildren(QPushButton)))
        page.show()
        app.processEvents()
        for label in page.findChildren(QLabel):
            if label.text() in ("X", "Y"):
                gap = label.buddy().mapToGlobal(label.buddy().rect().topLeft()).x() - label.mapToGlobal(label.rect().topRight()).x()
                self.assertLessEqual(gap, 8)
                self.assertGreaterEqual(gap, 0)
        for sheet in (page.ref, page.raw):
            sheet.set_frame(frame)
        self.assertTrue({'X', 'Y'} <= {label.text() for label in page.findChildren(QLabel)})
        page.primary.setCurrentIndex(page.primary.findData('y'))
        page.x_order.setCurrentIndex(page.x_order.findData(False))
        page.apply_sort()
        self.assertEqual(page.ref.frame().tag.tolist(), ['B', 'A', 'C', 'D'])
        self.assertEqual(page.raw.frame().tag.tolist(), ['B', 'A', 'C', 'D'])

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

    def test_raw_order_button_reorders_linked_ref_rows_and_preserves_ambiguous_points(self):
        from PyQt6.QtWidgets import QApplication, QPushButton
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage

        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(lambda app=app: page.close())
        page.ref.set_frame(pd.DataFrame({
            'Wafer ID': ['R1', 'R1', 'Unlinked', 'R2', 'R2'],
            'Field X': ['0', '1', '0', '0', '1'], 'Field Y': ['0'] * 5,
            'Value': ['10.00', '11.01', '99.90', '20.00', '21.02'],
        }))
        page.raw.set_frame(pd.DataFrame({
            'Wafer ID': ['D2', 'D2', 'D1', 'D1'],
            'Field X': ['1', '0', '1', '1'], 'Field Y': ['0'] * 4,
        }))
        page.set_link(('R1', '', ''), ('D1', '', ''))
        page.set_link(('R2', '', ''), ('D2', '', ''))
        links = page.links.copy()
        raw = page.raw.frame()
        raw_rows = page.raw.source_rows.copy()

        next(button for button in page.findChildren(QPushButton) if button.text() == 'Raw order').click()

        self.assertEqual(page.ref.frame()['Value'].tolist(), ['21.02', '20.00', '10.00', '11.01', '99.90'])
        self.assertEqual(page.ref.source_rows, [6, 5, 2, 3, 4])
        self.assertEqual([key[0] for key in page.ref_wafers.keys() if key], ['R2', 'R1', 'Unlinked'])
        self.assertEqual(page.links, links)
        pd.testing.assert_frame_equal(page.raw.frame(), raw)
        self.assertEqual(page.raw.source_rows, raw_rows)

    def test_ref_order_button_reorders_raw_and_success_messages_stay_hidden(self):
        from PyQt6.QtWidgets import QApplication, QPushButton
        from metrology_app.reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage

        app = QApplication.instance() or QApplication([])
        page = ReferenceAlignmentPage(CoordinateTrendPage())
        self.addCleanup(lambda app=app: page.close())
        page.ref.set_frame(pd.DataFrame({
            'Wafer ID': ['R1', 'R1', 'R2', 'R2'], 'Field X': ['0', '2', '1', '0'], 'Field Y': ['0'] * 4,
        }))
        page.raw.set_frame(pd.DataFrame({
            'Wafer ID': ['D2', 'D2', 'Unlinked', 'D1', 'D1'],
            'Field X': ['0', '1', '0', '2', '0'], 'Field Y': ['0'] * 5,
            'Value': ['20.00', '21.02', '99.90', '12.02', '10.00'],
        }))
        buttons = {button.text(): button for button in page.findChildren(QPushButton)}
        buttons['Ref Order'].click()
        self.assertFalse(page.status.isHidden())
        self.assertIn('Link at least one', page.status.text())
        page.set_link(('R1', '', ''), ('D1', '', ''))
        page.set_link(('R2', '', ''), ('D2', '', ''))
        links = page.links.copy()
        ref = page.ref.frame()

        buttons['Ref Order'].click()

        self.assertEqual(page.raw.frame()['Value'].tolist(), ['10.00', '12.02', '21.02', '20.00', '99.90'])
        self.assertEqual(page.raw.source_rows, [6, 5, 3, 2, 4])
        self.assertEqual([key[0] for key in page.raw_wafers.keys() if key], ['D1', 'D2', 'Unlinked'])
        self.assertEqual(page.links, links)
        pd.testing.assert_frame_equal(page.ref.frame(), ref)
        self.assertTrue(page.status.isHidden())
        buttons['Recover order'].click()
        self.assertEqual(page.raw.source_rows, [2, 3, 4, 5, 6])
        self.assertEqual([key[0] for key in page.raw_wafers.keys() if key], ['D2', 'Unlinked', 'D1'])
        self.assertTrue(page.status.isHidden())

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

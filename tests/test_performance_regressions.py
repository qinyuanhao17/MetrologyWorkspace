"""Bounded public-seam probes for real-workbook performance regressions."""
from time import perf_counter
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from metrology_app.matching import MatchWorkbook, ParameterMapping


class WorkbookPerformanceTests(unittest.TestCase):
    def test_grouped_trend_avoids_discarded_wafer_items_and_keeps_all_data(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        import pyqtgraph as pg
        from metrology_app.match_group_ui import draw_group_trend
        from metrology_app.plotting import InteractivePlotWidget
        app = QApplication.instance() or QApplication([])
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(40)], 20),
                            "Die Seq": list(range(1, 21)) * 40, "CD": np.arange(800.)})
        reference = pd.DataFrame({"CD Reference": raw["CD"] * 2 + 1})
        result = MatchWorkbook(reference, raw, [ParameterMapping("CD", "CD Reference", "CD")],
                               test_flags=pd.DataFrame({"TestFlag": [0] * 400 + [1] * 400}),
                               grouping_state={"enabled": True}).analyze()
        plot = InteractivePlotWidget(background="white")
        try:
            plot.resize(900, 420)
            # Instrument construction, never replace the renderer or its pens.
            with patch("metrology_app.match_group_ui.pg.InfiniteLine", wraps=pg.InfiniteLine) as edges:
                data = draw_group_trend(plot, result, "CD", group_only=True)
            self.assertLessEqual(edges.call_count, 2, "Discarded wafer edges are still constructed")
            self.assertEqual([line.value() for line in plot._group_boundaries], [400.5])
            np.testing.assert_array_equal(plot.listDataItems()[0].yData, data["Reference"])
            np.testing.assert_array_equal(plot.listDataItems()[1].yData, data["Trend value"])
            plot.show()
            app.processEvents()
            draw_group_trend(plot, result, "CD")
            self.assertEqual([line.value() for line in plot._group_boundaries],
                             [i + .5 for i in range(20, 800, 20)])
            self.assertTrue(all(isinstance(line, pg.InfiniteLine) for line in plot._group_boundaries))
            plot.setXRange(200.5, 600.5, padding=0)
            app.processEvents()
            np.testing.assert_array_equal(plot.listDataItems()[0].yData, data["Reference"])
            np.testing.assert_array_equal(plot.listDataItems()[1].yData, data["Trend value"])
            pd.testing.assert_frame_equal(result.group_plan.raw, raw)
        finally:
            plot.close()
            plot.deleteLater()
            app.processEvents()

    def test_measurement_metadata_reuses_numeric_updates_without_stale_identities(self):
        from metrology_app.measurements import detect_measurements
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(400)], 20),
                            "Lot ID": ["L1"] * 8000, "Die Seq": list(range(1, 21)) * 400,
                            "CD": np.arange(8000.)})
        expected = detect_measurements(raw, "Wafer ID", ["Wafer ID"], use_die_seq=False)
        start = perf_counter()
        for index in range(5):
            current = raw.copy()
            current.loc[0, "CD"] = 100 + index
            result = detect_measurements(current, "Wafer ID", ["Wafer ID"], use_die_seq=False)
            self.assertEqual(result, expected)
        elapsed = perf_counter() - start
        result[0].label = "caller mutation"
        current.loc[0, "Wafer ID"] = "Changed"
        rebuilt = detect_measurements(current, "Wafer ID", ["Wafer ID"], use_die_seq=False)
        self.assertEqual(rebuilt[0].wafer, "Changed")
        self.assertEqual(rebuilt[0].rows, (0,))
        current.loc[0, "Die Seq"] = 99
        rebuilt = detect_measurements(current, "Wafer ID", ["Wafer ID"], use_die_seq=False)
        self.assertIn("99–99", rebuilt[0].detail)
        self.assertEqual(expected[0].label, "W000")
        self.assertLess(elapsed, .15, f"Repeated metadata preparation stalled: {elapsed:.3f}s")

    def test_raw_paste_and_repeated_keyboard_undo_publish_latest_data_promptly(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.match_groups import row_ids
        from metrology_app.appearance import configure_fonts
        app = QApplication.instance() or QApplication([])
        previous_font, previous_palette = app.font(), app.palette()
        configure_fonts(app)  # Match the real app, not offscreen missing-glyph fallback.
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(400)], 20),
                                "Die Seq": list(range(1, 21)) * 400,
                                "CD": [f"{value}.000" for value in range(1, 8001)],
                                **{f"Metadata {i}": ["retained"] * 8000 for i in range(30)}}).astype(str)
            window.set_reference_frame(pd.DataFrame({"CD Reference": np.arange(1, 8001.) * 2 + 1}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True,
                                           "new_rows": row_ids(raw)[4000:]},
                                          pd.DataFrame({"TestFlag": ["0"] * 4000 + ["1"] * 4000}))
            window.run_analysis()
            saved_marks = {key: list(ids) for key, ids in window.group_controls.state["mark_rows"].items()}
            window.resize(1500, 950)
            window.show()
            app.processEvents()
            view = window.raw_view
            for row in range(1, 6):
                view.setCurrentIndex(view.model().index(row, 2))
                app.clipboard().setText("99.500")
                QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(150)
            start = perf_counter()
            key_times = []
            step_times = []
            for row in range(5, 0, -1):
                step_start = perf_counter()
                QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                key_times.append(perf_counter() - step_start)
                self.assertEqual(window.raw_model.cells[(row, 2)], f"{row}.000")
                QTest.qWait(10)  # Let Qt process native input/paint between keys.
                step_times.append(perf_counter() - step_start)
            deadline = start + 2
            while (abs(window.result.card("CD").slope - 2) > 1e-10
                   or window.result.series("CD")["Raw"].iloc[0] != 1):
                self.assertLess(perf_counter(), deadline, "Latest Undo result never became current")
                QTest.qWait(5)
            app.processEvents()
            elapsed = perf_counter() - start
            pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)
            self.assertTrue(window.raw_model.undo.isClean())
            self.assertAlmostEqual(window.result.card("CD").intercept, 1)
            self.assertEqual(window.result.source_rows, tuple(range(8000)))
            self.assertEqual(window.group_controls.state["mark_rows"], saved_marks)
            self.assertLess(elapsed, .65, f"Five keyboard Undo refreshes stalled: {elapsed:.3f}s; keys={key_times}; steps={step_times}")
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.setFont(previous_font)
            app.setPalette(previous_palette)
            app.processEvents()

    def test_repeated_raw_cell_edit_and_undo_refresh_exact_detached_sources_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel
        app = QApplication.instance() or QApplication([])
        model = SheetModel()
        raw = pd.DataFrame({"Wafer ID": ["001"] * 8000, "CD": ["1.000"] * 8000,
                            **{f"Metadata {i}": ["retained"] * 8000 for i in range(31)}})
        model.load(raw)
        accepted = model.document_frame()
        model.frame()
        started = perf_counter()
        for index in range(5):
            model.setData(model.index(index + 1, 1), "2.1000")
            current = model.document_frame()
            self.assertEqual(current.iloc[index, 1], "2.1000")
            model.undo.undo()
            restored = model.document_frame()
            self.assertEqual(restored.iloc[index, 1], "1.000")
            self.assertEqual(current.iloc[index, 1], "2.1000")
        elapsed = perf_counter() - started
        pd.testing.assert_frame_equal(restored, raw)
        pd.testing.assert_frame_equal(accepted, raw)
        current.iloc[0, 1] = "caller mutation"
        pd.testing.assert_frame_equal(model.document_frame(), raw)
        self.assertLess(elapsed, .15, f"Repeated single-cell source refresh stalled: {elapsed:.3f}s")
        model.deleteLater()
        app.processEvents()

    def test_restore_disabled_trend_does_not_run_old_queued_draw(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        window = CorrelationWindow()
        try:
            raw = pd.DataFrame({'Wafer ID': ['W1'] * 10, 'Die Seq': np.arange(1, 11),
                                'CD': np.arange(10.) + 1, 'Thickness': np.arange(10.) * 2 + 3})
            reference = pd.DataFrame({'Ref': raw['CD'] * 1.03 + 2,
                                      'Thickness Ref': raw['Thickness'] * 1.03 + 2})
            window.set_sources(reference, raw, [ParameterMapping('CD', 'Ref', 'CD'),
                ParameterMapping('Thickness', 'Thickness Ref', 'Thickness')])
            for page in (window.correlation_page, window.sequence_page):
                page.selector.selectAll()
                page.draw_plot()
                self.assertTrue(page.ready, page.status.text())
            state = window.selection_state()
            expected_raw = window.raw_model.document_frame().copy(deep=True)
            # Pending Draw in a saved workspace disables automatic drawing.
            # Zero interval makes the ordering deterministic, even on a fast
            # machine: Correlation processes events while fitting its result.
            state['trend_draw']['enabled'] = False
            window.sequence_page.input_refresh_timer.setInterval(0)
            window.restore_selection(state)
            QTest.qWait(50)
            self.assertTrue(window.correlation_page.ready)
            self.assertFalse(window.sequence_page.ready,
                             'The old queued Trend drew despite disabled saved Draw state')
            self.assertEqual(window.sequence_page.plot_widgets, [])
            pd.testing.assert_frame_equal(window.raw_model.document_frame(), expected_raw)
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_batched_wafer_edges_match_native_lines_after_zoom(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        import pyqtgraph as pg
        from metrology_app.plotting import InteractivePlotWidget
        app = QApplication.instance() or QApplication([])
        native, batched = InteractivePlotWidget(background='white'), InteractivePlotWidget(background='white')
        try:
            positions = [10.5, 40.5, 80.5]
            pen = pg.mkPen('#d4d7dc', width=1, style=Qt.PenStyle.DashLine)
            for plot in (native, batched):
                plot.resize(640, 320)
                plot.plot(np.arange(100.), np.sin(np.arange(100.)), pen='blue')
                plot.show()
            for position in positions:
                native.addItem(pg.InfiniteLine(position, angle=90, pen=pen))
            batched.add_vertical_boundaries(positions, pen)
            for limits in ((0, 100, -1, 1), (5, 50, -3, 3)):
                for plot in (native, batched):
                    plot.setRange(xRange=limits[:2], yRange=limits[2:], padding=0)
                app.processEvents()
                self.assertEqual(native.grab().toImage(), batched.grab().toImage(),
                                 'Batched wafer edges changed rendered positions or dash styles')
        finally:
            for plot in (native, batched):
                plot.close()
                plot.deleteLater()
            app.processEvents()

    def test_first_wide_trend_draw_preserves_all_source_columns_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sequence_page import SequencePage
        app = QApplication.instance() or QApplication([])
        page = SequencePage()
        rows = 8000
        frame = pd.DataFrame({'Wafer ID': np.repeat([f'W{i:03}' for i in range(400)], 20),
                              'Die Seq': list(range(1, 21)) * 400,
                              'CD': np.arange(rows, dtype=float),
                              'Thickness': np.arange(rows, dtype=float) * 2 + 3})
        metrics = ['CD', 'Thickness', 'Etch', 'Recess', 'Depth', 'Width']
        for column, name in enumerate(metrics[2:]):
            frame[name] = np.arange(rows, dtype=float) + column
        for column in range(25):
            frame[f'Source {column}'] = [f'{column}:000{i}' for i in range(rows)]
        original = frame.copy(deep=True)
        try:
            groups = {f'W{i:03}': tuple(range(i * 20, (i + 1) * 20)) for i in range(400)}
            page.set_input(frame, {'wafers': list(groups), 'metrics': metrics,
                                  'wafer_column': 'Wafer ID', 'groups': groups})
            page.selector.selectAll()
            start = perf_counter()
            page.draw_plot()
            elapsed = perf_counter() - start
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(sum(len(group['positions']) for group in page.groups), rows)
            restored = pd.concat([group['frame'].drop(columns='__die') for group in page.groups])
            pd.testing.assert_frame_equal(restored, original)
            for plot, name in zip(page.plot_widgets, page.metrics):
                curve = next(item for item in plot.listDataItems() if len(item.xData) == rows)
                np.testing.assert_array_equal(curve.xData, np.arange(rows))
                np.testing.assert_array_equal(curve.yData, frame[name])
            self.assertLess(elapsed, 1.0, f'First wide Trend draw blocked for {elapsed:.3f}s')
        finally:
            page.input_refresh_timer.stop()
            page.compare_timer.stop()
            page.deleteLater()
            app.processEvents()

    def test_trend_preparation_keeps_invalid_dies_and_stable_duplicates_consistent(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sequence_page import SequencePage
        app = QApplication.instance() or QApplication([])
        page = SequencePage()
        frame = pd.DataFrame({'Wafer ID': ['W1'] * 6,
                              'Die Seq': ['4', '1', '1', 'invalid', 'inf', '2'],
                              'CD': [10., 20., np.nan, 40., 50., 60.]},
                             index=[7, 9, 11, 13, 15, 17])
        original = frame.copy(deep=True)
        try:
            for preserve, expected in ((False, [9, 11, 17, 7]), (True, [7, 9, 11, 17])):
                page.set_input(frame, {'wafers': ['W1'], 'metrics': ['CD'],
                                      'wafer_column': 'Wafer ID',
                                      'preserve_group_order': preserve})
                page.selector.selectAll()
                page.draw_plot()
                self.assertTrue(page.ready, page.status.text())
                ordered = page.groups[0]['frame']
                self.assertEqual(ordered.index.tolist(), expected)
                np.testing.assert_array_equal(ordered['CD'], frame.loc[expected, 'CD'])
                np.testing.assert_array_equal(ordered['__die'],
                                              pd.to_numeric(frame.loc[expected, 'Die Seq']))
                pd.testing.assert_frame_equal(frame, original)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_dense_trend_screen_and_export_match_with_nan_gaps(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        import pyqtgraph as pg
        from metrology_app.appearance import widget_to_qimage
        from metrology_app.plotting import InteractivePlotWidget
        app = QApplication.instance() or QApplication([])
        plot = InteractivePlotWidget(background='white')
        try:
            plot.resize(720, 340)
            values = np.random.default_rng(10).normal(10, 1, 6000)
            values[500:550] = np.nan
            values[1700] = 100  # A narrow, truthful spike must remain present.
            item = plot.plot(np.arange(6000.), values, connect='finite',
                             pen=pg.mkPen('#4472c4', width=1.5, style=Qt.PenStyle.DashLine))
            plot.show()
            app.processEvents()
            plot.viewport().repaint()
            plot.grab()  # Starts screen rasterization on offscreen Qt too.
            deadline = perf_counter() + 15
            while item.render_pending and perf_counter() < deadline:
                QTest.qWait(10)
            self.assertFalse(item.render_pending, 'Full curve image did not finish')
            screen = plot.grab().toImage()
            # Exercise the same public export-mode contract pyqtgraph's
            # exporters use, with an immediate full-resolution QWidget capture.
            item.curve.setExportMode(True, {'antialias': pg.getConfigOption('antialias')})
            full = plot.grab().toImage()
            item.curve.setExportMode(False)
            if screen != full:
                screen.save(str(Path(tempfile.gettempdir()) / 'trend-screen.png'))
                full.save(str(Path(tempfile.gettempdir()) / 'trend-full.png'))
            self.assertEqual(screen, full, 'Cached screen trace differs from complete Qt painting')
            np.testing.assert_equal(item.getOriginalDataset()[1], values)
            # The public curve style API must invalidate an image independently
            # of data changes, including changes while a job is already running.
            item.curve.setPen(pg.mkPen('#ed7d31', width=2.4, style=Qt.PenStyle.DashDotLine))
            plot.grab()
            deadline = perf_counter() + 15
            while item.render_pending and perf_counter() < deadline:
                QTest.qWait(10)
            self.assertFalse(item.render_pending)
            styled = plot.grab().toImage()
            item.curve.setExportMode(True, {'antialias': pg.getConfigOption('antialias')})
            styled_full = plot.grab().toImage()
            item.curve.setExportMode(False)
            self.assertEqual(styled, styled_full, 'Screen image retained an obsolete pen style')
            # A subsequent data revision cannot publish the old curve image.
            item.setData(np.arange(6000.), values + 3)
            immediate, _scale = widget_to_qimage(plot, 1)
            from pyqtgraph.exporters import ImageExporter
            scene_export = ImageExporter(plot.getPlotItem()).export(toBytes=True)
            scene_pixels = np.frombuffer(scene_export.constBits().asstring(scene_export.sizeInBytes()),
                                         dtype=np.uint8).reshape(scene_export.height(), scene_export.bytesPerLine())
            scene_pixels = scene_pixels[:, :scene_export.width() * 4].reshape(scene_export.height(), scene_export.width(), 4)
            self.assertGreater(np.count_nonzero(scene_pixels[..., 0].astype(int) - scene_pixels[..., 2] > 50), 100,
                               'Native scene exporter lost the current complete curve')
            pixels = np.frombuffer(immediate.constBits().asstring(immediate.sizeInBytes()), dtype=np.uint8)
            pixels = pixels.reshape(immediate.height(), immediate.bytesPerLine())[:, :immediate.width() * 4]
            pixels = pixels.reshape(immediate.height(), immediate.width(), 4)
            self.assertGreater(np.count_nonzero(pixels[..., 0].astype(int) - pixels[..., 2] > 50), 100,
                               'Immediate PNG lost the measured blue curve')
            app.processEvents()
            plot.viewport().repaint()
            plot.grab()
            while item.render_pending and perf_counter() < deadline:
                QTest.qWait(10)
            self.assertFalse(item.render_pending)
            updated = plot.grab().toImage()
            completed_export, _scale = widget_to_qimage(plot, 1)
            self.assertEqual(immediate, completed_export,
                             'Export made before the screen job finished was stale')
            item.curve.setExportMode(True, {'antialias': pg.getConfigOption('antialias')})
            updated_full = plot.grab().toImage()
            self.assertEqual(updated, updated_full)
        finally:
            plot.close()
            plot.deleteLater()
            app.processEvents()

    def test_grouped_trend_wheel_preserves_full_curves_promptly(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            values = np.random.default_rng(20).normal(850, 12, 16000)
            raw = pd.DataFrame({'Wafer ID': np.repeat([f'W{i}' for i in range(800)], 20),
                                'Die Seq': list(range(1, 21)) * 800, 'Depth': values})
            window.set_reference_frame(pd.DataFrame({'Depth Reference': values * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({'enabled': True, 'mark_enabled': False},
                                          pd.DataFrame({'TestFlag': [0] * len(raw)}))
            window.run_analysis()
            window.resize(1500, 950)
            window.show()
            plot = next(iter(window.plot_groups.values()))['plots']['trend']
            window.setup_scroll.ensureWidgetVisible(plot)
            QTest.qWait(400)
            curves = plot.listDataItems()
            original = [(item.xData.copy(), item.yData.copy()) for item in curves]
            delays = []
            for i in range(6):
                point = plot.viewport().rect().center()
                event = QWheelEvent(QPointF(point), QPointF(plot.viewport().mapToGlobal(point)),
                                    QPoint(), QPoint(0, 120 if i % 2 else -120),
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
                start = perf_counter()
                app.sendEvent(plot.viewport(), event)
                app.processEvents()
                delays.append(perf_counter() - start)
            for item, (x, y) in zip(plot.listDataItems(), original):
                np.testing.assert_equal(item.xData, x)
                np.testing.assert_equal(item.yData, y)
            self.assertEqual(len(original[0][0]), 16000)
            self.assertLess(max(delays), .1, f'Trend wheel froze the UI: {delays}')
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_linked_source_update_publishes_one_consistent_selection(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({'Wafer ID': ['W1'] * 3, 'Die Seq': [1, 2, 3],
                                'CD': [1., 2., 3.]})
            window.set_reference_frame(pd.DataFrame({'CD Reference': [3., 5., 7.]}))
            window.set_raw_frame(raw)
            window.run_analysis()
            child = window.open_correlation_workspace()
            app.processEvents()
            updates = []
            child.correlation_page.selector.changed.connect(lambda: updates.append(child.selection))
            window.raw_model.edit({**{(row, 0): 'W2' for row in range(1, 4)}, (1, 2): '1.500'})
            window.run_analysis()
            app.processEvents()
            self.assertEqual(child.raw_model.document_frame().iloc[0, 2], '1.500')
            self.assertEqual(len(updates), 1, 'Published provisional source/selection combinations')
            self.assertEqual(child.raw_model.document_frame()['Wafer ID'].tolist(), ['W2'] * 3)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_warm_stage_switch_and_group_apply_keep_current_results_promptly(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({'Wafer ID': np.repeat([f'W{i}' for i in range(250)], 30),
                                'Die Seq': list(range(1, 31)) * 250})
            ref = pd.DataFrame()
            for i in range(3):
                raw[f'CD{i}'] = np.arange(7500.) + i + 1
                ref[f'CD{i} Reference'] = raw[f'CD{i}'] * 2 + 3
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.run_analysis()
            window.result_mode.setCurrentText('Final')
            window.set_raw_frame(raw.assign(CD0=raw.CD0 + 10))
            window.run_analysis()
            window.resize(1500, 950)
            window.show()
            QTest.qWait(400)
            delays = []
            for mode in ('Preview', 'Final', 'Preview', 'Final'):
                start = perf_counter()
                window.result_mode.setCurrentText(mode)
                app.processEvents()
                delays.append(perf_counter() - start)
                self.assertEqual(window.result.result_mode, mode.lower())
                self.assertAlmostEqual(window.result.card('CD0').slope, 2)
                self.assertAlmostEqual(window.result.card('CD0').intercept, 3 if mode == 'Preview' else -17)
                self.assertEqual(window.result.series('CD0')['Raw'].iat[0], 1 if mode == 'Preview' else 11)
            window.group_controls.order.setCurrentIndex(1)
            start = perf_counter()
            window.group_controls.apply_button.click()
            app.processEvents()
            delays.append(perf_counter() - start)
            self.assertFalse(window.group_controls.pending)
            self.assertEqual(window.result.group_plan.state['trend_order'], 'original')
            self.assertLess(max(delays), .25, f"Warm switch/Apply stalled: {delays}")
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_map_resize_queued_before_explicit_restore_keeps_latest_view(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.window import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        try:
            frame = pd.DataFrame({'Wafer ID': ['W1'] * 6 + ['W2'] * 6,
                                  'Xmm': [-2., -1., 0., 1., 2., 0.] * 2,
                                  'Ymm': [0., 1., 2., 0., -1., -2.] * 2,
                                  'Depth (nm)': np.arange(12.) + 10,
                                  'Thickness (nm)': np.arange(12.) + 20})
            window.resize(1000, 760)
            window.set_table(frame, 'Map view regression')
            window.show()
            window.check_all(window.wafer_list, True)
            window.check_all(window.parameter_list, True)
            page = window.plot_page
            window.tabs.setCurrentWidget(page)
            page.selector.selectAll()
            page.draw_maps()
            deadline = perf_counter() + 15
            while page.worker is not None and perf_counter() < deadline:
                QTest.qWait(10)
            self.assertIsNotNone(page.result)
            page.zoom.setCurrentText('200%')
            QTest.qWait(50)
            page.scroll.horizontalScrollBar().setValue(70)
            saved = page.capture_view()
            self.assertEqual(saved['h'], 70)
            page.zoom.setCurrentText('Fit width')
            page.resize(page.width() + 40, page.height() + 20)
            page.restore_view(saved)
            QTest.qWait(80)
            self.assertEqual(page.zoom.currentText(), '200%')
            self.assertAlmostEqual(page.capture_view()['h'], 70, delta=1)
            pd.testing.assert_frame_equal(window.model.document_frame(), frame.astype(str))
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_large_filtered_raw_selection_and_single_cell_remain_responsive(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.match_group_ui import ProjectedSheetModel
        from metrology_app.sheet import SheetModel, SheetView
        app = QApplication.instance() or QApplication([])
        model = SheetModel()
        raw = pd.DataFrame({f"C{c}": ["1.000"] * 8000 for c in range(33)})
        model.load(raw)
        projected = ProjectedSheetModel(model)
        projected.set_rows(range(7999, -1, -1))
        view = SheetView(projected)
        try:
            view.resize(850, 330)
            view.show()
            app.processEvents()
            delays = []
            for _ in range(3):
                start = perf_counter()
                QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                app.processEvents()
                delays.append(perf_counter() - start)
                self.assertTrue(view.selectionModel().isSelected(projected.index(8000, 32)))
                start = perf_counter()
                cell = projected.index(2, 2)
                QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                                 pos=view.visualRect(cell).center())
                app.processEvents()
                delays.append(perf_counter() - start)
                self.assertEqual(view.selectedIndexes(), [cell])
            pd.testing.assert_frame_equal(model.document_frame(), raw)
            self.assertTrue(model.undo.isClean())
            self.assertLess(max(delays), .1, f"Selection blocked the UI: {delays}")
            # Clear a filtered/reordered range and Undo, without changing the
            # source header or unselected records.
            view.selectAll()
            QTest.keyClick(view, Qt.Key.Key_Delete)
            model.undo.undo()
            pd.testing.assert_frame_equal(model.document_frame(), raw)
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()

    def test_equal_value_mapping_column_change_refreshes_the_raw_title(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({"Ref Reference": [4., 6., 8.]}))
            window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3],
                                              "CD": [1., 2., 3.], "Alias": [1., 2., 3.]}))
            picker = window.mapping_table.cellWidget(0, 3)
            picker.setCurrentText("CD")
            window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            window.run_analysis()
            name = window.mapping_table.item(0, 1).text()
            picker.setCurrentText("Alias")
            app.processEvents()
            self.assertIn("Alias", window.plot_groups[name]["match_title"].text())
            self.assertAlmostEqual(window.result.card(name).slope, 2)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_sheet_clear_ranges_keep_unselected_and_disabled_cells(self):
        from PyQt6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel, SheetView
        app = QApplication.instance() or QApplication([])
        raw = pd.DataFrame({"A": ["1.000", "2.000", "3.000"],
                            "B": ["4.000", "5.000", "6.000"], "C": ["7.000", "8.000", "9.000"]})
        model = SheetModel()
        model.load(raw)
        view = SheetView(model)
        try:
            index = model.index(1, 0)
            self.assertEqual(model.flags(index), QAbstractTableModel.flags(model, index) | Qt.ItemFlag.ItemIsEditable)
            view.selectionModel().select(QItemSelection(model.index(1, 0), model.index(2, 1)),
                                         QItemSelectionModel.SelectionFlag.ClearAndSelect)
            QTest.keyClick(view, Qt.Key.Key_Backspace)
            expected = raw.copy()
            expected.iloc[:2, :2] = ""
            pd.testing.assert_frame_equal(model.document_frame(), expected)
            model.undo.undo()
            pd.testing.assert_frame_equal(model.document_frame(), raw)
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()

        class ProtectedSheet(SheetModel):
            def flags(self, index):
                if (index.row(), index.column()) == (2, 1):
                    return Qt.ItemFlag.NoItemFlags
                return super().flags(index)

        protected = ProtectedSheet()
        protected.load(raw)
        view = SheetView(protected)
        try:
            view.selectAll()
            QTest.keyClick(view, Qt.Key.Key_Delete)
            self.assertEqual(protected.cells, {(2, 1): "5.000"})
            protected.undo.undo()
            pd.testing.assert_frame_equal(protected.document_frame(), raw)
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()

    def test_mapping_use_keeps_surviving_curves_and_views_while_analysis_updates(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300})
            reference = pd.DataFrame()
            for index in range(3):
                raw[f"CD{index}"] = np.arange(6000.) + index + 1
                reference[f"CD{index} Reference"] = raw[f"CD{index}"] * 1.03 + 2
            window.set_reference_frame(reference)
            window.set_raw_frame(raw)
            window.run_analysis()
            removed_name = window.mapping_table.item(0, 1).text()
            kept_name = window.mapping_table.item(1, 1).text()
            kept = window.plot_groups[kept_name]
            curve = kept["plots"]["trend"]
            curve.getViewBox().setRange(xRange=(100, 300), yRange=(105, 310), padding=0)
            zoom = curve.getViewBox().viewRange()
            window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
            app.processEvents()
            self.assertNotIn(removed_name, window.result.parameter_names)
            self.assertIs(window.plot_groups[kept_name]["card"], kept["card"])
            np.testing.assert_allclose(curve.getViewBox().viewRange(), zoom)
            self.assertAlmostEqual(window.result.card(kept_name).slope, 1.03)
            window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            app.processEvents()
            self.assertEqual(len(window.result.parameter_names), 3)
            self.assertIs(window.plot_groups[kept_name]["card"], kept["card"])
            np.testing.assert_allclose(curve.getViewBox().viewRange(), zoom)
            self.assertEqual(len(window.raw_model.document_frame()), 6000)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_raw_select_all_clear_and_undo_keeps_exact_cells_promptly(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel, SheetView
        app = QApplication.instance() or QApplication([])
        model = SheetModel()
        raw = pd.DataFrame({f"Column {column}": [f"{row + column}.000" for row in range(6000)]
                            for column in range(33)})
        model.load(raw)
        view = SheetView(model)
        try:
            view.resize(800, 400)
            view.show()
            app.processEvents()
            QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            ranges = view.selectionModel().selection()
            self.assertEqual(sum(cell.width() * cell.height() for cell in ranges), (len(raw) + 1) * len(raw.columns))
            start = perf_counter()
            QTest.keyClick(view, Qt.Key.Key_Delete)
            elapsed = perf_counter() - start
            self.assertFalse(model.cells)
            self.assertEqual(model.snapshot()[0][(6000, 0)], "")
            self.assertTrue(model.preserves_record_positions)
            QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            pd.testing.assert_frame_equal(model.document_frame(), raw)
            self.assertLess(elapsed, .6, f"Clearing selected Raw cells stalled for {elapsed:.3f}s")
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()

    def test_trend_font_changes_keep_curves_views_and_export_labels_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        child = CorrelationWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            raw["Thickness"] = raw["CD"] * 2 + 3
            reference = pd.DataFrame({"Ref": raw["CD"] * 1.03 + 2,
                                      "Thickness Ref": raw["Thickness"] * 1.03 + 2})
            mappings = [ParameterMapping("CD", "Ref", "CD"),
                        ParameterMapping("Thickness", "Thickness Ref", "Thickness")]
            child.set_sources(reference, raw, mappings)
            child.set_workbook_groups(MatchWorkbook(reference, raw, mappings,
                test_flags=pd.DataFrame({"TestFlag": [0] * len(raw)}),
                grouping_state={"enabled": True, "mark_enabled": False}))
            page = child.sequence_page
            page.draw_plot()
            child.tabs.setCurrentWidget(page)
            child.resize(1500, 950)
            child.show()
            app.processEvents()
            curves = [(item.xData.copy(), item.yData.copy()) for plot in page.plot_widgets
                      for item in plot.getPlotItem().listDataItems()]
            page.plot_widgets[0].getViewBox().setRange(xRange=(200, 400), yRange=(205, 405), padding=0)
            app.processEvents()
            zoom = page.plot_widgets[0].getViewBox().viewRange()
            labels = [(plot.getPlotItem().getAxis(name).labelText,
                       plot.getPlotItem().getAxis(name).labelUnits)
                      for plot in page.plot_widgets for name in ("left", "bottom")]
            start = perf_counter()
            page.font_size.setCurrentText("16")
            elapsed = perf_counter() - start
            self.assertLess(elapsed, .15, f"Changing Trend font blocked for {elapsed:.3f}s")
            app.processEvents()
            np.testing.assert_allclose(page.plot_widgets[0].getViewBox().viewRange(), zoom)
            self.assertEqual([(plot.getPlotItem().getAxis(name).labelText,
                               plot.getPlotItem().getAxis(name).labelUnits)
                              for plot in page.plot_widgets for name in ("left", "bottom")], labels)
            after = [item for plot in page.plot_widgets for item in plot.getPlotItem().listDataItems()]
            self.assertEqual(len(after), len(curves))
            for item, (x, y) in zip(after, curves):
                np.testing.assert_equal(item.xData, x)
                np.testing.assert_equal(item.yData, y)
            page.ensure_export_figure()
            self.assertEqual(page.figure.axes[0].title.get_fontsize(), 17)
            self.assertEqual(page.figure.axes[0].get_xlabel(), "Die Seq")
        finally:
            child.document.force_close = True
            child.close()
            child.deleteLater()
            app.processEvents()

    def test_large_participation_validation_keeps_exact_exclusions_promptly(self):
        from metrology_app.match_groups import row_ids
        raw = pd.DataFrame({"Wafer ID": ["W001"] * 10000,
                            "Die Seq": np.arange(1, 10001), "CD": np.arange(1., 10001.)})
        reference = pd.DataFrame({"Ref": raw["CD"] * 1.03 + 2})
        state = {"data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(raw))],
                                     "excluded": [str(i) for i in range(8000)]}}
        start = perf_counter()
        book = MatchWorkbook(reference, raw, [ParameterMapping("CD", "Ref", "CD")], grouping_state=state)
        elapsed = perf_counter() - start
        result = book.analyze()
        self.assertEqual(result.source_rows, tuple(range(8000, 10000)))
        self.assertEqual(result.card("CD").valid_pairs, 2000)
        self.assertAlmostEqual(result.card("CD").slope, 1.03)
        self.assertEqual(state["data_selection"]["excluded"], [str(i) for i in range(8000)])
        with self.assertRaisesRegex(ValueError, "unique source row identities"):
            MatchWorkbook(reference, raw, [ParameterMapping("CD", "Ref", "CD")],
                          grouping_state={"data_selection": {**state["data_selection"], "excluded": ["unknown"]}})
        self.assertLess(elapsed, .08, f"Participation validation blocked large filters: {elapsed:.3f}s")

    def test_saved_wide_workbook_dirty_checks_preserve_the_accepted_state_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_document import same_snapshot
        from metrology_app.match_groups import row_ids
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            for column in range(30):
                raw[f"Unmapped parameter {column}"] = np.arange(6000.) + column
            window.set_reference_frame(pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": False,
                "data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(raw))],
                                   "excluded": ["19"]}},
                                          pd.DataFrame({"TestFlag": [0] * len(raw)}))
            window.run_analysis()
            with tempfile.TemporaryDirectory() as directory:
                child = window.open_correlation_workspace()
                child.check_all(child.parameter_list, True)
                window.save_workbook(Path(directory) / "accepted.wkb")
                child.document.force_close = True
                child.close()
                child.deleteLater()
                app.processEvents()
                accepted = window.workspace_snapshot()
                times = []
                for _ in range(3):
                    start = perf_counter()
                    window.document.refresh_identity()
                    times.append(perf_counter() - start)
                    self.assertFalse(window.isWindowModified())
                self.assertTrue(same_snapshot(window.document.baseline, accepted))
                self.assertEqual(window.raw_model.document_frame().iloc[0]["CD"], "1.0")
                self.assertLess(min(times), .10, f"Dirty-title checks blocked unchanged controls: {times}")
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_wafer_window_opens_with_current_cards_and_uses_new_coefficients_after_edit(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.window import MainWindow as WaferWindow
        from metrology_app.match_groups import row_ids
        app = QApplication.instance() or QApplication([])
        # First-use imports are measured by the fresh-process window harness.
        # This public factory seam times opening with those modules loaded.
        window = MatchingWindow(wafer_window_factory=WaferWindow)
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            for column in range(30):
                raw[f"Unmapped parameter {column}"] = np.arange(6000.) + column
            window.set_reference_frame(pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": False,
                "data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(raw))],
                                   "excluded": ["19"]}}, pd.DataFrame({"TestFlag": [0] * len(raw)}))
            window.run_analysis()
            start = perf_counter()
            child = window.open_stage_workspace("preview")
            elapsed = perf_counter() - start
            self.assertAlmostEqual(child.parameter_cards["CD"][0], 1.03)
            self.assertAlmostEqual(child.parameter_cards["CD"][1], 2)
            self.assertEqual(len(child.model.document_frame()), 5999)
            child.document.force_close = True
            child.close()
            child.deleteLater()
            matrix = [list(raw.columns)] + raw.assign(CD=raw["CD"] * 2).astype(str).values.tolist()
            window.raw_model.replace_matrix(matrix)
            # Do not process the queued analysis: opening a child immediately
            # after an edit must not borrow the earlier fitted Card.
            updated = window.open_stage_workspace("preview")
            self.assertAlmostEqual(updated.parameter_cards["CD"][0], .515)
            self.assertAlmostEqual(updated.parameter_cards["CD"][1], 2)
            self.assertEqual(float(updated.model.document_frame().iloc[0]["CD"]), 2)
            self.assertLess(elapsed, .4, f"Opening Wafer Map stalled for {elapsed:.3f}s")
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_many_column_measurements_keep_exact_rows_and_die_details_promptly(self):
        from metrology_app.measurements import detect_measurements
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(600)], 20),
                            "Lot ID": "L01", "PAD Name": "ARRAY",
                            "Die Seq": list(range(1, 21)) * 600})
        for column in range(60):
            raw[f"Unmapped column {column}"] = "original value"
        raw.index = np.arange(len(raw)) * 3 + 7
        timings = []
        for _ in range(3):
            start = perf_counter()
            measurements = detect_measurements(raw, "Wafer ID", ["Wafer ID"])
            timings.append(perf_counter() - start)
        self.assertEqual(len(measurements), 600)
        self.assertEqual(measurements[0].rows, tuple(range(20)))
        self.assertEqual(measurements[-1].rows, tuple(range(11980, 12000)))
        self.assertEqual(measurements[0].label, "W000")
        self.assertIn("Die Seq: 1–20 (20 unique)", measurements[-1].detail)
        self.assertEqual(raw.iloc[0]["Unmapped column 59"], "original value")
        self.assertLess(min(timings), .15, f"Measurement identity scanned unrelated columns: {timings}")

    def setUp(self):
        import gc
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QApplication
        # processEvents alone does not deliver DeferredDelete. Dispose earlier
        # GUI fixtures before timing this workflow, without disabling GC or
        # removing any work from the action being measured.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def test_repeated_recovery_checks_keep_the_current_draft_without_a_long_pause(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.match_groups import row_ids
        from metrology_app.workspace_store import load_workspace
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            for column in range(30):
                raw[f"Additional parameter {column}"] = np.arange(6000.) + column + 1
            window.set_reference_frame(pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": False,
                "data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(raw))],
                                   "excluded": ["19"]}}, pd.DataFrame({"TestFlag": [0] * len(raw)}))
            window.run_analysis()
            with tempfile.TemporaryDirectory() as directory:
                child = window.open_correlation_workspace()
                child.check_all(child.parameter_list, True)
                window.save_workbook(Path(directory) / "accepted.wkb")
                child.document.force_close = True
                child.close()
                child.deleteLater()
                app.processEvents()
                window.raw_model.edit({(1, 2): "9.9990"})
                app.processEvents()
                window.document.recovery_path = Path(directory) / "draft.wkb"
                window.document.write_recovery()
                stamp = window.document.recovery_path.stat().st_mtime_ns
                times = []
                for _ in range(3):
                    start = perf_counter()
                    window.document.write_recovery()
                    times.append(perf_counter() - start)
                recovered = load_workspace(window.document.recovery_path)
                self.assertEqual(recovered.frames["raw"].iloc[0, 2], "9.9990")
                self.assertEqual(recovered.states["match"]["grouping_state"]["data_selection"]["excluded"], ["19"])
                self.assertEqual(window.document.recovery_path.stat().st_mtime_ns, stamp)
                from metrology_app.settings import get_settings
                self.assertEqual(window.document.timer.interval(), get_settings()["recovery_interval_seconds"] * 1000)
                self.assertLess(max(times), .25, f"Repeated recovery checks stalled: {times}")
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_disposed_plot_releases_its_native_menus_and_secondary_view(self):
        import pyqtgraph as pg
        from PyQt6 import sip
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
        from unittest.mock import patch
        from metrology_app.plotting import InteractivePlotWidget
        app = QApplication.instance() or QApplication([])
        host = QWidget()
        layout = QVBoxLayout(host)
        plot = InteractivePlotWidget()
        layout.addWidget(plot)
        plot.plot([1, 2, 3], [2, 4, 6])
        secondary = plot.add_secondary_axis("Thickness", "#ed7d31")
        secondary.addItem(pg.PlotDataItem([1, 2, 3], [3, 6, 9]))
        menus = [plot.getPlotItem().getMenu(), plot.getViewBox().getMenu(None), secondary.getMenu(None)]
        self.assertTrue(all(menu.actions() for menu in menus), "Native plot options must remain available")
        host.deleteLater()
        callback_errors = []
        with patch('sys.excepthook', side_effect=lambda *error: callback_errors.append(error)):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(callback_errors, [], 'Plot disposal raised a Qt callback error')
        self.assertTrue(sip.isdeleted(plot))
        self.assertTrue(all(sip.isdeleted(menu) for menu in menus), "Disposed plots left live native menus")
        app.processEvents()

    def test_saved_correlation_restores_complete_grouped_plots_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        child, restored = CorrelationWindow(), CorrelationWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            raw["Thickness"] = raw["CD"] * 2 + 3
            # Real workbooks retain many unmapped model columns in Raw Data.
            # Restoring two selected parameters must still preserve all of them.
            for column in range(29):
                raw[f"Unmapped parameter {column}"] = np.arange(6000.) + column
            reference = pd.DataFrame({"Ref": raw["CD"] * 1.03 + 2})
            reference["Thickness Ref"] = raw["Thickness"] * 1.03 + 2
            mappings = [ParameterMapping("CD", "Ref", "CD"),
                        ParameterMapping("Thickness", "Thickness Ref", "Thickness")]
            book = MatchWorkbook(reference, raw, mappings,
                                 test_flags=pd.DataFrame({"TestFlag": [0] * 6000}),
                                 grouping_state={"enabled": True, "mark_enabled": False})
            child.set_sources(reference, raw, mappings)
            child.set_workbook_groups(book)
            child.correlation_page.draw_plot()
            child.sequence_page.draw_plot()
            child.tabs.setCurrentWidget(child.sequence_page)
            self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
            self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
            snapshot = child.workspace_snapshot()
            expected_cor = child.correlation_page.selector.selected_cells()
            expected_trend = child.sequence_page.selector.selected_cells()
            # A managed child has Workbook-derived tables before its saved
            # document configuration and independent source frames are restored.
            restored.set_sources(reference, raw, mappings)
            restored.set_workbook_groups(book)
            start = perf_counter()
            restored.restore_workspace(snapshot)
            elapsed = perf_counter() - start
            self.assertTrue(restored.correlation_page.ready)
            self.assertTrue(restored.sequence_page.ready)
            self.assertEqual(restored.tabs.currentWidget(), restored.sequence_page)
            self.assertEqual(restored.correlation_page.selector.selected_cells(), expected_cor)
            self.assertEqual(restored.sequence_page.selector.selected_cells(), expected_trend)
            self.assertEqual(len(restored.correlation_page.all_fits), 2)
            for pair in restored.correlation_page.all_fits:
                for source in pair.sources:
                    self.assertEqual(len(source.fit.x), 6000)
                    self.assertAlmostEqual(source.fit.slope, 2)
                    self.assertAlmostEqual(source.fit.intercept, 3 if source.name == "Raw Data" else 1.09)
            self.assertEqual(sum(len(group["positions"]) for group in restored.sequence_page.groups), 12000)
            pd.testing.assert_frame_equal(restored.raw_model.document_frame(), child.raw_model.document_frame())
            self.assertLess(elapsed, 2.0, f"Restoring saved Correlation plots stalled for {elapsed:.3f}s")
        finally:
            for window in (child, restored):
                window.document.timer.stop()
                window.document.identity_timer.stop()
                window.document.force_close = True
                window.close()
                window.deleteLater()
            app.processEvents()

    def test_reused_group_plots_change_instrument_axis_and_legend_together(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.match_type.setCurrentText("NOVA")
            window.set_reference_frame(pd.DataFrame({"CD Reference": [4., 6., 8.]}))
            window.set_raw_frame(pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}))
            window.group_controls.restore({"enabled": True, "mark_enabled": False},
                                          pd.DataFrame({"TestFlag": [0, 0, 0]}))
            window.run_analysis()
            window.match_type.setCurrentText("KLA")
            window.run_analysis()
            block = window.group_plot_page.plot_groups[("All:0", "CD")]
            self.assertEqual(block["plots"]["match"].getAxis("left").labelText, "KLA")
            self.assertEqual({curve.name() for curve in block["plots"]["trend"].listDataItems()}, {"KLA", "PMISH"})
            self.assertAlmostEqual(window.result.card("CD").slope, 2)
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_export_immediately_after_edit_uses_current_data_and_card(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({"CD Reference": [4., 6., 8.]}))
            window.set_raw_frame(pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}))
            window.run_analysis()
            window.raw_model.edit({(1, 2): "2.000", (2, 2): "3.000", (3, 2): "4.000"})
            # Do not process the queued auto-analysis before the user's export.
            with tempfile.TemporaryDirectory() as folder:
                path = window.export_excel(Path(folder) / "immediate.xlsx")
                summary = pd.read_excel(path, sheet_name="Summary")
                saved_raw = pd.read_excel(path, sheet_name="Raw Data", dtype=str)
                self.assertAlmostEqual(summary.iloc[0]["Slope"], 2)
                self.assertAlmostEqual(summary.iloc[0]["Intercept"], 0)
                self.assertEqual(saved_raw["CD"].tolist(), ["2.000", "3.000", "4.000"])
            app.processEvents()
            self.assertAlmostEqual(window.result.card("CD").intercept, 0)
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_correlation_checkbox_changes_keep_exact_sources_and_are_prompt(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        child = CorrelationWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(600)], 10),
                                "Die Seq": list(range(1, 11)) * 600})
            reference = pd.DataFrame()
            mappings = []
            for column in range(3):
                name = f"CD{column}"
                raw[name] = np.arange(6000.) + column + 1
                reference[f"Ref{column}"] = raw[name] * 1.03 + 2
                mappings.append(ParameterMapping(name, f"Ref{column}", name))
            book = MatchWorkbook(reference, raw, mappings,
                                 test_flags=pd.DataFrame({"TestFlag": ([0] * 5 + [1] * 5) * 600}),
                                 grouping_state={"enabled": True, "mark_enabled": False})
            child.set_sources(reference, raw, mappings)
            child.set_workbook_groups(book)
            elapsed = []
            item = child.wafer_list.topLevelItem(0)
            key = item.data(0, Qt.ItemDataRole.UserRole)
            for state in (Qt.CheckState.Unchecked, Qt.CheckState.Checked):
                start = perf_counter()
                item.setCheckState(0, state)
                elapsed.append(perf_counter() - start)
                self.assertEqual(("Raw Data", key) in child.selection["wafers"], state == Qt.CheckState.Checked)
                self.assertEqual(sum(map(len, child.sequence_page.selection["groups"].values())),
                                 11990 if state == Qt.CheckState.Unchecked else 12000)
            parameter = next(child.parameter_list.topLevelItem(i) for i in range(child.parameter_list.topLevelItemCount())
                             if child.parameter_list.topLevelItem(i).text(0) == "CD0")
            for state in (Qt.CheckState.Unchecked, Qt.CheckState.Checked):
                start = perf_counter()
                parameter.setCheckState(0, state)
                elapsed.append(perf_counter() - start)
                selected = state == Qt.CheckState.Checked
                self.assertEqual((("Raw Data", key), "CD0") in child.selection["available_cells"], selected)
                self.assertIn((("Reference", key), "CD0"), child.selection["available_cells"])
            self.assertFalse(child.correlation_page.has_drawn_once)
            self.assertFalse(child.sequence_page.has_drawn_once)
            self.assertEqual(len(child.raw_model.document_frame()), 6000)
            self.assertLess(max(elapsed), .15, f"Correlation check/uncheck stalled: {elapsed}")
        finally:
            child.document.timer.stop()
            child.document.identity_timer.stop()
            child.document.force_close = True
            child.close()
            child.deleteLater()
            app.processEvents()

    def test_hidden_group_plots_show_latest_replacement_and_undo_without_blocking_edit(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.match_type.setCurrentText("NOVA")
            x = np.arange(1., 6001.)
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": x})
            for column in range(30):
                raw[f"Metadata {column}"] = "retained"
            window.set_reference_frame(pd.DataFrame({"CD Reference": x * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": False,
                "combined_groups": [{"id": "combined:ab", "name": "Heads A+B", "members": ["All:0", "All:1"]}]},
                pd.DataFrame({"TestFlag": np.repeat([0, 1, 2] * 100, 20)}))
            window.run_analysis()
            window.resize(1500, 950)
            window.show()
            app.processEvents()
            page = window.group_plot_page
            self.assertFalse(page.isVisible())
            timings = []
            for delta in (.01, .02, .03):
                matrix = [list(raw.columns)] + raw.assign(CD=x + delta).astype(str).values.tolist()
                start = perf_counter()
                window.raw_model.replace_matrix(matrix)
                app.processEvents()
                timings.append(perf_counter() - start)
            self.assertAlmostEqual(window.result.card("CD").slope, 1.03)
            self.assertAlmostEqual(window.result.card("CD").intercept, 2 - 1.03 * .03)
            window.results_tabs.setCurrentWidget(page)
            app.processEvents()
            self.assertTrue(page.isVisible())
            self.assertEqual(set(page.plot_groups), {(key, "CD") for key in ("All:0", "All:1", "All:2", "combined:ab")})
            np.testing.assert_allclose(page.plot_groups[("All:0", "CD")]["plots"]["match"].listDataItems()[0].xData[:20],
                                       np.arange(1., 21.) + .03)
            window.results_tabs.setCurrentIndex(0)
            window.raw_model.undo.undo()
            app.processEvents()
            # Export must refresh the hidden page too, without needing a tab click.
            self.assertFalse(page.page_image().isNull())
            np.testing.assert_allclose(page.plot_groups[("All:0", "CD")]["plots"]["match"].listDataItems()[0].xData[:20],
                                       np.arange(1., 21.) + .02)
            window.results_tabs.setCurrentWidget(window.wafer_groups_widget)
            app.processEvents()
            np.testing.assert_allclose(window.plot_groups["CD"]["wafer_model"].frame["Intercept"],
                                       2 - 1.03 * .02, atol=1e-8)
            self.assertLess(max(timings), .65, f"Hidden Group redraw blocked editing: {timings}")
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_measurement_metadata_is_reused_only_within_one_analysis_result(self):
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:04}" for i in range(1000)], 6),
                            "Lot ID": "L0", "PAD Name": "ARRAY",
                            "Die Seq": [1, 2, 3, 4, 5, 6] * 1000, "CD": np.arange(6000.) + 1})
        for column in range(28):
            raw[f"Metadata {column}"] = "retained"
        book = MatchWorkbook(pd.DataFrame({"Ref": raw["CD"] * 1.03 + 2}), raw,
                             [ParameterMapping("CD", "Ref", "CD")])
        result = book.analyze()
        first = result.wafer_summary("CD")
        self.assertEqual(len(first), 1000)
        self.assertAlmostEqual(first.iloc[0]["Slope"], 1.03)
        self.assertAlmostEqual(first.iloc[0]["Intercept"], 2)
        self.assertEqual(first.iloc[0]["Valid pairs"], 6)
        start = perf_counter()
        for _ in range(5):
            spans = result.measurement_spans()
            self.assertEqual(len(spans), 1000)
            self.assertEqual(spans[0], (.5, 6.5, "W0000\nL0\nARRAY"))
        elapsed = perf_counter() - start
        reference, wafer = result.wafer_frames(0)
        wafer.iloc[0, 0] = "caller edit"
        self.assertEqual(result.wafer_frames(0)[1].iloc[0, 0], "W0000")
        book.raw.loc[:5, "Wafer ID"] = "Changed wafer"
        fresh = book.analyze()
        self.assertEqual(fresh.measurement_spans()[0][2], "Changed wafer\nL0\nARRAY")
        self.assertEqual(result.measurement_spans()[0][2], "W0000\nL0\nARRAY")
        self.assertLess(elapsed, .25, f"Repeated measurement labels stalled for {elapsed:.3f}s")

    def test_repeated_source_snapshots_are_fast_detached_and_follow_undo(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel
        app = QApplication.instance() or QApplication([])
        model = SheetModel()
        matrix = [["Wafer ID", "CD", *[f"Metadata {i}" for i in range(31)]]]
        matrix += [["001", "1.000", *["retained"] * 31] for _ in range(6000)]
        matrix.append([""] * 33)
        model.load_matrix(matrix)
        expected = model.document_frame()
        # Warm once; repeated Save/dirty/child reads must not rebuild each cell.
        model.frame()
        start = perf_counter()
        for _ in range(5):
            saved, analysis = model.document_frame(), model.frame()
            self.assertEqual(len(saved), 6001)
            self.assertEqual(len(analysis), 6000)
        elapsed = perf_counter() - start
        saved.iloc[0, 1] = "caller edit"
        analysis.iloc[0, 1] = "another caller edit"
        pd.testing.assert_frame_equal(model.document_frame(), expected)
        model.edit({(1, 1): "2.1000", (6001, 1): "9.999"})
        self.assertEqual(model.document_frame().iloc[0, 1], "2.1000")
        self.assertEqual(len(model.frame()), 6001)
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), expected)
        self.assertEqual(len(model.frame()), 6000)
        model.replace_matrix([["Wafer ID", "CD"], ["002", "3.1400"]])
        self.assertEqual(model.frame().iloc[0].tolist(), ["002", "3.1400"])
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), expected)
        self.assertLess(elapsed, .1, f"Repeated source snapshots stalled for {elapsed:.3f}s")
        model.deleteLater()
        app.processEvents()

    def test_loaded_correlation_stays_responsive_and_later_source_edits_still_refresh(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        child = CorrelationWindow()
        heartbeat = QTimer(interval=10)
        try:
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(300)], 20),
                                "Die Seq": list(range(1, 21)) * 300, "CD": np.arange(6000.) + 1})
            for column in range(30):
                raw[f"Metadata {column}"] = "retained source"
            reference = pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2})
            child.set_sources(reference, raw, [ParameterMapping("CD", "CD Reference", "CD")])
            gaps, previous = [], perf_counter()
            def tick():
                nonlocal previous
                now = perf_counter()
                gaps.append(now - previous)
                previous = now
            heartbeat.timeout.connect(tick)
            heartbeat.start()
            loop = QEventLoop()
            QTimer.singleShot(700, loop.quit)
            loop.exec()
            heartbeat.stop()
            maximum_gap = max(gaps)
            child.raw_model.edit({(1, 2): "9.999"})
            QTimer.singleShot(700, loop.quit)
            loop.exec()
            self.assertEqual(child.sequence_page.frame.iloc[len(raw), 3], "9.999")
            self.assertEqual(len(child.raw_model.document_frame()), 6000)
            self.assertLess(maximum_gap, .1, f"Loaded Correlation stalled again for {maximum_gap:.3f}s")
        finally:
            heartbeat.stop()
            child.document.timer.stop()
            child.document.identity_timer.stop()
            child.document.force_close = True
            child.close()
            child.deleteLater()
            app.processEvents()

    def test_many_measurement_trend_spans_keep_stable_die_order_promptly(self):
        count = 2000
        raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:04}" for i in range(count)], 4),
                            "Die Seq": [4, 1, 3, 2] * count, "CD": np.arange(count * 4.)})
        for column in range(30):
            raw[f"Metadata {column}"] = "untouched"
        reference = pd.DataFrame({"Ref": raw["CD"] * 1.03 + 2})
        book = MatchWorkbook(reference, raw, [ParameterMapping("CD", "Ref", "CD")],
                             test_flags=pd.DataFrame({"TestFlag": [0] * len(raw)}),
                             grouping_state={"enabled": True, "mark_enabled": False,
                                             "head_names": {"0": "Head A"}})
        result = book.analyze()
        start = perf_counter()
        spans = result.group_plan.trend_spans()
        elapsed = perf_counter() - start
        self.assertEqual(len(spans), count)
        self.assertEqual(spans[0]["rows"], [1, 3, 2, 0])
        self.assertEqual(spans[-1]["rows"], [7997, 7999, 7998, 7996])
        self.assertEqual(spans[0]["label"], "Head A\nW0000")
        self.assertLess(elapsed, .15, f"Trend ordering stalled for {elapsed:.3f}s")

    def test_managed_correlation_dirty_check_keeps_baseline_and_undo_promptly(self):
        from copy import deepcopy
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.match_groups import row_ids
        from metrology_app.workspace_document import same_snapshot
        app = QApplication.instance() or QApplication([])
        owner = MatchingWindow()
        child = CorrelationWindow()
        try:
            rows = 6000
            raw = pd.DataFrame({"Wafer ID": "001", "Die Seq": np.arange(rows), "CD": np.arange(rows) + 1.})
            for column in range(30):
                raw[f"Metadata {column}"] = "retained source"
            reference = pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2})
            mappings = [ParameterMapping("CD", "CD Reference", "CD")]
            records = [{"key": key, "id": str(row)} for row, key in enumerate(row_ids(raw))]
            book = MatchWorkbook(reference, raw, mappings, grouping_state={
                "enabled": False, "mark_enabled": True,
                "data_selection": {"records": records, "excluded": ["5"]}})
            child.set_sources(reference, raw, mappings)
            child.set_workbook_groups(book)
            # Ownership only changes which UI fields count as local edits.
            child.configure_workbook_owner(owner, "correlation.preview")
            child.document.mark_clean()
            child.document.identity_timer.stop()
            baseline = deepcopy(child.document.baseline)
            start = perf_counter()
            for _ in range(3):
                self.assertFalse(child.document.is_dirty())
            elapsed = perf_counter() - start
            child.set_second_axis_ratio(2.75)
            self.assertFalse(child.document.is_dirty(), "Shared axes are not child-local edits")
            child.raw_model.edit({(1, 2): "9.999"})
            self.assertTrue(child.document.is_dirty())
            child.raw_model.undo.undo()
            self.assertFalse(child.document.is_dirty())
            self.assertTrue(same_snapshot(child.document.baseline, baseline), "Dirty checks must not modify the baseline")
            self.assertLess(elapsed, .35, f"Read-only dirty checks stalled for {elapsed:.3f}s")
        finally:
            child._managed_owner = None
            child.document.timer.stop()
            child.document.identity_timer.stop()
            child.document.force_close = True
            child.close()
            child.deleteLater()
            owner.document.timer.stop()
            owner.document.identity_timer.stop()
            owner.document.force_close = True
            owner.close()
            owner.deleteLater()
            app.processEvents()

    def test_large_plot_selection_preserves_disabled_cells_and_exact_choices_promptly(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.map_selector import MapSelector
        app = QApplication.instance() or QApplication([])
        selector = MapSelector()
        try:
            wafers = [f"W{i:04}" for i in range(2000)]
            metrics = [f"CD {i}" for i in range(8)]
            enabled = {(wafer, metric) for row, wafer in enumerate(wafers)
                       for column, metric in enumerate(metrics) if column % 2 == row % 2}
            start = perf_counter()
            selector.set_array(wafers, metrics, enabled_cells=enabled)
            elapsed = perf_counter() - start
            self.assertEqual(selector.selected_cells(), enabled)
            chosen = {("W0000", "CD 0"), ("W1999", "CD 7"), ("W0010", "CD 2")}
            selector.set_selected_cells(chosen)
            self.assertEqual(selector.selected_cells(), chosen)
            self.assertTrue(selector.pending_draw)
            selector.set_array(wafers, metrics, {"W0000": "Renamed label"}, enabled)
            self.assertEqual(selector.selected_cells(), chosen)
            selector.set_selected_cells(set())
            self.assertFalse(selector.selected_cells())
            self.assertLess(elapsed, .75, f"Plot selection initialization stalled for {elapsed:.3f}s")
        finally:
            selector.deleteLater()
            app.processEvents()

    def test_grouped_trend_keeps_die_values_with_many_rows_without_slow_label_preparation(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            window.match_type.setCurrentText("NOVA")
            die = np.tile(np.arange(1, 21), 450)
            raw = pd.DataFrame({"Wafer ID": np.repeat([f"W{i:03}" for i in range(450)], 20),
                                "Lot ID": "001", "PAD Name": "ARRAY", "Die Seq": die,
                                "CD": np.arange(9000.) + 1})
            for column in range(28):
                raw[f"Additional {column}"] = np.arange(9000.)
            window.set_reference_frame(pd.DataFrame({"CD Reference": raw["CD"] * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": False},
                                          pd.DataFrame({"TestFlag": [0] * len(raw)}))
            start = perf_counter()
            window.run_analysis()
            elapsed = perf_counter() - start
            self.assertAlmostEqual(window.result.card("CD").slope, 1.03)
            trend = window.plot_groups["CD"]["plots"]["trend"]
            lines = {item.name(): item for item in trend.listDataItems()}
            np.testing.assert_allclose(lines["NOVA"].yData, np.arange(1., 9001.) * 1.03 + 2)
            self.assertEqual(trend._group_tick_data[0][:22],
                             [str(i) for i in range(1, 21)] + ["1", "2"])
            self.assertLess(elapsed, 1.5, f"Grouped Trend preparation stalled for {elapsed:.3f}s")
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_unclassified_selected_record_stays_excluded_after_clear_and_undo(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.match_groups import row_ids
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            x = np.arange(1., 13.)
            raw = pd.DataFrame({"Wafer ID": ["W1"] * 6 + ["W2"] * 6,
                                "Die Seq": list(range(1, 7)) * 2, "CD": x})
            window.set_reference_frame(pd.DataFrame({"CD Reference": x * 1.03 + 2}))
            window.set_raw_frame(raw)
            window.group_controls.restore({
                "enabled": False, "mark_enabled": False,
                "data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(raw))],
                                   "excluded": ["1", "5", "6", "11"]}})
            window.run_analysis()
            expected_rows = (0, 2, 3, 4, 7, 8, 9, 10)
            for sheet_row in (2, 12):
                with self.subTest(sheet_row=sheet_row):
                    window.raw_model.edit({(sheet_row, column): "" for column in range(3)})
                    app.processEvents()
                    self.assertEqual(len(window.raw_frame), 12, "Blank selected source rows must not disappear")
                    self.assertEqual(window.group_controls.state["data_selection"]["excluded"], ["1", "5", "6", "11"])
                    self.assertEqual(window.result.source_rows, expected_rows)
                    self.assertTrue(window._analysis_current)
                    if sheet_row == 12:
                        with tempfile.TemporaryDirectory(prefix="metrology-blank-tail-") as scratch:
                            path = window.current_workbook().save(Path(scratch) / "blank-tail.wkb")
                            restored = MatchWorkbook.load(path)
                            self.assertEqual(len(restored.raw), 12)
                            self.assertEqual(restored.analyze().source_rows, expected_rows)
                            from metrology_app.sheet import SheetModel
                            reopened_sheet = SheetModel()
                            reopened_sheet.load(restored.raw)
                            self.assertEqual(len(reopened_sheet.document_frame()), 12)
                    window.raw_model.undo.undo()
                    app.processEvents()
                    self.assertEqual(window.group_controls.state["data_selection"]["excluded"], ["1", "5", "6", "11"])
                    self.assertEqual(window.result.source_rows, expected_rows)
                    self.assertEqual(window.result.card("CD").valid_pairs, 8)
                    self.assertAlmostEqual(window.result.card("CD").intercept, 2)
            # Two empty identities must not borrow the same participation ID.
            for sheet_row in (12, 2):
                window.raw_model.edit({(sheet_row, column): "" for column in range(3)})
                app.processEvents()
            self.assertEqual([record["id"] for record in window.group_controls.state["data_selection"]["records"]],
                             [str(i) for i in range(12)])
            self.assertTrue(window._analysis_current)
            self.assertEqual(window.result.source_rows, expected_rows)
            for _ in range(2):
                window.raw_model.undo.undo()
                app.processEvents()
            self.assertEqual(window.result.source_rows, expected_rows)
            self.assertEqual(window.group_controls.state["data_selection"]["excluded"], ["1", "5", "6", "11"])
            # Appending does not move an existing record's position either.
            window.raw_model.edit({(12, column): "" for column in range(3)})
            app.processEvents()
            window.set_reference_frame(pd.DataFrame({"CD Reference": np.arange(1., 14.) * 1.03 + 2}))
            window.raw_model.edit({(2, column): "" for column in range(3)}
                                  | {(13, 0): "W3", (13, 1): "1", (13, 2): "13"})
            app.processEvents()
            records = window.group_controls.state["data_selection"]["records"]
            self.assertEqual([record["id"] for record in records[:12]], [str(i) for i in range(12)])
            self.assertNotIn(records[12]["id"], {str(i) for i in range(12)})
            self.assertEqual(window.result.source_rows, expected_rows + (12,))
            self.assertTrue(window._analysis_current)
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_sheet_undo_restores_extent_after_appending_and_explicit_replacement(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel
        app = QApplication.instance() or QApplication([])
        model = SheetModel()
        model.load_matrix([["CD"], ["1.000"], ["2.000"], [""]])
        baseline = model.document_frame()
        self.assertEqual(len(baseline), 3)
        model.edit({(7, 0): "9.99"})
        self.assertEqual(len(model.document_frame()), 7)
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), baseline)
        model.undo.redo()
        self.assertEqual(len(model.document_frame()), 7)
        model.replace_matrix([["CD"], ["5.00"]])
        self.assertEqual(len(model.document_frame()), 1)
        model.undo.undo()
        self.assertEqual(len(model.document_frame()), 7)
        app.processEvents()

    def test_repeated_raw_replacement_retains_marks_participation_and_undo(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.match_groups import row_ids
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            x = np.arange(1., 13.)
            raw = pd.DataFrame({"Wafer ID": ["W1"] * 6 + ["W2"] * 6,
                                "Die Seq": list(range(1, 7)) * 2, "CD": x})
            window.set_reference_frame(pd.DataFrame({"CD Reference": x * 1.03 + 2}))
            window.set_raw_frame(raw)
            ids = row_ids(raw)
            window.group_controls.restore({
                "mark_enabled": True, "mark_rows": {"New": list(ids[6:])},
                "data_selection": {"records": [{"key": key, "id": str(i)} for i, key in enumerate(ids)],
                                   "excluded": ["5", "6", "7"]}})
            window.run_analysis()
            records = window.group_controls.state["data_selection"]["records"]
            for delta in (.1, .2, .3):
                updated = raw.copy()
                updated["CD"] = x + delta
                matrix = [list(updated.columns)] + updated.astype(str).values.tolist()
                window.raw_model.replace_matrix(matrix)
                app.processEvents()
                self.assertEqual(window.result.card("CD").valid_pairs, 9)
                self.assertAlmostEqual(window.result.card("CD").slope, 1.03)
                self.assertAlmostEqual(window.result.card("CD").intercept, 2 - 1.03 * delta)
                self.assertEqual(window.group_controls.state["mark_rows"]["New"], list(ids[6:]))
                self.assertEqual(window.group_controls.state["data_selection"]["records"], records)
                self.assertEqual(len(window.raw_model.document_frame()), 12)
                window.raw_model.undo.undo()
                app.processEvents()
                self.assertAlmostEqual(window.result.card("CD").intercept, 2)
                self.assertEqual(window.result.card("CD").valid_pairs, 9)
                self.assertEqual(window.group_controls.state["data_selection"]["excluded"], ["5", "6", "7"])
        finally:
            window.document.timer.stop()
            window.document.identity_timer.stop()
            window.document.force_close = True
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_interleaved_wafer_spans_do_not_require_per_span_dataframes(self):
        rows = 2000
        raw = pd.DataFrame({"Wafer ID": ["W1", "W2"] * (rows // 2),
                            "Lot ID": ["L1"] * rows, "PAD Name": ["ARRAY"] * rows,
                            "CD": np.arange(rows, dtype=float)})
        reference = pd.DataFrame({"CD Reference": raw.CD * 1.03 + 2})
        result = MatchWorkbook(reference, raw,
                               [ParameterMapping("CD", "CD Reference", "CD")]).analyze()
        original = raw.copy(deep=True)
        start = perf_counter()
        spans = result.measurement_spans()
        elapsed = perf_counter() - start
        self.assertEqual(len(spans), rows)
        self.assertEqual(spans[0], (.5, 1.5, "W1\nL1\nARRAY"))
        self.assertEqual(spans[-1], (1999.5, 2000.5, "W2\nL1\nARRAY"))
        pd.testing.assert_frame_equal(raw, original)
        # Broad guard, not an FPS target: old per-span pandas work takes >1s.
        self.assertLess(elapsed, .75, f"Identity footer preparation took {elapsed:.3f}s")

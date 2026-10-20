"""Bound repeated preparation while retaining native selection and full curves."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from metrology_app.map_selector import MapSelector
from metrology_app.sequence_page import SequencePage

APP = QApplication.instance() or QApplication([])


class RenderPreparationTests(unittest.TestCase):
    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_parameter_checks_batch_native_cell_notifications_without_changing_boxes(self):
        selector = MapSelector()
        self.addCleanup(selector.deleteLater)
        wafers = [(source, f'W{i:03}') for source in ('REF', 'RAW') for i in range(40)]
        metrics = ['A', 'B', 'C']
        labels = {key: f'{key[0]} / {key[1]}' for key in wafers}
        all_cells = {(key, metric) for key in wafers for metric in metrics}
        selector.set_array(wafers, metrics, labels, all_cells)
        retained = selector.item(0, 0)
        notifications = QSignalSpy(selector.model().dataChanged)
        allowed = {(key, metric) for key, metric in all_cells if key[0] != 'RAW' or metric != 'B'}
        with patch.object(selector, 'setVerticalHeaderLabels', wraps=selector.setVerticalHeaderLabels) as headers:
            selector.set_array(wafers, metrics, labels, allowed)
        self.assertEqual(headers.call_count, 0, 'A parameter check rewrote unchanged native headers')
        self.assertEqual(selector.selected_cells(), allowed)
        self.assertEqual({(wafers[index.row()], metrics[index.column()])
                          for index in selector.selectedIndexes()}, allowed)
        self.assertIs(selector.item(0, 0), retained)
        for row, key in enumerate(wafers):
            for column, metric in enumerate(metrics):
                item = selector.item(row, column)
                self.assertEqual(bool(item.flags() & Qt.ItemFlag.ItemIsEnabled), (key, metric) in allowed)
                self.assertEqual(item.text(), f'{metric}\n{labels[key]}')
        self.assertLessEqual(len(notifications), 1, 'One sidebar change emitted per-cell native notifications')
        selector.set_array(wafers, metrics, labels, all_cells)
        self.assertEqual(selector.selected_cells(), all_cells)
        self.assertEqual({(wafers[index.row()], metrics[index.column()])
                          for index in selector.selectedIndexes()}, all_cells)

    def test_trend_prepares_labels_without_per_wafer_scans_or_losing_rows(self):
        page = SequencePage()
        self.addCleanup(page.deleteLater)
        keys = [f'W{i:03}' for i in range(60)]
        identities = [value for key in keys for value in ('', f' {key} ')]
        identities[-2:] = [None, None]
        frame = pd.DataFrame({'Wafer ID': identities, 'Die Seq': [2, 1] * 60,
                              'A': np.arange(120.) + .125, 'B': np.arange(120.) * 2 + .25})
        before = frame.copy(deep=True)
        groups = {key: (2 * i, 2 * i + 1) for i, key in enumerate(keys)}
        selection = {'wafers': keys, 'metrics': ['A', 'B'], 'wafer_column': 'Wafer ID',
                     'groups': groups, 'labels': {key: key for key in keys}}
        page.set_input(frame, selection)
        original = pd.Series.astype
        normalized = []
        def counted(series, dtype, *args, **kwargs):
            if series.name == 'Wafer ID' and dtype is str:
                normalized.append(len(series))
            return original(series, dtype, *args, **kwargs)
        from metrology_app import sequence_page
        with patch.object(pd.Series, 'astype', counted), \
                patch.object(sequence_page, 'format_die', wraps=sequence_page.format_die) as formatted:
            page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(len(page.groups), 60)
        self.assertEqual(sum(len(group['frame']) for group in page.groups), 120)
        self.assertEqual([group['wafer'] for group in page.groups], keys)
        for plot, metric in zip(page.plot_widgets, ('A', 'B')):
            expected = frame.iloc[np.arange(120).reshape(-1, 2)[:, ::-1].ravel()][metric]
            np.testing.assert_array_equal(plot.listDataItems()[0].yData, expected)
        pd.testing.assert_frame_equal(frame, before)
        # Plot identity and the multiline footer each prepare the shared column.
        self.assertLessEqual(len(normalized), 2, 'Trend rescanned Wafer labels for every group')
        self.assertLessEqual(formatted.call_count, len(frame), 'Each parameter reformatted the same Die ticks')

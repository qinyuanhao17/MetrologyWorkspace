"""Ctrl+Alt selects an unordered set of source-qualified correlation pairs."""
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_page import CorrelationPage
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.plotting.parameter_filter import ParameterFilterBar

APP = QApplication.instance() or QApplication([])
PAIR_KEYS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier


class CorrelationMultiPairTests(unittest.TestCase):
    def close(self, widget):
        QTest.keyRelease(widget, Qt.Key.Key_Alt, Qt.KeyboardModifier.ControlModifier)
        QTest.keyRelease(widget, Qt.Key.Key_Control)
        if hasattr(widget, "document"):
            widget.document.force_close = True
        widget.close()
        widget.deleteLater()
        APP.processEvents()

    def test_keyboard_pair_selection_keeps_three_and_restore_and_removal_keep_pair_mode(self):
        bar = ParameterFilterBar(pair_selection=True)
        self.addCleanup(self.close, bar)
        bar.set_parameters(["A", "B", "C", "D"])
        bar.show()
        for name in ("B", "A", "C"):
            bar.buttons[name].setFocus()
            QTest.keyClick(bar.buttons[name], Qt.Key.Key_Space, PAIR_KEYS)
        expected = {"mode": "pair", "parameters": ["A", "B", "C"]}
        self.assertEqual(bar.parameter, expected)
        self.assertEqual({pair for pair in combinations(bar.names, 2) if bar.matches(pair)},
                         {("A", "B"), ("A", "C"), ("B", "C")})
        bar.set_selection(None)
        bar.set_selection(expected)
        self.assertEqual(bar.parameter, expected)
        self.assertFalse(bar.matches(("A", "D")))
        QTest.mouseClick(bar.buttons["D"], Qt.MouseButton.LeftButton, PAIR_KEYS)
        self.assertEqual(bar.parameter, {"mode": "pair", "parameters": ["A", "B", "C", "D"]})
        self.assertEqual(sum(bar.matches(pair) for pair in combinations(bar.names, 2)), 6)
        QTest.mouseClick(bar.buttons["D"], Qt.MouseButton.LeftButton, PAIR_KEYS)
        QTest.mouseClick(bar.buttons["C"], Qt.MouseButton.LeftButton, PAIR_KEYS)
        self.assertEqual(bar.parameter, {"mode": "pair", "parameters": ["A", "B"]})
        bar.set_parameters(["A", "B", "D"])
        self.assertEqual(bar.parameter, {"mode": "pair", "parameters": ["A", "B"]})

    def test_three_of_four_parameters_draw_three_pairs_not_the_union_or_reverse_duplicates(self):
        page = CorrelationPage()
        self.addCleanup(self.close, page)
        values = np.arange(1., 7.)
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 6,
                              **{name: values * (index + 1) + index
                                 for index, name in enumerate(("A", "B", "C", "D"))}})
        selection = {"wafer_column": "Wafer ID", "wafers": ["W1"],
                     "metrics": ["A", "B", "C", "D"], "groups": {"W1": range(6)}}
        page.set_input(frame, selection)
        page.selector.selectAll()
        page.draw_plot()
        original = list(page.all_fits)
        self.assertEqual(len(original), 6)
        for name in ("A", "B", "C"):
            QTest.mouseClick(page.parameter_filter.buttons[name], Qt.MouseButton.LeftButton, PAIR_KEYS)
        fits = page.display_fits()
        expected = {frozenset(pair) for pair in combinations(("A", "B", "C"), 2)}
        self.assertEqual(len(fits), 3)
        self.assertEqual({frozenset((fit.x_name, fit.y_name)) for fit in fits}, expected)
        self.assertEqual(len(page.plot_widgets), 3)
        self.assertTrue(all(any(fit is previous for previous in original) for fit in fits))
        page.swap_axes(fits[0])
        self.assertEqual(len(page.display_fits()), 3)
        page.ensure_export_figure()
        self.assertEqual(len(page.figure.axes), 3)
        self.assertEqual({frozenset((axis.get_xlabel(), axis.get_ylabel())) for axis in page.figure.axes}, expected)
        pd.testing.assert_frame_equal(page.frame, frame)

    def test_source_qualified_multi_pair_selection_saves_and_reopens_without_reverse_duplicates(self):
        window = CorrelationWindow()
        self.addCleanup(self.close, window)
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 6, "Die Seq": range(1, 7),
                            "DP": [1., 2., 3., 4., 5., 6.], "EW": [3., 5., 7., 9., 11., 13.]})
        reference = raw.assign(DP=raw["DP"] * 3 + 1, EW=raw["EW"] * 4 + 2)
        window.set_sources(reference, raw, [ParameterMapping(name, name, name) for name in ("DP", "EW")])
        page = window.correlation_page
        page.selector.selectAll()
        page.draw_plot()
        chosen = (("Reference", "DP"), ("Raw Data", "DP"), ("Raw Data", "EW"))
        for key in chosen:
            QTest.mouseClick(page.parameter_filter.buttons[key], Qt.MouseButton.LeftButton, PAIR_KEYS)
        expected = {frozenset(pair) for pair in combinations(chosen, 2)}
        self.assertEqual(len(page.display_fits()), 3)
        self.assertEqual({frozenset(fit.parameter_keys) for fit in page.display_fits()}, expected)
        self.assertFalse(page.parameter_filter.buttons[("Reference", "EW")].isChecked())
        with TemporaryDirectory() as folder:
            path = Path(folder) / "multi-pair.wct"
            window.document.save(path)
            restored = CorrelationWindow()
            self.addCleanup(self.close, restored)
            restored.load_workspace(path)
            other = restored.correlation_page
            self.assertEqual(other.parameter_filter.parameter, page.parameter_filter.parameter)
            self.assertEqual(len(other.display_fits()), 3)
            self.assertEqual({frozenset(fit.parameter_keys) for fit in other.display_fits()}, expected)
            other.ensure_export_figure()
            self.assertEqual(len(other.figure.axes), 3)
            self.assertIsNone(restored.sequence_page.parameter_filter.parameter)
            pd.testing.assert_frame_equal(restored.raw_model.document_frame(), window.raw_model.document_frame())
            pd.testing.assert_frame_equal(restored.reference_model.document_frame(), window.reference_model.document_frame())

"""Source-specific selection boxes stay exact during incremental choices."""
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.map_selector import MapSelector

APP = QApplication.instance() or QApplication([])


class SelectorUpdateTests(unittest.TestCase):
    def test_parameter_remove_add_and_reorder_keep_source_specific_boxes(self):
        selector = MapSelector()
        self.addCleanup(selector.deleteLater)
        wafers = [("Reference", "W1"), ("Raw Data", "W1"), ("Raw Data", "W2")]
        labels = {key: f"{key[0]} · {key[1]}" for key in wafers}
        original = ["Ref0", "Ref1", "CD0", "CD1", "CD2"]
        for metrics in (original, ["Ref0", "Ref1", "CD1", "CD2"], original,
                        ["CD2", "CD0", "Ref1", "CD1", "Ref0"]):
            enabled = {(key, metric) for key in wafers for metric in metrics
                       if metric.startswith("Ref") == (key[0] == "Reference")}
            selector.set_array(wafers, metrics, labels, enabled)
            self.assertEqual(selector.selected_cells(), enabled)
            self.assertTrue(selector.pending_draw)
            for row, wafer in enumerate(wafers):
                for column, metric in enumerate(metrics):
                    item = selector.item(row, column)
                    self.assertEqual(item.text(), f"{metric}\n{labels[wafer]}")
                    self.assertEqual(bool(item.flags() & Qt.ItemFlag.ItemIsSelectable), (wafer, metric) in enabled)
            selector.set_selected_cells({next(iter(enabled))})

    def test_simultaneous_wafer_and_parameter_changes_keep_exact_cells(self):
        selector = MapSelector()
        self.addCleanup(selector.deleteLater)
        selector.set_array(["W1", "W2"], ["A", "B", "C"])
        selector.set_selected_cells({("W1", "B")})
        selector.set_array(["W1", "W3", "W2"], ["A", "C", "D"])
        self.assertEqual(selector.selected_cells(), {(wafer, metric) for wafer in ("W1", "W3", "W2")
                                                    for metric in ("A", "C", "D")})
        for row, wafer in enumerate(selector.wafers):
            for column, metric in enumerate(selector.metrics):
                self.assertEqual(selector.item(row, column).text(), f"{metric}\n{wafer}")
        selector.set_selected_cells({("W3", "D")})
        self.assertEqual(selector.selected_cells(), {("W3", "D")})

"""Trend coordinates fall back to the visible, source-local sheet row number."""
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_window import CorrelationWindow


APP = QApplication.instance() or QApplication([])


class TrendRowNumberTests(unittest.TestCase):
    def setUp(self):
        self.window = CorrelationWindow()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def draw(self):
        page = self.window.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        return page

    def test_raw_without_die_seq_can_draw_using_sheet_row_numbers(self):
        raw = pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["1.00", "2.00"]})
        self.window.set_table(raw, "Raw")
        page = self.draw()
        self.assertEqual(page.groups[0]["frame"]["__die"].tolist(), [2, 3])
        self.assertEqual(page.plot_widgets[0].getPlotItem().getAxis("bottom").labelText,
                         "Row Number")
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), raw)

    def test_wafer_filter_keeps_gaps_in_original_visible_row_numbers(self):
        raw = pd.DataFrame({"Wafer ID": ["W1", "W2", "W1"],
                            "CD": ["1.00", "2.00", "3.00"]})
        self.window.set_table(raw, "Raw")
        self.window.wafer_list.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
        page = self.draw()
        self.assertEqual(page.groups[0]["frame"]["__die"].tolist(), [2, 4])
        axis = page.plot_widgets[0].getPlotItem().getAxis("bottom")
        self.assertEqual([text for _, text in axis.ticks], ["2", "4"])
        page.ensure_export_figure()
        exported = page.figure.axes[0]
        self.assertEqual(exported.get_xlabel(), "Row Number")
        self.assertEqual([tick.get_text() for tick in exported.get_xticklabels()], ["2", "4"])
        values = page.export_plot_data()[0]["series"][0]
        self.assertEqual(values["data"]["Row Number"].tolist(), [2, 4])
        self.assertNotIn("Die Seq", values["data"])
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), raw)

    def test_ref_and_raw_choose_coordinates_independently(self):
        for source_with_die in (None, "Reference", "Raw Data"):
            with self.subTest(source_with_die=source_with_die):
                reference = pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["3.00", "5.00"]})
                raw = pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["1.00", "2.00"]})
                if source_with_die == "Reference":
                    reference["Die Seq"] = ["020", "010"]
                elif source_with_die == "Raw Data":
                    raw["Die Seq"] = ["020", "010"]
                self.window.set_table(raw, "Raw")
                self.window.set_reference_table(reference)
                page = self.draw()
                self.assertEqual(len(page.panel_specs), 2)
                page.ensure_export_figure()
                for panel, widget, axis in zip(page.panel_specs, page.plot_widgets, page.figure.axes):
                    source = panel["source"]["name"]
                    label = "Die Seq" if source == source_with_die else "Row Number"
                    ticks = ["10", "20"] if source == source_with_die else ["2", "3"]
                    bottom = widget.getPlotItem().getAxis("bottom")
                    self.assertEqual(bottom.labelText, label)
                    self.assertEqual([text for _, text in bottom.ticks], ticks)
                    self.assertEqual(axis.get_xlabel(), label)
                    self.assertEqual([tick.get_text() for tick in axis.get_xticklabels()], ticks)
                pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), reference)
                pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), raw)

    def test_present_but_blank_die_seq_does_not_silently_change_semantics(self):
        self.window.set_table(pd.DataFrame({"Wafer ID": ["W1", "W1"],
                                          "Die Seq": ["", ""], "CD": ["1", "2"]}), "Raw")
        page = self.window.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertFalse(page.ready)
        self.assertIn("no valid Die Seq", page.status.text())

    def test_reference_only_without_die_seq_can_draw(self):
        reference = pd.DataFrame({"Wafer ID": ["REF1", "REF1"], "CD": ["1.000", "3.000"]})
        self.window.set_reference_table(reference)
        self.window.recognize()
        page = self.draw()
        self.assertEqual(len(page.panel_specs), 1)
        self.assertEqual(page.panel_specs[0]["source"]["name"], "Reference")
        self.assertEqual(page.groups[0]["frame"]["__die"].tolist(), [2, 3])
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), reference)

    def test_each_source_resolves_its_own_die_seq_header_alias(self):
        reference = pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["3", "5"],
                                  "Die ID": ["040", "030"]})
        raw = pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["1", "2"],
                            "Die Seq": ["020", "010"]})
        self.window.set_table(raw, "Raw")
        self.window.set_reference_table(reference)
        page = self.draw()
        self.assertEqual(len(page.panel_specs), 2)
        for panel, widget in zip(page.panel_specs, page.plot_widgets):
            ticks = ["30", "40"] if panel["source"]["name"] == "Reference" else ["10", "20"]
            self.assertEqual([text for _, text in widget.getPlotItem().getAxis("bottom").ticks], ticks)

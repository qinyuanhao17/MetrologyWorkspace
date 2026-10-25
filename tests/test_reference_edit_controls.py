"""Reference edits refit current data without replacing unchanged mapping controls."""
import unittest

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.matching_window import MatchingWindow

APP = QApplication.instance() or QApplication([])


class ReferenceEditControlTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()
        self.window.match_type.setCurrentText('NOVA')
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': ['2.000', '4.000', '6.000'],
                                                     'Candidate': ['', '', 'bad']}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1']*3, 'Die Seq': ['1', '2', '3'],
                                               'CD': ['1.000', '2.000', '3.000']}))
        self.window.run_analysis()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_reference_value_edit_and_undo_keep_controls_and_refit_current_values(self):
        window = self.window
        picker = window.mapping_table.cellWidget(0, 3)
        before = window.reference_model.document_frame()
        card = window.result.card('CD')
        window.reference_model.edit({(1, 0): '2.7500000000000'})
        APP.processEvents()
        self.assertIs(window.mapping_table.cellWidget(0, 3), picker)
        self.assertEqual(window.reference_model.document_frame().iat[0, 0], '2.7500000000000')
        self.assertNotEqual(window.result.card('CD').slope, card.slope)
        window.reference_model.undo.undo()
        APP.processEvents()
        self.assertIs(window.mapping_table.cellWidget(0, 3), picker)
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), before)
        self.assertAlmostEqual(window.result.card('CD').slope, card.slope, places=12)
        self.assertTrue(window._analysis_current)

    def test_numeric_qualification_changes_still_add_and_remove_mapping_candidates(self):
        window = self.window
        def candidates():
            return [window.mapping_table.item(row, 2).text() for row in range(window.mapping_table.rowCount())]
        self.assertNotIn('Candidate', candidates())
        window.reference_model.edit({(1, 1): '1.5000'})
        APP.processEvents()
        self.assertIn('Candidate', candidates())
        window.reference_model.undo.undo()
        APP.processEvents()
        self.assertNotIn('Candidate', candidates())
        window.reference_model.undo.redo()
        APP.processEvents()
        self.assertIn('Candidate', candidates())

"""Content rectangles are exact for sparse, blank, filtered and reordered sheets."""
import random
import unittest

from PyQt6.QtWidgets import QApplication
from metrology_app.match_group_ui import ProjectedSheetModel
from metrology_app.sheet import SheetModel, nonempty_cell_bounds

APP = QApplication.instance() or QApplication([])


class SheetBoundsTests(unittest.TestCase):
    def test_random_visible_rectangles_match_literal_cells_after_edit_and_undo(self):
        rng = random.Random(20261020)
        for density in (0, .1, .5, 1):
            model = SheetModel()
            proxy = ProjectedSheetModel(model)
            self.addCleanup(proxy.deleteLater)
            self.addCleanup(model.deleteLater)
            matrix = [[rng.choice(["", " ", "\t"]) if rng.random() >= density
                       else f"{row}.{column:03}" for column in range(9)] for row in range(17)]
            model.load_matrix(matrix)
            for rows in (None, (), tuple(range(15, -1, -1)), (15, 2, 9)):
                proxy.set_rows(rows)
                def check():
                    positions = None if rows is None else {r + 1: i + 1 for i, r in enumerate(rows)}
                    expected = nonempty_cell_bounds(model.cells.items(), positions)
                    self.assertEqual(proxy.selection_bounds(), expected)
                    self.assertEqual(model.selection_bounds(), nonempty_cell_bounds(model.cells.items()))
                check()
                model.edit({(1, 0): "1.0000", (16, 8): ""})
                check()
                model.undo.undo()
                check()

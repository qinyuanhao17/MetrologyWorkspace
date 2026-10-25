"""Content rectangles are exact for sparse, blank, filtered and reordered sheets."""
import random
import unittest
from time import perf_counter

import pandas as pd

from PyQt6.QtWidgets import QApplication
from metrology_app.match_group_ui import OrderModel, ProjectedSheetModel
from metrology_app.match_groups import GroupPlan, row_ids
from metrology_app.sheet import SheetModel, nonempty_cell_bounds

APP = QApplication.instance() or QApplication([])


class SheetBoundsTests(unittest.TestCase):
    def test_order_bounds_match_visible_values_for_flags_marks_and_empty_headers(self):
        raw = pd.DataFrame({'Wafer ID': ['W1']*8, 'Die Seq': list(range(1, 9)), 'CD': ['1.000']*8})
        flags = pd.DataFrame({'TestFlag': ['1', '', '2', '', '', '1', '', '']})
        keys = row_ids(raw)
        for enabled in (False, True):
            for marks in (False, True):
                model = OrderModel()
                self.addCleanup(model.deleteLater)
                model.load(flags)
                plan = GroupPlan(raw, flags, {'enabled': enabled, 'mark_enabled': marks,
                    'mark_values': [{'id': 'New', 'name': 'New'}, {'id': 'G', 'name': 'Group'}],
                    'mark_rows': {'New': [keys[-1]], 'G': [keys[2]]}})
                model.set_plan(plan)
                for edits in ({}, {(0, 0): ''}, {(12, 0): '1'}, {(12, 0): ''}):
                    if edits:
                        model.edit(edits)
                    expected = nonempty_cell_bounds((((r, c), model.data(model.index(r, c)))
                        for r in range(model.rowCount()) for c in range(4)))
                    self.assertEqual(model.selection_bounds(), expected)

    def test_first_100k_order_bounds_do_not_build_a_qmodelindex_for_every_cell(self):
        raw = pd.DataFrame({'Wafer ID': ['W1']*100000, 'Die Seq': list(range(100000)), 'CD': ['1']*100000})
        flags = pd.DataFrame({'TestFlag': ['']*len(raw)})
        model = OrderModel()
        model.load(flags)
        model.set_plan(GroupPlan(raw, flags, {'enabled': False, 'mark_enabled': False}))
        start = perf_counter()
        bounds = model.selection_bounds()
        self.assertLess(perf_counter()-start, .1)
        self.assertEqual(bounds, (0, 0, 0, 3))

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

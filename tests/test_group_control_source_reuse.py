"""Source updates allocate identifiers only for records that need them."""
from copy import deepcopy
from time import perf_counter
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.match_group_ui import GroupControls

APP = QApplication.instance() or QApplication([])


class GroupControlSourceReuseTests(unittest.TestCase):
    def controls(self):
        controls = GroupControls()
        self.addCleanup(controls.deleteLater)
        return controls

    def test_no_unused_participation_ids_without_an_empty_selection(self):
        controls = self.controls()
        raw = pd.DataFrame({'Wafer ID': ['W1']*3, 'Die Seq': ['1', '2', '3'], 'CD': ['1', '2', '3']})
        ref = pd.DataFrame({'CD Reference': ['2', '4', '6']})
        # A new GroupControls intentionally has two empty selections, which
        # really need identifiers. Only subsequent source updates can skip it.
        controls.set_sources(ref, raw)
        selection = deepcopy(controls.state['data_selection'])
        with patch('metrology_app.match_group_ui.participation_ids', side_effect=AssertionError('Unused ids allocated')):
            controls.set_sources(ref.copy(), raw.copy())
        self.assertIsNotNone(controls.plan)
        self.assertEqual(controls.state['data_selection'], selection)
        controls.state['data_selection'] = None
        controls.state['applied']['data_selection'] = None
        with patch('metrology_app.match_group_ui.participation_ids', side_effect=AssertionError('Unused ids allocated')):
            controls.set_sources(ref.copy(), raw.copy())
        self.assertIsNone(controls.state['data_selection'])

    def test_empty_draft_and_applied_selections_receive_the_same_identifiers(self):
        controls = self.controls()
        selection = {'records': [], 'excluded': []}
        state = {'enabled': False, 'mark_enabled': False, 'data_selection': selection}
        state['applied'] = deepcopy(state)
        controls.restore(state, None)
        raw = pd.DataFrame({'Wafer ID': ['W1']*3, 'Die Seq': ['1', '2', '3'], 'CD': ['1', '2', '3']})
        with patch('metrology_app.match_group_ui.participation_ids', return_value=('A', 'B', 'C')) as ids:
            controls.set_sources(pd.DataFrame({'CD Reference': ['2', '4', '6']}), raw)
        self.assertEqual(ids.call_count, 1)
        draft = controls.state['data_selection']['records']
        accepted = controls.state['applied']['data_selection']['records']
        self.assertEqual([r['id'] for r in draft], ['A', 'B', 'C'])
        self.assertEqual(draft, accepted)
        self.assertIsNot(draft, accepted)

    def test_reference_undo_rebinds_exact_plan_without_mutating_prior_sources_promptly(self):
        controls = self.controls()
        raw = pd.DataFrame({'Wafer ID': ['W1']*100000, 'Die Seq': list(map(str, range(100000))), 'CD': ['1.000']*100000})
        ref = pd.DataFrame({'CD Reference': ['2.000']*len(raw)})
        controls.set_sources(ref, raw)
        original = controls.plan
        changed = ref.copy()
        changed.iat[0, 0] = '2.125'
        controls.set_sources(changed, raw)
        restored = ref.copy()
        start = perf_counter()
        controls.set_sources(restored, raw)
        self.assertLess(perf_counter()-start, .2)
        self.assertIsNot(controls.plan, original)
        self.assertIs(controls.plan.reference, restored)
        self.assertIs(original.reference, ref)
        self.assertEqual(original.reference.iat[0, 0], '2.000')
        self.assertEqual(controls.plan.ids, original.ids)

        # Equal numeric values with different source strings are NOT the same
        # cache key, even after a successful A -> B -> A replay.
        literal = restored.copy()
        literal.iat[0, 0] = '2.0000000000000000'
        controls.set_sources(literal, raw)
        self.assertIs(controls.plan.reference, literal)
        self.assertEqual(controls.plan.reference.iat[0, 0], '2.0000000000000000')
        self.assertEqual(original.reference.iat[0, 0], '2.000')

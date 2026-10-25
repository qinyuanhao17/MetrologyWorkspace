"""Fast scalar transcriptions keep the exact dataclass serialization contract."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import unittest

import metrology_app.auto_weighting as writer_module
from metrology_app.auto_weighting import Cell


class WriterCellSerializationTests(unittest.TestCase):
    def test_plain_and_nested_cells_match_asdict_with_independent_mutable_values(self):
        @dataclass
        class ExtendedCell(Cell):
            extra: str = 'preserved'
        for cell in (Cell('1.230000'), Cell('bad', bbox=(1, 2, 3, 4), confidence=.4),
                     Cell('original', alternatives=[{'text': 'candidate', 'metadata': [1]}],
                          history=[{'text': 'old', 'nested': Cell('nested')}]),
                     ExtendedCell('extended')):
            expected = asdict(cell)
            actual = cell.to_dict()
            self.assertEqual(actual, expected)
            self.assertEqual(list(actual), list(expected))
            actual['alternatives'].append({'text': 'detached'})
            actual['history'].append({'text': 'detached'})
            self.assertEqual(asdict(cell), expected)

    def test_deserialization_retains_validation_and_does_not_take_input_lists(self):
        values = [Cell('1.000', bbox=(1, 2, 3, 4)).to_dict(),
                  Cell('1.000', alternatives=[{'text': 'other'}]).to_dict()]
        for value in values:
            before = deepcopy(value)
            restored = Cell.from_dict(value)
            self.assertEqual(restored.to_dict(), before)
            restored.alternatives.append({'text': 'detached'})
            restored.history.append({'text': 'detached'})
            self.assertEqual(value, before)
        for key, bad in (('text', 1), ('raw', 1), ('source', None), ('collected', 1),
                         ('reviewed', 0), ('confidence', -1), ('bbox', [1]),
                         ('alternatives', ()), ('history', {})):
            value = Cell('1.0').to_dict()
            value[key] = bad
            with self.assertRaises(ValueError, msg=key):
                Cell.from_dict(value)
        value = Cell('1.000').to_dict()
        value['history'] = value['alternatives']
        restored = Cell.from_dict(value)
        self.assertIs(restored.history, restored.alternatives)
        self.assertIsNot(restored.history, value['history'])

    def test_plain_cells_avoid_generic_recursive_serialization_cost(self):
        # Match the cold benchmark's fresh-process lifetime. This test also
        # runs last after thousands of Qt fixtures in the full suite; their
        # pending cleanup must not become this pure serializer's baseline.
        source = str(Path(writer_module.__file__).resolve().parents[1])
        probe = f"""
import json, sys
from time import perf_counter
sys.path.insert(0, {source!r})
from metrology_app.auto_weighting import Cell
cells = [Cell(f'{{i}}.123456789000', bbox=(1, 2, 3, 4)) for i in range(100000)]
start = perf_counter()
encoded = [cell.to_dict() for cell in cells]
print(json.dumps({{'elapsed': perf_counter()-start, 'last': encoded[-1]['text']}}))
"""
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', probe],
                                capture_output=True, text=True, timeout=30, check=True)
        measured = json.loads(result.stdout)
        elapsed = measured['elapsed']
        self.assertLess(elapsed, .3, f'Plain-cell encoding blocked for {elapsed:.3f}s')
        self.assertEqual(measured['last'], '99999.123456789000')

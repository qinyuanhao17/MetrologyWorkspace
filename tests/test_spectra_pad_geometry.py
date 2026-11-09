"""PAD geometry uses measured coordinates and unique shared borders."""
from dataclasses import replace
import math
import unittest

from metrology_app.spectra_pad_geometry import pad_layout
from tests.test_spectra_viewer import make_spectrum


def point(die, column, row, x, y):
    source = make_spectrum(die)
    return replace(source, identity=replace(source.identity, field_x=column, field_y=row), x_mm=x, y_mm=y)


class PadGeometryTests(unittest.TestCase):
    def test_grid_fills_circle_including_unmeasured_fields_without_moving_points(self):
        sources = (point(1, 0, 0, 2, 3), point(2, 1, 0, 12, 3), point(3, 0, 1, 2, 23))
        layout = pad_layout((*sources, sources[0]), radius_mm=25)
        self.assertEqual((layout.width_mm, layout.height_mm, layout.issue), (10, 20, ""))
        horizontal = [s for s in layout.segments if s[1] == s[3]]
        vertical = [s for s in layout.segments if s[0] == s[2]]
        self.assertEqual([s[1] for s in horizontal], [-20, 0, 20])
        self.assertEqual([s[0] for s in vertical], [-20, -10, 0, 10, 20])
        self.assertIn((-25, 0, 25, 0), horizontal)
        self.assertIn((0, -25, 0, 25), vertical)
        self.assertEqual(len(layout.segments), len(set(layout.segments)))
        for x0, y0, x1, y1 in layout.segments:
            self.assertAlmostEqual(math.hypot(x0, y0), 25)
            self.assertAlmostEqual(math.hypot(x1, y1), 25)
        self.assertEqual((sources[0].x_mm, sources[0].y_mm), (2, 3))

    def test_sparse_negative_fields_infer_pitch_without_origin_or_adjacent_samples(self):
        layout = pad_layout((point(1, -2, -1, -18, -17), point(2, 2, -1, 22, -17),
                             point(3, -2, 3, -18, 63)))
        self.assertEqual((layout.width_mm, layout.height_mm), (10, 20))
        self.assertIn((0, -150, 0, 150), layout.segments)

    def test_missing_or_inconsistent_coordinates_do_not_invent_a_pad_size(self):
        self.assertTrue(pad_layout((point(1, 0, 0, 0, 0),)).issue)
        sources = (point(1, 0, 0, 0, 0), point(2, 1, 1, 10, 20), point(3, 2, 2, 27, 40))
        self.assertFalse(pad_layout(sources).segments)
        self.assertTrue(pad_layout(sources).issue)

    def test_size_uses_only_three_references_and_rounds_to_two_decimal_mm(self):
        sources = (point(1, 0, 0, 2, 3), point(2, 1, 0, 12.174, 3),
                   point(3, 0, 1, 2, 23.536), point(4, 5, 5, 500, 600))
        layout = pad_layout(sources)
        self.assertEqual((layout.width_mm, layout.height_mm), (10.17, 20.54))
        self.assertTrue(any(abs(s[0] - 50.85) < 1e-9 and s[0] == s[2] for s in layout.segments))

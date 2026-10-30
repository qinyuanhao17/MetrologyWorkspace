"""Indexed label collision keeps the exact original greedy drawing order."""
import unittest

import numpy as np

from metrology_app.wafer_graphics import _LabelBoxIndex


def original_acceptance(boxes):
    accepted, indices = [], []
    for index, box in enumerate(boxes):
        if any(box[0] < other[2] and box[2] > other[0]
               and box[1] < other[3] and box[3] > other[1] for other in accepted):
            continue
        accepted.append(box)
        indices.append(index)
    return indices


class WaferLabelIndexTests(unittest.TestCase):
    def assert_matches_original(self, boxes):
        expected = original_acceptance(boxes)
        for cell_size in (4, 12, 24, 80):
            with self.subTest(cell_size=cell_size):
                index = _LabelBoxIndex(cell_size)
                actual = [position for position, box in enumerate(boxes) if index.add_if_clear(box)]
                self.assertEqual(actual, expected)

    def test_random_mixed_sizes_and_negative_coordinates_preserve_every_accepted_index(self):
        for seed in range(12):
            rng = np.random.default_rng(seed)
            xy = rng.uniform(-350, 350, (500, 2))
            sizes = rng.lognormal(2, .8, (500, 2))
            boxes = [(x, y, x + width, y + height)
                     for (x, y), (width, height) in zip(xy, sizes)]
            with self.subTest(seed=seed):
                self.assert_matches_original(boxes)

    def test_touching_edges_corners_and_float_neighbours_keep_strict_overlap(self):
        boxes = [(0., 0., 24., 24.), (24., 0., 48., 24.), (0., 24., 24., 48.),
                 (24., 24., 48., 48.), (-24., -24., 0., 0.),
                 (48. - 1e-10, 0., 72., 24.), (48., 0., 72., 24.),
                 (-48., -24., -24., 0.), (-24. - 1e-10, -24., -1e-10, 0.)]
        self.assert_matches_original(boxes)

    def test_repeated_wide_and_zero_size_boxes_keep_original_greedy_semantics(self):
        boxes = [(-100., -10., 100., 10.), (-1., -1., 1., 1.),
                 (-100., 10., 100., 30.), (100., -10., 110., 10.),
                 (0., 40., 0., 40.), (0., 40., 0., 40.),
                 (-3., 35., 3., 45.), (-100., -10., 100., 10.)]
        self.assert_matches_original(boxes)

    def test_input_order_is_preserved_instead_of_merging_or_sorting_rectangles(self):
        boxes = [(0., 0., 10., 10.), (9., 0., 19., 10.), (18., 0., 28., 10.)]
        self.assert_matches_original(boxes)
        self.assert_matches_original(list(reversed(boxes)))

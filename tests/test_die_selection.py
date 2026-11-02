from dataclasses import replace
import unittest
from metrology_app.die_selection import similar_wafer_selection
from tests.test_spectra_viewer import make_spectrum


class SimilarWaferSelectionTests(unittest.TestCase):
    def test_matching_requires_same_die_ids_and_every_xy_difference_below_tolerance(self):
        sources = (make_spectrum(1), make_spectrum(2))
        near = tuple(replace(make_spectrum(i, wafer="Near"), x_mm=float(i)+.399, y_mm=.399) for i in (1, 2))
        edge = tuple(replace(make_spectrum(i, wafer="Edge"), x_mm=float(i), y_mm=.4) for i in (1, 2))
        wrong_ids = (make_spectrum(1, wafer="Wrong"), make_spectrum(3, wafer="Wrong"))
        updates, matched, skipped = similar_wafer_selection((*sources, *near, *edge, *wrong_ids),
                                                           ("W1", "L1", "P1"), {sources[0].key})
        self.assertEqual(updates, {near[0].key: True, near[1].key: False})
        self.assertEqual(matched, [("Near", "L1", "P1")])
        self.assertEqual(len(skipped), 2)

    def test_conflicting_duplicate_die_coordinates_or_checks_are_not_copied(self):
        a = make_spectrum(1)
        other = replace(a, key="other", x_mm=20)
        with self.assertRaisesRegex(ValueError, "coordinates"):
            similar_wafer_selection((a, other), ("W1", "L1", "P1"), {a.key})
        with self.assertRaisesRegex(ValueError, "checkbox"):
            similar_wafer_selection((a, replace(a, key="other")), ("W1", "L1", "P1"), {a.key})

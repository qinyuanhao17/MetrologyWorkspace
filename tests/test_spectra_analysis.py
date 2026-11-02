"""Numerical examples for exact-wavelength residuals and GRR sample spread."""
import unittest

import numpy as np

from metrology_app.sme_spectra import SpectrumChannel
from metrology_app.spectra_analysis import SpectralSeries, residual_series, three_sigma_series


def channel(x, y, *, azi=45, instrument="UVSE", channel_id=1):
    numeric = np.full((len(x), 24), np.nan)
    numeric[:, 0] = x
    numeric[:, 5] = y
    return SpectrumChannel({"instrument": instrument, "channel_id": channel_id,
                            "angle_1_deg": 65, "angle_3_deg": azi},
                           numeric[:, 0], numeric, "mueller")


class SpectraAnalysisTests(unittest.TestCase):
    def test_residual_uses_only_exact_wavelengths_and_retains_gaps_and_sources(self):
        source = channel([200, 250, 300, 400, 500], [15, 22, 35, np.nan, 9])
        baseline = channel([200, 300, 400], [5, 20, 30])
        before = source.numeric.copy()
        result = residual_series(source, (baseline,), "S")
        np.testing.assert_equal(result.wavelength, [200, 250, 300, 400, 500])
        np.testing.assert_equal(result.values, [10, np.nan, 15, np.nan, np.nan])
        np.testing.assert_equal(source.numeric, before)
        np.testing.assert_equal(baseline.series("S"), [5, 20, 30])

    def test_three_sigma_is_sample_spread_at_exact_wavelengths_with_two_or_more_values(self):
        sources = (
            SpectralSeries(np.array([200., 250., 300., 400.]), np.array([1., 7., np.nan, 8.])),
            SpectralSeries(np.array([200., 300., 400.]), np.array([2., 4., 8.])),
            SpectralSeries(np.array([200., 300., 400.]), np.array([3., 6., 8.])),
        )
        result = three_sigma_series(sources)
        np.testing.assert_equal(result.wavelength, [200, 250, 300, 400])
        np.testing.assert_allclose(result.values, [3, np.nan, 3 * np.sqrt(2), 0], equal_nan=True)
        np.testing.assert_equal(result.counts, [3, 1, 2, 3])
        with self.assertRaisesRegex(ValueError, "at least two"):
            three_sigma_series(sources[:1])

    def test_baseline_channel_matches_exact_angles_across_instruments_but_rejects_ambiguity(self):
        source = channel([200, 300], [10, 20])
        baseline = channel([200, 300], [4, 6], instrument="BBSE", channel_id=3)
        np.testing.assert_equal(residual_series(source, (baseline,), "S").values, [6, 14])
        wrong_angle = channel([200, 300], [4, 6], azi=90)
        with self.assertRaisesRegex(ValueError, "matching channel"):
            residual_series(source, (wrong_angle,), "S")
        with self.assertRaisesRegex(ValueError, "multiple"):
            residual_series(source, (baseline, baseline), "S")

    def test_near_wavelengths_are_not_equal_and_duplicate_baseline_is_reported(self):
        source = channel([200, 300], [10, 20])
        with self.assertRaisesRegex(ValueError, "No exactly matching"):
            residual_series(source, (channel([200.00001, 300.00001], [4, 6]),), "S")
        with self.assertRaisesRegex(ValueError, "Repeated wavelengths"):
            residual_series(source, (channel([200, 200], [4, 6]),), "S")

    def test_three_sigma_retains_zero_spread_and_is_stable_for_large_offsets(self):
        sources = [SpectralSeries(np.array([200., 300.]), np.array([1e12 + n, 10.])) for n in (1, 2, 3)]
        np.testing.assert_equal(three_sigma_series(sources).values, [3, 0])
        bad = SpectralSeries(np.array([200., 200.]), np.array([1., 2.]))
        with self.assertRaisesRegex(ValueError, "Repeated wavelengths"):
            three_sigma_series((bad, sources[0]))

    def test_delta_residual_is_direct_subtraction_in_degrees(self):
        source = channel([200, 300], [0, 0])
        baseline = channel([200, 300], [0, 0])
        source.numeric[:, 2] = [1, 359]
        baseline.numeric[:, 2] = [359, 1]
        np.testing.assert_equal(residual_series(source, (baseline,), "delta").values, [-358, 358])


if __name__ == "__main__":
    unittest.main()

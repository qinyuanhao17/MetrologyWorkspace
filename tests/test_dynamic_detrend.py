import unittest

import numpy as np
import pandas as pd

from metrology_app.dynamic_detrend import detrend


class DynamicDetrendTests(unittest.TestCase):
    def test_configured_rsquared_threshold_changes_fit_acceptance(self):
        raw = pd.DataFrame({'CD': [10., 12., 13., 17., 17., 24.]}, index=range(1, 7))
        accepted = detrend(raw, 'linear', min_r_squared=.5)['CD']
        rejected = detrend(raw, 'linear', min_r_squared=1.)['CD']
        self.assertTrue(accepted.valid)
        self.assertFalse(rejected.valid)
        self.assertEqual(rejected.r_squared, accepted.r_squared)
        self.assertEqual(rejected.status, 'Fit R² below 1.00')

    def test_linear_uses_actual_cycles_and_preserves_mean_and_missing_values(self):
        cycles = [1, 2, 4, 7, 9, 12]
        raw = pd.DataFrame({"A": [14, 18, np.nan, 38, 46, 58]}, index=cycles)
        before = raw.copy(deep=True)
        fit = detrend(raw, "linear")["A"]

        self.assertTrue(fit.valid, fit.status)
        self.assertAlmostEqual(fit.raw_sigma, 3 * raw["A"].std(ddof=1))
        self.assertAlmostEqual(fit.sigma, 0)
        self.assertAlmostEqual(fit.parameters["slope"], 4)
        self.assertAlmostEqual(fit.amplitude, 44)
        self.assertAlmostEqual(np.nanmean(fit.corrected), raw["A"].mean())
        self.assertTrue(np.isnan(fit.corrected[2]))
        pd.testing.assert_frame_equal(raw, before)

    def test_exponential_fits_saturation_and_rejects_an_ordinary_linear_ramp(self):
        x = np.arange(1, 13, dtype=float)
        true_curve = 8000 - 25 * (-np.expm1(-(x - 1) / 2.5))
        noise = np.resize([.08, -.05, .01], len(x))
        raw = pd.DataFrame({"Saturation": true_curve + noise, "Linear": 100 + x * 4}, index=x)

        result = detrend(raw, "exponential")

        self.assertTrue(result["Saturation"].valid, result["Saturation"].status)
        self.assertAlmostEqual(result["Saturation"].parameters["tau"], 2.5, delta=.1)
        self.assertLess(result["Saturation"].sigma, .3)
        self.assertFalse(result["Linear"].valid)
        self.assertIsNone(result["Linear"].sigma)

    def test_common_modes_leave_current_die_out_and_reject_inconsistent_drift(self):
        x = np.arange(1, 13, dtype=float)
        for method, drift in (("common_linear", 2 * x),
                              ("common_exponential", 20 * (-np.expm1(-(x - 1) / 2)))):
            with self.subTest(method=method):
                raw = pd.DataFrame({"A": 100 + drift, "B": 51 + drift, "C": 15 + drift,
                                    "D": 84 + drift, "Opposite": 14 - drift}, index=x)
                raw.loc[4, "A"] += 3
                fit = detrend(raw, method)

                self.assertTrue(fit["A"].valid, fit["A"].status)
                np.testing.assert_allclose(fit["A"].fitted - fit["A"].fitted.mean(), drift - drift.mean(), atol=1e-6)
                self.assertAlmostEqual(fit["A"].sigma, 3 * np.std([3] + [0] * 11, ddof=1), places=5)
                self.assertFalse(fit["Opposite"].valid)

    def test_insufficient_or_flat_data_have_raw_results_only(self):
        raw = pd.DataFrame({"Short": [12, 13, np.nan, np.nan, np.nan],
                            "Flat": [5, 5, 5, 5, 5]}, index=range(1, 6))

        for method in ("linear", "exponential", "common_linear", "common_exponential"):
            with self.subTest(method=method):
                result = detrend(raw, method)
                self.assertTrue(all(not fit.valid and fit.sigma is None for fit in result.values()))
                self.assertAlmostEqual(result["Short"].raw_sigma, 3 * np.std([12, 13], ddof=1))
                self.assertEqual(result["Flat"].raw_sigma, 0)
        self.assertEqual(detrend(raw, "raw"), {})

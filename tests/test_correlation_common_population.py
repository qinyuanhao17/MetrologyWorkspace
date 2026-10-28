"""Common-population fits retain source pairing and the ordinary OLS meaning."""
import unittest

import numpy as np
import pandas as pd

from metrology_app.correlation_page import pairwise_linear_fits, source_pairwise_linear_fits, fit_numeric_pair


class CommonPopulationFitTests(unittest.TestCase):
    def frame(self):
        rng = np.random.default_rng(801750)
        latent = rng.normal(size=480)
        return pd.DataFrame({f'P{i}': (10 + i + (i - 3.5) * latent + rng.normal(0, .2, 480)) * scale
                             for i, scale in enumerate((1e-9, 1, 1e6, .3, 2, 10, 1e-3, 1e3))})

    def check(self, fit, expected):
        x = pd.to_numeric(expected[fit.x_name], errors='coerce').to_numpy(float)
        y = pd.to_numeric(expected[fit.y_name], errors='coerce').to_numpy(float)
        keep = np.isfinite(x) & np.isfinite(y)
        x, y = x[keep], y[keep]
        np.testing.assert_array_equal(fit.x, x)
        np.testing.assert_array_equal(fit.y, y)
        mean, scale = x.mean(), np.ptp(x)
        design = np.column_stack(((x - mean) / scale, np.ones(len(x))))
        coeff = np.linalg.lstsq(design, y, rcond=None)[0]
        np.testing.assert_allclose(fit.predicted, design @ coeff, rtol=1e-10, atol=max(np.ptp(y) * 1e-12, 1e-20))
        np.testing.assert_allclose(fit.slope, coeff[0] / scale, rtol=1e-10)
        expected_rsq = 1 - np.square(y - fit.predicted).sum() / np.square(y - y.mean()).sum()
        self.assertAlmostEqual(fit.rsquared, expected_rsq, places=14)

    def test_complete_scaled_population_matches_independent_centered_svd(self):
        frame = self.frame()
        original = frame.copy()
        fits, errors = pairwise_linear_fits(frame, list(frame))
        self.assertFalse(errors)
        self.assertEqual(len(fits), 28)
        self.assertEqual([fit.rsquared for fit in fits], sorted((fit.rsquared for fit in fits), reverse=True))
        for fit in fits:
            self.check(fit, frame)
        pd.testing.assert_frame_equal(frame, original)

    def test_shared_selected_rows_keep_duplicates_and_source_order(self):
        frame = self.frame()
        rows = tuple(range(350, 150, -1)) + (225, 225)
        groups = {'selected': rows, 'other': tuple(range(100))}
        cells = {('selected', name) for name in frame}
        fits, errors = pairwise_linear_fits(frame, list(frame), groups, cells)
        self.assertFalse(errors)
        for fit in fits:
            self.check(fit, frame.iloc[list(rows)])

    def test_nan_and_different_parameter_selections_keep_paired_cleanup(self):
        frame = self.frame()
        frame.loc[17, 'P0'] = np.nan
        groups = {'A': tuple(range(240)), 'B': tuple(range(240, 480))}
        cells = {(key, name) for key in groups for name in frame if name != 'P1' or key == 'A'}
        fits, errors = pairwise_linear_fits(frame, list(frame), groups, cells)
        self.assertFalse(errors)
        for fit in fits:
            expected = frame.iloc[:240] if 'P1' in (fit.x_name, fit.y_name) else frame
            self.check(fit, expected)

    def test_source_populations_and_cross_source_row_alignment_stay_independent(self):
        frame = self.frame()
        sources = ({'name': 'Reference', 'color': '#ed7d31', 'rows': tuple(range(240))},
                   {'name': 'Raw Data', 'color': '#5b9bd5', 'rows': tuple(range(240, 480))})
        groups = {'REF': sources[0]['rows'], 'RAW': sources[1]['rows']}
        cells = {(key, name) for key in groups for name in frame}
        panels, errors = source_pairwise_linear_fits(frame, list(frame), sources, groups, cells)
        self.assertFalse(errors)
        self.assertEqual(len(panels), 120)
        for panel in panels:
            fit = panel.sources[0].fit
            (x_source, x_name), (y_source, y_name) = panel.parameter_keys
            x_rows = sources[0 if x_source == 'Reference' else 1]['rows']
            y_rows = sources[0 if y_source == 'Reference' else 1]['rows']
            expected = pd.DataFrame({fit.x_name: frame.iloc[list(x_rows)][x_name].to_numpy(),
                                     fit.y_name: frame.iloc[list(y_rows)][y_name].to_numpy()})
            self.check(fit, expected)

    def test_constant_and_badly_conditioned_columns_keep_legacy_solver_results(self):
        frame = self.frame()
        frame['P0'] = 1e12 + np.arange(len(frame))
        frame['P1'] = 3.
        fits, errors = pairwise_linear_fits(frame, list(frame))
        self.assertEqual(len(errors), 7)
        for fit in fits:
            reference = fit_numeric_pair(frame, fit.x_name, fit.y_name)
            np.testing.assert_allclose(fit.predicted, reference.predicted, rtol=1e-10, atol=1e-6)

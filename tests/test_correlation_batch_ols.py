"""Batch OLS is checked against the unchanged individual lmfit reference."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from lmfit.models import LinearModel
from metrology_app.correlation_page import (
    pairwise_linear_fits, fit_numeric_pair, source_pairwise_linear_fits,
)

class CorrelationBatchOlsTests(unittest.TestCase):
    def test_many_well_scaled_pairs_do_not_restart_an_iterative_solver(self):
        rng=np.random.default_rng(6327)
        x=rng.normal(size=(128,50))
        frame=pd.DataFrame(x,columns=[f'P{i}' for i in range(50)])
        original=LinearModel.fit
        calls=[]
        def fit(model,*args,**kwargs):
            calls.append(1)
            return original(model,*args,**kwargs)
        with patch.object(LinearModel,'fit',fit):
            fits,errors=pairwise_linear_fits(frame,list(frame))
        self.assertFalse(errors)
        self.assertEqual(len(fits),1225)
        self.assertEqual(len(calls),0,'ordinary batch pairs should not each start lmfit')

    def test_batch_matches_lmfit_for_noisy_scaled_nan_and_outlier_data(self):
        rng=np.random.default_rng(3090)
        for scale in (1e-9,1.,1e6):
            x=rng.normal(10,2,360)*scale
            frame=pd.DataFrame({'A':x,'B':(2.1*x+3*scale)+rng.normal(0,.1,360)*scale,
                                'C':(-.9*x-5*scale)+rng.normal(0,.3,360)*scale})
            frame.loc[4,'A']=np.nan
            frame.loc[9,'B']=np.inf
            frame.loc[13,'C']=-np.inf
            frame.loc[17,'C']+=20*scale
            before=frame.copy(deep=True)
            fits,errors=pairwise_linear_fits(frame,list(frame))
            self.assertFalse(errors)
            for fit in fits:
                reference=fit_numeric_pair(frame,fit.x_name,fit.y_name)
                np.testing.assert_array_equal(fit.x,reference.x)
                np.testing.assert_array_equal(fit.y,reference.y)
                np.testing.assert_allclose([fit.slope,fit.intercept],[reference.slope,reference.intercept],rtol=1e-10,atol=scale*1e-11)
                np.testing.assert_allclose(fit.predicted,reference.predicted,rtol=1e-11,atol=scale*1e-11)
                self.assertAlmostEqual(fit.rsquared,reference.rsquared,places=13)
            pd.testing.assert_frame_equal(frame,before)

    def test_ill_conditioned_offset_keeps_the_existing_solver(self):
        x=1e12+np.arange(20,dtype=float)
        frame=pd.DataFrame({'A':x,'B':np.arange(20,dtype=float)*3+2})
        original=LinearModel.fit
        calls=[]
        def fit(model,*args,**kwargs):
            calls.append(1)
            return original(model,*args,**kwargs)
        with patch.object(LinearModel,'fit',fit):
            fits,errors=pairwise_linear_fits(frame,list(frame))
        self.assertFalse(errors)
        self.assertEqual(len(calls),1)
        reference=fit_numeric_pair(frame,'A','B')
        np.testing.assert_array_equal(fits[0].predicted,reference.predicted)

    def test_single_pair_public_api_still_uses_lmfit(self):
        original=LinearModel.fit
        calls=[]
        def fit(model,*args,**kwargs):
            calls.append(1)
            return original(model,*args,**kwargs)
        with patch.object(LinearModel,'fit',fit):
            fit_numeric_pair(pd.DataFrame({'A':[1.,2.,3.],'B':[4.,5.,7.]}),'A','B')
        self.assertEqual(len(calls),1)

    def test_repeated_batch_pairs_share_only_immutable_owned_vectors(self):
        frame=pd.DataFrame({'A':np.arange(30,dtype=float),'B':np.arange(30,dtype=float)*2+1,
                            'C':np.arange(30,dtype=float)*3+np.sin(np.arange(30))})
        fits,errors=pairwise_linear_fits(frame,list(frame),{'W':tuple(range(30))},{('W',name) for name in frame})
        self.assertFalse(errors)
        ab=next(fit for fit in fits if (fit.x_name,fit.y_name)==('A','B'))
        ac=next(fit for fit in fits if (fit.x_name,fit.y_name)==('A','C'))
        self.assertIs(ab.x,ac.x)
        self.assertFalse(ab.x.flags.writeable)
        with self.assertRaises(ValueError): ab.x[0]=99
        frame.iloc[0,0]=999
        self.assertEqual(ab.x[0],0)

    def test_small_batch_retains_exact_legacy_results(self):
        rng = np.random.default_rng(741)
        frame = pd.DataFrame(rng.normal(size=(64, 4)), columns=list('ABCD'))
        fits, errors = pairwise_linear_fits(frame, list(frame))
        self.assertFalse(errors)
        for fit in fits:
            reference = fit_numeric_pair(frame, fit.x_name, fit.y_name)
            np.testing.assert_array_equal(fit.predicted, reference.predicted)
            self.assertEqual((fit.slope, fit.intercept, fit.rsquared),
                             (reference.slope, reference.intercept, reference.rsquared))

    def test_large_source_selections_keep_pairing_and_do_not_reuse_stale_moments(self):
        rng = np.random.default_rng(7105)
        frame = pd.DataFrame(rng.normal(size=(600, 3)), columns=list('ABC'))
        frame['B'] += frame['A'] * 1.7
        frame.loc[17, 'A'] = np.nan
        sources = ({'name': 'Reference', 'color': '#ed7d31', 'rows': tuple(range(300))},
                   {'name': 'Raw Data', 'color': '#5b9bd5', 'rows': tuple(range(300, 600))})
        groups = {'R': tuple(range(300)), 'D': tuple(range(300, 600))}
        cells = {(key, name) for key in groups for name in frame}
        for iteration in range(2):
            with self.subTest(iteration=iteration):
                panels, errors = source_pairwise_linear_fits(frame, list(frame), sources, groups, cells)
                self.assertFalse(errors)
                self.assertEqual(len(panels), 15)
                for panel in panels:
                    values = panel.sources[0].fit
                    x_source, x_name = panel.parameter_keys[0]
                    y_source, y_name = panel.parameter_keys[1]
                    x_rows = sources[0 if x_source == 'Reference' else 1]['rows']
                    y_rows = sources[0 if y_source == 'Reference' else 1]['rows']
                    expected = pd.DataFrame({'X': frame.iloc[list(x_rows)][x_name].to_numpy(),
                                             'Y': frame.iloc[list(y_rows)][y_name].to_numpy()})
                    reference = fit_numeric_pair(expected, 'X', 'Y')
                    np.testing.assert_array_equal(values.x, reference.x)
                    np.testing.assert_array_equal(values.y, reference.y)
                    # lmfit's finite-difference stopping error can exceed 1e-10
                    # for near-zero predictions. An independent SVD solve is
                    # the coefficient oracle; keep exact legacy point pairing
                    # and the legacy R² comparison as separate requirements.
                    design = np.column_stack((reference.x, np.ones(len(reference.x))))
                    coefficients = np.linalg.lstsq(design, reference.y, rcond=None)[0]
                    np.testing.assert_allclose(values.predicted, design @ coefficients,
                                               rtol=1e-10, atol=1e-11)
                    np.testing.assert_allclose([values.slope, values.intercept], coefficients,
                                               rtol=1e-12, atol=1e-14)
                    self.assertAlmostEqual(values.rsquared, reference.rsquared, places=13)
            frame['B'] = frame['B'] * 1.3 + rng.normal(size=len(frame))

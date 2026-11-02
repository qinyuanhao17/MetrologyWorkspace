# Spectra BSL, exact residuals and GRR 3σ

## Agreed behavior

- Each legend section has Show All. It restores visibility in that section, reuses curves/caches, and does not change checked spectra.
- Set as BSL is available for one selected spectrum. It marks that row, displays the baseline identity and activates Residual. The baseline remains usable while unchecked. Deleting it returns Residual to Original; replacing the catalog clears it. Adding source files preserves an existing baseline, and replacing that file rebinds to the current catalog data.
- Options → Plot Mode provides exclusive Original, Residual and 3-Sigma actions. Main/floating titles identify the mode. Changing mode preserves X navigation and enables automatic Y bounds for the new quantity.
- Residual is measured minus BSL, only at exactly equal numeric wavelengths. Unmatched or invalid observations remain NaN gaps. There is no interpolation, extrapolation, rounding-based wavelength match or Delta phase wrapping. BSL matching prefers the same ChannelKey; otherwise exact AOI/AZI must identify one and only one baseline channel with the requested metric. Missing/ambiguous matches and repeated BSL wavelengths are reported rather than guessed.
- 3σ is a single curve of `3 × sample SD`, using divisor `n−1`, separately for each Wafer ID and ChannelKey (instrument, Channel ID, original AOI/AZI and data type). It uses checked original spectra, independent of BSL and legend hiding. At each exact wavelength it uses finite observations only, requiring at least two; otherwise it leaves a gap. It is not a confidence interval or a mean±3σ band. Clicking the aggregate curve selects its contributing spectrum files.

Numerical calculations live in `metrology_app/spectra_analysis.py`, without Qt imports. Source arrays are never modified. Residual results are cached per source/channel/metric and catalog/baseline revision; 3σ results are retained for each unchanged wafer/channel membership. Legend toggles reuse the prepared results and plot items. Notes for unavailable results appear in the footer with details in its tooltip.

## Focused verification

`python run_tests.py tests.test_spectra_analysis tests.test_spectra_viewer tests.test_spectra_map tests.test_sme_spectra -v`: **86 passed**, 22.624 seconds. The tests include literal worked numerical examples, exact versus near wavelengths, missing data, channel ambiguity, unchanged sources, large-offset variance, sample SD rather than population SD, zero spread, insufficient samples, independent wafer/channel groups, BSL lifecycle, floating plots, and legend item reuse. The aggregate-curve mouse selection check also passed separately after being added.

## Representative files

```powershell
python scripts/verify_spectra_analysis.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-analysis-real-2026-11-02.json
```

The current fixture has 594 readable spectra: the original 198 and the two 30 nm synthetic shift groups. The probe checked all files, selected the first original AZI45 spectrum as BSL, compared 99 available S residuals with an independent dictionary-based exact-wavelength subtraction, and compared **126 3σ curves** across N/C/S, Psi/Delta and all Mueller terms with NumPy `nanstd(ddof=1)` on an exact-wavelength matrix. All comparisons passed. SHA256 of all source numeric arrays was unchanged. Legend hide/Show All retained curve object identities, and the floating title identified 3σ.

With the chosen single-channel BSL, AZI90 files do not have a matching baseline channel. The shifted files in this fixture have no exact common wavelengths with that baseline. They are therefore unavailable for Residual and explicitly reported, as required by the selected no-interpolation rule. They remain independent groups in 3σ mode.

The probe ran on offscreen Qt at 1800×1000 while broad regression was also running. Residual submit/complete were 1.034/1.898 seconds; 3σ submit/complete were 1.358/2.055 seconds for the 594-file stress case. These are recorded timings, not a before/after speedup claim. Screenshots `qa_spectra_residual.png` and `qa_spectra_3sigma.png` were visually inspected: white backgrounds, mode titles, per-wafer colors, BSL identity, and four Show All buttons are present.

For the user's normal GRR-sized case, the same command with `--grr10` selected ten real spectra of the first wafer/channel. All 10 S residuals and 21 metric 3σ curves passed the independent comparison, source hashes stayed unchanged and Show All reused plot items. Offscreen submit/complete were **0.047/0.326 seconds** for Residual and **0.032/0.263 seconds** for 3σ. Details: `spectra-analysis-grr10-2026-11-02.json`.

Broad regression is recorded separately in `spectra-analysis-regression-2026-11-02.json`; AutoWeighting-related modules remain excluded at the user's request. Focused success does not imply a fully green repository suite.

The completed broad run executed **1,317 tests** in isolated `run_tests.py` shards (676 + 641): one failure and two errors, all present in the preceding regression. They concern the Correlation pagination pending-state assertion, `FakeCorrelationWorkspace` missing `raw_model`, and a read-only pandas literal frame. The pagination test passed a serial retry (0.540 s). All Spectra tests passed. No unrelated application/test fixes were made. `git diff --check` and syntax parsing passed, and `config/settings.yaml` remains unmodified.

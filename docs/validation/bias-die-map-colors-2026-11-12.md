# Show Die Map participation colors

Date: 2026-11-12. Full-suite testing remains deferred by the user. AutoWeighting
was not run; no release or tag was published.

## Behavior and cause

Show Die Map previously built coordinates only for analysis `source_rows`, so
Data selection exclusions removed points altogether. Its checked color also
represented outlier status, leaving every other point gray.

Coordinate context now comes from all original Raw rows. Data selection
participation and strict finite Bias exceedance remain separate:

- Excluded: light gray `#D6D9DE`, including a formerly out-of-range row.
- Included and out of range: red `#dc2626`.
- Included and not out of range: blue `#3E8BD8`.

Existing scope is retained: only wafers with outliers are shown; no exceedances
still gives an empty map. Nonfinite Bias is not counted as an exceedance. At a
shared physical position, any included outlier takes red priority, otherwise any
included row gives blue; only all-excluded positions are gray. Hiding excluded
table rows does not hide their map context. Source coordinates and regression
or Bias formulas are unchanged.

Identical point tuples are reused after analysis participation changes. Colors
update on existing scatter points, retaining plot objects and ranges. Ordinary
Spectra Viewer Die Map behavior remains unchanged.

A focused test also exposed a previously unsupported `StoredFrame` membership
check for closed Spectra drafts. The map now projects its metadata column using
the read-only native SQLite `StoredFrame.column_values()` interface; samples are
neither loaded nor decoded and the Spectra child remains unopened.

## Verification

The new exclusion test first failed with 4 points instead of 5. The deferred
draft test first failed with `TypeError: argument of type 'StoredFrame' is not
iterable`. Both now pass.

```powershell
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' run_tests.py tests.test_bias_die_map tests.test_spectra_map tests.test_deferred_workspace_frames -v
```

**26 targeted tests passed in 3.841 seconds**. Coverage includes Data selection
Apply with hidden excluded table rows, exclusion of a prior outlier, exact three
colors, unchanged scatter/plot/ranges, coordinate identity, strict Bias limits,
metadata-only closed drafts and existing ordinary map/storage behavior.

The real-file probe uses the first wafer's 21 original Raw/Reference rows from
`JC1913/matching-analysis.mwkb`, with all 1,890 saved coordinate metadata rows
available through a deferred frame. Excluding one outlier yields **gray 1 / red
8 / blue 12**, with all 21 points retained, unchanged plot/ranges, no opened
Spectra Viewer and no decoded spectral samples. The rendered map was inspected.
The Workbook SHA-256 remains unchanged.

Executable scenarios: `docs/features/card_matching.feature`, connected to
`tests/test_bias_die_map.py`. Machine evidence:
[bias-die-map-colors-2026-11-12.json](bias-die-map-colors-2026-11-12.json).
Local probe, log and screenshot: `.cache/validate_bias_map_colors.py`,
`.cache/bias-map-colors-final.log`, `.cache/bias-map-colors-validation/`.
Production `config/settings.yaml` has no worktree modification.

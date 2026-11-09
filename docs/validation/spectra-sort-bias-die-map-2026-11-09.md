# Spectra tree sorting and mapping Bias Die Map — 2026-11-09

Spectrum tree headers sort siblings within the existing hierarchy. Repeating a
header click reverses the order; double-clicking any header disables sorting
and rebuilds default catalog order while retaining expansion, checked/selected
spectra and plot axes. Die/Field/count columns use numeric ordering (including
negative Fields), and text uses natural ordering. Lazy population batches
inserts before enabling sorting. Collapsed branches use their first
default-order source's metadata for sorting without instantiating leaves.
Sorting does not rebuild spectral curves.

Parameter mapping adds a final Die Map column with a Show Die Map button for
each analyzed parameter. It uses the same strict finite absolute Bias test as
the count: `abs(Bias) > limit`, including when the displayed Bias plot is in
percent. Exact-limit and non-finite Bias values are excluded. Included source
row identities, not compacted table positions, locate the original Raw Data.

Maps reuse Spectra Die Map cards, fixed sizes, paging, PAD grid and selection.
Only wafers containing exceedances appear; exceedances are blue and other
included rows on those wafers are gray. These maps are read-only and do not
change Workbook participation. Changing a limit refreshes open maps and reuses
points/cards when the affected wafer population is unchanged. Stale analysis
disables buttons and labels existing maps as needing a new analysis.

Coordinates come from explicitly labelled X (mm)/Y (mm) columns, or embedded
Spectra metadata joined by Wafer/Lot/PAD/Die. An open Spectra child's current
metadata supersedes its saved draft. No SME path/name matching, spectral-array
decoding or Field-to-mm guess is used. Missing/ambiguous coordinates are listed
with source row numbers and the count of unmapped exceedances is shown.

Validation:

- Three new workflows cover ascending/descending negative numeric Fields,
  header double-click reset, participation/selection and axes preservation,
  strict threshold membership, source identity joins, missing/ambiguous XY,
  the actual mapping button and card reuse on limit updates.
- Expanded focused run: 249 tests in 91.309 s; 246 passed and three SQLite
  temporary-file errors occurred in the sandbox. All three unchanged save/load
  tests passed outside the sandbox with normal TEMP/SQLITE_TMPDIR (2.837 s).
  This is a scoped run plus an environment recheck, not a full-suite result.
- After the final read-only captions and cache/error handling, all 18
  new-workflow/Die Map tests passed in 2.953 s.
- Final sort/cache changes passed all 75 new-workflow/Spectra Viewer tests
  (22.070 s); the final three workflows, including collapsed-branch sorting,
  passed again (0.546 s).
- The supplied JC1913/matching-analysis.mwkb produced exactly 1,568 mapped
  out-of-range OCD_Depth records across 89 wafers, with zero missing XY.
  No Spectra child was opened and no spectral arrays were decoded by this map
  adapter. The source WKB SHA-256 was unchanged. Native screenshots were
  inspected. Probe/logs: `.cache/verify_bias_die_map_real.py`,
  `.cache/bias-map-real/` and `.cache/bias-map-*.log`.

Existing unrelated working-tree edits were retained. AutoWeighting remains
deferred. The full repository regression was not repeated; earlier failures
are documented in `die-map-pads-2026-11-09.md`.

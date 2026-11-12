# Spectra Info XY coordinates and default order

Date: 2026-11-12. Local development only. Full-suite testing remains deferred at
the user's request; AutoWeighting was not run.

## Behavior

- Spectra Info now has a third **XY** tab containing Wafer ID, Lot ID, PAD Name,
  Die Seq, FIELD X, FIELD Y, X(mm), Y(mm). The existing two report schemas are
  unchanged. All tabs support Copy Table / CSV export.
- X/Y come directly from the parsed SME coordinates already held by the Viewer,
  not Workbook coordinate cells, Field indices, PAD geometry or interpolation.
  Missing values stay blank and original numeric precision is retained.
- With nonempty Workbook Raw Data, the same validated pairing used by the other
  tabs supplies exact original row order and preserves row-aligned Reference.
  Timestamp validation, ambiguous matches and unmatched spectra still block export.
- Standalone Viewer and empty Workbook Raw Data use existing `SpectrumFile.sort_key`:
  natural Wafer ID → Lot ID → PAD Name, numeric Die Seq, natural measurement time,
  normalized source-path tie break. Missing Die Seq sorts last. No Reference
  pairing or identity is fabricated. Spectra Info is available independently.
- Data selection includes X(mm)/Y(mm). Its applied checkboxes determine report
  participation. Coordinate filters are retained by Selection Script and .spec
  save/load. Filtered rows / search remain editing views and do not independently
  restrict already checked report rows.

## Default-order evidence

Eight existing recent Workbooks were inspected using native SQLite fetches of
Raw Data only, without decoding spectra. Across their 1,235 Wafer/Lot/PAD groups,
all numeric Die sequences are ascending. These include related saved variants,
not 1,235 independent measurement experiments. Four files have manually/import
ordered wafer blocks rather than a globally natural identity order. Therefore
the implementation never substitutes default sorting for actual Raw row order.

The fallback deliberately reuses the Viewer's existing natural identity/Die
sort, with measurement time and path used only for deterministic ties; physical
XY does not establish a universal acquisition sequence. The JC1913 example's
complete default identity order happens to equal its actual Raw order.

## Verification

- Red/green tests first demonstrated missing XY output, missing standalone
  access and missing Data selection coordinate columns.
- 73 related tests passed in 22.236 seconds:
  `tests.test_spectra_info_xy`, `tests.test_spectra_info`, `tests.test_sme_spectra`,
  `tests.test_spectra_workbook`, `tests.test_selection_script`.
- The four new XY tests were rerun after adding coordinate-filter persistence
  assertions: passed in 0.828 seconds. Coverage includes exact SME-vs-Raw
  coordinate provenance, natural numeric sorting and repeated Die times, missing
  coordinates, clipboard/CSV, live participation, filter Apply and .spec restore.
- Actual `JC1913/matching-analysis.mwkb`: 1,890 output rows, all original Raw row
  positions and all X/Y values checked. Checking only Die 1 and 3 produces 180
  rows in the report UI and export. CSV round-trip values match.
- Real-file coordinate verification reads the saved SME metadata without sample
  payload decoding. Three original SME files were also parsed anew; their XY
  values agree exactly. The Workbook SHA-256 and three SME hashes remain unchanged.
- A rendered XY table from the three real SME files was inspected with the normal
  application font setup; all eight columns and copy/export controls are visible.
- Scratch settings were used; `config/settings.yaml` has no worktree modification.

The new scenarios in `docs/features/spectra_viewer.feature` map to the executable
tests in `tests/test_spectra_info_xy.py`. Existing source-update/matching scenarios
remain covered by `tests/test_spectra_info.py`.

Evidence: [spectra-info-xy-2026-11-12.json](spectra-info-xy-2026-11-12.json).
Local probe: `.cache/validate_spectra_xy.py`; actual CSV and screenshot:
`.cache/spectra-xy-validation/Spectra_XY.csv` and `xy-table.png`.

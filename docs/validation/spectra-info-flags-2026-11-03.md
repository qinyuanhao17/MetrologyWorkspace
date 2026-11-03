# Spectra Info and Test Flags — 2026-11-03

## Final behavior

The black Spectra Info button sits immediately before Open Die Map in a Match
Workbook's Spectra Viewer. Its two tabs omit/include Test Flag respectively;
Test Flag is the last column in the second tab. Both tables, full-table copy,
selected-cell copy and CSV retain original Raw Data order.

**The user's final scope correction is authoritative:** report only currently
checked spectra. Data selection's saved filters/search/show mode remain intact
for editing participation, but do not further limit Spectra Info. This fixes the
provided Workbook case where a retained filter locates the 21 excluded rows
while Hide excluded is enabled; applying both to the report had produced zero
rows despite 1,869 checked spectra.

Match on Wafer ID, Lot ID, PAD Name, Die Seq, FIELD X and FIELD Y. Options →
Verify Spectra Info Filename Timestamp defaults on and also checks the final
timestamp in Raw Data's SME filename against the time read from SME metadata.
It does not compare full paths or filesystem modification times. Missing,
extra or ambiguous checked-source matches are listed and block copy/export.

Relative Column is FIELD X; Relative Row is FIELD Y. Time comes from the SME,
Type is Accuracy, and Reference values use original paired row positions.
**The user's final naming correction is authoritative:** Reference columns keep
their actual names and order (e.g. `OCD_Depth`), rather than the earlier requested
generated `OCD_DEPTH1`, `OCD_DEPTH2` names. CSV protects the long Time string with
the same leading-tab convention as the supplied company export.

Data → Set Test Flag supports default 0 (Fallback), 1 and -1, integer values
added/deleted/renamed locally, measurement-set grouping by Wafer/Lot/Tool/PAD,
search, Assign Visible and Shift-range assignment. Cancel leaves live state
unchanged. Both this editor and existing Marks use ScrollSafeComboBox: wheel
events scroll the surrounding table without changing values. Test Flag values,
assignments, grouping and timestamp-check preference persist in `.spec` and WKB
Spectra drafts. None of these edits changes source measurement strings.

Die Map uses 12 px points and moves Die labels from an 8 px to 5 px offset.
Nonzero flags use a separate upper-right glyph: 1 green, -1 red, custom integers
neutral gray with numeric hover text; 0 has no glyph. Flag changes retain map
widgets, sizes, coordinate ranges and participation colors. The glyph occupies
7 × 9 px; a padded cache tile avoids clipping the offset symbol. Pixel tests
verify that both default colors are actually painted.

Two independent context actions replace the old Apply to Similar Wafer:
Apply Check To Similar Wafer copies only participation; Apply Flag to Similar
Wafer copies only Test Flags (including clearing to zero). Both require identical
Die ID sets and every corresponding absolute X/Y coordinate difference strictly
below 0.4 mm. Decimal comparisons prevent an exact 0.4 boundary from being
accepted through binary rounding. Conflicting duplicate Die states are rejected.

## Validation

- The initial Spectra/Die Map/selection/Marks focused run passed 171 tests.
- After the empty-report correction, the relevant selection/workbook/info/bulk
  tests and two Matching-window selection tests passed 46 tests in 11.439 s.
- After the final Reference naming correction, all 9 Spectra Info tests passed
  in 1.896 s. These include metadata pairing, errors, both report tabs, copy,
  CSV, flags, `.spec`, grouping, safe wheel, flag pixels and independent similar
  wafer actions. `git diff --check` passed.
- No full regression was run: it remains deferred at the user's request.
  AutoWeighting was not tested. Earlier unrelated full/scoped-suite limitations
  remain documented in `spectra-selection-ui-2026-11-03.md`.

The supplied `JC1913/matching-analysis.mwkb` embedded metadata and company CSV
were checked across all 1,890 rows. Tool SN, both field axes, Time, Accuracy and
Reference values matched all 1,890 company-export rows after identity alignment.
The actual Reference name is `OCD_Depth`. Company CSV has 735 Test Flag=1 rows;
the new viewer intentionally defaults all flags to 0 as requested, until edited.

Copying that Workbook's complete Selection Script produced **1,869 report/CSV
rows**, retaining the original included-row sequence despite the old editor
filter. A separate 20-checked-spectrum case produced exactly 20 copied and
exported rows. Source WKB and CSV SHA-256 hashes were unchanged. The real-file
probe loads embedded metadata, not numerical sample arrays; it establishes
pairing, report and selection behavior, not 1,890-spectrum rendering speed.

All probes used isolated settings/recovery/Matplotlib/temp paths under `.cache`.
Existing pending changes and source files were preserved. Logs, screenshots and
the repeatable probe are `.cache/spectra-info-*` and
`.cache/verify_spectra_info_real.py`; summary data is in the adjacent JSON file.

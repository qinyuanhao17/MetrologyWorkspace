# SME compatibility validation — 2026-11-03

Validated local changes against source tag `v5-dev2` / commit
`59828a439018851a0da410e5f4954167c5880df2`. Compatibility validation preceded
the `v5-dev3` source-tag publication; no installer was rebuilt. Parser cache
version is now `3.2.0`.

## Reading rules

- Instrument, mode and internal version strings are retained as metadata. They
  do not select a reader or determine whether a supported numeric layout can load.
- SE3 records are read using compact or expanded counted-array layouts. Each
  channel has its own wavelength vector and point count. The optional global
  word, declared channel boundaries, array lengths and complete footer are checked.
- Series come from populated arrays: Mueller, Psi/Delta/N/C/S, or reflectance.
  An all-zero matrix placeholder is not exposed as measured Mueller data.
- No fixed wavelength point count or wavelength-range allowlist is imposed.
  Single-point and longer arrays are accepted. A one-million-point allocation
  guard remains; wavelength arrays must be nonempty, finite and increasing, and
  associated vectors must have matching lengths.
- The verified zlib-compressed legacy layout uses little-endian float32 values
  in a fixed-capacity record. Its valid wavelength prefix determines point count;
  padding is excluded. Missing N/C/S, instrument and azimuth are not invented.
- Filename parsing accepts both `Die1_C4_R2` and `Die1_R2_C4`, retaining the named
  column/row axes. Embedded source metadata still takes priority.

## Supplied files

| Source under JC1913 | Result |
| --- | --- |
| `OCD_RP01_OFFSETLTO_JC_FM.rcp` directory | 404 / 404 readable; compressed SE2.8 records, 916 valid points in this batch |
| `spectra_all_IRSE` directory | 470 readable IRSE_II_E(1700) files; 1,128 explicitly reported as TSD encrypted |
| `DPC00703.10_DH0912.003-OCD_NAN-ANA_PAD-E-45_Die1_C-1_R4_20260909141623387.sme` | Readable; SE3.5 UVSE_II+, 903 points |
| `LP300005.23_GK-PadN-PLDSR-Dynamic_A13-048_PAD N_Die1_C-5_R0_20261016111859433.sme` | Readable; SE3.5 LDSR-P / PSR; two reflectance channels with 902 and 903 points |

The encrypted files still require a decrypted copy exported from an authorized
environment. They are not rejected because of head, mode or point count.

SHA-256 checks before/after public-reader and UI verification covered all 2,004
supplied source files above; every source remained byte-identical. The original
42-file fixture plus the prior IRSE sample (43 files) produced exactly the same
numeric arrays and spectrum types as `HEAD`. Combined numeric digest:
`a43d1d1657f86f66359738fc92446088016e67cc07d1fa16695e60465449e96a`.

Actual Qt verification loaded six source files / twelve channel records together:
legacy, UVSE, IRSE, LDSR-P, IMSE and six-channel BBSE. All expected plot families
rendered. Legend entry counts were NCS 3, Psi Delta 4, Mueller 9, Reflectance 2.
Both LDSR-P vectors retained their independent sampling. Die Map had five tiles;
the two-channel LDSR-P file remained a single source measurement point.

## Executable acceptance checks

`tests.test_sme_compatibility` covers eight public-reader behaviors, including:

- Unknown instrument and mode strings retain exactly the original series and
  values across compact, expanded, IMSE, BBSE, DTS and multichannel LDSR records.
- An unknown internal version retains identity and numeric values.
- Dynamic counts of 1, 2, 17 and 1,200 work for compact and expanded layouts.
- A real multichannel file retains independent 902 / 903 point vectors.
- Corrupt channel counts, vector lengths, incomplete footers and extra bytes
  fail without returning a partial spectrum.
- Legacy stored values, missing-series semantics, R/C names and source bytes
  remain correct.

The broader focused run passed 139 tests across SME, Viewer, Die Map, analysis,
WKB, Selection Script, original-file export and source smoke modules. The final
compatibility module passed all eight tests after the dynamic-count checks.

Regression used `python run_tests.py` in two isolated shards covering all 112
in-scope modules: **1,373 run; 1,370 passed; three previously recorded failures**:

1. `MatchingWindowTests.test_correlation_button_opens_active_reference_and_raw_sources`:
   its fake Correlation workspace lacks `raw_model`.
2. `CorrelationRenderBatchTests.test_pagination_filter_and_threshold_changes_replace_pending_page`:
   `background_render_pending` assertion fails.
3. `LiteralFrameSourceTests.test_proved_source_retains_all_literals_without_rescanning_values`:
   pandas reports a read-only assignment destination.

Full regression is therefore not green. No new failures appeared. AutoWeighting
remained deferred: `test_auto_weighting`, `test_auto_weighting_ocr`,
`test_auto_weighting_window`, and the two modules that import those workflows
(`test_shell`, `test_writer_cell_serialization`) were excluded, as in the prior run.

All runs used scratch settings, recovery, reminders and Matplotlib directories,
with the user's normal Windows TEMP/TMP location. `config/settings.yaml` was not
changed. Full module lists, observed counts and failure names are in the adjacent
JSON report. `git diff --check` passed.

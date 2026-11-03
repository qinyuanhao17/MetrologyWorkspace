# SME metadata, structural compatibility and linked legend selection

The user requested analysis of format recognition, plus implementation of linked
legend highlighting. This change keeps the existing parser routes (including
the preceding local IRSE fix) and implements the legend behavior.

## Reader analysis

Instrument, measurement mode and the embedded version string describe the
source. Their spelling alone should not make compatible data unreadable. The
current `parse_one` routes by exactly `SE3.3`/`SE3.5` and exact instrument names,
and each reader repeats instrument/mode checks. This rejects a new label even
when its data is otherwise supported. Plotting already mainly depends on the
available series and spectrum type, rather than an instrument whitelist.

The verified files have common spectral concepts but different byte layouts:

| Supplied data | Verified structure difference |
| --- | --- |
| UVSE SE3.3 | No global header tag; zero array followed directly by wavelength, Psi/Delta, N/C/S and 16 matrix values per wavelength. |
| IRSE SE3.5 | A global tag and additional empty arrays/scalar precede the same spectral series; the supplied file has 234 wavelengths and a nonzero matrix block. |
| IMSE SE3.5 | A different prefix; Psi/Delta and N/C/S are present, while its matrix block is an all-zero placeholder. These files must not acquire a fabricated Mueller measurement. |
| BBSE SE3.5 | Multiple independently headed channels; wavelength and Mueller blocks are present without populated Psi/Delta or N/C/S arrays. |
| DTS SE3.5 | Wavelength and reflectance arrays, with a different prefix/tail. Unknown auxiliary arrays from other layouts must not be relabeled reflectance. |

Recommended next reader change: recognize the outer envelope, decode the
common metadata, and try the bounded, verified structural layouts independently
of instrument/version labels. An optional global header tag is a structural
candidate, not a reason to reject a new version label. Accept only an unambiguous
layout with valid array lengths, channel boundaries, wavelengths and required
data blocks; retain source metadata verbatim. Report ambiguity, truncation,
invalid arrays and encryption precisely. Draw only the series actually present.

The leading file bytes `SE3` are the supplied format's envelope signature;
they are distinct from its embedded version string. Envelope decoding remains
necessary. Instrument may still identify channels for grouping and legends.
The current `spectrum_identity` also special-cases all `BBSE` records as
Simulation; that assumption should be limited to the known simulation fixture
when source identity is generalized.

Two additional checks deserve separation from compatibility: the DTS locator
currently assumes 32 or more points and a 50–10,000 nm range, and the IMSE reader
requires N/C/S to agree with Psi/Delta to 1e-9. Those are sample-specific
heuristics/consistency checks, not instrument-independent proof of a byte
layout. A structural reader should preserve valid stored series and report
quality warnings separately. Missing samples can remain gaps, and a missing
measurement family should not suppress other readable families. Units and
unknown auxiliary quantities must not be guessed or silently rescaled.

## Legend behavior and verification

Selecting checked spectra or a main/floating curve emphasizes matching entries
in every applicable legend with a native selected background, bold text and a
thicker original-color sample. Wafer grouping highlights matching wafer/channel
entries; SME Name grouping highlights the individual source/channel entries.
Multiple entries can remain emphasized; a newly selected entry is scrolled into
view. Clearing linked selection clears emphasis. Checks, hidden/struck entries,
colors and manual ranges stay intact. Selection updates existing list items and
does not call the full plot-refresh path.

Executable acceptance: `SpectraViewerTreeTests.test_legend_selection_follows_wafer_and_sme_groups_without_changing_checks`
and `test_curve_and_blank_clicks_sync_selection_with_map_and_floating_plot` in
`tests/test_spectra_viewer.py`. Both failed before the implementation and passed
afterward. AutoWeighting remains deferred; settings use scratch files.

The focused SME/Viewer/Die Map/calculation/Workbook suite passed **115 tests**.
The scoped repository regression ran **1,357 tests**: 1,354 passed, with the same
three existing failures as v5-dev (Correlation test double, Correlation pending
page assertion and pandas literal-frame writeability); no new failures.
See [structured results](sme-format-and-legend-2026-11-03.json).

A separate native Qt probe used the original 42-file verified fixture plus the
supplied IRSE file. Light and dark themes each showed a selected, bold,
on-screen entry in all four legend families; clearing selection removed every
highlight. Images are in `.cache/legend-selection-visual/light.png` and
`dark.png`. No source measurement file, published tag/package or personal
settings file was changed by these checks.

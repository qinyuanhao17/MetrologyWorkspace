# v5-dev2 — source tag

This publication contains source only. Existing GitHub Releases and Windows
Setup/portable ZIP assets are unchanged.

- Read the verified `IRSE_II(1700)` SE3.5 layout, preserving its stored N/C/S,
  Psi/Delta, Mueller values, coordinates and embedded source identity.
- Emphasize linked legend entries when spectra or curves are selected, in
  Wafer and SME Name coloring modes, including multi-selection and clearing.
- Keep Die Map plots at a fixed size in three columns with scrollbars. Add
  Check Unselected / Uncheck Unselected for the wafer where the menu opens.
- Export existing SME bytes in a background child window with Retry, Skip,
  cancellation and a complete unavailable-file report. Handle long Windows
  paths for batch export and subsequent reading; preserve folder structure
  and prevent overwriting existing files.

The general instrument/version-independent structural reader remains an
analysis proposal; it has not replaced the verified parser routes in this tag.

Validation: 130 focused tests passed. The scoped repository regression ran
1,365 tests, with 1,362 passing and the same three existing unrelated failures
as the v5-dev baseline. AutoWeighting-related tests remain deferred. Actual
JC1913 validation copied and read back 1,891 files, with matching source/target
SHA-256 hashes and unchanged source files.

Details: [reader and legend analysis](../validation/sme-format-and-legend-2026-11-03.md)
and [Die Map/export validation](../validation/die-map-export-2026-11-03.md).

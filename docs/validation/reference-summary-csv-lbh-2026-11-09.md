# Reference Summary CSV compatibility and LBH — 2026-11-09

NOVA accepts data records wider than the header only when every surplus
field is empty (including surrounding whitespace). Extra nonempty values and
short rows remain errors. CSV records are parsed and reserialized instead of
stripping comma characters: quoted commas, empty declared columns, measurement
strings and original physical source-line identities remain intact.

Per the user's final correction, all `*_LBH` columns collapse to one final
`LBH` column: 0 only when every flag is `NO_LBH`, otherwise 1 (including blank
or numeric values). Comparison ignores surrounding whitespace and case. Files
without those columns remain unchanged. NOVA, KLA and PMISH share this rule;
CDSEM1's independent Excel conversion remains unchanged.

The Reference Summary page title and subtitle, vendor-processing paragraph
and redundant VENDOR eyebrow are removed. The source panel heading is Vendor.
Vendor help is available as the combo tooltip.

Five Reference Summary tests passed, including rejected bad widths, preserved
quoted commas/measurement strings, missing values and non-NO_LBH flags, original
line numbers, UI captions and CDSEM1 conversion. The supplied
`Desktop/X1U301results.CSV` parsed and merged 414 records, removing two repeated
headers. All 414 rows have LBH=0. Every retained measurement value was compared
to the original CSV and the source SHA-256 remained unchanged. Scratch output
and raw evidence are under `.cache/ref-summary-validation/`.

No complete repository regression was repeated for this focused update. The
earlier repository-wide limitations remain recorded in
`die-map-pads-2026-11-09.md`. AutoWeighting remains deferred.

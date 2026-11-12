# Spectra Group presentation and interaction acceptance

Date: 2026-11-12. Local changes only. The user continues to defer the full suite;
AutoWeighting was not run. This supersedes the earlier separate Group TestFlag
contract in the Group feature's initial acceptance.

## Behavior

- Compact Head/Mark controls above an identity-aware table: Wafer ID, Lot ID,
  PAD Name, Die Seq, TestFlag, Head, Mark, Group. Native table headers replace
  spreadsheet letter headers. The table uses available height; status and
  Apply/Close stay in the footer.
- TestFlag uses the Viewer's authoritative Spectra Info/Die Map state. Editing
  Group flags is staged until Apply; external flag edits refresh the open Group
  table. Applying Group settings or explicitly copying WKB Groups updates shared
  flags and supports the existing Undo/Redo history. Copy remains one-time and
  identity-based; check states and source data are unchanged.
- New Spectra Mark definitions are POR (first/fallback), POR+, POR-. Existing
  Workbook or saved custom definitions remain unchanged. Add Mark has Replace
  and Append modes. Append creates/reuses an actual composite definition such
  as Old/POR. Multiple distinct Marks are summarized with commas to distinguish
  them from a composite Mark. Mark edits are atomic undoable operations.
- Tree Highlight is a checkable toggle. It adds a thick foreground magenta
  stroke independently of transient selection, on both axes and in enlarged
  plots. It respects hidden channels and spectrum checks, preserves original
  curves and axis ranges, and persists in .spec/WKB child state. Batched SME
  colours and unbatched rendering use the same overlay semantics.
- Plot-local U unchecks selected spectra in main and enlarged plots. It is
  handled only by plot widgets, not a window-wide text shortcut.

Colour source: [Paul Tol's vibrant scheme](https://sronpersonalpages.nl/~pault/),
magenta `#EE3377`. Thickness and foreground placement supplement colour;
original sample arrays and normal channel colours are retained.

## Focused verification

`run_tests.py` with scratch settings:

- Initial four new behavioral checks failed on missing behavior before edits.
- Related regression: **123 tests passed, 80.809 seconds** across
  `tests.test_spectra_group_interactions`, `tests.test_spectra_groups`,
  `tests.test_spectra_viewer`, `tests.test_spectra_workbook`,
  `tests.test_spectra_map`, `tests.test_spectra_info_edits`.
- An earlier 85-test related run passed in 49.677 seconds; a final 10-test
  Group/interaction run passed in 3.561 seconds during UI refinement.
- After clearing persistent overlays on source replacement/deletion and adding
  the text-editor U guard assertion, **31 Group/interaction/storage tests passed
  in 24.323 seconds**. Full-suite testing remains deferred.
- Executable BDD scenarios: `docs/features/spectra_viewer.feature`, exercised
  through these test modules, not treated as standalone proof.

Actual JC1913 `matching-analysis.mwkb`: native SQLite fetch reads all **1,890**
stored spectrum metadata identities without loading sample payloads. The open
Group table shows the full count, composite Old/POR, and shared flags 1/-1.
Three original SME files verify magenta rendering, selection clearing,
unchanged base curve objects and ranges, and U in the enlarged plot. Rendered
Group settings and plot screenshots were inspected. WKB and source SME SHA-256
hashes were unchanged.

Evidence: [machine report](spectra-group-interactions-2026-11-12.json).
Local reproducible harness: `.cache/validate_spectra_group_interactions.py`;
screenshots: `.cache/spectra-group-interactions/group-settings.png` and
`.cache/spectra-group-interactions/highlight.png`.

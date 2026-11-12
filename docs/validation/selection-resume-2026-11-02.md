# Completed on 2026-11-03 — historical pause plan below

The scheduled continuation completed these tasks and the later Die Map rename/
rectangle request. Source commit `7a3175a` is published as GitHub tag `v5-dev`.
Semantic Selection Script v2, actual supplied-Workbook paste, native Die Map
selection/toggling and original SME export are validated. See the tracked
`docs/validation/v5-dev-2026-11-03.md` for current results and the three known
unrelated scoped-suite failures. The following is the superseded pause plan.

## Paused at the user's request — 2026-11-02 23:39 Asia/Shanghai

Resume in this chat three hours after the pause, at approximately 2026-11-03
02:42 Asia/Shanghai. Scope is unfinished requests raised after 23:00 on
2026-11-02. The user prioritized finishing Selection Script/Data selection and
original-SME export before the newer wafer-map interactions.

## Highest priority: correct selection identity

The latest user correction is definitive: match selection using **Wafer ID,
Lot ID, PAD Name and Die only**. SME names and filesystem paths must not enter
the matching criterion. This correction has NOT been implemented yet.

`metrology_app/selection_script.py` currently exports version-1 JSON and uses
paths, with a just-added unique-filename relocation fallback. Those rules are
superseded and must be replaced, not retained as an alternative primary key.
Keep grouped filters, AND/OR joins, global search, visibility, Hide excluded
rows and complete check/uncheck states. Preserve source strings and identities.
For repeated identical Wafer/Lot/PAD/Die identities, apply one consistent state
to all matching spectra; report conflicting source check states rather than
silently choosing one. Die integer representations may need canonicalization
without changing stored measurement strings. Missing Lot/PAD can represent
empty identity fields; never fall back to display row numbers or SME names.

Update the public JSON format/tests and tell users to recopy old scripts if
their incompatible old identity schema cannot be supported safely. Script
panel validation must display ambiguity/errors without crashing or copying a
stale recipe. Main Data selection and Spectra should share the same semantic
identity. A change of filename/path alone must not affect transferred checks.

## Reproduce against the user's actual Workbook

File: `C:/Users/Yuanhao Qin/OneDrive/Desktop/JC1913/matching-analysis.mwkb`.
It contains 1,890 rows in `raw`, one-column `reference`, `test_flags`, and 1,890
embedded files in `spectra.preview.spectra`. Parent selection filters
`Raw Data / Wafer ID` to `AI01750.00-06`, with 21 excluded and Hide excluded
rows enabled. Raw source paths start at historical `C:/Users/JC1913/...` while
embedded Spectra point at the current Desktop/JC1913 tree. All 1,890 full paths
differ. The filename workaround passed real UI paste (1,869 checked), but this
is **not acceptance evidence for the latest semantic-identity requirement**.

Read the Workbook; do not save over it or rewrite its paths. One-off probes:
`.cache/verify_provided_selection.py`, `.cache/verify_selection_workflows.py`.
Update them and rerun using the semantic rule, including reordered records and
different SME names. Existing reports in `selection-script-provided-workbook-2026-11-02.json`
and `selection-script-real-2026-11-02.json` describe earlier rules.

## Local features already implemented; finish acceptance after identity fix

- Spectra Viewer has Data → Data selection, one row per SME file, Apply updates
  tree checks/plots, and view state persists in `.spec`/Workbook drafts.
- All Selection dialogs have a top-right Selection Script button and a live
  JSON editor with Copy/Paste/Apply. Invalid scripts leave the draft unchanged.
- Parent-following child dialogs inherit parent checks, filters and hide/view
  settings. Accepted local changes switch to Full data without replacing
  source tables; unchanged Apply/Cancel retain following mode.
- Export Checked Spectra copies existing source SME bytes only, preserving
  folder hierarchy, on a background thread. It never writes reconstructed SME
  content. Missing originals/target collisions fail preflight; cancellation
  removes only this export's new files. Actual exported fixtures reload and
  have identical bytes/hashes.

Code added/modified this phase: `selection_script.py`, `data_selection.py`,
`input_planning.py`, `window.py`, `matching_window.py`, `sme_spectra.py`,
`spectra_viewer.py`, and `spectra_workbook.py`. Preserve earlier uncommitted
Spectra/WKB/UI work and unrelated `asdf.xlsx` / `matching-matplotlib.xlsx`.

## Wafer-map requests still unimplemented

1. Show unchecked points in light gray, keeping checked points blue.
2. Double-click a point to check/uncheck its corresponding spectrum(s) and
   synchronize the tree, selection and plots.
3. Eliminate page rebuilding and size changes for check/uncheck. Current
   `SpectraViewerWindow._sync_map` includes checked keys in its signature and
   calls `SpectraMapWindow.set_data`, which clears/rebuilds the entire page.
   Update existing point appearances/state instead; retain plot widgets,
   layout, ranges and titles. Measure repeatable before/after latency using
   JC1913 before claiming improvement. No baseline has been collected yet.
4. Add Apply to Similar Wafer to each wafer's context menu. Proposed accepted
   rule: the Die-ID sets must match and **every** corresponding Die must satisfy
   abs(delta X) < 0.4 mm AND abs(delta Y) < 0.4 mm. Same count alone is
   insufficient. Reject/skip absent coordinates or conflicting duplicate Die
   coordinates. Handle mixed checks explicitly. Group wafers by Wafer/Lot/PAD.
   This design was discussed but no product code or tests were changed yet.

## Verification and next runs

Use `C:/Users/Yuanhao Qin/.conda/envs/metrology-workspace/python.exe` and
`python run_tests.py`; use scratch settings, never `config/settings.yaml`.
Set TEMP/TMP to the long path `C:/Users/Yuanhao Qin/AppData/Local/Temp` for
repository tests; short 8.3 temp paths cause unrelated recovery assertions.
AutoWeighting is explicitly deferred: do not run its tests or detection.

Before the latest semantic correction, focused runs passed 117 tests, 35
source/script tests and 51 acceptance tests. The last scoped broad run ran
1,346 tests and retained the three previously known unrelated failures:
FakeCorrelationWorkspace missing raw_model; Correlation pending-page assertion;
pandas read-only literal-frame assignment. See
`selection-script-final-regression-2026-11-02.json`. The subsequent filename
fallback passed six script tests and real supplied-Workbook paste, but has not
had another full regression and must now be superseded anyway.

After the semantic fix, update acceptance scenarios and validation docs, run
the focused tests, actual provided-Workbook workflow and the full scoped suite.
`.cache/run_selection_script_final_regression.py` runs all 108 non-deferred
modules in two shards via run_tests.py; verify new modules are included.
Do not present earlier path/filename tests as proof of semantic matching.

Work stopped on the pause request; background test/probe sessions completed.
No original SME, Workbook, production settings or GitHub tag was changed.

The app created a heartbeat automation named `继续 Metrology Workspace 未完成工作`,
ID `metrology-workspace`, attached to this same chat. Its sole future occurrence
is approximately 2026-11-03 02:42 Asia/Shanghai. Do not create another schedule.

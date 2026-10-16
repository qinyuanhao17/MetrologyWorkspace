# Home reminders and NOVA export validation

## Release boundary

The existing source was published first as `v3.2.0`, dereferencing to
`aa5281dd38bbe58688a51b27e86c70635aef7a77`. Its release checks passed 730 tests
and `main.py --self-test`. The changes described below remain local and are not
part of that tag. No new installer or binary release was produced.

## Home reminders

Current Session is replaced with an English Reminders panel. It supports
titles, notes, optional dates/times, flags, completion/restoration, confirmed
deletion, search, and Today/Scheduled/All/Flagged/Completed views. Today includes
overdue reminders, with overdue text distinguished from ordinary dates.
Long titles wrap; keyboard F2 and Delete work in the list. Light and dark
themes use the same layout and an orange accent.

Edits commit immediately to a separate SQLite file, not settings or any WKB.
Two application instances can update different reminders without replacing
each other's lists. Invalid edits and unsupported newer files are rejected;
there is no silent reset to an empty file. The UI and persistence logic are
separate modules. This version has no cloud account or closed-application
notification service.

Interaction references (not copied code):
[Planify](https://github.com/alainm23/planify),
[Reminders](https://github.com/remindersdevs/Reminders).

## Mapping deletion

The minus button is removed. Delete from a row's context menu removes exactly
that row, regardless of Use. The same action is available over Raw Data pickers
and Bias limit editors. The latter use an event filter before the spin box's
text menu handles the event. Other mappings, shared Reference comparisons and
source measurements are retained. Deleted mappings stay deleted after saving
and reopening; plus can explicitly add them again.

## Representative export measurement

The current NOVA input was copied before probing: 7,731 Raw Data rows, 33 Raw
Data columns, five active Groups, three selected parameters, both Preview and
Final. Its SHA256 was
`fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f`.
The original file was never saved by a probe.

The reported failure did not reproduce as an exception: both old workers
completed, but took a long time with generic progress and sparse cancellation
checks. Profiling identified repeated Alignment construction/style hashing and
per-observation pandas indexing. Changes reuse registered styles and column
values, check cancellation in table batches and between figures, report the
current stage/parameter, and detach completed Agg canvases. Resolution, panel
sizes, data, regression and chart contents are not reduced or changed.

One paired, unprofiled run on this machine, with the same frozen input and no
other heavy validation running, produced:

| Renderer | Published v3.2.0 | Local changes |
| --- | ---: | ---: |
| Native Excel | 70.362 s | 53.336 s |
| Matplotlib embedded in XLSX | 146.156 s | 128.428 s |

These are measured runs, not portable timing guarantees. The baseline ran from
a separate extraction of the tag, not a reset of the working checkout.
The diagnostic profile (196.805 s native, 291.423 s Matplotlib) was separate
and is not used as the performance comparison.

All 25 sheets and 2,555,474 cell coordinates/types/values/formulas match before
and after, and across the two renderers. All native chart/drawing XML and all
Matplotlib PNG bytes also match before and after. Source frame and persisted
UI/selection snapshots remain unchanged. The Matplotlib workbook still embeds
210 pictures, so exporting it is not instantaneous.

Actual File-menu cancellation on the same large input completed in 0.359 s
(native, during parameter preparation) and 0.094 s (Matplotlib, at rendering).
Progress text updated, both actions became available again, the prior complete
XLSX stayed byte-identical, and no partial export remained. During the final
XLSX serialization step, cancellation waits for that step to finish safely
before refusing publication; no thread is terminated forcibly.

## Executable checks

- `tests.test_reminders`: persistence, editing, completion/restoration, smart
  views, search, validation, future-version protection and two-instance edits.
- `tests.test_reminder_panel`: real home-screen add/date/validation, tool
  independence, restart, wrapping, completion/restoration and confirmed deletion.
- `tests.test_mapping_row_controls`: real context-menu deletion, embedded
  editors, shared Reference comparisons, re-addition and WKB reopen.
- `tests.test_excel_export` and `tests.test_excel_report_layout`: both renderers,
  formulas, native editability, sizes, original row identity, cancellation and
  injected partial disk-write failure preserving the previous complete report.

The test runner and probes isolate settings/recovery/Matplotlib/temporary paths;
an audit guard rejects writes to the user's config directory. Diagnostic logs
and repeatable scripts are kept locally under `.cache/v320-resume/`, not in the
published tag or measurement files.

Final full suite: `python run_tests.py`, **739 tests passed in 311.648 s**.
Light/dark UI renders show no outer clipping at 1180 × 820. The user's settings
SHA256 remained `2e0a712de33dd735ae531fba2b2d3051cb7575a45a0cde4c0e6c9c61cca235f6`.

# NOVA export performance, 2026-10-16

## Scope and preserved behavior

This is the first stage of the user's request to continue performance work,
prioritizing the two-minute Matplotlib report. It is not completion of the
entire control-responsiveness plan. All work stays local, after the published
v3.2.0 baseline. No tag, push or distributable package is produced here.

The measured input is an isolated copy of Desktop
`matching-analysis_nova_multi_param.wkb`: 7,731 Raw Data rows, 33 columns,
five Groups, three selected parameters, both Preview and Final. SHA256:
`fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f`.
Its output has 25 sheets, 2,555,474 cells and 210 Matplotlib pictures.
Original/Wafer/Group projections, exact source strings and source-row formulas,
fit results, full curves, captions, physical sizes and the existing DPI budget
are retained. No points, panels or Wafer captions are omitted.

## Diagnosis and implementation

The frozen pre-change export spent about 88 seconds in PNG saving, 23 seconds
in XLSX writing and 11 seconds repeatedly measuring equivalent Wafer layouts.
These are nested diagnostic timings, not disjoint totals. Fitting was not the
dominant cost. The original environment used openpyxl's pure-Python XML writer.

- A per-workbook layout cache reuses identical label layouts without sharing
  chart-category metadata. Measurement of repeated text is cached locally.
- `lxml>=5,<7` is now a runtime dependency; 6.1.3 was measured. The build spec
  explicitly includes its etree extension. The existing openpyxl format and
  authoring logic remain in place.
- Detached parameter/plot descriptions enter an export-owned Agg queue.
  At most four processes and eight queued descriptions are retained. Small
  reports stay serial to avoid process-startup overhead. No Qt widget, live
  canvas or mutable GUI model is sent to a render process. Each process receives
  the captured Matplotlib settings and releases each completed canvas.
- Large menu exports run their complete preparation and serialization outside
  the GUI's Python process. IPC conveys progress and cooperative cancellation.
  Small menu exports retain the existing thread path. Direct scripting exports
  remain synchronous and retain their interface.
- The owner creates one private temporary directory for the large export.
  The worker writes candidates and temporary XML only there. After successful
  preparation and cancellation checks, the owner replaces the target atomically.
  On failure it cleans only its owned directory, never another export's files.
- A Windows pipe-end race found by the real-file probe was corrected: receiving
  the terminal result ends IPC polling instead of polling the closed pipe again.

PNG compression experiments were not retained. Neither PNG byte contents nor
resolution need to change to obtain the improvement.

## Repeatable before/after measurement

The baseline is a separate copy of the entire dirty application source at the
start of this task, not Git HEAD. It runs with its original XML backend.
The working checkout is never reset. Baseline and candidate run sequentially,
with no competing heavy test/verification process. Settings, recovery,
Matplotlib cache and temporary paths are isolated for each process.

Host: 20 logical CPUs, approximately 32 GB installed RAM; conda Python 3.11,
openpyxl 3.1.5, Matplotlib 3.11.2. Offscreen Qt heartbeat is not native Windows
display frame-rate measurement.

| Complete actual ExportJob | Frozen source | Final owner-controlled candidate |
| --- | ---: | ---: |
| Native Excel | 56.390 s | 43.284 s |
| Matplotlib in XLSX | 154.588 s | 54.997 s |
| Native maximum GUI heartbeat gap | 2.858 s | 0.190 s |
| Matplotlib maximum GUI heartbeat gap | 0.521 s | 0.020 s |

The preceding independent run measured 56.552/154.510 seconds before; the
four-renderer candidate measured 43.697/55.309 seconds. The first two-renderer
experiment measured 41.879/72.352 seconds. These are observed samples on this
machine, not cross-hardware guarantees or a claim of universal sub-100ms latency.

The diagnostic scripts and outputs are under `.cache/export-speed-20261016/`:
`probe.ps1`, `probe.py`, `baseline-2.txt`, `final-1.txt`, `compare.py`, and
`cancel.py`. The copied baseline package is `baseline/metrology_app`.

Example PowerShell commands, executed one at a time from the repository root:

```powershell
& .cache/export-speed-20261016/probe.ps1 baseline-repeat .cache/export-speed-20261016/baseline both -NoLxml
& .cache/export-speed-20261016/probe.ps1 after-repeat . both
```

## Validation status

The first complete two-renderer candidate passed exact comparisons of every
cell value/formula, all 210 PNG bytes and decoded RGBA pixels, and all native
chart/drawing geometry. XML namespace prefix spelling is normalized when
comparing the supported XML writers. Source frames, selection and UI snapshots
are unchanged. The final owner-controlled candidate passed the same complete
comparison against the repeated frozen-source baseline, including identical
cell contents across both renderers.

31 focused export/layout tests passed, including a 3,000-row serial-versus-
parallel pixel comparison, a large actual menu export with GUI heartbeat and
successful completion status, and injected final-publication failure retaining
the previous report and removing its private candidate directory.

Actual menu cancellation on the same full NOVA copy finished in 0.250 seconds
during native preparation and 1.890 seconds during parallel rendering. During
final XLSX serialization it took 17.422 seconds: cancellation remains cooperative
and waits for the current library write before discarding the unpublished
candidate. All three checks preserved the previous report byte-for-byte,
removed the private output directory and retained source frames/UI state.
No process is killed to cancel a report.

First-pass complete `python run_tests.py`: **742 tests passed in 334.157 seconds**.
The runner uses isolated settings/recovery/Matplotlib/TEMP paths and rejects
writes to the user's config directory. The original WKB and settings SHA256
remain unchanged. No original measurement file was saved by a probe.

## Remaining stages

- Non-blocking WKB opening and complete saved-child restoration.
- Version-owned background preparation/analysis and incremental GUI application.
- Background formal WKB Save with existing locks, conflicts, revision checks,
  accepted baselines, newer edits and close/recovery decisions preserved.
- Native Windows long-session and frozen-binary validation. Source subprocess
  tests and offscreen heartbeat do not establish either of these results.

## Follow-up: redundant caption and style work

The next pass freezes the already optimized package separately under
`.cache/export-next-20261016/baseline`. This is not the earlier pure-Python XML
baseline. A child-process cProfile trace found 4,632 merge operations formatting
roughly 438,000 merged-interior cells; most repeated caption values/styles were
immediately discarded by merging. Named-style resolution was also repeated
over one million times. Profiled timings include profiler overhead and are not
used as complete-report speed measurements.

Parameter blocks now write only the first Wafer caption in each original
Group/Wafer/Lot/PAD span, register the identical borderless merge range, and
copy the same resolved style arrays per cell. No mutable cell style is shared.
The optimization is confined to newly authored, borderless parameter captions;
it is not a generic replacement for openpyxl's merge/border propagation.
Original Raw Data, category caches, formulas and rendering inputs are unchanged.

The public layout regression additionally covers hidden Lot/PAD captions,
separate Group identities, numeric-style isolation and ordinary unmerge/edit/
save/reopen of the exported file. After the first caption-only change, every
uncompressed report part except creation/modified timestamps was byte-identical
to the current frozen baseline (296 parts in each renderer).

Lossless archive-policy experiments were not adopted: native level-1 compression
saved about 0.8 seconds but grew the file from 20.9 to 25.0 MB; storing existing
PNG members without ZIP recompression saved about 4.3 seconds but grew the
Matplotlib report from 159.6 to 167.0 MB. The standard workbook writer and
compression policy remain unchanged.

The detached-renderer experiment then compared four and six workers with the
same optimized tables. On this 20-logical-CPU host, six reduced the full
Matplotlib report from 99.644 to 91.364 seconds. The adopted policy therefore
allows at most six renderers on hosts with at least 12 logical CPUs; smaller
hosts retain the previous cap of four and always leave one logical CPU free.
Pending descriptions remain bounded at twice the worker count. A mid-run
snapshot of the owned eight Python processes (GUI, export owner, six renderers)
totalled about 3.5 GiB working set; this is a sample, not a measured peak or a
cross-machine memory guarantee. No new dependency or compression change is used.

### Follow-up measurement method

Separate fresh processes run the same complete NOVA copy sequentially, with no
competing test suite or comparison job. Both before samples use the frozen
package and the same lxml backend. This round's unchanged baseline is slower
than the preceding 43/55-second samples; the cause of that cross-run difference
has not been isolated. The new optimization is evaluated only against this
round's repeated baseline, not by subtracting timings across sessions.

| ExportJob sample | Native Excel | Matplotlib in XLSX |
| --- | ---: | ---: |
| Current frozen package, run 1 | 91.310 s | 107.066 s |
| Current frozen package, run 2 | 92.502 s | 107.201 s |
| Caption-only change, four renderers | 74.770 s | 100.339 s |
| Caption/style change, four renderers | 70.236 s | 99.644 s |
| Six-renderer isolated experiment | not measured | 91.364 s |
| Final adopted package, repeat | 70.568 s | 90.717 s |

The final repeat's maximum offscreen GUI heartbeat gaps were 0.386 s Native
and 0.193 s Matplotlib. All 296 uncompressed ZIP members other than the
creation/modified timestamp part are byte-identical for each mode against the
second frozen baseline. This includes worksheet cells, formulas, merge ranges,
style definitions, row heights, drawing geometry, native chart definitions and
all PNG contents; identical PNG contents retain identical pixels and resolution.
Source frames, participation and UI-state snapshots are unchanged in every run.

Actual File-menu cancellation on the final code retained the previous valid
report and removed all owned partial outputs: 0.250 s during Native preparation,
2.468 s during Matplotlib rendering, and 40.219 s during final XLSX serialization.
The last result remains a limitation of cooperative cancellation around the
unmodified library writer, not an instant-cancellation claim. No process is
forcibly killed. Final publication failure is also covered by the existing
public-menu regression.

Scripts: `.cache/export-next-20261016/phase_probe.py`, `profile.ps1`,
`run.ps1`, `acceptance.py`, `strict_compare.py`, `zip_probe.py`.
Logs and report candidates are under `.cache/export-speed-20261016/next-*`.
The local performance tracer first failed its 80-second Native budget on the
unchanged baseline. These machine-local budgets are not portable unit-test
thresholds and are not added to the full suite.

### Follow-up validation status

The focused public export/layout suite passed all 32 checks. The final complete
`python run_tests.py` ran **743 tests in 612.228 seconds: 738 passed, five timing
assertions failed**. This is not an all-green full-suite result.

| Timing check | Full modified suite | Fresh frozen-package repeat | Fresh modified-package repeat |
| --- | --- | --- | --- |
| Correlation check/uncheck, <0.150 s | 0.209 s, fail | pass | pass |
| Five paste/keyboard Undo refreshes, <0.650 s | 0.673 s, fail | 0.686 s, fail | 0.687 s, fail |
| Saved Correlation restoration, <2.000 s | 2.112 s, fail | pass | pass |
| Accepted-state dirty checks, <0.100 s | 0.107 s, fail | pass | pass |
| Wafer window opening, <0.400 s | 0.547 s, fail | 0.439 s, fail | 0.493 s, fail |

Each five-case repeat uses a fresh isolated process and identical unchanged
test selectors. `baseline_check.py` prints the frozen package path before
loading the tests. Two limits therefore also fail before this optimization;
three failures are not reproduced in either fresh five-case repeat. This does
not establish the cause of all full-suite timing variation or erase the five
full-suite failures. No tests are skipped, and no budgets are relaxed. None of
the five failing workflows call the changed parameter-table or export-pool
code; their latency remains pending work, not a result claimed by this pass.

Evidence: `.cache/v320-resume/next-export-full.txt`,
`next-export-focused.txt`, `next-baseline-failed-checks.txt`,
`next-current-failed-checks.txt`. The isolated source `main.py --self-test`
also exits successfully. This is not a packaged-binary or native long-session
verification. User settings and original NOVA file hashes remain unchanged.

## Follow-up after v4-dev1: 30-second investigation

The published `v4-dev1` source tag remains unchanged. This follow-up is local;
it does not push, retag, build or publish a release. It targets the same full
NOVA fixture and output, not a reduced report or a raw-cell-only benchmark.

### GitHub research and rejected experiments

- [XlsxWriter's official writer benchmark](https://github.com/jmcnamara/XlsxWriter/blob/main/dev/performance/bench_excel_writers.py)
  compares simple cell-writing workloads. Its
  [constant-memory documentation](https://xlsxwriter.readthedocs.io/working_with_memory.html)
  says performance is approximately normal-mode performance and limits
  cross-row merging. It is not a drop-in speed switch for these reports.
- [PyExcelerate's scalar serializer](https://github.com/kz26/PyExcelerate/blob/dev/pyexcelerate/Worksheet.py)
  uses 15-significant-digit numeric formatting. Replacing the current writer
  without precision and complete chart/layout validation was not adopted.
- [Matplotlib issue 26150](https://github.com/matplotlib/matplotlib/issues/26150)
  concerns repeated layout/bounding-box work and a fix shipped in 3.10. The
  measured runtime is already 3.11.2; report panels already use explicit axes
  margins. This is not evidence of another untested automatic speedup.
- Full-report PNG compression level 1 measured 47.772 s and 214,800,517 bytes;
  run-length PNG encoding measured 48.447 s and 214,381,949 bytes. Both are
  slower and larger than the frozen 46.683/47.023 s, 159,622,965-byte report.
  Neither changes production PNG encoding.
- Eight render processes measured 43.272 s versus 43.366 s for the same
  batched-parser prototype with six. This negligible single-run difference
  does not justify extra processes/memory; the existing six-process cap stays.

### Retained implementation

Large reports now batch validated scalar cells into one bounded XML row,
instead of using multiple Python XML context managers per cell. Styles are
resolved per worksheet; numeric serialization still uses openpyxl's existing
`safe_string`, including its precision and non-finite handling. XML escaping
preserves literal CR, Unicode and formula-as-text source strings. Illegal XML
characters fail safely rather than publishing unreadable output.

`xlsx_serialization.save_workbook` contains this implementation behind the
existing atomic-save interface. Openpyxl still writes worksheet metadata,
merges, styles, native charts, drawings, relationships and the XLSX package.
Dates, rich text, array/data-table formulas, hyperlinks and comments use its
normal row writer. Small reports, write-only workbooks and non-lxml environments
retain normal `Workbook.save`. No process-global writer monkeypatch is used.
The adapter targets the installed openpyxl 3.1 writer seams; dependency upgrades
must retain the export regressions. Its derived orchestration retains the MIT
notice in the source file.

Large XLSX reports store already-compressed PNGs directly in ZIP, keeping the
exact PNG bytes instead of compressing them a second time. This increases the
full Matplotlib report from 159,622,965 to 167,000,883 bytes (about 4.6%), without
changing pixels, DPI, metadata or drawing dimensions. XML compression is unchanged.

Serialization checks cancellation every 256 rows and at worksheet boundaries;
the old report is replaced only after complete success and the final cancellation
check. Owned XML files and partial XLSX files are closed and cleaned on failure.

### Fresh sequential measurements

The frozen baseline is the clean `11acb44` package, copied before source edits.
This session runs substantially faster even on the unchanged package than the
earlier follow-up. The cause is not isolated, so **do not subtract the older
70/91-second results from this session**. Only the following same-session,
sequential full-report measurements support this improvement:

| Complete ExportJob | Frozen v4-dev1 | Final local implementation |
| --- | ---: | ---: |
| Native Excel, sample 1 | 31.612 s | 25.938 s |
| Native Excel, sample 2 | 31.729 s | 26.095 s |
| Matplotlib in XLSX, sample 1 | 46.683 s | 38.550 s |
| Matplotlib in XLSX, sample 2 | 47.023 s | 38.282 s |

The same input SHA256, Python environment, isolated settings/cache/temp paths
and full output are used. No heavy comparison or test process runs alongside
these measurements. Snapshot capture, measured separately, is 0.146/0.149 s;
opening the WKB and the save dialog are not counted as export writing time.
Maximum final sample-2 offscreen GUI timer gaps are 0.197 s Native and 0.017 s
Matplotlib; these are not native Windows frame-rate measurements.

Both modes improve by more than 10% against their own frozen sample. Native
Excel meets the machine-local 30-second goal; **Matplotlib does not**. Its full
210-picture report still takes about 38 seconds. The 30-second combined goal
check is intentionally still red, not relaxed or removed. Rendering and
preparing all panels remain substantial costs; no claim of impossibility or
universal timing guarantee is made.

### Equivalence and validation

The final sample-2 comparison passes all **296 uncompressed XLSX members per
mode, byte-for-byte**, excluding only creation/modified timestamps. This covers
all 2,555,474 cells, literal strings, formulas, styles, row heights, merge ranges,
chart definitions, chart-category caches, drawing geometry and PNG bytes. ZIP
compression choice does not change the uncompressed members. All probes also
assert unchanged source frames, participation/UI state and the input WKB hash.

An independent differential fixture also matches the normal library writer for
Unicode/CR/XML special characters, numeric precision, dates/times/durations,
rich text, array/data-table formulas, links, comments, styled blanks, bordered
merges and row attributes. New public export regressions cover large-sheet
cancellation, literal/typed values and invalid-XML failure preserving an older
valid report. The cancellation tracer fails on the frozen behavior before the
implementation and passes afterward.

The final focused export/layout run passes **35 tests in 39.261 seconds**.
The complete `python run_tests.py` runs **746 tests in 615.759 seconds: 744 pass,
two UI timing assertions fail**. This is not an all-green full-suite result:

| UI timing check | Full modified suite | Fresh frozen v4-dev1 repeat | Fresh modified repeat |
| --- | ---: | --- | --- |
| Correlation check/uncheck, <0.150 s | 0.185 s, fail | pass | pass |
| Wafer window opening, <0.400 s | 0.512 s, fail | 0.477 s, fail | 0.490 s, fail |

The frozen checker prints the copied package path before loading the unchanged
test selectors. Wafer-opening latency therefore also exceeds the limit before
this optimization. The Correlation failure does not reproduce in either fresh
two-case process; this does not erase its full-suite failure or establish the
cause of context-dependent timing variation. Neither workflow calls the changed
export serializer. No budgets are relaxed and no tests are skipped. Broader
interactive/background-work optimization remains pending.

Real File-menu cancellation on the same full fixture preserves the previous
valid report and leaves no owned partial output: Native preparation 0.234 s,
Matplotlib rendering 2.469 s, Native worksheet writing 1.454 s, Matplotlib
worksheet writing 1.672 s. Both source frames and UI-state snapshots remain
unchanged. This is cooperative cancellation, not a guarantee of instant
interruption inside every library/compression operation.

Logs: `.cache/v320-resume/target30-focused-final.txt`, `target30-full.txt`,
`target30-baseline-cases.txt`, `target30-current-cases.txt`, and
`.cache/export-speed-20261016/target30-cancel-final.txt`. Earlier suite failures
above remain historical results, not silently reclassified.

The isolated source `main.py --self-test` exits 0
(`.cache/v320-resume/target30-smoke.txt`). `git diff --check` passes.
The original Desktop WKB and personal `config/settings.yaml` retain their
pre-pass SHA256 values. This is source/offscreen validation, not a new packaged
binary or a native Windows long-session validation.

Evidence is in `.cache/export-target30-20261016/` (`run.ps1`, `phase_probe.py`,
`goal_check.py`, `parts_compare.py`, `review_cells.py`, `verify.ps1`) and
`.cache/export-speed-20261016/target30-*` (logs and complete reports).
These diagnostics are ignored local artifacts; no measurement data is published.

## Further local pass: GC ownership and bounded render scheduling

The next frozen package is the previous **local** implementation, not a new
release or another checkout of `v4-dev1`. It includes the scalar XLSX writer
above. The original WKB, literal source strings, calculation rules and complete
report scope remain unchanged. No dependency, tag or remote branch changes.

### Diagnosis and retained changes

A renderer-process profile of the complete 210-image report puts most rendering
time in Agg text drawing, not figure cleanup. RGB PNG encoding with an opacity
scan measured 38.593 s against the initial 38.414 s baseline; it was not retained.
A process-local font-metrics cache gave little benefit (69.119 s versus a nearby
70.912 s unchanged run during a machine-wide slowdown), so it was not retained
either. The unchanged serializer also doubled in time during that interval;
these slow samples are not mixed into the final stable comparisons below.
ZIP compression level 3 saved approximately one writing second but increased
Native output from 20,876,692 to 23,602,252 bytes. This tradeoff was not retained.
The production PNG encoding, ZIP compression level and image bytes stay unchanged.

The export owner instead spent about 2.3 seconds in **17 generation-2 cyclic-GC
scans** per report, collecting only 6 objects in the Native sample and 45 in the
Matplotlib sample. The millions of still-live worksheet cells were repeatedly
scanned without being reclaimable. Only the existing one-shot export subprocess
now pauses cyclic GC, restoring its incoming policy in `finally` after closing
the IPC endpoint. The GUI, direct/small exports and separate Agg workers retain
their existing collection policies. Reference-counted cleanup, cancellation and
atomic publication are unchanged; this is not a global application GC switch.

The bounded pending render queue also grows from twice to four times the worker
count (24 jobs on this machine), keeping workers fed while an early wide Wafer
panel takes longer than its neighbours. The worker cap remains six, not twelve;
figures still render once with the same resolution and numerical inputs.
Completed images are attached in the original order and cancellation still
signals/cancels owned work before joining the workers. A GC-only prototype
measured 36.967 s for Matplotlib, versus 35.805 s with the larger bounded queue.

### Sequential full-report measurements

Both fresh baseline/final pairs run the same public `ExportJob`, with isolated
settings, recovery, font-cache and temporary paths. No other heavy benchmark or
test runs alongside them. These are complete 25-sheet, 2,555,474-cell reports,
including all 210 PNGs in Matplotlib mode, not reduced selections or raw-writing
microbenchmarks. Snapshot preparation and WKB opening remain outside these times.

| Complete ExportJob | Frozen preceding local version | Final local version |
| --- | ---: | ---: |
| Native Excel, sample 1 | 25.916 s | 23.361 s |
| Native Excel, sample 2 | 26.069 s | 23.289 s |
| Matplotlib in XLSX, sample 1 | 38.836 s | 35.504 s |
| Matplotlib in XLSX, sample 2 | 38.685 s | 35.457 s |

The mean improvement is approximately 10.3% Native and 8.5% Matplotlib for this
fixture and machine. **The Matplotlib 30-second goal is still red**: the final
sample is 35.457 s, not rounded down to 30 and not a universal timing guarantee.
The explicit goal check keeps the original 30-second limit for both modes.

Peak export-owner working set changes from 1,165,922,304 to 1,180,569,600 bytes
Native, and 1,280,122,880 to 1,294,540,800 bytes Matplotlib in sample 1: about
14 MiB more in each owner. These are Windows process peak counters, not a
simultaneous total for the GUI and six render workers. The bounded worker/raster
cap is unchanged. Final sample-2 maximum offscreen GUI timer gaps are 0.188 s
Native and 0.019 s Matplotlib; native Windows long-session validation remains
separate and pending.

### Equivalence and repeatability

Both final samples pass the all-part comparison: **296 uncompressed XLSX parts
per mode are byte-identical**, excluding only the core creation/modified
metadata part. This includes every PNG, cell/formula, row height, merged range,
style, chart definition and drawing anchor. CRC checks pass. There is no new
file-size tradeoff beyond timestamp/container variation. Probes assert unchanged
source frames, participation/UI state and WKB hash.

The existing large-export public regression now also compares the parallel
Trend and Bias PNGs to the ordinary serial render, in addition to Match; it
checks the exact number of panels rather than truncating an unequal comparison.
The export/layout subset passes 35 tests in 38.200 s. The final guarded
`python run_tests.py` passes **all 746 tests in 332.657 s**, with no timing
threshold relaxed or test skipped. This is a new run, not a relabeling of the
earlier 744/746 result. The strengthened Match/Trend/Bias pixel check also passes
in this complete run.

Actual-menu cancellation on the real fixture passes during Native preparation
(0.281 s), Matplotlib rendering (1.844 s), Native worksheet writing (1.140 s)
and Matplotlib worksheet writing (1.203 s). Each old valid report remains
byte-identical, no owned partial report remains, both actions re-enable and
the source frames/UI state stay unchanged. The full suite also retains the
existing publish-failure and invalid-text failure protections.

The isolated source `main.py --self-test` exits 0. `git diff --check` passes.
The personal settings SHA256 remains
`2E0A712DE33DD735AE531FBA2B2D3051CB7575A45A0CDE4C0E6C9C61CCA235F6`;
the original and copied WKB both remain
`FBE22DA2A55571B136A1F3E17DB1F69284C391E9A2FAC86019C5ABB919336B4F`.
No native Windows long-session or frozen-binary claim is made. Asynchronous
WKB open/complete restoration, version-owned background analysis and formal
background WKB saving remain outside this export-only pass.

Owned diagnostic scripts and logs are under `.cache/export-render-next-20261016`
and `.cache/export-speed-20261016/render-next-*`. Reproduction commands:

```powershell
& .cache/export-render-next-20261016/run.ps1 reproduce-before .cache/export-render-next-20261016/baseline both
& .cache/export-render-next-20261016/run.ps1 reproduce-after . both
& 'C:/Users/Yuanhao Qin/.conda/envs/metrology-workspace/python.exe' .cache/export-next-20261016/strict_compare.py reproduce-before reproduce-after
& .cache/export-render-next-20261016/cancel.ps1 reproduce-cancel
& .cache/export-render-next-20261016/verify.ps1 focused
& .cache/export-render-next-20261016/verify.ps1 full
```

The full action invokes the repository's `python run_tests.py` through a
config-write guard, not an alternative reduced suite. `check_budget.py` reports
the actual final sample against the unchanged 30-second goal and intentionally
returns failure while Matplotlib exceeds it. TDD/Matplotlib guidance keeps the
public export guards and exact rendering comparison; the minimal-change policy
rejects new renderer internals, additional processes and new dependencies.

## Method references

The Matplotlib skill influenced explicit Agg ownership, bounded rendering,
canvas cleanup and pixel-equivalence checks. Its procedural source is:
Timothy Kassis, Vinayak Agarwal, Yuhuan He, Darshil Patel and Aubrey M. Brueckner,
*Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*,
2026, [doi:10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065).
Performance numbers come from the local probes above, not this paper.

[openpyxl's optimized modes](https://openpyxl.readthedocs.io/en/stable/optimized.html)
document its lxml support. [Matplotlib savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html)
documents the existing PNG/DPI interface; this change retains that interface
and validates the same output rather than substituting a lower-quality renderer.

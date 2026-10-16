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

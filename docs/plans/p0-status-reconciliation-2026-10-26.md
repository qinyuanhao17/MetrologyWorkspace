# P0 first-issue status reconciliation (2026-10-26)

## Local progress versus the supplied handoff

The supplied `017c10d` is an ancestor of the actual entry HEAD,
`991431daf1a3a26935ff7c3dbda122113ad944a9` (v4.3.1). The older final-audit
Markdown/JSON correctly describe their historical snapshot; they are not the
latest progress record. Subsequent checkpoints already include:

- `b3fe61b`: the requested new-window initialization diagnosis, changing only
  benchmark fixtures and evidence, not production code.
- `4f353b7`: v4.3.0, including separately documented Workbook input-scan work.
- `991431d`: v4.3.1 grouped export geometry. It still uses numeric XY sources
  for all Group/Wafer trends, so the newly requested native Die Seq source
  selection is a separate, not-yet-completed follow-up at entry.

No P0 optimization is repeated here and no P1/P2 restructuring is started.
Existing user changes to AGENTS.md, .vscode/settings.json and docs/todos remain
outside these checkpoints.

## First issue: reproducible conditions and evidence

The detailed diagnosis is
[p0-window-initialization-diagnosis-2026-10-25.md](p0-window-initialization-diagnosis-2026-10-25.md),
with tracked evidence in
[p0-window-initialization-2026-10-25.json](../validation/p0-window-initialization-2026-10-25.json).
Current benchmark code retains the QWidget host introduced by `b3fe61b`.

The historical reproducer used Qt 6.11 Windows UIA, with accessibility listening,
and three bare top-level SheetViews (one source payload plus an empty target and
a reverse projected view), before constructing another real analysis window.
This is not three complete copies of the source data. Qt's
`windowForAccessible()` fallback enumerates the accessible roots' direct children;
a bare table root exposes its virtual cells as those children. Production tables
are embedded below ordinary window/container roots.

The Qt 6.11.0 fixed-version source was rechecked during this reconciliation:
[window lookup](https://github.com/qt/qtbase/blob/v6.11.0/src/plugins/platforms/windows/uiautomation/qwindowsuiautils.cpp#L19-L45)
and [accessible table interfaces](https://github.com/qt/qtbase/blob/v6.11.0/src/widgets/accessible/itemviews.cpp).
This corroborates the recorded profiling and controlled comparison; it is not a
new capture of every native C++ stack frame.

Historical three-process construction P50, not new measurements:

| Dataset | Bare top-level table | Same table in QWidget host |
| --- | ---: | ---: |
| 10k x 30 | 2089.92 ms | 44.70 ms |
| 100k x 33 | 38180.98 ms | 45.57 ms |

The 100k profile recorded 44.735 s construction and 44.297 s CPU, but only
0.260 ms GC. A resident-memory control adding 1536 MiB still constructed in
32.01-49.54 ms with the container. These isolate the benchmark-root effect;
they do not establish behavior under paging or extremely low available memory.

Actual Shell.open_component checks with three sorted 100k x 33 workbooks had
85.16-89.70 ms entry calls and 147.90-167.09 ms including first Qt painting.
Three saved NOVA workbooks instead had 324.81-361.27 ms entry calls and
501.13-576.20 ms including painting. Setup/loading is outside those operations,
and these figures are neither DWM FPS nor a claim of millisecond file opening.

## Production change and minimum repair

No new production change is warranted for this reported tens-of-seconds
initialization anomaly. The minimum repair already exists in `b3fe61b`:
`sheet_probe_host()` embeds the benchmark's table in QWidget/QVBoxLayout, while
retaining data, projections, accessibility, notifications, exposure, repaint and
Undo assertions. Do not disable GC/UIA, alter model ownership, force global
winId creation, or change Recovery/WKB/async publication to address this fixture.

The saved-NOVA recent-menu/read-and-validate cost is a separately documented
behavior contract, not this root enumeration. It is not changed here.

## Verification boundary and checkpoint

The tracked first-issue record reports 1086/1086 historical full tests and two
native workflow runs containing 52 actions. The older audit's 1083/1083 full,
68/68 native, 240 Dirty decisions and 120-map comparison are likewise historical
results, not newly rerun acceptance numbers.

This checkout has neither the original `.cache/p0-audit/init-special/` raw logs
nor `.cache/p0-audit/input/nova.wkb`. Their hashes and key results remain in the
tracked JSON. This machine uses Python 3.10.20 / Qt 6.11.0; the report used Python
3.11.16. Therefore no same-environment performance improvement or new native
reproduction is claimed. A fresh replay requires the original read-only input
and the documented isolated `python -m benchmarks.benchmark_window_initialization`
entry point. No user dataset is synthesized and presented as that original input.

Real settings SHA-256 at entry:
`cb419604ac0620206baa212ac3c527dee022d8d98c1ff1e23dd7db580683014f`.
No user WKB or Excel file is opened or overwritten for this status check.

The implementation checkpoint for issue 1 remains `b3fe61b`. This reconciliation
is a separate documentation-only checkpoint. Work on performance issues 2-5
stops here; actual operation frequency has not been supplied and is not invented.
The explicitly requested Excel follow-up is isolated from those performance
hotspots and will have its own tests/checkpoint. No push or release is authorized
or performed in this round.

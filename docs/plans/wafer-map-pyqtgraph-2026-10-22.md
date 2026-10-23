# Static Wafer Map / Radius rendering and responsive child close

## Scope

Wafer Map screen presentation now uses pyqtgraph ImageItems and batched Qt
annotations. Remove plot zoom, pan, hover, point selection and rectangle
highlighting. Keep map-box selection outside the graph, wafer/parameter filters,
pagination, point values/precision, measured points/outlines, contours, fill edge,
shared scale, palettes/range/opacity, identity captions and all export formats.
Radius screen presentation also uses pyqtgraph scatter/curve items and the same
static scene. Window resizing/maximising, page scrolling and whole-grid
magnification remain available; plot-internal coordinate navigation and
selection do not. Other analysis renderers are unchanged.

## Whole-page zoom clarification

The user clarified that Ctrl+wheel must magnify the complete array, not zoom the
coordinates inside one map. Both Map and Radius now share that page-only wheel
handler. View exposes 1–300% presets and Fit width; Fit width no longer clamps to
65%, which prevented wide arrays fitting into the window. Pointer anchoring is
retained where the scrollbar bounds permit it. Ordinary wheel scrolling and
Shift+wheel horizontal scrolling remain separate. Deferred centering cannot
override an explicit wheel zoom. Existing document zoom/scroll fields are reused.

The red test sent real Qt wheel events to the page viewport: both scales stayed
at 1.0. After fixing event handling, the remaining Radius Fit-width test still
failed with a 1,012-pixel scrollbar range; lowering the display-only limit fixed
that independently. No numerical coordinates, interpolation surfaces, label
precision or export DPI change when zooming. Scientific plot mouse input remains
disabled. Obsolete tests expecting Ctrl+wheel to do nothing were updated; their
source, selection and export invariants remain.

67 related regressions passed, followed by four zoom-specific checks (two overlap
that run) covering wide arrays, pointer anchoring, limits and normal/Shift scroll.
Windows-platform QA additionally exercises a 1x24 array without creating a
Matplotlib export figure. Full-suite testing remains deferred.

## Data and visual contract

`prepare_array` / `prepare_surfaces` remain unchanged. No resolution reduction,
new interpolation, sample dropping, altered measured strings or row remapping.
The screen consumes the existing prepared grid and the same display colormap.
ImageItem rows are flipped for Qt's Y-down display; numerical grids are not.

The subplot geometry, circular clipping, limits, ticks, titles and colorbar follow
the existing renderer. Point text uses the existing half-up label formatter and
glyphs, including deterministic overlap suppression. Contours use the same
ContourPy algorithm, masks and levels, without path simplification.

Matplotlib is materialised lazily for Copy PNG, PNG/SVG/PDF and Excel FM output.
It continues to use the original `draw_array` renderer; screen refreshes must not
create these export artists. Existing cached export point overlays can update in
place when only point precision/visibility changes.

Radius keeps the previous signed-radius calculation, missing-value mask,
limits, colours, point size/alpha, captions and original Matplotlib export.
Screen geometry, scatter data and Y limits are compared to the export mirror;
visual QA includes constant-valued parameters and multiple wafers.

## Floating editors

The native title-bar icon at the upper left is the pin control; the old title
instruction and extra client toolbar row are removed. Alt+P provides keyboard
access. Unpinned editors are raised only over their logical parent; pinned
editors are raised over other active windows of this application. They are
unowned native windows, not system-topmost windows. A coalesced local raise
rechecks application activation so it cannot raise over a foreign application,
modal prompt or another editor. Real Windows activation/z-order QA verifies
the native icon, both scopes, foreign-app activation and that clicking the
editor does not raise its Workbook over sibling analysis windows.

## Diagnosis and measurements

The original red-capable test was
`python run_tests.py tests.test_wafer_static -v`: 10 prepared maps blocked the GUI
for a median 1.6446 seconds (250 ms budget). Two maps still reproduced the issue
at 0.3175 seconds. Profiling the ten-map callback attributed 0.887 seconds to
Matplotlib artist construction and 1.142 seconds to canvas/background rendering;
interpolation had already finished before timing began.

Controlled same-process comparison against the v4.1.1 source (c50183a), using
two wafers, five parameters, 69 measured points per map and identical prepared
surfaces: five repeated presentations had medians 1.7028 seconds before and
0.1739 seconds after (about 9.8x faster). The window requested 1200x800; its
actual minimum-size-constrained viewport can be wider, and all ten maps were
present. These are presentation timings, not application cold-start timings or
an interpolation speedup. First-use costs and machine load vary.

Re-run the current benchmark with
`python run_tests.py benchmarks.benchmark_wafer_rendering -v`.
The disposable original-version comparison/profile harness and synthetic visual
QA PNGs are under the ignored `.cache/wafer-pg/` directory.

## Closing analysis windows

The common slow path was synchronous aggregate recovery during Discard, not
the plot scene alone. The original 3,000-row/36-column synthetic Workbook
reproduced a 2.6594-second first close. Profiling identified repeated SQLite
table commits and repeated copying of large grouping state.

The private unpublished SQLite candidate now has one enclosing transaction;
its interim journal is in memory, with intermediate sync disabled. The complete
candidate still passes integrity checking, closes, and **must be fsynced** before
atomic replacement. Published files, backups, locks and revision checks retain
their safety guarantees. Subsequent connections retain SQLite's default
durability. Tests inject final-fsync and backup failures and verify the previous
formal file remains byte-identical. Equal recovery tables share stored payloads
but unpack into independently editable frames; differing literal strings are
never merged. GUI-only read views are frozen once before storage rather than
deep-copied repeatedly.

Five repetitions against the same v4.1.1 storage/close implementation and fixed
fixture gave first-dirty-close medians **3.7620 -> 0.2153 seconds**. Current
samples ranged 0.1688–0.3063 seconds: disk-flush latency still varies; two
samples exceeded the 250 ms development target, so this is not a guarantee of
every close below that threshold. The later unchanged-payload Correlation and
Dynamic closes were already fast, around 70 and 30 ms respectively.

A second red test held a numerical call in progress: child close previously
waited 2.0018 seconds. Closing now requests cancellation, disconnects and retires
the data-only worker without waiting, and invalidates any already-queued result.
The worker is retained until natural completion; only application shutdown joins
remaining jobs. Regression verifies no late render, no destroyed-running-thread
hazard and cleanup after completion. Numerical algorithms are not interrupted
by unsafe thread termination.

## Verification

Regression tests compare screen coordinate rectangles, limits, raw RGBA pixels,
iso-line paths and unchanged Matplotlib PNG output. They also exercise disabled
chart navigation, source-string preservation, replacement without leaked scene
items, point precision, linked workspaces and existing exports. Only obsolete
zoom/hover expectations were changed to the requested non-interactive behavior;
MapSelector selection tests remain.

Verification: 127 related rendering/export/case-switching/storage workflow
tests and 53 pin/recovery/document-store tests passed. Five additional focused
visual/lifecycle checks passed after the final small changes; these include
repeated tests, not five new unique suite cases. Native Windows pin/z-order QA
also passed. `git diff --check` is clean. Diagnostics and images are confined to
the ignored `.cache/wafer-pg/` folder.

The earlier full run was interrupted at the user's explicit request; it has no
complete result and was not resumed. Full-suite testing, packaging and publishing
remain deferred. Real user settings were not restored over concurrent changes.

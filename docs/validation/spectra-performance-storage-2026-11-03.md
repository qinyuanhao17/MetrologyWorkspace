# Spectra storage and responsiveness validation — 2026-11-03

## Scope and accepted behavior

The user requested two save modes before the full regression run, plus fixes for
slow channel re-showing, Workbook opening/saving and Spectra window geometry
changes. AutoWeighting remains explicitly deferred. Source measurement files,
the supplied Workbook and production settings must remain unchanged by probes.

Options → **Spec Save Type** contains two exclusive radio actions:

- **Embed Spectra Data** preserves the existing self-contained format and is the
  default for existing files without a saved mode.
- **Spectra Paths Only** stores original SME paths, checks and UI state without
  numeric sample payloads. A managed Spectra child saves this choice into its
  Match Workbook. Standalone `.spec` files support the same choice.

Saving after switching from embedded data to paths writes a replacement SQLite
container: embedded sample strings are absent from the new file, rather than
being left in unused database pages. The normal previous-file `.bak` policy is
retained; that backup may still contain the preceding embedded version.

Path mode requires the original SME files at their saved locations. Missing or
changed references are reported and retained with their check/flag state on a
subsequent path save. A file with no available references clears the prior
viewer's data instead of displaying unrelated old spectra. Embedding is
disabled while references are unavailable; restoring/reloading those originals
enables it again. A normal failed replacement import still keeps current data.

## Causes and changes

- Hiding every member of a multicolor batch previously discarded its source
  arrays. Re-showing rebuilt those buffers. Batches now retain their data and
  screen cache while hidden, and ordinary channel toggles preserve curve items.
- A re-shown dense native curve could become visible before its preparation
  timer. Painting millions of antialiased samples then blocked Qt's event loop.
  Dense native painting is suppressed before exposure while the screen cache
  prepares the image. Full source data remains authoritative for bounds/export.
- Geometry changes no longer disable the plot viewport's updates. Resize work
  is coalesced until geometry settles; the preceding cached image remains
  available. Detached joined buffers are immutable and reused for worker jobs,
  avoiding another full-array copy at every size change. Dimension-dependent
  rasterization still runs in workers; a size change cannot reuse an image at
  its original geometry indefinitely.
- Refreshing Open Recent used to read and validate an entire large Workbook
  merely to identify its type. Routing now reads only format/type metadata;
  actual opening still performs full validation.
- Large detached document I/O and Spectra decoding run outside the GUI thread
  under a modal progress dialog. Widgets/models publish results on the GUI
  thread. The existing revision checks, atomic replacement, backup and fsync
  semantics remain intact. Embedded saves are responsive, but their total I/O
  time is not claimed to be lower.

No interpolation, numerical samples, color order or export semantics were
changed for these optimizations. Screen simplification tolerance remains 0.25
physical pixels for eligible dense multicolor batches.

## Repeatable real-file measurements

Fixture: `C:/Users/Yuanhao Qin/OneDrive/Desktop/JC1913/matching-analysis.mwkb`,
1,890 spectra, 409,559,040 bytes. Before and after used the same cProfile/Qt
harness, scratch settings and operation sequence. These are observations on
this machine, not a general latency guarantee. Settled time includes event
processing and background rendering, with a final 50 ms observation interval.

| Operation | Before | After |
| --- | ---: | ---: |
| Workbook load callback, including Open Recent refresh | 4,420.6 ms | 2,483.2 ms |
| Spectra first opening, settled | 9,192.6 ms | 8,155.9 ms |
| Channel show, first toggle, settled | 51,906.1 ms | 555.9 ms |
| Channel show, second toggle, settled | 49,680.4 ms | 611.8 ms |
| Channel show batch `set_groups` calls | 252 | 0 |
| Resize, settled | 3,616.6 ms | 2,659.3 ms |
| Main splitter, settled | 3,234.0 ms | 2,355.1 ms |
| Embedded `.spec` save total | 1,122.5 ms | 1,257.3 ms |
| Embedded Workbook save total | 1,322.7 ms | 1,226.7 ms |

The after resize callback was 31.8 ms and the splitter callback 8.9 ms. Background
geometry jobs account for the remaining settled time. Curve item identities
were retained. Initial opening and background size-dependent rendering still
have measurable cost; this report does not claim instantaneous completion.

A second verification used native Windows Qt windows with the same 1,890
spectra, requiring 150 ms of stable completion after processing geometry events.
Maximize completed its background renders in 7.36 s and restore in 3.42 s; the
20 ms GUI heartbeat fired 337 and 145 times respectively. All viewports kept
updates enabled, every curve retained its identity and no cache jobs remained
pending. Settled captures were inspected. This confirms responsive event
processing during rendering, not instant final-image generation. The earlier
offscreen maximize observation returned before delayed geometry work, so its
raw timing is retained in JSON but excluded from speed comparisons. A settled
capture cannot prove the absence of every transient OS/compositor artifact.

A separate scratch copy was converted from embedded data to paths, then saved
again and reopened:

| Measurement | Result |
| --- | ---: |
| Original embedded container | 409,559,040 bytes |
| Paths-only container | 2,867,200 bytes |
| Reduction | 99.30% |
| Conversion save including the original large-file protection/backup | 2,582.7 ms |
| Subsequent paths-only save | 114.5 ms |
| Paths-only container read | 36.6 ms |
| Original SME files with exactly equal numeric and wavelength arrays | 1,890 / 1,890 |
| Missing/corrupt references in this actual fixture | 0 |

The 36.6 ms measurement is container reading, not opening and plotting all
referenced SME files. The actual 1,890-file numerical comparison took 5.62 s.
SHA-256 confirmed that the supplied Workbook stayed unchanged. All conversion
and save measurements used `.cache` copies, not the user's formal document.

## Executable verification and remaining failures

The focused Spectra/Workbook/storage run passed **105 tests in 32.888 s**.
Follow-up tests covered recovery of missing path references and their check/flag
state, enabled viewports during resize, curve-buffer identity retention, pixel
fidelity on a populated plot, and current Checked/Unchecked row-mode semantics.

Relevant acceptance tests include:

- `test_path_save_type_removes_embedded_samples_and_reloads_original_files`
- `test_workbook_path_mode_and_missing_references_survive_save_without_embedding`
- `test_document_storage_work_keeps_gui_timers_running`
- `test_hiding_and_restoring_a_batched_channel_retains_its_source_buffers`
- `test_resizing_dense_plots_keeps_curves_and_coalesces_paint_batches`
- `test_dense_screen_geometry_preserves_peaks_gaps_and_full_detail_on_zoom`
- `test_selection_show_modes_keep_all_rows_and_can_filter_rows`

The pixel comparison test now populates its actual Spectra layout before
rendering. Previously it added a dense curve to the collapsed no-data layout,
leaving an approximately one-pixel-high plot region. Its mean/max pixel
acceptance thresholds were not relaxed.

The requested repository-wide run selected every `tests/test_*.py` module except
the three explicitly deferred `test_auto_weighting*` modules, through the normal
`python run_tests.py` runner. It ran **1,421 tests in 533.348 s** with an initial
result of **1 failure and 3 errors**:

1. The old Checked/Unchecked rows test expected filter intersection. Its
   expectation was updated to the user's approved whole-participation scope;
   it now passes while also verifying that saved filter conditions survive.
2. The storage hard-link test hit sandbox `WinError 5` during `os.link`. The same
   test passed an approved, isolated outside-sandbox retry in 0.242 s.
3. `test_proved_source_retains_all_literals_without_rescanning_values` still
   raises `ValueError: assignment destination is read-only` when modifying its
   prepared document fixture.
4. `test_correlation_button_opens_active_reference_and_raw_sources` still raises
   `AttributeError` because its `FakeCorrelationWorkspace` lacks `raw_model`.

The last two failures were already documented before this optimization in
`spectra-selection-ui-2026-11-03.md` and remain reproducible on focused retry.
They have not been hidden or fixed by broad unrelated changes. This is **not a
fully green regression claim**. The full run preceded the final small
missing-reference and test-fixture follow-ups, which have focused verification.

All runs used the metrology-workspace conda interpreter and scratch settings,
recovery, reminders, Matplotlib and temporary directories. The production
`config/settings.yaml` was not changed. No AutoWeighting tests were run.

Machine-readable measurements are stored in the adjacent JSON report. The
repeatable probe scripts and detailed test/profile logs remain under `.cache`.

# Match Workbook loading and unopened Spectra storage

## Scope and root cause

The current working directory contains the 5.2.0 source plus unsubmitted development changes. This fix preserves those changes and does not update tags, branches or release assets. The actual input is `JC1913/matching-analysis.mwkb`, 409,559,040 bytes with 1,890 embedded spectra.

The startup chooser and Shell recent menu loaded entire documents just to obtain their type. Shell routing also loaded a complete snapshot that the receiving window discarded and read again. Match then hashed the same loaded file again. Embedded Spectra frames were eagerly built as large text DataFrames even when no Spectra child was opened. Saving validated the old document by materializing these frames again.

## Changes and safety

- `workspace_kind` performs only routing checks, optionally excluding recovery drafts. Recent menus never materialize tables. Opening still performs document schema/state validation.
- The startup chooser passes its validated snapshot to the window. A cheap file identity/size/mtime/ctime guard detects a replacement before installation. Loading retains a SHA-256 revision; actual overwrite conflicts and the final save guard still compare full SHA-256 values.
- All application SQLite reads use native `fetchone` / `fetchall` / `fetchmany`. Literal strings, dtype restoration, duplicate headers and catalog row order remain intact. Large TEXT is fetched without a SQLite full-payload sort; only row references are sorted when physical row order differs.
- `StoredFrame` holds unopened Spectra on disk. One private copy of the source container pins the bytes independently of external changes, Save As or backup rotation. This intentionally uses temporary disk space rather than retaining all sample strings in Python. References share immutable backing through snapshot/recovery copies; opening a child materializes its own frame in a worker.
- Save copies deferred frame records in bounded native batches. Validation of an existing destination checks state, schemas and row ownership without retaining sample payloads. Recovery equality checks structure before reading any values, so an unrelated changed Raw table cannot cause spectra to load.
- The container remains format version 1. Embedded sample strings and precision are unchanged. Atomic temporary-file publication, final integrity check, fsync, exclusive lock, SHA-256 conflict checks and copied `.bak` remain. No hard-linked backups or sample format migration are introduced.

## Executable validation

- Focused storage/startup/legacy/Spectra/recovery/lifecycle run: 138 tests passed in 36.839 s. After the final recovery comparison guard, the narrower final set passed 94 tests in 27.207 s; the external-replacement chooser test also passed separately.
- New cases reproduce the recent-list full load, duplicate chooser load and recovery deduplication's unintended materialization before the corresponding fixes.
- Real-file probe `.cache/validate_workbook_loading.py`: all 1,890 payload records have identical before/after digest; the backup is byte-identical to the previous file. All 1,890 spectra decode after an actual UI save and their check state is preserved. Every array of the first source matches independently decoded stored arrays exactly. Plot drawing is deliberately disabled only for this decode probe.
- Original source SHA-256: `c002afab609b5b5820263e71abd5cdb677e77df7e464d22266af5e9e61985ab2`, unchanged after validation. The production settings file is never used for writes; all UI/test probes use scratch settings and test-owned save targets.
- Final full regression outside the sandbox: **1,462 tests passed in 532.500 s**, 121 modules, exit code 0. AutoWeighting's three explicitly deferred modules remain excluded. Full log: `.cache/workbook-loading-validation/full.log`; machine-readable evidence: [workbook-loading-2026-11-11.json](workbook-loading-2026-11-11.json).
- The first full run completed 1,460 tests in 543.232 s with one environment error: the sandbox denied `os.link` while creating the fixture for `test_copy_cannot_overwrite_owner_or_samefile_alias`; no application assertion in that case ran. The identical test passed outside the sandbox in 0.240 s. No skip or weakened assertion was introduced. Final routing failure/temporary-backing cleanup checks passed 77 tests in 16.425 s, followed by the successful final full run above. Test-only scratch directories left by the interrupted earlier run were removed after checking their paths and contents; pre-existing local files were retained.

## Repeatable measurements

Probe `.cache/measure_workbook_loading.py` runs in a fresh process and saves only a private copy. The pre-edit measurements used this working directory before changing the loading code. A nine-entry stress case lists the same 409.6 MB source nine times; it is not the user's actual nine-file recent list. Initial before/after timings are 23.898 / 0.032 s for that chooser, 6.320 / 1.478 s for Shell open, and 5.328 / 2.071 s for storage overwrite with backup. Shell loaded RSS was 599.0 / 180.1 MB. These are same-machine observations, not fixed latency guarantees; final repetitions and actual-recent-list measurements are recorded in the JSON report.

Final repeat probe `.cache/measure_workbook_loading_repeated.py` alternates three fresh-process samples per case/phase, with no regression suite running concurrently. Baseline is the isolated published v5.2.0 source (`f441c0e`), whose affected loading functions match the pre-edit working directory. After is this working directory. The actual personal recent list was read only and offered the same eight valid Match files in both phases.

| Case | Before median | After median |
| --- | ---: | ---: |
| Cold module button click until chooser becomes modal/visible, actual 8 files | 2.824 s | 0.346 s |
| Startup chooser, actual 8 recent files | 2.525 s | 0.0319 s |
| Shell opening the 409.6 MB Workbook | 4.659 s | 1.470 s |
| Storage overwrite with copied backup, unopened spectra | 3.412 s | 2.053 s |
| Loaded Shell RSS | 599.6 MB | 180.3 MB |

Storage overwrite timings measure `save_workspace`, including validation, atomic write, backup, checksums and fsync; they do not claim timing for encoding newly imported spectra in a live child. Memory uses Windows working set (RSS), not private commit or virtual address space. All individual samples are in `.cache/workbook-loading-validation/timings.json` and the durable JSON report.

The cold-button case includes the first import and actual Shell launch/dialog event loop; the 0.0319 s chooser construction result excludes that import. Final real-file verification was repeated after all code changes and after the full suite, with the same payload digest and unchanged original file. No production settings or source measurements were overwritten. This work remains local and does not modify the published 5.2.0 tag or assets.

# Spectra Viewer import compression

Measured on the local Windows machine with 16 logical CPUs, using every SME file found recursively under `D:\spectra`. The 4,809 files occupy 782,829,634 bytes. The existing reader decoded 3,123 spectra and reported 1,686 encrypted files in every run.

| Run | Compression threads | Embedded preparation | Import to Viewer ready |
| --- | ---: | ---: | ---: |
| Original implementation | 1 | 13.54 s | 29.23 s |
| Updated, Auto, run 1 | 4 | 4.94 s | 18.05 s |
| Updated, serial, run 1 | 1 | 13.60 s | 27.22 s |
| Updated, serial, run 2 | 1 | 13.69 s | 27.95 s |
| Updated, Auto, run 2 | 4 | 5.20 s | 19.04 s |
| Updated, serial median | 1 | 13.64 s | 27.58 s |
| Updated, Auto median | 4 | 5.07 s | 18.54 s |

The paired medians show a 62.8% reduction in embedded preparation time and a 32.8% reduction in overall import time. The original implementation was measured before editing the loader. The paired runs used the same updated Viewer and codec on the same corpus, with only the encoder's worker limit overridden for the serial runs. Filesystem caches were left in their normal Windows state.

The benchmark starts a real Viewer and invokes its usual background import with Qt offscreen. Preparation is measured inside the loader's encoder call. Overall time ends when the worker has published the catalog, the import controls are available again, and pending plot-paint ticks have settled. The measurement includes scanning and parsing. It uses a fresh temporary application configuration and reads source files in place.

All runs embedded 3,123 records. The SHA-256 digest covers every record's source identifier, metadata text and compressed payload in order. It matched the original serial run and all paired runs.

`6845667056d11a2172ad757f1a4d7bfa2444721abb8bb13d9cd86aac7d89a7f8`

Reproduce the paired runs with the following command from the repository root.

```powershell
.venv\Scripts\python.exe benchmarks\benchmark_spectra_import.py D:/spectra compare.json --modes auto serial serial auto
```

## Verification

The final targeted run passed 47 of 51 tests and skipped four cases requiring the separate mixed-instrument SME fixture. It covered worker limits, settings persistence, stage progress, empty and Paths Only imports, interruption, encoder failure, and serial and parallel record equivalence. The run also reopened a standalone `.spec`, a Match Workbook with embedded Spectra, and a `.ref` session with cached Ref outputs after deleting the original test CSVs.

The full `run_tests.py` run completed 1,603 tests in 682.9 seconds and reported 26 failures, 417 errors, and 22 skips. Of those results, 392 error entries explicitly required a parameter mapping where old fixtures assumed the Match Workbook had created one automatically. Other failures included old mapping-editor expectations, source pairing, and a workspace menu test. The directly targeted Spectra and Reference Summarizer modules passed their executed tests.

Both test runs used disposable settings, recovery and reminder paths. The SHA-256 of the user's `config/settings.yaml` matched before and after the work.

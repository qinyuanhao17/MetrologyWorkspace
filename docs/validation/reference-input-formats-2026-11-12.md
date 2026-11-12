# Reference Summary CSV / Excel and single-wafer CDSEM1

Date: 2026-11-12. Development changes after v5.2.0; no tag or binary published.

## Scope

The user explicitly deferred full-suite testing. Only the 30 relevant parser,
Reference Summary/Alignment, reference-edit and startup tests were run here.
All passed in 3.992 seconds through `run_tests.py`, with scratch settings.
AutoWeighting was not run. Earlier full-suite results do not certify these new changes.

## Behavior

- NOVA, PMISH, KLA and CDSEM1 accept CSV, XLSX and XLSM. Excel uses only the first
  worksheet. File selection and recursive folder scans accept the same formats,
  skip Excel lock files and skip previous output directories.
- CSV/first-sheet Excel transport is shared in `reference_input.py`; vendor
  grammars, channel separation, unit strings and deduplication are retained.
- CDSEM1 requires ACD_No, MP_Name, Chip_X, Chip_Y and Result. Missing Lot_ID or
  Wafer_ID stays blank. A source without Wafer_ID must truly contain one wafer;
  coordinates alone cannot detect multiple anonymous wafers.
- CD matching is whitespace/case insensitive. MP names and measurement strings
  are retained, with MP order taken from first appearance. Chip/MP blanks fail
  with source rows; full duplicates exclude SourceRow, conflicting Chip+MP
  records fail instead of overwriting data. Source files remain independent.
- Common 11 fields, LOCAL 34 fields per MP, dual-header CD Pivot, CD Results,
  Results CSV and Checks retain their structure. Checks additionally records raw
  source rows and notes when wafer identity is blank. Missing identities are not
  fabricated to enable later wafer linking.
- Existing `main.py` also supports `--vendor CDSEM1 --files <source>` and optional
  `--output-parent <directory>`. No separate application or dependency was added.

## Real-file acceptance

Source: `C:\Users\Yuanhao Qin\OneDrive\Desktop\cd_sem_ref.xlsx`.

| Check | Verified result |
| --- | --- |
| First-sheet raw rows | 17,199 |
| ACD_No=CD rows | 1,911 |
| Chips / MP names | 91 / 21 |
| CD Pivot data shape | 91 × 725 |
| CD Results data shape | 91 × 32 |
| Duplicates / missing Chip×MP | 0 / 0 |
| Wafer_ID and Lot_ID | Both blank |
| Result values verified | All 1,911 |
| Original source | SHA-256 unchanged |
| Summary UI integration | Completion and Ref table loading succeeded |
| Actual main.py CLI | Exit 0, 91 chips, 21 MPs, 0 errors |

An independent openpyxl read validated source measurements against actual
exported XLSX and CSV. Source XML contains long floating-point literals such as
`37.619999999999997`; they were retained, not rounded. All exported Results
compare equal to their original Excel numeric values. The JSON evidence records
the input hash and generated artifact paths.

The previously supplied four-vendor ZIP contains 13 source files. Their parsed
records, field order and channel metadata were compared with isolated v5.2.0
source commit `f441c0e`; every digest matched. This includes the original CDSEM1
workbook with wafer identity. Each real input was also converted between CSV
and first-sheet Excel and checked for equivalent parsed measurements. The ZIP
hash remained unchanged. These are targeted compatibility checks, not a full regression.

## Executable acceptance mapping

`docs/features/reference_summary.feature` scenarios are covered by:

- `tests.test_cdsem1_compatibility`: optional identities, exact MP spelling/order,
  schema, dedup/conflicts, blank coordinate errors, independent files and main.py CLI.
- `tests.test_reference_input_formats`: all-vendor CSV/XLSX/XLSM equivalence,
  cancellation, first-sheet-only processing and original row provenance.
- `tests.test_reference_summary`: UI file selection, recursive folder discovery,
  completion/error/cancellation workflow.

Final command:

```powershell
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' run_tests.py tests.test_cdsem1_compatibility tests.test_reference_input_formats tests.test_reference_summary tests.test_reference_alignment tests.test_reference_source_columns tests.test_reference_edit_controls tests.test_startup_imports -v
```

Machine-readable evidence: [reference-input-formats-2026-11-12.json](reference-input-formats-2026-11-12.json).
Local real-file probes and outputs are under `.cache/cdsem-compatibility-validation/`.
`git diff --check` passed and `config/settings.yaml` has no worktree modification.

# Follow-up: two recorded regression errors — 2026-11-04

## Scope

Fix the two remaining errors reported for v5.1.0. The fixes were first verified
locally. The user then explicitly requested replacing the v5.1.0 tag, Setup and
portable ZIP with this fixed source, and fast-forwarding CXMT to the same commit.
The initial test results remain a historical record; the replacement release's
validation report uses the successful rerun below. AutoWeighting/OCR remains
explicitly excluded.

## Causes and fixes

### Prepared literal-frame contract

`prepare_sheet_version()` intentionally publishes immutable preparation buffers.
`LiteralFrameSource` can prove identity only for such a read-only region. Loaded
editors and `SheetModel.document_frame()` expose independently editable data.
This contract is already verified by
`test_prepared_version_is_readonly_while_loaded_sheet_and_public_reads_are_editable`.

The older
`test_proved_source_retains_all_literals_without_rescanning_values` incorrectly
attempted an in-place write to the internal prepared buffer. It now verifies
that this write is rejected, edits the model's public detached frame and checks
that the preparation, model and original proved source remain unchanged. Its
no-rescan assertion and inability to re-enable source-buffer writes remain.
Production preparation is unchanged: no extra large-table copies are added to
make an obsolete test expectation pass.

### Correlation factory compatibility

`MatchingWindow` accepts a Correlation window factory. Its existing source-load
contract does not require the factory's result to expose the standard window's
internal `raw_model` cache. The prepared-load optimization dereferenced that
optional model unconditionally, causing the valid minimal factory test to fail.

The cache lookup now checks for the model first. Standard Correlation windows
retain their prepared-load path; factories without the optional model use the
existing ordinary `set_sources()` path. The existing minimal factory test and
real `CorrelationWindow` test both pass without adding fields to the test fake.

## Verification

Both original tests reproduced their errors before edits (2 tests, 0.146 s).

- Literal frame source, linked table versions and sheet read-view suites:
  **24 tests passed in 0.423 s**.
- Both original tests plus the real default Correlation factory workflow:
  **3 tests passed in 0.274 s**.
- Complete authorized regression through `python run_tests.py`: **1,421 tests
  passed in 528.043 s**, no failures, errors or skips. The three explicitly
  deferred `test_auto_weighting*` modules were excluded. Both formerly failing
  tests and the temporary hard-link protection test passed within this run.
- `git diff --check` passed. Production settings retain their pre-test last-write
  time. No tags or binary assets were changed during the regression validation;
  their subsequent replacement is a separately authorized delivery step.

Logs use `.cache/regression-two-errors-red.log`,
`.cache/literal-frame-contract-green.log`,
`.cache/regression-two-errors-green.log` and
`.cache/regression-two-errors-full.log`.

Settings, recovery, reminders, Matplotlib and temporary files are isolated.
The full run uses the approved normal execution context because the restricted
sandbox blocks the storage suite's temporary hard-link test. User measurement
files, production settings and published tags are preserved.

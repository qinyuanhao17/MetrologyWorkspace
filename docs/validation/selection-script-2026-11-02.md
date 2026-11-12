# Data selection scripts and checked SME export

Spectra Viewer now has Data → Data selection. Applying the dialog sets the
same file participation used by tree checks, plots and checked-SME export.
Multichannel SME files remain one participation row. Selection filters, search,
visibility and Hide excluded rows are retained in `.spec` and Workbook drafts.

Every Data selection dialog has a Selection Script button at the top right.
The panel exposes a versioned JSON recipe with grouped filters, AND/OR joins,
search, row visibility, Hide excluded rows and all source checkbox states.
Open panels follow changes to the draft. Copy Selection Script copies current
state; Paste from Clipboard and Apply Script update the target draft. The
outer Apply accepts it; Cancel preserves the window's previous selection.
Recipes contain data, not executable Python.

Updated on 2026-11-03: JSON version 2 uses only Wafer ID, Lot ID, PAD Name and
Die. SME names and paths do not participate. Integer Die forms such as 001 and
1 compare equally without rewriting source strings. Repeated identities share
one state; conflicting source checkbox states produce a visible validation
message and disable copying a stale recipe. Version-1 path scripts must be
copied again from the updated source window. Reordering records does not
change participation. Missing
source records, unavailable filter columns and malformed recipes are rejected
before mutating the draft. Newly present target records remain checked.

Linked analysis children following Match Workbook selection now open with the
parent's current checks, conditions and view settings. Applying a local change
switches the radio choice to Full data without replacing editable tables.
Unchanged Apply and Cancel preserve the parent-following mode. Local Hide
excluded rows works in child Raw/Reference tables and is saved with its view.

Export Checked Spectra copies existing SME source files in a background thread,
preserving their folder hierarchy and bytes. It never generates SME files from
embedded numeric arrays. Missing originals and existing destinations fail
preflight without overwrites. Cancellation removes only files newly created by
that export, retaining source files and any pre-existing target files.

## Validation

The focused selection/Spectra/Workbook run passed 117 tests. An earlier linked
selection/grouping run passed 79 tests. The source export test reloads actual
copied SME fixtures and compares their complete bytes.

Real JC1913 validation at Qt scale factor 1.25 loaded 1,890 files with no issues,
compared complete parent/child recipes and transferred a selection to Spectra
Viewer (1,848 checked, 42 excluded). The child switched to Full data after a
local change without changing its source table. Three original SME files were
copied, their SHA-256 hashes matched, and all three reloaded successfully.
Results are in `selection-script-real-2026-11-02.json`; the rendered dialogs
were inspected at the same scale.

The full scoped regression is recorded in
`selection-script-regression-2026-11-02.json`. The five previously deferred
AutoWeighting-related test modules remain excluded. All tests and probes use
scratch settings and do not write the production settings file.

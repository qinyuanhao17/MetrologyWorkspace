# AutoWeighting Writer — V1 (v4.0.1)

The v4.0.0 release and its later-added installer do **not** contain this tool.
Version v4.0.1 adds this fifth independent tool to the home screen; see the
[release validation and limitations](releases/v4.0.1.md).
It runs recognition inside the application on the user's CPU, not through a
chat assistant, cloud service, or manually transcribed reference tables.

## Workflow

1. Open **AutoWeighting Writer**. Paste a screenshot with the toolbar button or
   Ctrl+Shift+V (Ctrl+V also works outside a cell editor), open PNG/JPEG/BMP files,
   or drop image files. Select multiple screenshots in the left list for a
   scrolling table. Images are retained locally as source evidence.
2. Choose automatic template detection or the intended table type. Click
   **Recognize selected images**. Recognition runs in a worker; Cancel never
   partially imports its result. Closing during OCR waits for cancellation.
3. Review the editable candidate dialog. Clicking a cell displays the original
   source crop. Fix unreadable Names before import. Confirm **Import / merge**.
4. The two result tabs are **Base Parameters** (Name/Nominal/Min/Max) and
   **Multiple Step** (Name plus Step1–Step5 Mode/Value). Overlapping screenshots
   merge by exact Name anchors and consistent row offsets. Name disagreements
   inside an anchored overlap become conflicts, not extra duplicate rows.
5. Amber cells remain unreviewed, red cells have validation/conflict issues,
   and gray cells were not collected. Click any cell to inspect evidence.
   Select the intended conflict candidate (including Current), then **Use selected
   candidate**, or edit it explicitly. **Mark selected reviewed** does not clear
   unresolved conflicts. Undo/Redo includes imports, corrections and review state.
6. **Save** creates a `.waw` project with screenshots, original OCR strings,
   confidence, rectangles, conflicts and correction history. Save/Save As,
   backups, revision-conflict protection, recovery drafts, and Save/Discard/Cancel
   reuse the existing document system. Projects reopen from the home screen.
7. **Export Excel** writes Parameters, Multiple Step, Combined, and
   Collection & Review sheets. Numeric source text keeps its precision; formulas
   remain literal text, never active Excel formulas. The review sheet distinguishes
   visible blanks from uncollected cells. **Copy table** produces TSV.

V1 does not read Float/DFF/Seed/Ignore/Extend checkbox states, weighting-button
internals, cropped-away rows, arbitrary document layouts, or hidden values.
It does not calculate an AutoWeighting algorithm, execute constraints, assume
angle units, fill Fix blanks from previous steps/Nominal, or write JP settings.
The name “Writer” describes preparation/export, not automated control of JP.

## Plan assessment and chosen implementation

The supplied proposal's fixed-grid approach is feasible. Its V1 scope is used;
source-crop review and conflict safeguards were moved forward from V2 because
small text can yield confidently wrong formulas. The proposal's example Max=23
for TopPoly differs from the supplied screenshot (22); examples are not truth.
Its suggestion to convert all numbers immediately to float is intentionally not
used: literal strings plus Decimal validation preserve signs and trailing digits.

| Route | Benefit | Tradeoff / V1 decision |
| --- | --- | --- |
| OpenCV grid + RapidOCR recognizer | Explicit cell geometry; same in-process CPU runtime and locally bundled model | Selected; only two known templates, readable headers required |
| Tesseract per cell | Mature alternative, useful future numeric comparison | Not benchmarked here; would add a second executable/model deployment |
| Generic table/layout models or img2table | Useful for diverse documents | Extra structure/integration not needed for these two software grids; no accuracy claim without tests |
| Small language model | Could help interpret unfamiliar layouts | Not selected: numerical transcription and constraint completion must not invent data; additional model/deployment cost |

Within RapidOCR, both bundled PP-OCRv6 and an official English PP-OCRv4 model
were locally probed. Tight text crops substantially changed results compared
with feeding mostly empty cell rectangles. The English probe still lost some
formula minus signs; the final adapter uses the bundled PP-OCRv6 recognition
model. No general benchmark superiority or performance improvement is claimed.
Recognition scores are not correctness guarantees. Numeric/name strings are not
silently repaired. Mode normalization alone uses the closed Float/Fix/Constrain
vocabulary (unique one-character edit), preserving raw OCR and unreviewed status.

## Offline contract and packaging

Pinned dependencies: RapidOCR 3.10.0, ONNX Runtime 1.23.2 (CPU),
opencv-python-headless 5.0.0.93. Other tools do not import the OCR engine at
startup. The adapter verifies the local model before loading, explicitly sets
its path and disables detection/direction recognition. It never invokes OCR
visualization, which otherwise has a separate font-download path.

Model: `PP-OCRv6_rec_small.onnx` (21,234,383 bytes), SHA-256
`6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884`.
The pinned wheel includes it. Missing/wrong models fail with an actionable error;
there is no first-run download. The PyInstaller spec includes the local model,
YAML configuration, package metadata and code/model license notices. The English
comparison model is not a runtime dependency or bundled application asset.

Upstream implementation/provenance:
[RapidOCR](https://github.com/RapidAI/RapidOCR),
[model attribution](https://github.com/RapidAI/RapidOCR/blob/v3.10.0/python/rapidocr/MODEL_LICENSES.md),
[Tesseract table guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

## Verification

Run `python run_tests.py tests.test_auto_weighting tests.test_auto_weighting_ocr
tests.test_auto_weighting_window -v`, then the complete `python run_tests.py`.
The launcher `--self-test` includes all five tools and an actual local OCR
inference on a generated numeric text crop, including in frozen builds.

The three private screenshots were processed with socket connections and
RapidOCR downloads forbidden. The base table's 40 fields matched the screenshot;
the Step screenshots produced 20 and 17 parameter rows, merging into 20 rows.
Case-sensitive identifiers, a small cropped first row and formula characters
still need review. The tool preserves those discrepancies; it does not hard-code
the sample values or claim universal screenshot accuracy. Input screenshots and
generated QA workbooks are not committed or distributed.

Executable acceptance scenarios: [auto_weighting_writer.feature](features/auto_weighting_writer.feature).
Target-company-PC testing (actual offline environment, screen scaling, security
policy and typical inputs) remains necessary; local packaged validation cannot
certify another computer or its installation policies.

### Final local verification — 2026-10-19

- 29 new data/OCR/window tests pass; 53 focused tests including existing shell
  and workspace-store coverage pass.
- Complete suite: **809 executed, 801 pass, 8 fail elapsed-time thresholds**
  (666.228 s). No other failures/errors. The suite is not entirely green; none
  of its timing thresholds was skipped or changed. The eight cases are the
  previously documented Correlation checkbox, equal identity snapshot, large
  Raw selection, keyboard Undo, saved Correlation restore, unchanged dirty
  check, Wafer window open and warm stage switch/Apply checks. Fewer failures
  in this run do not establish a performance improvement.
- The actual application worker processes all three supplied images, opens
  editable candidates, merges to 10 base rows/20 Step rows, saves a `.waw` and
  exports Excel. Qt renders of the candidate/base/Step views were inspected.
  The private inputs and outputs remain outside version control and packages.
- The PyInstaller EXE opens all five tools and performs real local OCR with a
  Windows-only PATH from an empty scratch working directory. Its self-test
  exits 0, without relying on a local Python/Conda path. The recognition model
  and code/model/dependency notices are included.
- The user's `config/settings.yaml` SHA-256 remains
  `f23479ce51455e70eab67fca72699896bd9514c01b0a3377f9eb06f634d53a1f`.

The preview is local under `release/auto-weighting-v1-preview/`; it has not been
pushed/tagged or added to GitHub Release. The separate v4.0.0 installer was
uploaded and verified, and that tag/payload remains unchanged.

Preview ZIP: `MetrologyWorkspace-AutoWeightingWriter-V1-Preview-Windows-x64.zip`,
199,772,591 bytes, SHA-256
`1356cf347a1295ec9939894b56eb2481a5e81586973cc816fdb4b3ed712952d0`.
All 1,565 ZIP entries pass integrity checks; no personal/QA workspaces, logs,
settings or reminder store are present. A fresh extraction's EXE hash matches
the built file and its application/OCR self-test also exits 0 with Windows-only
PATH from the empty scratch working directory.

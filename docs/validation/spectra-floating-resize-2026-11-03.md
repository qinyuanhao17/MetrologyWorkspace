# Spectra floating windows and resize scheduling — 2026-11-03

Die Map and double-click enlarged spectrum windows now share the Measurement
Table editor's application-scoped pin behavior. The native title icon toggles
the pin; Alt+P provides keyboard access. The duplicate toolbar button and its
empty toolbar row have been removed. No system-wide always-on-top flag is used.

A splitter resize retains curve objects and source arrays. New pixel dimensions
still require axes and screen geometry to be painted. Previously each dense
panel restarted the shared paint queue separately; one resize could restart it
20 times. Resize notifications now coalesce into one batch per event turn, and
resuming Qt updates no longer also forces a synchronous viewport repaint.
Splitter dragging continues to use a rubber band rather than continuously
resizing every plot while the handle moves.

## Measurement

The repeatable probe `.cache/profile_spectra_resize.py` loaded the 20 original
UVSE SME files in `all_uploaded_SME_spectra_42_files/01_AIT_UVSE_20_Die`, checked
all spectra, and resized the same viewer from 1500 pixels wide to 1700, 1400,
then 1600 (height 900). Both runs retained all 21 batched curve objects and made
zero data refresh calls during resizing. Settings and temporary paths were
isolated under `.cache`.

| Width | Initial event before / after (ms) | Settled before / after (ms) | Queue starts before / after |
| --- | --- | --- | --- |
| 1700 | 31.72 / 26.59 | 439.00 / 453.58 | 20 / 1 |
| 1400 | 46.05 / 21.35 | 407.75 / 407.19 | 20 / 1 |
| 1600 | 37.44 / 19.39 | 438.46 / 423.85 | 20 / 1 |

Initial event median decreased from 37.44 to 21.35 ms. Total settling remained
roughly 0.4 seconds, including the probe's fixed 50 ms settling allowance;
this does not establish an equivalent gain for a 1,890-file workload. Numerical
data and visible peaks/gaps are preserved by the focused image and zoom checks.

## Validation scope

Only Spectra Viewer, Die Map and floating pin tests are run for this follow-up.
The user has deferred full regression until explicitly requested. AutoWeighting
remains deferred and was not tested. Existing source measurement files and
unrelated pending edits are preserved.

An initial scoped run accidentally named the nonexistent
`tests.test_floating_editor` module and also observed one intermittent Die Map
double-click assertion. The module name was corrected to `tests.test_float_pin`;
the double-click test passed in isolation. That UI test now waits for the next
layout event and resolves the current marker location before each click instead
of reusing a pre-paint pixel location. Final scoped run:
`python run_tests.py tests.test_spectra_viewer tests.test_spectra_map tests.test_float_pin -v`
passed all 88 tests in 42.054 seconds. This includes peak/gap pixel equivalence,
zoom detail, curve reuse, coalesced resizing, no duplicate toolbar, application
pin scope, and existing Measurement Table pin behavior. No full-suite success
is implied. Machine-readable results are in the adjacent JSON file.

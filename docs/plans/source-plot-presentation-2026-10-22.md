# Correlation / Match numeric axes and source-qualified plot styling

## Requested behavior

- Y ticks represent original values, with no automatic multiplier/offset in the
  axis title. Complete tick text also distinguishes large neighbouring values.
- Source-qualified correlations use orange for REF–REF, blue for RAW–RAW and
  green for REF–RAW. Darker matching fit lines retain the category after Swap
  X/Y. Standalone unqualified correlations keep their existing style.
- Every added Trend axis includes its own Reference / Raw Data source, parameter
  and existing unit. This also applies to PNG and native/Matplotlib Excel output.

## Implementation and regressions

The initial public-page regressions reproduced enabled automatic SI scaling,
one shared correlation palette and missing source names on secondary axes.
Match already disabled Y SI prefixes. Visual QA exposed an additional default
formatter issue: large narrow-range ticks were all shortened to `1e+06`.
Unscaled interactive Y axes now format to the tick step, preserving fractional
steps such as 0.25/2.5 and distinct full large values. Bottom-axis behavior and
source observations, row alignment, regression and R² remain unchanged.

One source-pair color function drives the screen, Matplotlib mirror and detached
Excel descriptions. Presentation metadata does not become a measurement column.
Source-qualified secondary axes retain separate identities even when their units
match; units are still stored independently from the display label.

`tests/test_source_plot_presentation.py` contains seven regressions. Two older
tests asserting one shared correlation color were updated to the requested three
category colors without removing their data/identity assertions. The related
138-test run passed in 128.967 seconds. The seven focused tests were rerun after
the final fractional-step formatter change. Windows-platform visual QA verified
readable unscaled Y ticks, the three categories and source-qualified extra axes.

Only targeted tests were run, through the isolated `run_tests.py` entry point.
Full-suite testing, packaging and publishing remain deferred at the user's
request. The real settings file was not changed by this work.

The follow-up palette adjustment replaces REF–RAW's purple with green points
(`#009e73`) and a dark green fit (`#006b4f`), without changing the other categories.
Screen, axis swapping, PNG/Matplotlib and native Excel colors share this mapping.
The updated color assertion failed before the change, then all 11 tests in
`tests.test_analysis_plot_style` and `tests.test_source_plot_presentation` passed
in 4.653 seconds. Measurement strings, coordinates and fit calculations are unchanged.

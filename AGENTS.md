# Metrology Workspace agent guidance

This repository is a Python 3.10+ / PyQt6 desktop application for editing metrology data and producing wafer maps, radius plots, correlations, and trends.

## Skill policy

The allowlist below applies only to user-installed skills. Built-in Codex system skills and bundled plugin skills keep their default activation behavior.

For work in this repository, implicitly invoke only these user-installed skills:

- `tdd`: calculation rules, data transformations, state transitions, bug fixes, and other behavior that can be tested through a stable public seam.
- `bdd`: user-visible workflows, acceptance criteria, validation messages, and observable product behavior. Keep scenarios independent of Qt implementation details.
- `codebase-design`: changes to module boundaries or public interfaces across `metrology_app/`; keep UI orchestration separate from data, calculation, and rendering logic.
- `improve-codebase-architecture`: focused architecture reviews and deepening work; prefer a small, high-leverage module over broad directory churn.
- `scientific-visualization`: truthful plots, scales, legends, color maps, comparison semantics, accessibility, and publication-quality output.
- `matplotlib`: low-level Matplotlib rendering, layout, artists, axes, colorbars, vector/raster export, and rendering performance.
- `uncertainty-and-units`: physical units, tolerances, rounding, conversion, calibration, and measurement uncertainty. Never infer missing units or uncertainty models silently.
- `statistical-analysis`: correlation, regression, R-squared interpretation, filtering thresholds, assumptions, and statistical reporting.
- `ponytail`: coding, review, refactoring, and dependency choices. Prefer the smallest correct change and reuse existing code, but never remove requested behavior, validation, data-loss protection, accessibility, or required tests.

Do not implicitly invoke any other user-installed skill for this repository. A user may still explicitly request a non-allowlisted skill by name for a particular task; that explicit request applies only to that task.

## Implementation and verification

Apply the Karpathy-derived coding guardrails from
https://github.com/multica-ai/andrej-karpathy-skills without installing a
duplicate always-on skill:

- Surface material assumptions and tradeoffs before committing to an ambiguous implementation.
- Prefer the simplest implementation that fully satisfies the request; add no speculative flexibility.
- Make surgical changes only, preserving unrelated code, comments, formatting, and user work.
- Turn each non-trivial change into observable success criteria and verify them before completion.

- Preserve source measurement strings and row mappings unless the requested behavior explicitly changes them.
- Keep numerical logic testable without launching the full GUI where practical; test Qt integration separately.
- Connect BDD scenarios to executable tests rather than treating feature text as proof by itself.
- Run the smallest relevant tests during development, then run the full suite before claiming completion:

  `python run_tests.py`

  The runner points `METROLOGY_SETTINGS_PATH` at a scratch file. Never run the
  suite (or any scratch script) so that it writes `config/settings.yaml`: that
  file holds the user's theme and Open Recent WKB list, and a stray save used to
  replace them with defaults.

- Do not claim a performance improvement without a repeatable before/after measurement using representative data.
- Do not change interpolation, regression, color scaling, or export semantics merely for speed without checking numerical and visual equivalence.

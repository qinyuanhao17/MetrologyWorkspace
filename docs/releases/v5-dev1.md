# v5-dev1

Windows x64 development release, supplied as a per-user Setup installer and a
portable ZIP. The source tag preserves the existing v5-dev and v5.0.0 tags.

Spectra Viewer's spatial window is **Die Map**. Left-drag within one plot to
select its enclosed points; Ctrl/Shift adds points and blank-space clicks clear
selection. Unchecked points remain light gray. Double-clicking toggles their
source spectra; check changes retain existing map widgets and sizes. Similar
wafer participation requires matching Die IDs and corresponding X/Y differences
strictly below 0.4 mm.

This release includes the v5-dev Spectra Workbook integration, `.spec` files,
semantic Wafer/Lot/PAD/Die selection scripts and original-SME copy export.
Recopy Selection Script from updated source windows when using old path-based
scripts. Child save shortcuts continue to prioritize the owning Workbook.

The frozen application has an opt-in `--spectra-smoke-test <SME-folder>
<report.json>` release check. It exercises actual SME loading, native rectangle
selection and double-click checking without opening or testing AutoWeighting.
The portable build explicitly includes the Conda SQLite runtime DLL.

Builds use an isolated extraction of this tag. Setup and ZIP share the verified
application payload; personal settings, workbooks and SME files are excluded.
See [build and validation](../validation/v5-dev1-2026-11-03.md) for exact results
and known pre-existing repository test failures.

# v5-dev

This source development tag follows the preserved v5.0.0 snapshot.

- Spectra Viewer can be opened as a named Match Workbook child. Its samples
  and choices are embedded in the Workbook and can also be saved as `.spec`.
  Child Ctrl+S/Ctrl+Shift+S prioritize the owning Workbook.
- Data selection has a live, portable Selection Script. Version 2 matches
  Wafer ID/Lot ID/PAD Name/Die, independently of file names or paths. Grouped
  conditions, AND/OR, search, display mode, Hide excluded rows and participation
  are retained. Recopy scripts from updated source windows after upgrading.
- Linked analysis dialogs reflect the Workbook's selection. Accepted local
  changes switch to Full data while retaining complete editable sources.
- Spectra's spatial window is now Die Map. All measured sites remain visible;
  unchecked sites are gray. Rectangle selection and double-click checking link
  back to the tree and plots. Checkbox updates retain existing map widgets.
- Apply to Similar Wafer copies a Die participation pattern only when Die IDs
  match and every corresponding X/Y difference is strictly below 0.4 mm.
- Export Checked Spectra copies existing original SME files with their folder
  hierarchy and unchanged bytes. Missing originals and destination collisions
  are reported; reconstructed SME writing is not implemented or used.

See [development validation](../validation/v5-dev-2026-11-03.md). AutoWeighting
remains deferred. This tag contains source; it does not publish application
binaries or move existing release tags.

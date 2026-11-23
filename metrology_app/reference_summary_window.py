"""PyQt6 workflow for consolidating reference exports from four vendors."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from PyQt6.QtCore import QDateTime, QSignalBlocker, QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QKeySequence, QTextOption
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, help_title_label
from .cdsem1 import merge_cdsem1
from .reference_alignment import aligned_raw_analysis_frame
from .reference_merge import merge, scan_reference_files
from .reference_input import SOURCE_EXTENSIONS
from .reference_metadata import (BATCH_SUMMARY, find_output_summary, frame_metadata, measurement_csv_path,
                                 summary_html, write_output_summary)
from .reference_reports import REPORT_WORKBOOK
from .file_dialogs import choose_files, choose_folders
from .file_paths import filesystem_path
from .widgets import CheckableListWidget, ScrollSafeComboBox


VENDOR_DETAILS = {
    "NOVA": {
        "filter": "Reference files (*.csv *.xlsx *.xlsm)",
        "extensions": SOURCE_EXTENSIONS,
        "description": "Combine NOVA tables, remove repeated headers, consolidate _LBH flags and de-duplicate complete rows.",
    },
    "PMISH": {
        "filter": "Reference files (*.csv *.xlsx *.xlsm)",
        "extensions": SOURCE_EXTENSIONS,
        "description": "Split PMISH blocks by Recipe, Metrology unit and AzimuthAngle, preserving source values and units.",
    },
    "KLA": {
        "filter": "Reference files (*.csv *.xlsx *.xlsm)",
        "extensions": SOURCE_EXTENSIONS,
        "description": "Split KLA Offline blocks by TestID and TestLabel, retaining Slot as the cross-vendor PadName.",
    },
    "CDSEM1": {
        "filter": "Reference files (*.csv *.xlsx *.xlsm)",
        "extensions": SOURCE_EXTENSIONS,
        "description": "Read CSV or only the first sheet of Excel, keep ACD_No=CD, and export one workbook per source. Missing IDs stay blank; sources without Wafer_ID must contain a single wafer.",
    },
}


@dataclass(frozen=True, slots=True)
class ReferenceSummaryRequest:
    vendor: str
    files: tuple[Path, ...]
    output_parent: Path


@dataclass(frozen=True, slots=True)
class ReferenceSummaryReport:
    request: ReferenceSummaryRequest
    result: object
    output_files: tuple[Path, ...]
    issue_lines: tuple[str, ...]


def _issue_rows(report: Path):
    if report.suffix == '.xlsx':
        from openpyxl import load_workbook

        with report.open('rb') as stream:
            book = load_workbook(stream, read_only=True)
            try:
                for name in book.sheetnames:
                    if name == '_issues' or name.startswith('_issues_'):
                        rows = book[name].values
                        columns = next(rows)
                        for row in rows:
                            yield dict(zip(columns, row))
            finally:
                book.close()
    elif report.is_file():
        with report.open(encoding='utf-8-sig', newline='') as stream:
            yield from csv.DictReader(stream)


def _issue_lines(output_dir: Path, total: int, limit: int = 6) -> tuple[str, ...]:
    from contextlib import closing
    from itertools import islice

    if not total:
        return ()
    report = filesystem_path(output_dir.resolve() / REPORT_WORKBOOK)
    label = f'{REPORT_WORKBOOK} → _issues'
    if not report.is_file():
        report = report.with_name('_issues.csv')
        label = report.name
    lines = []
    with closing(_issue_rows(report)) as rows:
        for row in islice(rows, limit):
            source = Path(row.get('File') or '').name or 'Unknown file'
            detail = row.get('Issue') or row.get('Detail') or 'Unspecified issue'
            kind = (row.get('Kind') or '').strip()
            lines.append(f"{source} — {kind + ': ' if kind else ''}{detail}")
    if total > limit:
        lines.append(f'… {total - limit} more; open {label} for details')
    return tuple(lines)


def run_reference_summary(request: ReferenceSummaryRequest, cancelled=None, progress=None):
    """Run one vendor batch behind the window's stable processing seam."""
    if request.vendor == "CDSEM1":
        result = merge_cdsem1(
            list(request.files), request.output_parent,
            cancelled=cancelled, progress=progress,
        )
    else:
        result = merge(
            request.vendor, list(request.files), request.output_parent,
            cancelled=cancelled, progress=progress,
        )
    output_dir = Path(result.output_dir)
    files = tuple(sorted(
        (output_dir / path.name for path in filesystem_path(output_dir.resolve()).iterdir() if path.is_file()),
        key=lambda path: path.name.casefold(),
    ))
    return ReferenceSummaryReport(
        request=request,
        result=result,
        output_files=files,
        issue_lines=_issue_lines(output_dir, result.error_count),
    )


class _SummaryWorker(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request

    def run(self):
        try:
            report = run_reference_summary(
                self.request,
                cancelled=self.isInterruptionRequested,
                progress=self.progress.emit,
            )
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.completed.emit(report)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class _SummaryBrowser(QTextBrowser):
    def loadResource(self, resource_type, name):
        # Generated summaries are self-contained. Reopened HTML never fetches resources.
        return None


class ReferenceSummaryWindow(QMainWindow):
    """Select vendor exports, run in the background, and review a compact report."""

    workspace_type = "reference_summary"
    ANALYSIS_TAB_TITLES = ('4. Ref Data', '5. Raw Data', '6. Correlation',
                           '7. Trend', '8. Ref WaferMap', '9. Ref Radius Plot')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("referenceSummaryWindow")
        self.setWindowTitle("Reference Summarizer")
        fit_window_to_screen(self, (1180, 790), minimum=(900, 620))
        self.files: tuple[Path, ...] = ()
        self.output_parent: Path | None = None
        self.worker: _SummaryWorker | None = None
        self.report: ReferenceSummaryReport | None = None
        self._source_metadata = {}
        self._output_summaries = {}
        self._summary_path = None
        self._suggested_ref_name = 'Reference.ref'
        self._close_when_finished = False
        self._aligned_results = None
        self._aligned_inputs = None
        self._analysis = None
        self._build_ui()
        self._vendor_changed()
        from .settings import apply_theme
        apply_theme(self)
        from .workspace_document import WkbDocument
        self.document = WkbDocument(self)
        self.groups_menu = self.menuBar().addMenu("Groups")
        self.analysis_menu = self.menuBar().addMenu('Analysis')
        for menu in (self.groups_menu, self.analysis_menu):
            menu.aboutToShow.connect(self._load_analysis)
        self.tabs.currentChanged.connect(self._analysis_tab_opened)
        self.alignment.alignment_changed.connect(self._refresh_analysis)
        self._refresh_analysis()
        self.alignment.alignment_changed.connect(self.document.identity_timer.start)
        self.source_list.itemChanged.connect(lambda *_: self.document.identity_timer.start())
        self.output_path.textChanged.connect(lambda *_: self.document.identity_timer.start())
        self.tabs.currentChanged.connect(lambda *_: self.document.identity_timer.start())
        for button in self.trend_page.order_buttons.values():
            button.clicked.connect(lambda *_: self.document.identity_timer.start())
        self.document.mark_clean()

    @property
    def analysis(self):
        self._load_analysis()
        return self._analysis

    def _analysis_tab_opened(self, index):
        if index >= self._first_analysis_tab:
            self._load_analysis()

    def _load_analysis(self):
        if self._analysis is not None:
            return
        from .reference_analysis_ui import ReferenceAnalysisPages

        analysis = self._analysis = ReferenceAnalysisPages(self.tabs, self)
        current = self.tabs.currentIndex()
        with QSignalBlocker(self.tabs):
            for index, (page, title) in enumerate(zip(analysis.embedded_pages, self.ANALYSIS_TAB_TITLES),
                                                  start=self._first_analysis_tab):
                placeholder = self.tabs.widget(index)
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, page, title)
                placeholder.deleteLater()
            self.tabs.setCurrentIndex(current)
        for picker in (analysis.reference_die_picker, analysis.die_picker):
            picker.currentIndexChanged.connect(lambda _: self.document.identity_timer.start())
        for action in analysis.display_options.menu.actions():
            self.groups_menu.addAction(action)
        trend_axes = analysis.trend_y_axes_menu
        analysis.analysis_menu.removeAction(trend_axes.menuAction())
        trend_axes.setParent(self.analysis_menu, trend_axes.windowFlags())
        self.analysis_menu.addMenu(trend_axes)
        self.trend_page.data_point_edits = analysis._chart_edits
        trend = analysis.sequence_page
        trend.axis_mode.currentIndexChanged.connect(lambda _: self.document.identity_timer.start())
        trend.axis_ratio.valueChanged.connect(lambda _: self.document.identity_timer.start())
        if self._aligned_inputs is None:
            analysis.set_alignment_inputs(None, set(), False)

    @property
    def vendor_name(self):
        return self.vendor.currentText()

    def _build_ui(self):
        root = QWidget(objectName="appRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 18, 24, 20)
        outer.setSpacing(14)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_source_panel())
        split.addWidget(self._build_result_panel())
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 6)
        split.setSizes([430, 680])
        outer.addWidget(split, 1)
        from .reference_alignment_ui import ReferenceAlignmentPage, CoordinateTrendPage
        self.tabs = QTabWidget()
        self.tabs.addTab(root, '1. Summary')
        self.trend_page = CoordinateTrendPage()
        self.alignment = ReferenceAlignmentPage(self.trend_page)
        self.alignment.external_outputs_loaded.connect(self._summarize_external_outputs)
        self.alignment.active_output_changed.connect(self._show_output_summary)
        self.load_folders_button.clicked.connect(self.alignment.choose_output_folders)
        self.tabs.addTab(self.alignment, '2. Wafer Alignment')
        self.tabs.addTab(self.trend_page, '3. XY Bias')
        self._first_analysis_tab = self.tabs.count()
        for title in self.ANALYSIS_TAB_TITLES:
            self.tabs.addTab(QWidget(), title)
        self.setCentralWidget(self.tabs)
        self.alignment.plotted.connect(lambda: self.tabs.setCurrentIndex(2))
        self.file_menu = self.menuBar().addMenu("File")
        self.open_reference_action = self.file_menu.addAction("Open Reference Workspace…")
        self.open_reference_action.setShortcut("Ctrl+O")
        self.open_reference_action.triggered.connect(self.open_reference_dialog)
        self.save_reference_action = self.file_menu.addAction("Save Reference Workspace")
        self.save_reference_action.setShortcut("Ctrl+S")
        self.save_reference_action.triggered.connect(self.save_wkb)
        self.save_reference_as_action = self.file_menu.addAction("Save Reference Workspace As…")
        self.save_reference_as_action.setShortcut("Ctrl+Shift+S")
        self.save_reference_as_action.triggered.connect(lambda: self.save_wkb(save_as=True))
        self.show_summary_action = self.file_menu.addAction("Show Summary in File Explorer")
        self.show_summary_action.triggered.connect(self.show_summary)

        self.data_menu = self.menuBar().addMenu('Data')
        self.data_selection_action = self.data_menu.addAction('Data selection…')
        self.data_selection_action.triggered.connect(self.open_data_selection)

        cancel_action = QAction(self)
        cancel_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        cancel_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        cancel_action.triggered.connect(self.cancel)
        self.addAction(cancel_action)

    def _refresh_analysis(self):
        results = self.alignment.results or None
        if results is not self._aligned_results:
            try:
                self._aligned_inputs = self.alignment.reference_data() if results else None
            except ValueError as error:
                self._aligned_inputs = None
                self.statusBar().showMessage(str(error), 10000)
            self._aligned_results = results
        self._publish_analysis_selection()

    def _publish_analysis_selection(self):
        from .match_groups import participation_rows, participation_source_keys

        inputs = self._aligned_inputs
        state = self.alignment._dataset.data_selection or {}
        allowed, excluded = set(), set()
        if inputs is not None:
            raw = aligned_raw_analysis_frame(inputs[1], inputs[4])
            allowed = set(participation_rows(raw, state))
            if len(allowed) < len(raw):
                excluded = {key for row, key in enumerate(participation_source_keys(raw)) if row not in allowed}
        if inputs is not None or self._analysis is not None:
            self.analysis.set_alignment_inputs(inputs, excluded, state.get('hide_excluded', False))
        self.data_selection_action.setEnabled(inputs is not None and not inputs[1].empty)
        self.trend_page.refresh_point_checks(allowed)

    def open_data_selection(self):
        if self._aligned_inputs is None or self._aligned_inputs[1].empty:
            return
        from PyQt6.QtWidgets import QDialog
        from .data_selection import DataSelectionDialog
        from .match_groups import GroupPlan

        dataset = self.alignment._dataset
        reference, raw, _, _, metadata = self._aligned_inputs
        raw = aligned_raw_analysis_frame(raw, metadata)
        try:
            plan = GroupPlan(raw, state={'data_selection': dataset.data_selection}, reference=reference)
        except ValueError as error:
            QMessageBox.warning(self, 'Cannot select analysis data', str(error))
            return
        dialog = DataSelectionDialog(plan, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dataset.data_selection = dialog.selection
            self._publish_analysis_selection()
            self.document.identity_timer.start()
        dialog.deleteLater()

    def change_analysis_rows(self, rows, checked):
        from .match_groups import missing_excluded_records, participation_ids, row_ids

        if self._aligned_inputs is None:
            return set()
        _, raw, _, _, metadata = self._aligned_inputs
        raw = aligned_raw_analysis_frame(raw, metadata)
        dataset = self.alignment._dataset
        state = dataset.data_selection or {}
        excluded = set(state.get('excluded', ()))
        ids = participation_ids(raw, state)
        changed = {row for row in rows if 0 <= row < len(ids) and (ids[row] in excluded) == checked}
        if not changed:
            return changed
        changes = {ids[row] for row in changed}
        excluded = excluded - changes if checked else excluded | changes
        records = [{'key': key, 'id': identifier} for key, identifier in zip(row_ids(raw), ids)]
        dataset.data_selection = {**state, 'records': records + missing_excluded_records(state, records),
                                  'excluded': sorted(excluded)}
        self._publish_analysis_selection()
        self.document.identity_timer.start()
        return changed

    def workspace_snapshot(self):
        from .reference_workspace import snapshot
        return snapshot(self)

    def restore_workspace(self, snapshot):
        from .reference_workspace import install, prepare
        install(self, prepare(snapshot))

    def workspace_save_default(self):
        directory = self.document.path.parent if self.document.path else self.output_parent
        return (directory or Path.cwd()) / self._suggested_ref_name

    def _summary_metadata(self):
        from .reference_metadata import FIELDS, collect_sources, frame_metadata

        page = self.alignment
        active = page._dataset.path
        vendor = page._output_vendors.get(active, self.vendor_name)
        if vendor not in FIELDS:
            vendor = self.vendor_name
        if self.report is None:
            inputs = self.selected_source_files()
        else:
            inputs = self.report.request.files if self.report.request.vendor == vendor else ()
        cached = self._source_metadata.get(vendor, {})
        sources = collect_sources(vendor, inputs, cached)
        fields = frame_metadata(vendor, page.ref.frame())
        outputs = [(str(active) if active else 'Wafer Alignment', fields)] if fields or active else []
        for output in page._output_vendors:
            if output == active or page._output_vendors[output] not in (vendor, 'Ref'):
                continue
            dataset = page._datasets.get(output)
            frame = dataset.ref.frame() if dataset is not None else page._saved_output_frames.get(output)
            if frame is not None:
                outputs.append((str(output), frame_metadata(vendor, frame)))
        return vendor, fields, outputs, sources

    def save_reference(self, path=None, *, save_as=False):
        from .reference_workspace import cache_available_outputs
        from .reference_metadata import suggested_filename
        if self.worker is not None:
            raise ValueError("Wait for the current summary to finish.")
        cache_available_outputs(self.alignment)
        vendor, fields, outputs, sources = self._summary_metadata()
        self._suggested_ref_name = suggested_filename(vendor, fields, sources,
                                                       [metadata for _, metadata in outputs])
        suggested_base = suggested_filename(
            vendor, fields, sources, [metadata for _, metadata in outputs], include_date=False,
        )
        previous = self._source_metadata
        cached = {**previous.get(vendor, {}), **{name: fields for name, fields in sources.items() if fields}}
        self._source_metadata = {**previous, vendor: cached} if cached else previous
        saved = None
        try:
            if path is None and (save_as or self.document.path is None):
                filename = _reference_save_filename(self, suggested_base)
                if filename is None:
                    return None
                directory = (self.document.path.parent if self.document.path is not None
                             else self.output_parent or Path.cwd())
                chosen, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Reference Workspace As",
                    str(directory / filename),
                    "Reference Workspace (*.ref)",
                )
                if not chosen:
                    return None
                path = Path(chosen)
                save_as = False
            saved = self.document.save(path, save_as=save_as)
        finally:
            if saved is None:
                self._source_metadata = previous
        return saved

    def save_wkb(self, *, save_as=False):
        try:
            return self.save_reference(save_as=save_as)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot save Reference Workspace", str(error))
            return None

    def _summarize_external_outputs(self, entries):
        errors = []
        for path, vendor, frame in entries:
            vendor = self.vendor_name if vendor == 'Ref' else vendor
            try:
                summary = find_output_summary(path)
                if summary is None:
                    fields = frame_metadata(vendor, frame)
                    summary = write_output_summary(path, summary_html(vendor, path, fields, {}))
                self._output_summaries[path] = summary
            except OSError as error:
                errors.append(f'{path.name}: {error}')
        active = self.alignment._dataset.path
        if active is not None:
            self._show_output_summary(active)
        if errors:
            self.statusBar().showMessage('Could not write summary for ' + '; '.join(errors), 10000)

    def _show_output_summary(self, path):
        if path is None:
            if self.report is None:
                self._summary_path = None
                self.metadata_preview.clear()
            self._refresh_output_picker(self._summary_path)
            return
        self._summary_path = None
        try:
            summary = find_output_summary(path)
            if summary is not None:
                self._output_summaries[path] = summary
                self._show_html_summary(summary)
        except (OSError, UnicodeError) as error:
            self.statusBar().showMessage(f'Could not read the summary for {path.name}: {error}', 10000)
        if self._summary_path is None:
            vendor = self.alignment._output_vendors.get(path, self.vendor_name)
            vendor = self.vendor_name if vendor == 'Ref' else vendor
            fields = frame_metadata(vendor, self.alignment.ref.frame())
            self.metadata_preview.setHtml(summary_html(vendor, path, fields, {}))
        if self.report is not None and path in self.report.output_files:
            self._show_issues(self.report.issue_lines)
        else:
            self.issue_summary.clear()
        self._refresh_output_picker(path)

    def _show_html_summary(self, path):
        self.metadata_preview.setHtml(filesystem_path(path).read_text(encoding='utf-8'))
        self._summary_path = path

    def _output_paths(self):
        refs = self.alignment.output_picker
        outputs = [Path(refs.itemData(index)) for index in range(refs.count())]
        files = list(self.report.output_files) if self.report is not None else []
        files.extend(self._output_summaries[path] for path in outputs if path in self._output_summaries)
        return outputs, list(dict.fromkeys(outputs + files))

    def _refresh_output_picker(self, selected=None):
        outputs, files = self._output_paths()
        ref_role = Qt.ItemDataRole.UserRole + 1
        picker = self.summary_output_picker
        with QSignalBlocker(picker):
            picker.clear()
            for ref in outputs:
                path = measurement_csv_path(ref)
                if path.suffix.casefold() != '.csv' or picker.findData(str(path)) >= 0:
                    continue
                if path != ref and path not in files and not filesystem_path(path).is_file():
                    continue
                picker.addItem(path.name, str(path))
                picker.setItemData(picker.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole)
                picker.setItemData(picker.count() - 1, str(ref), ref_role)
            picker.setCurrentIndex(picker.findData(str(selected), role=ref_role))
        self._update_output_actions()

    def _select_output_file(self, _index):
        path = self._selected_output_file()
        if path is None:
            return
        refs = self.alignment.output_picker
        ref = self.summary_output_picker.currentData(Qt.ItemDataRole.UserRole + 1)
        index = refs.findData(ref)
        if index >= 0:
            if refs.currentIndex() == index:
                self._show_output_summary(Path(ref))
            else:
                refs.setCurrentIndex(index)
        self._update_output_actions()

    def _selected_output_file(self):
        value = self.summary_output_picker.currentData()
        return Path(value) if value else None

    def _update_output_actions(self):
        path = self._selected_output_file()
        self.summary_output_picker.setToolTip(str(path) if path else '')
        active = path or self._summary_path or self.alignment._dataset.path
        directory = active.parent if active else None
        if directory is None and self.report is not None:
            directory = self.report.result.output_dir
        self.open_folder_button.setEnabled(directory is not None)
        self.result_path.setText(str(directory) if directory else '')
        self.result_path.setCursorPosition(0)
        self.result_path.setToolTip(self.result_path.text())
        _, all_files = self._output_paths()
        files = [value for value in all_files if value.parent == directory]
        current = [self.output_list.item(index).data(Qt.ItemDataRole.UserRole)
                   for index in range(self.output_list.count())]
        if current != files:
            self.output_list.clear()
            for file in files:
                item = QListWidgetItem(file.name)
                item.setData(Qt.ItemDataRole.UserRole, file)
                item.setToolTip(str(file))
                self.output_list.addItem(item)
        selected = active if active in files else self._summary_path
        self.output_list.setCurrentRow(files.index(selected) if selected in files else -1)

    def _select_listed_output(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        picker = self.summary_output_picker
        index = picker.findData(str(path))
        if index >= 0:
            picker.setCurrentIndex(index)
        elif path.suffix.casefold() in ('.html', '.htm'):
            try:
                self._show_html_summary(path)
            except (OSError, UnicodeError) as error:
                self.statusBar().showMessage(f'Could not read the summary: {error}', 10000)

    def show_summary(self):
        from .matching_window import reveal_path_in_folder

        path = self._summary_path
        if path is None and self.report is not None:
            path = next((path for path in self.report.output_files if path.name == BATCH_SUMMARY), None)
        if path is None:
            return
        try:
            reveal_path_in_folder(path)
        except OSError as error:
            self.statusBar().showMessage(f"Could not show the summary: {error}", 10000)

    def load_workspace(self, path):
        from .reference_workspace import install, prepare
        from .workspace_store import file_revision, load_workspace
        if self.worker is not None:
            raise ValueError("Wait for the current summary to finish.")
        draft = load_workspace(path, expected_type=self.workspace_type)
        prepared = prepare(draft)
        if not self.document.confirm_close():
            return None
        if draft.revision != file_revision(path):
            draft = load_workspace(path, expected_type=self.workspace_type)
            prepared = prepare(draft)
        if "recovery" in draft.states:
            self.document.recover(path, draft)
            return draft
        self._output_summaries.clear()
        install(self, prepared)
        self.document.path = Path(path).resolve()
        self.document.revision = draft.revision
        self.document.untrusted_recovery = False
        self.document.mark_clean()
        self.document.remember_recent()
        return draft

    def open_reference_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Reference Workspace", str(self.document.path or ""),
                                              "Reference workspaces (*.ref);;Backups (*.bak)")
        if path:
            try:
                self.load_workspace(path)
            except (KeyError, OSError, TypeError, ValueError) as error:
                QMessageBox.warning(self, "Cannot open Reference Workspace", str(error))

    def _build_source_panel(self):
        panel = QFrame(objectName="panel")
        panel.setMinimumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(11)
        layout.addWidget(help_title_label(
            "Vendor",
            "Choose one vendor format and one or more source files. Folder selection scans subfolders and skips prior output folders.",
        ))

        self.vendor = QComboBox(objectName="referenceVendor")
        self.vendor.addItems(VENDOR_DETAILS)
        self.vendor.currentTextChanged.connect(self._vendor_changed)
        layout.addWidget(self.vendor)

        source_actions = QHBoxLayout()
        self.files_button = QPushButton("Choose files…")
        self.files_button.clicked.connect(self.choose_files)
        self.folder_button = QPushButton("Choose folders…")
        self.folder_button.clicked.connect(self.choose_folder)
        source_actions.addWidget(self.files_button)
        source_actions.addWidget(self.folder_button)
        layout.addLayout(source_actions)

        self.source_summary = QLabel("No source files selected", objectName="accent")
        layout.addWidget(self.source_summary)
        self.source_list = CheckableListWidget(objectName="referenceSourceList")
        self.source_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.source_list.setMinimumHeight(130)
        self.source_list.itemChanged.connect(self._update_source_selection)
        layout.addWidget(self.source_list, 1)

        output_row = QHBoxLayout()
        output_text = QLabel("OUTPUT LOCATION", objectName="eyebrow")
        output_row.addWidget(output_text)
        output_row.addStretch()
        change_output = QPushButton("Change…", objectName="link")
        change_output.clicked.connect(self.choose_output)
        output_row.addWidget(change_output)
        layout.addLayout(output_row)
        self.output_path = QLineEdit()
        self.output_path.setReadOnly(True)
        self.output_path.setPlaceholderText("Defaults to the selected source location")
        layout.addWidget(self.output_path)

        self.progress = QProgressBar(objectName="referenceProgress")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)
        self.status = QLabel("Choose source files to begin.", objectName="muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.run_button = QPushButton("Run summary", objectName="primary")
        self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.run_button, 1)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)
        return panel

    def _build_result_panel(self):
        panel = QFrame(objectName="panel")
        panel.setMinimumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        ref_row = QHBoxLayout()
        label = help_title_label('Output', 'Select a Ref measurement CSV. Measurement rows are intentionally not previewed here.')
        self.summary_output_picker = ScrollSafeComboBox()
        self.summary_output_picker.setSizeAdjustPolicy(ScrollSafeComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.summary_output_picker.setAccessibleName('Output file')
        self.summary_output_picker.setPlaceholderText('Select an output file')
        self.summary_output_picker.currentIndexChanged.connect(self._select_output_file)
        label.setBuddy(self.summary_output_picker)
        ref_row.addWidget(label)
        ref_row.addWidget(self.summary_output_picker, 1)
        self.load_files_button = QPushButton('Load files…')
        self.load_files_button.setToolTip('Load one or more existing Ref output CSVs.')
        self.load_files_button.clicked.connect(self.choose_output_files)
        ref_row.addWidget(self.load_files_button)
        self.load_folders_button = QPushButton('Load folders…')
        self.load_folders_button.setToolTip('Load existing Ref output CSVs from one or more folders.')
        ref_row.addWidget(self.load_folders_button)
        layout.addLayout(ref_row)

        self.result_path = QLineEdit()
        self.result_path.setReadOnly(True)
        self.result_path.setAccessibleName('Output directory')
        self.result_path.setPlaceholderText('Output directory')
        layout.addWidget(self.result_path)

        self.metadata_preview = _SummaryBrowser(objectName='referenceMetadata')
        self.metadata_preview.setAccessibleName('Reference metadata summary')
        self.metadata_preview.setOpenLinks(False)
        self.metadata_preview.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.metadata_preview.setPlaceholderText('Run a summary or load a Ref output to view its metadata.')
        self.metadata_preview.setMinimumHeight(175)
        layout.addWidget(self.metadata_preview, 1)

        file_actions = QHBoxLayout()
        file_actions.addWidget(QLabel('OUTPUT FILES', objectName='eyebrow'))
        file_actions.addStretch()
        self.open_file_button = QPushButton('Open file', objectName='link')
        self.open_file_button.setEnabled(False)
        self.open_file_button.clicked.connect(self.open_output_file)
        file_actions.addWidget(self.open_file_button)
        self.open_folder_button = QPushButton('Open folder', objectName='link')
        self.open_folder_button.clicked.connect(self.open_output_folder)
        file_actions.addWidget(self.open_folder_button)
        layout.addLayout(file_actions)
        self.output_list = QListWidget(objectName='referenceOutputList')
        self.output_list.setMinimumHeight(76)
        self.output_list.setMaximumHeight(108)
        self.output_list.itemClicked.connect(self._select_listed_output)
        self.output_list.itemDoubleClicked.connect(lambda item: self.open_output_file())
        self.output_list.currentItemChanged.connect(lambda item, previous: self.open_file_button.setEnabled(item is not None))
        layout.addWidget(self.output_list)

        layout.addWidget(QLabel("CHECKS", objectName="eyebrow"))
        self.issue_summary = QPlainTextEdit(objectName="referenceIssues")
        self.issue_summary.setReadOnly(True)
        self.issue_summary.setPlaceholderText("No run yet")
        self.issue_summary.setMaximumHeight(88)
        layout.addWidget(self.issue_summary)
        return panel

    def _vendor_changed(self):
        detail = VENDOR_DETAILS[self.vendor_name]
        self.vendor.setToolTip(detail["description"])
        if self.files:
            self.set_source_files(())
        self._clear_result()
        self._update_actions()

    def _clear_result(self):
        self.report = None
        self.issue_summary.clear()
        self.issue_summary.setPlaceholderText("No run yet")
        self._show_output_summary(self.alignment._dataset.path)

    def set_source_files(self, files):
        allowed = VENDOR_DETAILS[self.vendor_name]["extensions"]
        unique = tuple(sorted(
            {Path(path).resolve() for path in files if Path(path).suffix.casefold() in allowed},
            key=lambda path: str(path).casefold(),
        ))
        self.files = unique
        with QSignalBlocker(self.source_list):
            self.source_list.clear()
            for path in unique:
                item = QListWidgetItem(str(path))
                item.setToolTip(str(path))
                item.setCheckState(Qt.CheckState.Checked)
                self.source_list.addItem(item)
        if unique and self.output_parent is None:
            # The first selected file is a safe writable default; a common path
            # can otherwise collapse to a drive root when folders differ.
            self.output_parent = unique[0].parent
        self.output_path.setText(str(self.output_parent) if self.output_parent else "")
        self._clear_result()
        self._update_source_selection()

    def selected_source_files(self):
        return tuple(path for index, path in enumerate(self.files)
                     if self.source_list.item(index).checkState() == Qt.CheckState.Checked)

    def _update_source_selection(self, *_):
        selected = len(self.selected_source_files())
        total = len(self.files)
        if total and selected != total:
            self.source_summary.setText(f"{selected} / {total} source files selected")
        elif selected:
            self.source_summary.setText(f"{selected} source {'file' if selected == 1 else 'files'} selected")
        else:
            self.source_summary.setText("No source files selected")
        if self.report is None:
            self.status.setText("Ready to summarize." if selected else "Choose source files to begin.")
        self._update_actions()

    def choose_files(self):
        detail = VENDOR_DETAILS[self.vendor_name]
        paths = choose_files(
            self, f"Choose {self.vendor_name} source files", detail["filter"],
            directory=self.files[0].parent if self.files else self.output_parent,
        )
        if paths:
            self.output_parent = None
            self.set_source_files(paths)

    def choose_folder(self):
        folders = choose_folders(self, f"Choose {self.vendor_name} source folders", directory=self.output_parent)
        if not folders:
            return
        try:
            self.set_source_folders(folders)
        except Exception as error:
            QMessageBox.warning(self, "Cannot scan folders", str(error))

    def set_source_folders(self, folders):
        folders = tuple(dict.fromkeys(Path(folder).resolve() for folder in folders))
        if not folders:
            return
        files = [path for folder in folders for path in scan_reference_files(folder)]
        if not files:
            QMessageBox.information(self, "No source files", "No CSV or Excel (.xlsx/.xlsm) files were found in the selected folders.")
            return
        self.output_parent = folders[0]
        self.set_source_files(files)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose output parent folder", str(self.output_parent or ""),
        )
        if folder:
            self.output_parent = Path(folder)
            self.output_path.setText(folder)

    def choose_output_files(self):
        paths = choose_files(self, 'Load Ref output files', 'Ref output CSVs (*.csv)',
                             directory=self.result_path.text())
        if paths:
            self.alignment.add_output_files(paths)

    def _update_actions(self):
        busy = self.worker is not None
        for action in (self.open_reference_action, self.save_reference_action, self.save_reference_as_action):
            action.setEnabled(not busy)
        self.vendor.setEnabled(not busy)
        self.files_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
        self.load_files_button.setEnabled(not busy)
        self.load_folders_button.setEnabled(not busy)
        self.source_list.setEnabled(not busy)
        self.run_button.setEnabled(bool(self.selected_source_files() and self.output_parent) and not busy)
        self.cancel_button.setEnabled(busy)

    def run(self):
        selected = self.selected_source_files()
        if self.worker is not None or not selected or self.output_parent is None:
            return
        self._clear_result()
        request = ReferenceSummaryRequest(self.vendor_name, selected, self.output_parent)
        worker = self.worker = _SummaryWorker(request, self)
        worker.progress.connect(self._progress)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._worker_finished)
        self.progress.setRange(0, max(1, len(selected)))
        self.progress.setValue(0)
        self.status.setText(f"Starting {self.vendor_name} summary…")
        self._update_actions()
        worker.start()

    def _progress(self, current, total, message):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)
        self.status.setText(message)

    def _completed(self, report):
        self._show_report(report)
        self.alignment.set_report(report)

    def _show_report(self, report):
        self.report = report
        result = report.result
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status.setText("Summary complete. Source files were not modified.")
        self._show_issues(report.issue_lines)
        overview = result.output_dir / BATCH_SUMMARY
        self._summary_path = None
        self.metadata_preview.clear()
        if overview in report.output_files and filesystem_path(overview).is_file():
            try:
                self._show_html_summary(overview)
            except (OSError, UnicodeError) as error:
                self.statusBar().showMessage(f'Could not read the summary: {error}', 10000)
        self._refresh_output_picker(self._summary_path)
        self.document.identity_timer.start()

    def _show_issues(self, issues):
        self.issue_summary.setPlainText("\n".join(issues) if issues else "No issues reported")

    def _failed(self, message):
        self.status.setText("Summary failed. No incomplete output was published.")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        QMessageBox.warning(self, "Reference Summarizer failed", message)

    def _cancelled(self):
        self.status.setText("Cancelled. No incomplete output was published.")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

    def _worker_finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self._update_actions()
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()

    def cancel(self):
        if self.worker is not None:
            self.status.setText("Cancelling after the current parse step…")
            self.worker.requestInterruption()

    def open_output_folder(self):
        if directory := self.result_path.text():
            QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def open_output_file(self):
        item = self.output_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        suffix = path.suffix.casefold()
        if suffix in ('.html', '.htm'):
            self._select_listed_output(item)
            self.tabs.setCurrentIndex(0)
        elif suffix in ('.csv', '.xlsx', '.txt'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.statusBar().showMessage("This file type cannot be opened from Reference Summary.", 10000)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self._close_when_finished = True
            self.cancel()
            event.ignore()
            return
        if not self.document.confirm_close():
            event.ignore()
            return
        if self._analysis is not None and not self._analysis.close():
            event.ignore()
            return
        self.document.closed()
        super().closeEvent(event)


def _reference_save_filename(parent, suggested_name):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Name Reference Workspace")
    form = QFormLayout(dialog)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    timestamp = QDateTimeEdit(QDateTime.currentDateTime(), dialog)
    timestamp.setDisplayFormat("yyyy-MM-dd HH:mm")
    timestamp.setCalendarPopup(True)
    form.addRow("Date and Time", timestamp)

    base = Path(suggested_name).stem
    preview = QLabel(dialog)
    preview.setObjectName("FileNamePreview")
    preview.setTextFormat(Qt.TextFormat.PlainText)
    preview.setWordWrap(True)
    form.addRow("File Name", preview)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dialog,
    )
    proceed = buttons.button(QDialogButtonBox.StandardButton.Ok)
    proceed.setText("Continue")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    def update_preview():
        stamp = timestamp.dateTime().toString("yyyyMMdd_HHmm")
        filename = f"{base}_{stamp}.ref"
        message = ""
        if not base or any(re.search(r'[<>:"/\\|?*\x00-\x1f]', part) for part in (base, stamp)):
            message = "Remove characters that Windows does not allow in file names."
        elif PureWindowsPath(filename).is_reserved():
            message = "Choose a file name that Windows does not reserve."
        preview.setText(message or filename)
        proceed.setEnabled(not message)

    timestamp.dateTimeChanged.connect(update_preview)
    update_preview()
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return preview.text()
        return None
    finally:
        dialog.deleteLater()


__all__ = [
    "ReferenceSummaryReport",
    "ReferenceSummaryRequest",
    "ReferenceSummaryWindow",
    "run_reference_summary",
]

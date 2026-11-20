"""PyQt6 workflow for consolidating reference exports from four vendors."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, help_title_label
from .cdsem1 import merge_cdsem1
from .reference_merge import merge, scan_reference_files
from .reference_input import SOURCE_EXTENSIONS
from .file_dialogs import choose_files, choose_folders
from .file_paths import filesystem_path
from .widgets import CheckableListWidget


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


def _issue_lines(output_dir: Path, limit: int = 6) -> tuple[str, ...]:
    """Return a compact issue digest; detailed rows stay in the exported CSV."""
    report = filesystem_path(output_dir.resolve() / "_issues.csv")
    if not report.is_file():
        return ()
    lines = []
    total = 0
    with report.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            total += 1
            if len(lines) >= limit:
                continue
            source = Path(row.get("File", "")).name or "Unknown file"
            detail = row.get("Issue") or row.get("Detail") or "Unspecified issue"
            kind = row.get("Kind", "").strip()
            lines.append(f"{source} — {kind + ': ' if kind else ''}{detail}")
    if total > limit:
        lines.append(f"… {total - limit} more; open _issues.csv for details")
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
        issue_lines=_issue_lines(output_dir),
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


def _metric(title: str):
    frame = QFrame(objectName="summaryMetric")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(3)
    label = QLabel(title.upper(), objectName="eyebrow")
    value = QLabel("—", objectName="detailValue")
    value.setWordWrap(True)
    value.setMinimumHeight(36)
    value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label)
    layout.addWidget(value)
    return frame, value


class ReferenceSummaryWindow(QMainWindow):
    """Select vendor exports, run in the background, and review a compact report."""

    workspace_type = "reference_summary"

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
        self._summary_path = None
        self._suggested_ref_name = 'Reference.ref'
        self._close_when_finished = False
        self._build_ui()
        self._vendor_changed()
        from .settings import apply_theme
        apply_theme(self)
        from .workspace_document import WkbDocument
        self.document = WkbDocument(self)
        self.alignment.alignment_changed.connect(self.document.identity_timer.start)
        self.source_list.itemChanged.connect(lambda *_: self.document.identity_timer.start())
        self.output_path.textChanged.connect(lambda *_: self.document.identity_timer.start())
        self.tabs.currentChanged.connect(lambda *_: self.document.identity_timer.start())
        for button in self.trend_page.order_buttons.values():
            button.clicked.connect(lambda *_: self.document.identity_timer.start())
        self.document.mark_clean()

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
        from .reference_analysis_ui import ReferenceAnalysisPages
        self.tabs = QTabWidget()
        self.tabs.addTab(root, '1. Summary')
        self.trend_page = CoordinateTrendPage()
        self.alignment = ReferenceAlignmentPage(self.trend_page)
        self.tabs.addTab(self.alignment, '2. Wafer Alignment')
        self.tabs.addTab(self.trend_page, '3. XY Bias')
        self.setCentralWidget(self.tabs)
        self.analysis = ReferenceAnalysisPages(self.tabs, self.alignment)
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

        cancel_action = QAction(self)
        cancel_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        cancel_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        cancel_action.triggered.connect(self.cancel)
        self.addAction(cancel_action)

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
        from .reference_metadata import suggested_filename, summary_text, write_summary
        if self.worker is not None:
            raise ValueError("Wait for the current summary to finish.")
        cache_available_outputs(self.alignment)
        vendor, fields, outputs, sources = self._summary_metadata()
        self._suggested_ref_name = suggested_filename(vendor, fields, sources,
                                                       [metadata for _, metadata in outputs])
        previous = self._source_metadata
        cached = {**previous.get(vendor, {}), **{name: fields for name, fields in sources.items() if fields}}
        self._source_metadata = {**previous, vendor: cached} if cached else previous
        saved = None
        try:
            saved = self.document.save(path, save_as=save_as)
        finally:
            if saved is None:
                self._source_metadata = previous
        if saved is not None:
            self._summary_path = None
            try:
                self._summary_path = write_summary(saved, summary_text(vendor, saved, outputs, sources))
            except OSError as error:
                self.statusBar().showMessage(f"Saved {saved.name}. Summary could not be written: {error}", 10000)
        return saved

    def save_wkb(self, *, save_as=False):
        try:
            saved = self.save_reference(save_as=save_as)
            if saved and self._summary_path and QApplication.platformName() != 'offscreen':
                self.show_summary()
            return saved
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot save Reference Workspace", str(error))
            return None

    def show_summary(self):
        from .matching_window import reveal_path_in_folder
        from .reference_metadata import MARKER

        if not self.document.path:
            return
        workspace = self.document.path
        try:
            prefix = workspace.stem + '.summary'
            candidates = [workspace.with_suffix('.txt'), *sorted(path for path in workspace.parent.iterdir()
                          if path.name.startswith(prefix) and path.suffix == '.txt')]
            for path in (self._summary_path, *candidates):
                if path is None or not path.is_file():
                    continue
                with path.open(encoding='utf-8-sig', errors='replace') as stream:
                    if stream.readline().strip() != MARKER:
                        continue
                reveal_path_in_folder(path)
                return
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
        install(self, prepared)
        self._summary_path = None
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
        layout.addWidget(help_title_label(
            "Run summary",
            "Shows counts, warnings and generated files. Measurement rows are intentionally not previewed here.",
        ))

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(10)
        self.metric_values = {}
        for index, key in enumerate(("Files", "Rows kept", "Channels / MP", "Issues")):
            frame, value = _metric(key)
            self.metric_values[key] = value
            metrics.addWidget(frame, index // 2, index % 2)
        layout.addLayout(metrics)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("OUTPUT", objectName="eyebrow"))
        folder_row.addStretch()
        self.open_folder_button = QPushButton("Open folder", objectName="link")
        self.open_folder_button.clicked.connect(self.open_output_folder)
        self.open_folder_button.setEnabled(False)
        folder_row.addWidget(self.open_folder_button)
        layout.addLayout(folder_row)
        self.result_path = QLineEdit()
        self.result_path.setReadOnly(True)
        self.result_path.setPlaceholderText("Output appears after a successful run")
        layout.addWidget(self.result_path)

        layout.addWidget(QLabel("GENERATED FILES", objectName="eyebrow"))
        self.output_list = QListWidget(objectName="referenceOutputList")
        self.output_list.setMinimumHeight(155)
        self.output_list.itemDoubleClicked.connect(self.open_output_file)
        layout.addWidget(self.output_list, 1)

        layout.addWidget(QLabel("CHECKS", objectName="eyebrow"))
        self.issue_summary = QPlainTextEdit(objectName="referenceIssues")
        self.issue_summary.setReadOnly(True)
        self.issue_summary.setPlaceholderText("No run yet")
        self.issue_summary.setMaximumHeight(130)
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
        self.result_path.clear()
        self.output_list.clear()
        self.issue_summary.clear()
        self.issue_summary.setPlaceholderText("No run yet")
        self.open_folder_button.setEnabled(False)
        for value in self.metric_values.values():
            value.setText("—")

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

    def _update_actions(self):
        busy = self.worker is not None
        for action in (self.open_reference_action, self.save_reference_action, self.save_reference_as_action):
            action.setEnabled(not busy)
        self.vendor.setEnabled(not busy)
        self.files_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
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
        self.alignment.set_report(report)
        self._show_report(report)

    def _show_report(self, report):
        self.report = report
        result = report.result
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status.setText("Summary complete. Source files were not modified.")
        self.metric_values["Files"].setText(
            f"{result.parsed_files} / {len(report.request.files)}"
        )
        self.metric_values["Rows kept"].setText(
            f"{result.kept_rows:,} kept\n{result.duplicates:,} duplicates removed"
        )
        if report.request.vendor == "CDSEM1":
            channel_text = f"{result.site_count:,} chips  ·  {result.mp_count:,} MP groups"
        else:
            channel_text = f"{result.channel_count:,} channel{'s' if result.channel_count != 1 else ''}"
        self.metric_values["Channels / MP"].setText(channel_text)
        self.metric_values["Issues"].setText(str(result.error_count))
        self.result_path.setText(str(result.output_dir))
        self.open_folder_button.setEnabled(True)
        self.output_list.clear()
        for path in report.output_files:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(f"Double-click to open\n{path}")
            self.output_list.addItem(item)
        if report.issue_lines:
            self.issue_summary.setPlainText("\n".join(report.issue_lines))
        else:
            self.issue_summary.setPlainText("No issues reported")
        self.document.identity_timer.start()

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
        if self.report is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report.result.output_dir)))

    def open_output_file(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self._close_when_finished = True
            self.cancel()
            event.ignore()
            return
        if not self.document.confirm_close():
            event.ignore()
            return
        self.analysis.document.force_close = True
        if not self.analysis.close():
            event.ignore()
            return
        self.document.closed()
        super().closeEvent(event)


__all__ = [
    "ReferenceSummaryReport",
    "ReferenceSummaryRequest",
    "ReferenceSummaryWindow",
    "run_reference_summary",
]

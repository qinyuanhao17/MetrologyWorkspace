"""PyQt6 workflow for consolidating reference exports from four vendors."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QTreeView,
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
from .cdsem1 import merge_cdsem1, scan_workbooks
from .reference_merge import merge, scan_csv
from .file_paths import filesystem_path


VENDOR_DETAILS = {
    "NOVA": {
        "filter": "CSV files (*.csv)",
        "extensions": {".csv"},
        "description": "Combine NOVA tables, remove repeated headers, consolidate _LBH flags and de-duplicate complete rows.",
    },
    "PMISH": {
        "filter": "CSV files (*.csv)",
        "extensions": {".csv"},
        "description": "Split PMISH blocks by Recipe, Metrology unit and AzimuthAngle, preserving source values and units.",
    },
    "KLA": {
        "filter": "CSV files (*.csv)",
        "extensions": {".csv"},
        "description": "Split KLA Offline blocks by TestID and TestLabel, retaining Slot as the cross-vendor PadName.",
    },
    "CDSEM1": {
        "filter": "Excel workbooks (*.xlsx *.xlsm)",
        "extensions": {".xlsx", ".xlsm"},
        "description": "Read only the first sheet, keep ACD_No=CD, and export one chip-by-MP workbook per source file.",
    },
}


class _SourceFoldersDialog(QFileDialog):
    """Qt's directory browser with multi-selection and no navigation on Accept."""

    def __init__(self, parent, title):
        super().__init__(parent,title)
        self.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        self.setOption(QFileDialog.Option.ShowDirsOnly,True)
        self.setFileMode(QFileDialog.FileMode.Directory)
        self.folders = ()
        for view in self.findChildren(QListView) + self.findChildren(QTreeView):
            if view.objectName() in ('listView','treeView'):
                view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def accept(self):
        selected = []
        for view in self.findChildren(QListView) + self.findChildren(QTreeView):
            if view.objectName() not in ('listView','treeView'):
                continue
            model = view.model()
            if hasattr(model,'filePath'):
                selected.extend(model.filePath(index) for index in view.selectionModel().selectedRows(0))
        paths = selected or self.selectedFiles()
        self.folders = tuple(dict.fromkeys(Path(path).resolve() for path in paths if Path(path).is_dir()))
        if self.folders:
            QDialog.accept(self)


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("referenceSummaryWindow")
        self.setWindowTitle("Reference Summary")
        fit_window_to_screen(self, (1180, 790), minimum=(900, 620))
        self.files: tuple[Path, ...] = ()
        self.output_parent: Path | None = None
        self.worker: _SummaryWorker | None = None
        self.report: ReferenceSummaryReport | None = None
        self._close_when_finished = False
        self._build_ui()
        self._vendor_changed()
        from .settings import apply_theme
        apply_theme(self)

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
        self.tabs.addTab(self.alignment, '2. Wafer Alignment')
        self.tabs.addTab(self.trend_page, '3. XY Bias Trends')
        self.alignment.plotted.connect(lambda: self.tabs.setCurrentIndex(2))
        self.setCentralWidget(self.tabs)

        cancel_action = QAction(self)
        cancel_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        cancel_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        cancel_action.triggered.connect(self.cancel)
        self.addAction(cancel_action)

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
        self.source_list = QListWidget(objectName="referenceSourceList")
        self.source_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.source_list.setMinimumHeight(130)
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
        self.source_list.clear()
        for path in unique:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            self.source_list.addItem(item)
        noun = "workbook" if self.vendor_name == "CDSEM1" else "CSV file"
        self.source_summary.setText(
            f"{len(unique)} {noun}{'' if len(unique) == 1 else 's'} selected"
            if unique else "No source files selected"
        )
        if unique and self.output_parent is None:
            # The first selected file is a safe writable default; a common path
            # can otherwise collapse to a drive root when folders differ.
            self.output_parent = unique[0].parent
        self.output_path.setText(str(self.output_parent) if self.output_parent else "")
        self.status.setText("Ready to summarize." if unique else "Choose source files to begin.")
        self._clear_result()
        self._update_actions()

    def choose_files(self):
        detail = VENDOR_DETAILS[self.vendor_name]
        paths, _ = QFileDialog.getOpenFileNames(
            self, f"Choose {self.vendor_name} source files", "", detail["filter"],
        )
        if paths:
            self.output_parent = None
            self.set_source_files(paths)

    def choose_folder(self):
        dialog = _SourceFoldersDialog(self,f"Choose {self.vendor_name} source folders")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.set_source_folders(dialog.folders)
        except Exception as error:
            QMessageBox.warning(self, "Cannot scan folders", str(error))

    def set_source_folders(self, folders):
        folders = tuple(dict.fromkeys(Path(folder).resolve() for folder in folders))
        if not folders:
            return
        scan = scan_workbooks if self.vendor_name == 'CDSEM1' else scan_csv
        files = [path for folder in folders for path in scan(folder)]
        if not files:
            kind = "Excel workbooks" if self.vendor_name == "CDSEM1" else "CSV files"
            QMessageBox.information(self, "No source files", f"No {kind} were found in the selected folders.")
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
        self.vendor.setEnabled(not busy)
        self.files_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
        self.run_button.setEnabled(bool(self.files and self.output_parent) and not busy)
        self.cancel_button.setEnabled(busy)

    def run(self):
        if self.worker is not None or not self.files or self.output_parent is None:
            return
        self._clear_result()
        request = ReferenceSummaryRequest(self.vendor_name, self.files, self.output_parent)
        worker = self.worker = _SummaryWorker(request, self)
        worker.progress.connect(self._progress)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._worker_finished)
        self.progress.setRange(0, max(1, len(self.files)))
        self.progress.setValue(0)
        self.status.setText(f"Starting {self.vendor_name} summary…")
        self._update_actions()
        worker.start()

    def _progress(self, current, total, message):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)
        self.status.setText(message)

    def _completed(self, report):
        self.report = report
        self.alignment.set_report(report)
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

    def _failed(self, message):
        self.status.setText("Summary failed. No incomplete output was published.")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        QMessageBox.warning(self, "Reference Summary failed", message)

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
        super().closeEvent(event)


__all__ = [
    "ReferenceSummaryReport",
    "ReferenceSummaryRequest",
    "ReferenceSummaryWindow",
    "run_reference_summary",
]

"""Summarize REF: themed, independent batch-import and export window."""
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .appearance import fit_window_to_screen
from .ref_summary import export_ref_summary, summarize_ref
from .settings import apply_theme


class RefSummaryWorker(QThread):
    progress = pyqtSignal(int, int, str)

    def __init__(self, operation, arguments, parent):
        super().__init__(parent)
        self.operation, self.arguments = operation, arguments
        self.result, self.error, self.cancelled = None, "", False

    def run(self):
        try:
            function = summarize_ref if self.operation == "parse" else export_ref_summary
            self.result = function(*self.arguments, cancelled=self.isInterruptionRequested,
                                   progress=self.progress.emit)
        except InterruptedError:
            self.cancelled = True
        except Exception as error:
            self.error = str(error)


class RefSummaryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.summary = None
        self.worker = None
        self.directory = ""
        self.last_directory = str(Path.cwd())
        self._close_requested = False
        self._build_ui()
        self.setWindowTitle("Summarize REF")
        fit_window_to_screen(self, (1200, 820), minimum=(850, 580))
        apply_theme(self)
        self.statusBar().showMessage("Choose a vendor and a REF data folder to begin.")

    @staticmethod
    def _card():
        card = QFrame(objectName="componentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        return card, layout

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)
        controls, tools = self._card()
        tools.addWidget(QLabel("Summarize REF", objectName="panelTitle"))
        guidance = QLabel("Combine KLA, NOVA or PMISH REF files into one Excel workbook. "
                          "CSV and TXT files in subfolders are included.", objectName="hint")
        guidance.setWordWrap(True)
        tools.addWidget(guidance)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Vendor"))
        self.vendor_combo = QComboBox()
        self.vendor_combo.addItems(["KLA", "NOVA", "PMISH"])
        self.vendor_combo.setMinimumWidth(110)
        source_row.addWidget(self.vendor_combo)
        source_row.addSpacing(12)
        source_row.addWidget(QLabel("Data folder"))
        self.folder_path = QLineEdit()
        self.folder_path.setReadOnly(True)
        self.folder_path.setPlaceholderText("Choose a REF data folder…")
        source_row.addWidget(self.folder_path, 1)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.browse_folder)
        source_row.addWidget(self.browse_button)
        tools.addLayout(source_row)

        actions = QHBoxLayout()
        self.parse_button = QPushButton("Parse REF files", objectName="primary")
        self.parse_button.clicked.connect(self.start_parse)
        self.export_button = QPushButton("Export summary Excel…")
        self.export_button.clicked.connect(self.start_export)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_job)
        for button in (self.parse_button, self.export_button, self.cancel_button):
            actions.addWidget(button)
            button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumWidth(140)
        self.progress_bar.hide()
        actions.addWidget(self.progress_bar, 1)
        actions.addStretch()
        tools.addLayout(actions)
        self.counts_label = QLabel("No data parsed", objectName="hint")
        tools.addWidget(self.counts_label)
        layout.addWidget(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        preview, preview_layout = self._card()
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Data preview", objectName="panelTitle"))
        self.preview_label = QLabel("First 100 rows · export includes all records", objectName="hint")
        heading.addWidget(self.preview_label)
        heading.addStretch()
        preview_layout.addLayout(heading)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(150)
        preview_layout.addWidget(self.table, 1)
        splitter.addWidget(preview)

        log_card, log_layout = self._card()
        log_layout.addWidget(QLabel("Parsing and export log", objectName="panelTitle"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setPlaceholderText("File progress and parsing errors appear here.")
        log_layout.addWidget(self.log, 1)
        splitter.addWidget(log_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 160])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.vendor_combo.currentTextChanged.connect(self._clear_summary)

    def _clear_summary(self, *_):
        self.summary = None
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.counts_label.setText("No data parsed")
        self.preview_label.setText("First 100 rows · export includes all records")
        self.export_button.setEnabled(False)
        self.log.clear()
        self.statusBar().showMessage("Ready to parse the selected vendor and folder.")

    def browse_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose REF data folder", self.last_directory)
        if not directory:
            return
        self.directory = self.last_directory = directory
        self.folder_path.setText(directory)
        self.folder_path.setToolTip(directory)
        self._clear_summary()
        self.parse_button.setEnabled(True)

    def _set_busy(self, busy):
        self.vendor_combo.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.parse_button.setEnabled(not busy and bool(self.directory))
        self.export_button.setEnabled(not busy and self.summary is not None)
        self.cancel_button.setEnabled(busy)
        self.progress_bar.setVisible(busy)

    def _start_job(self, operation, arguments):
        self.progress_bar.setRange(0, 0)
        self.worker = RefSummaryWorker(operation, arguments, self)
        self.worker.progress.connect(self._show_progress)
        self.worker.finished.connect(self._job_finished)
        self._set_busy(True)
        self.worker.start()

    def start_parse(self):
        if self.worker is not None:
            return
        if not Path(self.directory).is_dir():
            QMessageBox.warning(self, "Cannot parse REF", "Choose an existing REF data folder first.")
            return
        self._clear_summary()
        vendor = self.vendor_combo.currentText()
        self.log.appendPlainText(f"{vendor} · {self.directory}")
        self.statusBar().showMessage("Scanning REF data files…")
        self._start_job("parse", (self.directory, vendor))

    def start_export(self):
        if self.worker is not None or self.summary is None:
            return
        default = Path(self.last_directory) / f"{self.summary.vendor}_REF_Summary.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export REF summary", str(default), "Excel workbook (*.xlsx)")
        if not path:
            return
        self.last_directory = str(Path(path).parent)
        self.statusBar().showMessage("Writing REF summary Excel…")
        self._start_job("export", (self.summary, path))

    def _show_progress(self, done, total, message):
        if self.worker is None or self.worker.isInterruptionRequested():
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.log.appendPlainText(message)
        self.statusBar().showMessage(f"{done:,} / {total:,} · {message}")

    def _show_summary(self, result):
        self.counts_label.setText(
            f"Files: {result.file_count:,}  ·  Parsed: {result.successful_files:,}  ·  "
            f"Skipped: {len(result.errors):,}  ·  Records: {len(result.frame):,}  ·  Wafers: {result.wafer_count:,}"
        )
        if result.frame.empty:
            self.statusBar().showMessage("No files could be parsed. See the log for details.")
            QMessageBox.warning(self, "No REF data parsed", "No files could be parsed successfully. See the parsing log for details.")
            return
        self.summary = result
        frame = result.frame.head(100).fillna("")
        self.table.setColumnCount(len(frame.columns))
        self.table.setHorizontalHeaderLabels([str(column) for column in frame.columns])
        self.table.setRowCount(len(frame))
        for row, values in enumerate(frame.itertuples(index=False, name=None)):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        for column in range(len(frame.columns)):
            self.table.setColumnWidth(column, max(85, min(360, self.table.columnWidth(column))))
        self.preview_label.setText(f"Showing {len(frame):,} of {len(result.frame):,} rows · export includes all records")
        message = f"Parsing complete · {len(result.frame):,} records · {len(result.errors):,} files skipped"
        self.log.appendPlainText(message)
        if result.by_pad is not None:
            self.log.appendPlainText(f"PAD worksheets: {', '.join(map(str, result.by_pad))}")
        self.statusBar().showMessage(message)

    def _job_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        if self._close_requested:
            QTimer.singleShot(0, self.close)
            return
        try:
            if worker.cancelled:
                self.log.appendPlainText("Cancelled. Incomplete results were discarded.")
                self.statusBar().showMessage("Cancelled")
            elif worker.error:
                self.log.appendPlainText(f"Failed · {worker.error}")
                self.statusBar().showMessage(worker.error)
                QMessageBox.warning(self, "Cannot summarize REF" if worker.operation == "parse" else "Cannot export REF", worker.error)
            elif worker.operation == "parse":
                self._show_summary(worker.result)
            else:
                message = f"Saved · {worker.result}"
                self.log.appendPlainText(message)
                self.statusBar().showMessage(message)
                QMessageBox.information(self, "REF summary exported", f"Summary saved to:\n{worker.result}")
        finally:
            self._set_busy(False)

    def cancel_job(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling after the current file or worksheet…")

    def closeEvent(self, event):
        if self.worker is not None:
            self._close_requested = True
            self.cancel_job()
            event.ignore()
        else:
            event.accept()

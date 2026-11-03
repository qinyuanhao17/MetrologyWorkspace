"""Background original-SME copying with GUI retry/skip decisions and a report."""
from pathlib import Path
from html import escape
from threading import Condition
from time import monotonic

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from .appearance import fit_window_to_screen
from .settings import apply_theme
from .spectra_export import export_spectra


class SpectraExportThread(QThread):
    progress = pyqtSignal(int, int, str)
    issue = pyqtSignal(str, str)
    completed = pyqtSignal(object)

    def __init__(self, paths, destination, parent=None):
        super().__init__(parent)
        self.paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
        self.destination = Path(destination)
        self._condition = Condition()
        self._choice = None

    def respond(self, choice):
        with self._condition:
            self._choice = choice
            self._condition.notify_all()

    def run(self):
        skipped, unresolved = [], {}
        retries = 0
        last_progress = 0.0
        def decide(path, error):
            nonlocal retries
            unresolved[str(path)] = str(error)
            with self._condition:
                self._choice = None
                self.issue.emit(str(path), str(error))
                while self._choice is None and not self.isInterruptionRequested():
                    self._condition.wait(.1)
                choice = self._choice or "cancel"
            if choice == "skip":
                skipped.append((str(path), str(error)))
            elif choice == "retry":
                retries += 1
            return choice
        def progress(done, total, name):
            nonlocal last_progress
            path = str(self.paths[done - 1])
            if not any(source == path for source, _ in skipped):
                unresolved.pop(path, None)
            now = monotonic()
            if done == total or now - last_progress >= .05:
                self.progress.emit(done, total, name)
                last_progress = now
        exported, error, cancelled = (), "", False
        try:
            exported = export_spectra(self.paths, self.destination, cancelled=self.isInterruptionRequested,
                                      progress=progress, on_error=decide)
        except InterruptedError as caught:
            error, cancelled = str(caught), True
        except Exception as caught:
            error = str(caught)
        message = ("Export cancelled; files copied by this run were removed." if cancelled else
                   f"Export failed: {error}" if error else
                   f"Exported {len(exported)} checked spectra; skipped {len(skipped)}. Folder: {self.destination}")
        message += "\nExport Failed×" if error or cancelled or skipped or unresolved else "\nExport Succeeded√"
        self.completed.emit({"exported": tuple(map(str, exported)), "skipped": tuple(skipped),
                             "unavailable": tuple(unresolved.items()), "retries": retries,
                             "error": error, "cancelled": cancelled, "message": message})


class SpectraExportDialog(QDialog):
    def __init__(self, paths, destination, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Checked Spectra")
        self.setWindowModality(Qt.WindowModality.NonModal)
        fit_window_to_screen(self, (820, 520), minimum=(600, 380))
        apply_theme(self)
        self.report = None
        self.worker = SpectraExportThread(paths, destination, self)
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Copying original SME files…")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.worker.paths))
        layout.addWidget(self.progress)
        self.issue_label = QLabel()
        self.issue_label.setTextFormat(Qt.TextFormat.PlainText)
        self.issue_label.setWordWrap(True)
        layout.addWidget(self.issue_label)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.summary, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.retry_button = QPushButton("Retry")
        self.skip_button = QPushButton("Skip")
        self.close_button = QPushButton("Cancel Export")
        for button in (self.retry_button, self.skip_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.retry_button.clicked.connect(lambda: self._respond("retry"))
        self.skip_button.clicked.connect(lambda: self._respond("skip"))
        self.close_button.clicked.connect(self._cancel_or_close)
        self.retry_button.hide()
        self.skip_button.hide()
        self.worker.progress.connect(self._progress)
        self.worker.issue.connect(self._issue)
        self.worker.completed.connect(self._completed)
        self.worker.finished.connect(self._finished)

    def _progress(self, done, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(f"Copying {done} / {total} · {name}")

    def _issue(self, path, message):
        self.status_label.setText("Original SME could not be copied. Restore access and Retry, or Skip this file.")
        self.issue_label.setText(f"{path}\n{message}")
        self.summary.appendPlainText(f"Could not copy: {path}\n{message}\n")
        self.retry_button.show()
        self.skip_button.show()

    def _respond(self, choice):
        self.retry_button.hide()
        self.skip_button.hide()
        self.issue_label.clear()
        if self.worker is not None:
            self.worker.respond(choice)

    def _completed(self, report):
        self.report = report
        self.retry_button.hide()
        self.skip_button.hide()
        self.issue_label.clear()
        self.status_label.setText(report["message"])
        outcome = "Export Succeeded√" if report["message"].endswith("Export Succeeded√") else "Export Failed×"
        color = "#15803d" if "Succeeded" in outcome else "#dc2626"
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(escape(report["message"]).replace("\n", "<br>").replace(
            outcome, f'<b style="color:{color}">{outcome}</b>'))
        text = [report["message"], f"Retry attempts: {report['retries']}"]
        if report["unavailable"]:
            text.extend(("", "Unavailable / not copied:"))
            for path, error in report["unavailable"]:
                text.extend((path, error, ""))
        else:
            text.append("No unavailable originals remain.")
        self.summary.setPlainText("\n".join(text))
        cursor = self.summary.document().find(outcome)
        emphasis = QTextCharFormat()
        emphasis.setForeground(QColor(color))
        emphasis.setFontWeight(QFont.Weight.Bold)
        cursor.mergeCharFormat(emphasis)
        self.close_button.setText("Close")
        self.close_button.setEnabled(True)

    def _finished(self):
        self.worker = None

    def _cancel_or_close(self):
        if self.worker is not None and self.report is None:
            self.worker.requestInterruption()
            self.close_button.setEnabled(False)
            self.status_label.setText("Cancelling export…")
        else:
            self.accept()

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.requestInterruption()
        super().closeEvent(event)

    def reject(self):
        if self.worker is not None:
            self.worker.requestInterruption()
        super().reject()

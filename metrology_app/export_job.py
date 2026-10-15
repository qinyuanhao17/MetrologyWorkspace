"""Responsive export menus; only detached Python data crosses to the worker."""
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QProgressDialog


class ExportJob(QThread):
    exported = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, path, snapshot, *, matching, native, parent):
        super().__init__(parent)
        self.path, self.snapshot = Path(path).with_suffix(".xlsx"), snapshot
        self.matching, self.native = matching, native
        self.cancelled = Event()

    def run(self):
        try:
            from .analysis_export import append_report
            from .excel_export import save_atomic, style_workbook, write_workbook
            if self.matching:
                write_workbook(self.path, native=self.native,
                               cancelled=self.cancelled.is_set, **self.snapshot)
            else:
                from openpyxl import Workbook
                book = Workbook()
                book.remove(book.active)
                append_report(book, set(), self.snapshot, native=self.native)
                style_workbook(book)
                save_atomic(book, self.path, cancelled=self.cancelled.is_set)
            self.exported.emit(str(self.path))
        except InterruptedError:
            self.failed.emit("Export cancelled")
        except Exception as error:
            self.failed.emit(str(error))


def start_export(window, path, snapshot, *, matching=False, native=True):
    if getattr(window, "_excel_export_job", None) is not None:
        return
    progress = QProgressDialog("Exporting Excel charts…" if native else "Exporting Matplotlib…",
                               "Cancel", 0, 0, window)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    job = ExportJob(path, snapshot, matching=matching, native=native, parent=window)
    window._excel_export_job = job
    actions = (window.export_action, window.images_action) if matching else (window.export_excel_action, window.export_matplotlib_action)
    for action in actions:
        action.setEnabled(False)
    progress.canceled.connect(job.cancelled.set)
    def success(path):
        progress.close()
        window.statusBar().showMessage(f"Exported {Path(path).name}")
        if matching:
            window.result_status.setText(f"Exported {Path(path).name}")
    def failure(message):
        progress.close()
        if message == "Export cancelled":
            window.statusBar().showMessage(message)
        else:
            QMessageBox.warning(window, "Cannot export", message)
    def finished():
        for action in actions:
            action.setEnabled(True)
        window._excel_export_job = None
        progress.deleteLater()
        job.deleteLater()
    job.exported.connect(success)
    job.failed.connect(failure)
    job.finished.connect(finished)
    progress.show()
    job.start()


def finish_export_before_close(window, event):
    """Allow a cancelling writer to close its own temporary file safely."""
    jobs = [getattr(owner, "_excel_export_job", None)
            for owner in (window, *getattr(window, "_stage_windows", ()))]
    jobs = [job for job in jobs if job is not None]
    if not jobs:
        return False
    for job in jobs:
        job.cancelled.set()
        requested = getattr(job, "close_requested", set())
        if id(window) not in requested:
            requested.add(id(window))
            job.close_requested = requested
            if job.isRunning():
                job.finished.connect(window.close)
            else:
                QTimer.singleShot(0, window.close)
    event.ignore()
    return True

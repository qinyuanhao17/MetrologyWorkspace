"""Responsive export menus; only detached Python data crosses to the worker."""
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QProgressDialog


def _write_export(path, snapshot, matching, native, cancelled, progress):
    from .analysis_export import append_report
    from .excel_export import save_atomic, style_workbook, write_workbook
    if matching:
        write_workbook(path, native=native, cancelled=cancelled, progress=progress, **snapshot)
    else:
        from openpyxl import Workbook
        from .export_rendering import rendering_session
        book = Workbook()
        book._export_cancelled, book._export_progress = cancelled, progress
        with rendering_session(book, native=native):
            book.remove(book.active)
            append_report(book, set(), snapshot, native=native)
            style_workbook(book)
            save_atomic(book, path, cancelled=cancelled)


def _export_process(path, snapshot, matching, native, cancelled, messages, settings):
    """Only owned data and an IPC endpoint enter this non-GUI process."""
    try:
        import tempfile
        tempfile.tempdir = str(Path(path).parent)
        import matplotlib
        matplotlib.rcParams.update(settings)
        _write_export(path, snapshot, matching, native, cancelled.is_set,
                      lambda value: messages.send(('status', value)))
        messages.send(('success', str(path)))
    except InterruptedError:
        messages.send(('failed', 'Export cancelled'))
    except Exception as error:
        messages.send(('failed', str(error)))
    finally:
        messages.close()


class ExportJob(QThread):
    exported = pyqtSignal(str)
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, path, snapshot, *, matching, native, parent):
        super().__init__(parent)
        self.path, self.snapshot = Path(path).with_suffix(".xlsx"), snapshot
        self.matching, self.native = matching, native
        self.cancelled = Event()

    def run(self):
        try:
            if self.cancelled.is_set():
                raise InterruptedError('Export cancelled')
            if self.matching:
                cost = sum(len(raw) * len(result.parameter_names)
                           for _book, result, raw, _frames in self.snapshot['stages'])
            else:
                cost = sum(len(frame) for frame in self.snapshot['frames'].values()) * max(1, len(self.snapshot.get('plots', ())))
            if cost >= 10000:
                self._run_process()
                return
            _write_export(self.path, self.snapshot, self.matching, self.native,
                          self.cancelled.is_set, self.status.emit)
            self.exported.emit(str(self.path))
        except InterruptedError:
            self.failed.emit("Export cancelled")
        except Exception as error:
            self.failed.emit(str(error))

    def _run_process(self):
        import os
        from tempfile import TemporaryDirectory
        # The owner can remove this worker's partial files even after a native
        # crash. Never scan/delete another export's temporary siblings.
        with TemporaryDirectory(prefix='.export-job-', dir=self.path.parent) as folder:
            candidate = Path(folder) / self.path.name
            kind, value = self._collect_process(candidate)
            if kind != 'success':
                self.failed.emit(value)
                return
            if self.cancelled.is_set():
                raise InterruptedError('Export cancelled')
            os.replace(candidate, self.path)
        self.exported.emit(str(self.path))

    def _collect_process(self, candidate):
        import matplotlib
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        cancelled = context.Event()
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_export_process,
            args=(candidate, self.snapshot, self.matching, self.native, cancelled, sender, dict(matplotlib.rcParams)))
        outcome = None
        started = False
        try:
            process.start()
            started = True
            sender.close()
            while outcome is None:
                if self.cancelled.is_set():
                    cancelled.set()
                try:
                    if receiver.poll(.05):
                        kind, value = receiver.recv()
                        if kind == 'status':
                            self.status.emit(value)
                        else:
                            outcome = kind, value
                    elif not process.is_alive():
                        break
                except EOFError:
                    break
                except OSError as error:
                    if getattr(error, 'winerror', None) not in (109, 232, 233):
                        raise
                    break
            process.join()
            if outcome is None:
                raise RuntimeError(f'Export worker exited without a result (code {process.exitcode})')
            return outcome
        finally:
            cancelled.set()
            if started:
                process.join()
                process.close()
            receiver.close()
            sender.close()


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
    def cancel():
        job.cancelled.set()
        window.statusBar().showMessage('Cancelling export… Finishing the current step safely.')
    progress.canceled.connect(cancel)
    def update(message):
        if not job.cancelled.is_set():
            progress.setLabelText(message)
    job.status.connect(update)
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

"""Responsive export menus; only detached Python data crosses to the worker."""
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QMessageBox, QProgressDialog

from .export_sheet_dialog import choose_export_sheets


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
            from .export_sheets import select_export_sheets
            select_export_sheets(book, snapshot.get('selected_sheets'))
            style_workbook(book)
            save_atomic(book, path, cancelled=cancelled)


def _export_process(path, snapshot, matching, native, cancelled, messages, settings):
    """Only owned data and an IPC endpoint enter this non-GUI process."""
    import gc
    collecting = gc.isenabled()
    # This one-shot process owns the report until it exits. Repeatedly scanning
    # millions of still-live cells costs seconds but collects almost nothing.
    # Keep the GUI, small in-process exports and Agg workers on their normal GC
    # policies; reference-counted cleanup and all cancellation checks still run.
    gc.disable()
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
        try:
            messages.close()
        finally:
            if collecting:
                gc.enable()


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
    """Paint progress before preparing a detached snapshot on the GUI thread."""
    if getattr(window, "_excel_export_job", None) is not None:
        return
    progress = QProgressDialog("Preparing export data…",
                               "Cancel", 0, 0, window)
    progress.setFixedWidth(480)
    label = progress.findChild(QLabel)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    job = ExportJob(path, None, matching=matching, native=native, parent=window)
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
            label.setToolTip(message)
            progress.setLabelText(label.fontMetrics().elidedText(
                message, Qt.TextElideMode.ElideRight, label.contentsRect().width()))
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
    def prepare():
        try:
            if job.cancelled.is_set() or progress.wasCanceled():
                raise InterruptedError("Export cancelled")
            # Qt widgets and child plot captures belong to the GUI thread.
            # Only the resulting detached data may enter the writer thread.
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            progress.repaint()
            if job.cancelled.is_set() or progress.wasCanceled():
                raise InterruptedError("Export cancelled")
            job.snapshot = snapshot() if callable(snapshot) else snapshot
            if job.cancelled.is_set() or progress.wasCanceled():
                raise InterruptedError("Export cancelled")
            from .export_sheets import export_sheet_names
            progress.hide()
            selected = choose_export_sheets(window, export_sheet_names(job.snapshot, matching=matching))
            if selected is None or job.cancelled.is_set():
                raise InterruptedError("Export cancelled")
            job.snapshot = dict(job.snapshot, selected_sheets=selected)
            progress.show()
            update("Exporting Excel charts…" if native else "Exporting Matplotlib…")
        except InterruptedError:
            failure("Export cancelled")
            finished()
            return
        except Exception as error:
            failure(str(error))
            finished()
            return
        job.start()
    job.exported.connect(success)
    job.failed.connect(failure)
    job.finished.connect(finished)
    progress.show()
    # Return to Qt before the potentially expensive capture. Explicit repaint
    # also covers an immediately queued preparation before the first paint.
    QTimer.singleShot(0, prepare)


def finish_export_before_close(window, event):
    """Allow a cancelling writer to close its own temporary file safely."""
    from .export_sheet_dialog import ExportSheetDialog
    jobs = [getattr(owner, "_excel_export_job", None)
            for owner in (window, *getattr(window, "_stage_windows", ()))]
    jobs = [job for job in jobs if job is not None]
    if not jobs:
        return False
    for job in jobs:
        job.cancelled.set()
        for chooser in job.parent().findChildren(ExportSheetDialog):
            chooser.reject()
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

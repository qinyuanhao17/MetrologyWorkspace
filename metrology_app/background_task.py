"""One running data-only task and one replaceable request per GUI owner."""
from PyQt6.QtCore import QCoreApplication, QObject, QThread, pyqtSignal

_RETIRED = set()


def _release(job):
    if job not in _RETIRED:
        return
    _RETIRED.discard(job)
    job.deleteLater()


def _finish_retired():
    for job in tuple(_RETIRED):
        job.wait()


class _DataJob(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, request, generation, parent):
        super().__init__(parent)
        self.function, self.request, self.generation = function, request, generation

    def run(self):
        try:
            result = self.function(self.request, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.ready.emit(result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class LatestTask(QObject):
    """Publish only the latest generation, always on this object's GUI thread.

    The function receives detached Python data, never a widget or GUI callback.
    It must observe cancellation between expensive steps. A library call may
    finish after cancellation; its result will still be rejected here.
    """
    changed = pyqtSignal()

    def __init__(self, function, publish, failed, parent):
        super().__init__(parent)
        self.function, self.publish, self.failed = function, publish, failed
        self.generation = 0
        self.worker = None
        self.pending = None
        self.closed = False
        parent.destroyed.connect(self.close)

    @property
    def busy(self):
        return self.worker is not None or self.pending is not None

    def submit(self, request):
        if self.closed:
            return
        self.generation += 1
        self.pending = request
        if self.worker is not None:
            self.worker.requestInterruption()
        else:
            self._start()
        self.changed.emit()

    def _start(self):
        request, self.pending = self.pending, None
        job = self.worker = _DataJob(self.function, request, self.generation, self)
        job.ready.connect(self._ready)
        job.failed.connect(self._failed)
        job.finished.connect(self._finished)
        job.start()

    def _current(self, job):
        return not self.closed and job is self.worker and job.generation == self.generation

    def _ready(self, result):
        if self._current(self.sender()):
            try:
                self.publish(result)
            except Exception as error:
                self.failed(str(error))

    def _failed(self, message):
        if self._current(self.sender()):
            self.failed(message)

    def _finished(self):
        job = self.sender()
        if job is not self.worker:
            return
        self.worker = None
        job.deleteLater()
        if self.pending is not None and not self.closed:
            self._start()
        self.changed.emit()

    def cancel(self):
        self.generation += 1
        self.pending = None
        if self.worker is not None:
            self.worker.requestInterruption()
        self.changed.emit()

    def close(self):
        if self.closed:
            return
        self.cancel()
        self.closed = True
        job, self.worker = self.worker, None
        if job is not None:
            for signal in (job.ready, job.failed, job.finished):
                signal.disconnect()
            job.setParent(None)
            _RETIRED.add(job)
            job.finished.connect(lambda: _release(job))
            app = QCoreApplication.instance()
            try:
                app.aboutToQuit.disconnect(_finish_retired)
            except TypeError:
                pass
            app.aboutToQuit.connect(_finish_retired)
            if not job.isRunning():
                _release(job)

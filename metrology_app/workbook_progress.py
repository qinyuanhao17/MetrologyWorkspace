"""Progress feedback for foreground workbook operations with detached work."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QProgressDialog, QSizePolicy, QWidget


class _OpeningDialog(QProgressDialog):
    def reject(self):
        pass


class InlineProgress(QWidget):
    def __init__(self, parent=None, *, compact=False):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        layout.addWidget(self.label)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        if compact:
            self.label.hide()
            self.bar.setFixedHeight(5)
            policy = self.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            policy.setRetainSizeWhenHidden(True)
            self.setSizePolicy(policy)
        else:
            self.bar.setMaximumWidth(self.bar.fontMetrics().horizontalAdvance("0000000000000000"))
        layout.addWidget(self.bar)
        self.hide()

    def setLabelText(self, message):
        self.label.setText(message)
        self.bar.setToolTip(message)
        self.bar.setAccessibleName(message)


class WorkbookProgress:
    def __init__(self, widget, *, delay=250):
        self.widget = widget
        self.timer = QTimer(widget, singleShot=True, interval=delay)
        self.timer.timeout.connect(widget.show)

    def suspend(self):
        self.timer.stop()
        self.was_visible = self.widget.isVisible()
        self.widget.hide()

    def resume(self, label):
        self.widget.setLabelText(label)
        if self.was_visible:
            self.widget.show()
        else:
            self.timer.start()

    def step(self, label):
        self.widget.setLabelText(label)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if self.widget.isVisible():
            self.widget.repaint()

    def compute(self, action):
        """Run a callable over owned data while the GUI processes paint events."""
        loop = QEventLoop()
        poll = QTimer(interval=15)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(action)
            poll.timeout.connect(lambda: loop.quit() if future.done() else None)
            if not future.done():
                poll.start()
                try:
                    loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                finally:
                    poll.stop()
            return future.result()

    @contextmanager
    def display(self, label):
        self.widget.setLabelText(label)
        self.timer.start()
        try:
            yield self
        finally:
            self.timer.stop()
            self.widget.hide()


@contextmanager
def opening_workbook_progress(parent, label):
    dialog = _OpeningDialog(label, "", 0, 0, parent)
    dialog.setCancelButton(None)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    progress = WorkbookProgress(dialog)
    try:
        with progress.display(label):
            yield progress
    finally:
        dialog.deleteLater()


@contextmanager
def correlation_opening_progress(window, label):
    indicator = InlineProgress(window)
    window.statusBar().addPermanentWidget(indicator)
    progress = WorkbookProgress(indicator, delay=0)
    window._opening_sources = True
    window.setEnabled(False)
    try:
        with progress.display(label):
            window.show()
            progress.step(label)
            yield progress
    finally:
        window._opening_sources = False
        window.setEnabled(True)
        window.statusBar().removeWidget(indicator)
        indicator.deleteLater()

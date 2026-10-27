"""GUI-owned, view-driven replay of accepted linked plot choices."""
from copy import deepcopy
from time import monotonic
from PyQt6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication


def logical_window(widget):
    """Floating editors and owned dialogs count as their workspace."""
    seen = set()
    while widget is not None and id(widget) not in seen:
        seen.add(id(widget))
        controller = getattr(widget, 'controller', None)
        owner = getattr(controller, 'owner', None)
        parent = owner if owner is not None else widget.parentWidget()
        if parent is None:
            return widget
        widget = parent
    return widget


def defer_linked_draw(page, state):
    controller = getattr(page.window(), 'viewed_plots', None)
    if controller is None or controller.forcing or not getattr(page.window(), '_defer_plot_refresh', False):
        return False
    controller.defer(page, state)
    return True


def defer_unviewed_result(page):
    controller = getattr(page.window(), 'viewed_plots', None)
    if (controller is not None and page in controller.automatic
            and not controller.forcing and not controller.is_viewed(page)):
        controller.pause(page)
        return True
    return False


class ViewedPlots(QObject):
    """Data commits immediately; replay only the current page of the watched child."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = {}
        self.automatic = set()
        self.forcing = False
        self.closed = False
        self.timer = QTimer(self, interval=10, singleShot=True)
        self.timer.timeout.connect(self.update_view)
        window.installEventFilter(self)
        window.tabs.currentChanged.connect(self.queue)
        QApplication.instance().applicationStateChanged.connect(self.queue)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate:
            self.remember_current_view(activating=True)
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate,
                            QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange):
            self.queue()
        return False

    def remember_current_view(self, *, activating=False):
        window = self.window
        if self.closed or self.forcing or getattr(window, '_input_update_depth', 0):
            return
        owner = getattr(window, '_managed_owner', None)
        remember = getattr(owner, 'remember_viewed_plot', None)
        if (window.isVisible() and not window.isMinimized() and window.tabs.currentWidget() in self.pages()
                and (activating or logical_window(QApplication.activeWindow()) is window) and callable(remember)):
            remember(window)

    def queue(self, *_):
        if not self.closed:
            self.remember_current_view()
            self.timer.start()

    def pages(self):
        return tuple(page for name in ('plot_page', 'radius_page', 'correlation_page', 'sequence_page')
                     if (page := getattr(self.window, name, None)) is not None
                     and self.window.tabs.indexOf(page) >= 0)

    def is_viewed(self, page):
        window = self.window
        if (not window.isVisible() or window.isMinimized() or window.tabs.currentWidget() is not page
                or QApplication.applicationState() != Qt.ApplicationState.ApplicationActive):
            return False
        owner = getattr(window, '_managed_owner', None)
        allowed = getattr(owner, 'may_refresh_viewed_plot', None)
        if callable(allowed):
            return allowed(window)
        return logical_window(QApplication.activeWindow()) is window

    def update_view(self):
        if self.forcing:
            return
        window = self.window
        page = window.tabs.currentWidget()
        owner = getattr(window, '_managed_owner', None)
        remember = getattr(owner, 'remember_viewed_plot', None)
        if page in self.pages() and logical_window(QApplication.activeWindow()) is window and callable(remember):
            remember(window)
        for item in tuple(self.automatic):
            if not self.is_viewed(item) and self._busy(item):
                self.pause(item)
        if not getattr(window, '_source_refresh_pending', False) and self.is_viewed(page):
            self.resume(page, background=True)

    @staticmethod
    def _busy(page):
        return (getattr(page, 'background_render_pending', False)
                or getattr(page, 'worker', None) is not None or page.input_refresh_timer.isActive())

    def defer(self, page, state):
        self.pending[page] = deepcopy(state)
        page.input_refresh_timer.stop()
        page.selector.pending_draw = False  # These are accepted Draw choices, not a new box selection.
        if hasattr(page, 'ready'):
            page.ready = False
        if hasattr(page, 'dirty'):
            page.dirty = True
        for name in ('export_button', 'export_all_button', 'copy_button'):
            button = getattr(page, name, None)
            if button is not None:
                button.setEnabled(False)
        page.status.setText('Data updated · Plot will refresh when viewed')
        self.queue()

    def pause(self, page):
        if page.selector.pending_draw:
            self.pending.pop(page, None)
            page.input_refresh_timer.stop()
        else:
            self.defer(page, page.draw_state())
        cancel = getattr(page, '_cancel_background_draw', None)
        if callable(cancel):
            cancel()
        if hasattr(page, 'revision') and hasattr(page, 'worker'):
            page.revision += 1
            if page.worker is not None:
                page.worker.requestInterruption()
        if hasattr(page, 'pending_input_refresh'):
            page.pending_input_refresh = False
        self.automatic.discard(page)

    def resume(self, page, *, background):
        state = self.pending.pop(page, None)
        if state is None:
            return
        if page.selector.pending_draw:
            return  # A newer manual choice still requires Draw selected.
        current = (getattr(page, 'ready', False) or
                   (getattr(page, 'result', None) is not None and not getattr(page, 'dirty', True)))
        if current:
            return  # A completed manual Draw supersedes the deferred replay.
        self.automatic.add(page)
        previous_view = page.stack.currentWidget()
        try:
            if hasattr(page, 'request_background_draw'):
                page.restore_draw_state(state, background=background)
            else:
                page.restore_draw_state(state)
        finally:
            if background and page.stack.indexOf(previous_view) >= 0:
                page.stack.setCurrentWidget(previous_view)

    def finish(self):
        """Explicit export materializes current results, including hidden pages."""
        views = {page: page.stack.currentWidget() for page in self.pages()}
        self.forcing = True
        try:
            for page in tuple(self.pending):
                self.resume(page, background=False)
            for page in self.pages():
                finish = getattr(page, 'finish_background_draw', None)
                if callable(finish):
                    finish()
                if page.input_refresh_timer.isActive():
                    page.input_refresh_timer.stop()
                    page.refresh_previous_selection()
            deadline = monotonic() + 60
            while any(getattr(page, 'worker', None) is not None for page in self.pages()):
                if monotonic() >= deadline:
                    raise ValueError('Wait for the current Wafer Map drawing to finish before exporting.')
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 20)
        finally:
            for page, view in views.items():
                if page.stack.indexOf(view) >= 0:
                    page.stack.setCurrentWidget(view)
            self.forcing = False

    def stop(self):
        self.closed = True
        self.timer.stop()
        self.pending.clear()
        self.automatic.clear()

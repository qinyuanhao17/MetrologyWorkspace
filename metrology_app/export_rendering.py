"""Bounded PNG preparation over detached plot descriptions, never Qt widgets."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from contextlib import contextmanager
from io import BytesIO
import multiprocessing
import os

_cancelled = None


def _configure_renderer(settings, cancelled):
    global _cancelled
    _cancelled = cancelled
    import matplotlib
    matplotlib.rcParams.update(settings)


def _render_picture(kind, args, kwargs, title):
    if _cancelled is not None and _cancelled.is_set():
        raise InterruptedError('Export cancelled')
    from .excel_export import parameter_figure
    from .analysis_export import plot_figure
    from .appearance import export_dpi, MAX_EXPORT_PIXELS
    figure = parameter_figure(*args, **kwargs) if kind == 'parameter' else plot_figure(*args, **kwargs)
    try:
        if _cancelled is not None and _cancelled.is_set():
            raise InterruptedError('Export cancelled')
        buffer = BytesIO()
        figure.savefig(buffer, format='png', dpi=(150 if kind == 'window' else export_dpi(figure, 150, MAX_EXPORT_PIXELS)),
                       facecolor='white', **({} if kind == 'window' else {'metadata': {'Title': title}}))
        width = figure.get_figwidth() * 96
        return buffer.getvalue(), (width, width * figure.get_figheight() / figure.get_figwidth())
    finally:
        figure.clear()
        figure.set_canvas(None)


class _Pictures:
    def __init__(self, book):
        self.book, self.pending, self.pool = book, deque(), None
        self.cancelled, self.limit = None, 4

    def add(self, sheet, anchor, title, images, kind, args, kwargs, cost):
        self.pending.append((sheet, anchor, title, images, kind, args, kwargs, cost, None))
        # Small reports render locally: spawning Python would cost more than
        # drawing them. The queue and wide Agg rasters are bounded in both modes.
        if self.pool is None and sum(item[7] for item in self.pending) >= 10000 and (os.cpu_count() or 1) > 1:
            import matplotlib
            context = multiprocessing.get_context('spawn')
            self.cancelled = context.Event()
            cores = os.cpu_count() or 2
            workers = min(6 if cores >= 12 else 4, cores - 1)
            self.limit = 2 * workers
            self.pool = ProcessPoolExecutor(max_workers=workers, mp_context=context,
                initializer=_configure_renderer, initargs=(dict(matplotlib.rcParams), self.cancelled))
            self.pending = deque((*item[:-1], self.pool.submit(_render_picture, item[4], item[5], item[6], item[2]))
                                 for item in self.pending)
        elif self.pool is not None:
            item = self.pending.pop()
            self.pending.append((*item[:-1], self.pool.submit(_render_picture, kind, args, kwargs, title)))
        if len(self.pending) >= self.limit:
            self._complete()

    def _complete(self):
        from .excel_export import _checkpoint
        from openpyxl.drawing.image import Image
        sheet, anchor, title, images, kind, args, kwargs, _cost, future = self.pending[0]
        _checkpoint(self.book, f'Rendering {title}')
        if future is None:
            contents, size = _render_picture(kind, args, kwargs, title)
        else:
            while True:
                _checkpoint(self.book)
                try:
                    contents, size = future.result(timeout=.05)
                    break
                except TimeoutError:
                    if future.done():
                        contents, size = future.result()
                        break
                    continue
        picture = Image(BytesIO(contents))
        picture.width, picture.height = size
        sheet.add_image(picture, anchor)
        if images is not None:
            images.append((title, contents))
        self.pending.popleft()
        _checkpoint(self.book)

    def flush(self):
        while self.pending:
            self._complete()

    def close(self):
        if self.cancelled is not None:
            self.cancelled.set()
        for item in self.pending:
            if item[-1] is not None:
                item[-1].cancel()
        self.pending.clear()
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)


@contextmanager
def rendering_session(book, *, native):
    pictures = None if native else _Pictures(book)
    book._export_pictures = pictures
    try:
        yield
    finally:
        if pictures is not None:
            pictures.close()
        del book._export_pictures


def flush_pictures(book):
    pictures = getattr(book, '_export_pictures', None)
    if pictures is not None:
        pictures.flush()


def embed_plot(sheet, plot, anchor, title, images=None, *, window=False):
    from .excel_export import _embed_figure
    from .analysis_export import plot_figure
    pictures = getattr(sheet.parent, '_export_pictures', None)
    if pictures is None:
        _embed_figure(sheet, plot_figure(plot), anchor, title, images)
    else:
        pictures.add(sheet, anchor, title, images, 'window' if window else 'plot', (plot,), {},
                     sum(len(series['data']) for series in plot['series']))


def embed_parameter(sheet, anchor, title, images, parameter, data, card, stage, scope, **kwargs):
    from .excel_export import _embed_figure, parameter_figure
    pictures = getattr(sheet.parent, '_export_pictures', None)
    if pictures is None:
        _embed_figure(sheet, parameter_figure(parameter, data, card, stage, scope, **kwargs), anchor, title, images)
    else:
        pictures.add(sheet, anchor, title, images, 'parameter',
                     (parameter, data[['Raw', 'Reference']], card, stage, scope), kwargs, len(data))

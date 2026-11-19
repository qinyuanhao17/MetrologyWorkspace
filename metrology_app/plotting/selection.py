"""Shared point-selection gestures and independent plot/data edits."""

from numbers import Integral
from weakref import WeakSet

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PyQt6.QtWidgets import QApplication, QRubberBand

from ..appearance import SELECTION_HIGHLIGHT_COLOR, SELECTION_LINKED_COLOR


class BoxDrag(QObject):
    """Own left drags in a plot's data area while preserving its clicks."""

    def __init__(self, view, target_at, select, zoom, *, select_click=True, on_click=None):
        super().__init__(view)
        self.view = view
        self.target_at = target_at
        self.select = select
        self.zoom = zoom
        self.select_click = select_click
        self.on_click = on_click
        self.start = None
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, view.viewport())
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            self.start = None
            self.band.hide()
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                point = event.position().toPoint()
                target = self.target_at(point)
                if target is not None or self.on_click is not None:
                    self.start = point, target, event.modifiers()
        elif self.start is not None and kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            point = event.position().toPoint()
            start, target, modifiers = self.start
            rect = QRect(start, point).normalized()
            dragged = self.band.isVisible() or (start - point).manhattanLength() >= QApplication.startDragDistance()
            if kind == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                if dragged:
                    self.band.setGeometry(rect)
                    self.band.show()
                # Retain native point clicks but prevent the ViewBox from starting a pan.
                return True
            if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.start = None
                self.band.hide()
                if dragged:
                    if modifiers & Qt.KeyboardModifier.ControlModifier:
                        if rect.width() > 3 and rect.height() > 3:
                            self.zoom(target, rect)
                    else:
                        self.select(target, rect, modifiers)
                    return True
                if self.on_click is not None and not modifiers & Qt.KeyboardModifier.ControlModifier:
                    self.on_click(target, point, modifiers)
                elif self.select_click and not modifiers & Qt.KeyboardModifier.ControlModifier:
                    self.select(target, QRect(point.x() - 4, point.y() - 4, 9, 9), modifiers)
        elif kind in (QEvent.Type.Hide, QEvent.Type.UngrabMouse):
            self.start = None
            self.band.hide()
        return False


class DataPointEdits:
    """Track the rows each plot action actually unchecked."""

    def __init__(self, set_checked, set_flag=None, records=None, flag_values=None):
        self.set_checked = set_checked
        self.set_flag = set_flag
        self.records = records
        self.flag_values = flag_values
        self.unchecked = set()
        self.applied_unchecks = set()
        self.removed_by_plot = {}
        self.preview_keys = set()
        self.preview_rows = set()
        self.preview_context = None
        self._selections = WeakSet()
        self._preview_listeners = WeakSet()

    def register(self, selection):
        self._selections.add(selection)
        selection.update_preview()

    def highlight(self, keys, context=None, source=None, rows=()):
        self.preview_keys = set(keys)
        self.preview_rows = {
            int(row) for row in rows
            if isinstance(row, Integral)
        }
        self.preview_context = context
        for selection in list(self._selections):
            if selection is not source and selection.in_context(context):
                selection.selected.clear()
                selection.update_highlight()
            selection.update_preview()
        self._notify_preview()

    def clear_highlight(self):
        context = self.preview_context
        self.preview_keys.clear()
        self.preview_rows.clear()
        self.preview_context = None
        for selection in list(self._selections):
            if selection.in_context(context):
                selection.selected.clear()
                selection.update_highlight()
            selection.update_preview()
        self._notify_preview()

    def add_preview_listener(self, listener):
        """Let a separate map mirror the same chart highlight without selecting it."""
        self._preview_listeners.add(listener)
        self._notify_preview(listener)

    def _notify_preview(self, listener=None):
        rows = frozenset(self.preview_rows)
        listeners = (listener,) if listener is not None else tuple(self._preview_listeners)
        for target in listeners:
            callback = getattr(target, "set_chart_preview_rows", None)
            if callback is None:
                continue
            try:
                callback(rows)
            except RuntimeError:
                self._preview_listeners.discard(target)

    def uncheck(self, keys, *, from_removed=False):
        records = self.records() if self.records is not None else None
        changed = self.set_checked(set(keys), False)
        changed_keys = changed if records is None else {records[row] for row in changed}
        if not changed_keys:
            return set()
        history, other = (self.applied_unchecks, self.unchecked) if from_removed else (
            self.unchecked, self.applied_unchecks)
        other.difference_update(changed_keys)
        history.update(changed_keys)
        return changed_keys

    def restore(self, *, from_removed=False):
        history = self.applied_unchecks if from_removed else self.unchecked
        return self.restore_keys(history, from_removed=from_removed)

    def restore_keys(self, keys, *, from_removed=False):
        history = self.applied_unchecks if from_removed else self.unchecked
        selected = set(history) & set(keys)
        if not selected:
            return set()
        if self.records is None:
            restored = self.set_checked(selected, True)
            history.difference_update(restored)
            return set(restored)
        else:
            records = self.records()
            rows = {row for row, key in enumerate(records) if key in selected}
            restored = self.set_checked(rows, True)
            restored_keys = {records[row] for row in restored}
            history.difference_update(restored_keys)
            return restored_keys

    def record_key(self, row):
        if self.records is None:
            return row
        records = self.records()
        return records[row] if 0 <= row < len(records) else None

    def available_flags(self):
        if callable(self.flag_values):
            return tuple(self.flag_values())
        return ("0", "1", "-1")

    def reset(self):
        self.unchecked.clear()
        self.applied_unchecks.clear()
        self.removed_by_plot.clear()
        self.clear_highlight()


def populate_test_flag_menu(menu, values, callback):
    """Populate the same value-style Test Flag menu used by Spectra Viewer."""
    from ..match_groups import flag_order

    flags = menu.addMenu("Set Test Flag")
    for value in flag_order(dict.fromkeys(str(value) for value in values if str(value).strip())):
        action = flags.addAction("0 (Fallback)" if value == "0" else value)
        action.setData(value)
        action.triggered.connect(lambda _checked=False, value=value: callback(value))
    flags.setEnabled(bool(flags.actions()))
    return flags


def add_selection_actions(menu, selection, removed, remove, restore, data_keys, data, *,
                          can_restore=None, data_selection=None):
    """Add actions to an existing chart menu without removing navigation."""
    actions = menu.actions()
    if actions and not actions[-1].isSeparator():
        menu.addSeparator()
    menu.addAction("Remove Selection", lambda: remove(selection())).setEnabled(bool(selection()))
    menu.addAction("Restore Removed Selection", restore).setEnabled(
        bool(removed()) if can_restore is None else can_restore())
    if data is not None:
        checked = data_keys(selection())
        all_checked = data_keys(data_selection()) if data_selection is not None else checked
        removed_keys = data_keys(removed())
        menu.addSeparator()
        menu.addAction("Uncheck Selection", lambda: data.uncheck(all_checked)).setEnabled(bool(all_checked))
        menu.addAction("Restore Unchecked Selection", lambda: data.restore()).setEnabled(bool(data.unchecked))
        menu.addSeparator()
        menu.addAction("Apply Remove to Uncheck", lambda: data.uncheck(removed_keys, from_removed=True)).setEnabled(
            bool(removed_keys))
        menu.addAction("Restore Applied Unchecks", lambda: data.restore(from_removed=True)).setEnabled(
            bool(data.applied_unchecks))
        if data.set_flag is not None:
            menu.addSeparator()
            flags = populate_test_flag_menu(menu, data.available_flags(),
                                            lambda value: data.set_flag(checked, value))
            flags.setEnabled(bool(checked))


class CurveSelection:
    """Selection and plot-local masks for one PyQtGraph panel."""

    def __init__(self, plot):
        import pyqtgraph as pg

        self.plot = plot
        self.selected = set()
        self.masks = {}
        self.original_rows = {}
        self.original_spots = {}
        self.original_point_data = {}
        self.unchecked_clicks = {}
        self.data = None
        self.scope = None
        self.highlight = pg.ScatterPlotItem(
            size=16,
            pen=pg.mkPen(SELECTION_HIGHLIGHT_COLOR, width=2.4),
            brush=None,
        )
        self.highlight.setZValue(100)
        self.highlight.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.highlight.setEnabled(False)
        self.preview = pg.ScatterPlotItem(
            size=16,
            pen=pg.mkPen(SELECTION_LINKED_COLOR, width=2.4),
            brush=None,
        )
        self.preview.setZValue(101)
        self.preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.preview.setEnabled(False)
        self._preview_tokens = set()
        self.primary = plot.getPlotItem().getViewBox()
        self.primary.addItem(self.highlight, ignoreBounds=True)
        self.primary.addItem(self.preview, ignoreBounds=True)
        BoxDrag(plot, self.view_at, self.select_rect, self.zoom_rect,
                select_click=False, on_click=self.preview_click)
        self.primary.sigRangeChanged.connect(self.update_highlight)
        self.primary.sigRangeChanged.connect(self.update_preview)
        self.menus = []

    def set_data(self, data, scope=None):
        self.data = data
        self.scope = scope
        if data is not None:
            data.register(self)
        else:
            self.update_preview()

    def add_menu(self, menu):
        if menu is None or menu in self.menus:
            return
        self.menus.append(menu)
        actions = []

        def populate():
            self.prune()
            for action in actions:
                menu.removeAction(action)
                action.deleteLater()
            previous = set(menu.actions())
            add_selection_actions(menu, lambda: self.selected, self.removed, self.remove, self.restore,
                                  self.data_keys, self.data,
                                  can_restore=lambda: bool(self.removed() or self.saved_removed()),
                                  data_selection=lambda: self.selected | self._preview_tokens)
            actions[:] = [action for action in menu.actions() if action not in previous]

        menu.aboutToShow.connect(populate)

    def view_at(self, point):
        return self.primary if self.primary.sceneBoundingRect().contains(self.plot.mapToScene(point)) else None

    def series(self, *, include_hidden=False):
        import pyqtgraph as pg

        for view in (self.primary, *getattr(self.plot, "secondary_views", ())):
            items = [item for item in view.addedItems if item not in (self.highlight, self.preview)
                     and isinstance(item, (pg.PlotDataItem, pg.PlotCurveItem, pg.ScatterPlotItem, pg.BarGraphItem))
                     and not getattr(item, "_selection_ignore", False)]
            explicit = [item for item in items
                        if getattr(getattr(item, "scatter", item), "_selection_rows", None) is not None]
            yield from ((view, item) for item in (explicit or items) if include_hidden or item.isVisible())

    @staticmethod
    def values(item):
        import pyqtgraph as pg
        import numpy as np

        if isinstance(item, pg.BarGraphItem):
            return np.asarray(item.opts["x"]), np.asarray(item.opts["height"])
        return item.getData()

    def prune(self):
        live = {item for _, item in self.series(include_hidden=True)}
        for item, (_, _, hidden, masked) in tuple(self.masks.items()):
            if item not in live or not self._still_masked(item, hidden, masked):
                del self.masks[item]
        self.selected = {(item, index) for item, index in self.selected if item in live}
        if self.data is not None:
            self.unchecked_clicks = {key: point for key, point in self.unchecked_clicks.items()
                                     if key in self.data.unchecked}
        self.update_preview()

    def _still_masked(self, item, hidden, expected):
        import numpy as np
        _, values = self.values(item)
        if values is None or not np.array_equal(values, expected, equal_nan=True):
            return False
        if hasattr(item, "scatter") and item.scatter is not None:
            return len(item.scatter.points()) == len(values)
        return True

    def _item_rows(self, item):
        if item in self.original_rows:
            return self.original_rows[item]
        scatter = item if hasattr(item, "scatter") and item.scatter is None else getattr(item, "scatter", item)
        rows = getattr(scatter, "_selection_rows", None)
        return None if rows is None else tuple(rows)

    def select_rect(self, _view, rect, modifiers):
        self.prune()
        picked = self.points_in(rect)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected |= picked
        else:
            self.selected = picked
        self.update_highlight()
        self._sync_shared_highlight()

    def preview_click(self, _view, point, _modifiers):
        visible = self.points_near(point, include_hidden=False)
        if not visible or self.data is None:
            if self.data is not None:
                self.selected.clear()
                self.data.clear_highlight()
                self.update_highlight()
            return
        views = {item: view for view, item in self.series(include_hidden=True)}

        def distance(token):
            item, index = token
            x, y = self._original_values(item)
            scene = views[item].mapViewToScene(QPointF(x[index], y[index]))
            return (self.plot.mapFromScene(scene) - point).manhattanLength()

        nearest = {min(visible, key=distance)}
        if _modifiers & Qt.KeyboardModifier.ControlModifier:
            self.selected ^= nearest
        elif _modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected |= nearest
        else:
            self.selected = nearest
        self.update_highlight()
        self._sync_shared_highlight()

    def _sync_shared_highlight(self):
        if self.data is None:
            return
        rows = self.data_keys(self.selected)
        keys = set()
        for row in rows:
            try:
                key = self.data.record_key(int(row))
            except (TypeError, ValueError):
                key = row
            if key is not None:
                keys.add(key)
        context = self.scope[2] if isinstance(self.scope, tuple) and len(self.scope) > 2 else None
        if keys:
            self.data.highlight(keys, context, source=self, rows=rows)
        else:
            self.data.clear_highlight()

    def tokens_for_preview(self):
        if self.data is None:
            return set()
        if (self.data.preview_context is not None
                and (not isinstance(self.scope, tuple) or len(self.scope) <= 2
                     or self.scope[2] != self.data.preview_context)):
            return set()
        return self.tokens_for_keys(self.data.preview_keys)

    def tokens_for_keys(self, keys):
        if self.data is None or not keys:
            return set()
        picked = set()
        for _view, item in self.series(include_hidden=False):
            rows = self._item_rows(item)
            if rows is None:
                continue
            hidden = self.masks.get(item, (None, None, set(), None))[2]
            for index, row in enumerate(rows):
                if index in hidden:
                    continue
                try:
                    key = self.data.record_key(int(row))
                except (TypeError, ValueError):
                    key = row
                if key in keys:
                    picked.add((item, index))
        return picked

    def in_context(self, context):
        return (context is None or
                isinstance(self.scope, tuple) and len(self.scope) > 2
                and self.scope[2] == context)

    def update_preview(self, *_):
        import numpy as np

        self._preview_tokens = self.tokens_for_preview() - self.selected
        if not self._preview_tokens:
            if len(self.preview.data):
                self.preview.setData([], [])
            return
        views = {item: view for view, item in self.series(include_hidden=False)}
        points = []
        for item, index in self._preview_tokens:
            view = views.get(item)
            x, y = self._original_values(item)
            if view is None or x is None or y is None:
                continue
            if index >= len(x) or not np.isfinite(y[index]):
                continue
            points.append(self.primary.mapSceneToView(
                view.mapViewToScene(QPointF(float(x[index]), float(y[index])))))
        self.preview.setData([point.x() for point in points], [point.y() for point in points])

    def points_in(self, rect):
        import numpy as np

        scene = self.plot.mapToScene(rect).boundingRect()
        picked = set()
        for view, item in self.series():
            bounds = view.mapSceneToView(scene.topLeft()), view.mapSceneToView(scene.bottomRight())
            (left, right), (bottom, top) = (sorted((p.x() for p in bounds)), sorted((p.y() for p in bounds)))
            x, y = self._original_values(item)
            if x is not None and y is not None:
                inside = np.flatnonzero((x >= left) & (x <= right) & (y >= bottom) & (y <= top))
                hidden = self.masks.get(item, (None, None, (), None))[2]
                picked.update((item, int(index)) for index in inside if index not in hidden)
        return picked

    def double_click(self, point, modifiers):
        self.prune()
        visible = self.points_near(point, include_hidden=False)
        hidden = self.points_near(point, include_hidden=True) - visible
        views = {item: view for view, item in self.series(include_hidden=True)}

        def distance(token):
            item, index = token
            x, y = self._original_values(item)
            scene = views[item].mapViewToScene(QPointF(x[index], y[index]))
            return (self.plot.mapFromScene(scene) - point).manhattanLength()

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            nearest = min(visible, key=distance) if visible else None
            rows = self.data_keys({nearest}) if nearest is not None else set()
            keys = ({self.data.record_key(int(row)) for row in rows}
                    if self.data is not None and self.data.records is not None else set(rows))
            keys.discard(None)
            if not keys:
                keys = self.unchecked_key_at(point)
            if not keys or self.data is None:
                return False
            restore = keys & set(self.data.unchecked)
            if restore:
                self.data.restore_keys(restore)
                for key in restore:
                    self.unchecked_clicks.pop(key, None)
            else:
                changed = self.data.uncheck(rows)
                if nearest is not None:
                    for key in changed:
                        self.unchecked_clicks[key] = QPoint(point)
            return True
        if hidden:
            nearest = min(hidden, key=distance)
            self.restore({nearest})
            return True
        if not visible:
            return False
        nearest = min(visible, key=distance)
        self.remove({nearest})
        return True

    def points_near(self, point, *, include_hidden=False):
        import numpy as np

        picked = set()
        for view, item in self.series(include_hidden=True):
            x, y = self._original_values(item)
            if x is None or y is None:
                continue
            hidden = self.masks.get(item, (None, None, set(), None))[2]
            mapped = [self.plot.mapFromScene(view.mapViewToScene(QPointF(float(px), float(py))))
                      for px, py in zip(x, y)]
            for index, position in enumerate(mapped):
                if index in hidden and not include_hidden:
                    continue
                if np.isfinite(y[index]) and (position - point).manhattanLength() <= 9:
                    picked.add((item, index))
        return picked

    def unchecked_key_at(self, point):
        for key, saved in self.unchecked_clicks.items():
            if (saved - point).manhattanLength() <= 12:
                return {key}
        return set()

    def _original_values(self, item):
        x, y, _hidden, _masked = self.masks.get(item, (None, None, None, None))
        if x is None:
            return self.values(item)
        return x, y

    def zoom_rect(self, _view, rect):
        from PyQt6.QtCore import QRectF

        scene = self.plot.mapToScene(rect).boundingRect()
        for view in (self.primary, *getattr(self.plot, "secondary_views", ())):
            a, b = view.mapSceneToView(scene.topLeft()), view.mapSceneToView(scene.bottomRight())
            view.setRange(rect=QRectF(a, b).normalized(), padding=0)

    def data_keys(self, points):
        keys = set()
        for item, index in points:
            rows = self._item_rows(item)
            if rows is not None and index < len(rows):
                row = rows[index]
                if isinstance(row, (tuple, set, frozenset, list)):
                    keys.update(row)
                else:
                    keys.add(row)
        return keys

    def saved_removed(self):
        if self.data is None or self.scope is None:
            return set()
        return self.data.removed_by_plot.get(self.scope, set())

    def _identities(self, item, indices, records):
        name = item.name() if hasattr(item, "name") else None
        if not name:
            name = next((i for i, (_, series) in enumerate(self.series(include_hidden=True)) if series is item), None)
        for index in indices:
            positions = self.data_keys({(item, index)})
            keys = tuple(records[row] for row in sorted(positions) if 0 <= row < len(records))
            if keys:
                yield index, (name, keys)

    def apply_saved(self, item):
        hidden = self.saved_removed()
        if not hidden or self.data.records is None:
            return
        x, y = self.values(item)
        if y is None:
            return
        records = self.data.records()
        picked = {(item, index) for index, key in self._identities(item, range(len(y)), records)
                  if key in hidden}
        if picked:
            self.remove(picked, remember=False)

    def removed(self):
        return {(item, index) for item, (_, _, removed, _) in self.masks.items() for index in removed}

    def _write(self, item, x, y, hidden=()):
        import numpy as np
        import pyqtgraph as pg

        hidden = set(hidden)
        visible = np.array([index for index in range(len(x)) if index not in hidden], dtype=int)
        rows = self._item_rows(item)
        if isinstance(item, pg.BarGraphItem):
            if hidden and item not in self.original_rows and rows is not None:
                self.original_rows[item] = tuple(rows)
            width = item.opts.get("width", 1)
            width = (np.asarray(width)[visible]
                     if np.ndim(width) and len(width) == len(x) else width)
            item.setOpts(x=np.asarray(x)[visible], height=np.asarray(y)[visible],
                         width=width)
            item._selection_rows = (
                tuple(self.original_rows[item][index] for index in visible)
                if item in self.original_rows
                else tuple(rows[index] for index in visible)
                if rows is not None else None)
        elif isinstance(item, pg.ScatterPlotItem):
            if hidden and item not in self.original_spots:
                self.original_spots[item] = [
                    dict(pos=spot.pos(), data=spot.data(), symbol=spot.symbol(),
                         size=spot.size(), pen=spot.pen(), brush=spot.brush())
                    for spot in item.points()
                ]
            spots = self.original_spots.get(item)
            spots = ([dict(pos=(x[index], y[index]), data=spot["data"],
                           symbol=spot["symbol"], size=spot["size"],
                           pen=spot["pen"], brush=spot["brush"])
                      for index, spot in enumerate(spots) if index not in hidden]
                     if spots is not None else
                     [dict(pos=(x[index], y[index])) for index in visible])
            if spots:
                item.setData(spots=spots)
            else:
                item.setData([], [])
        else:
            if hidden and item not in self.original_rows and rows is not None:
                self.original_rows[item] = tuple(rows)
            if hidden and item not in self.original_point_data:
                self.original_point_data[item] = item.opts.get("data")
            # Omit removed coordinates from both line and marker data, so the
            # neighbours join directly and the curve never leaves a gap.
            point_data = self.original_point_data.get(item)
            point_data = (None if point_data is None or len(point_data) != len(x)
                          else np.asarray(point_data, dtype=object)[visible])
            item.setData(x=np.asarray(x)[visible], y=np.asarray(y)[visible],
                         data=point_data)
            scatter = getattr(item, "scatter", None)
            if scatter is not None:
                if scatter._selection_rows is not None:
                    scatter._selection_rows = (
                        tuple(self.original_rows[item][index] for index in visible)
                        if item in self.original_rows
                        else tuple(rows[index] for index in visible))
        if not hidden:
            if item in self.original_point_data:
                original_data = self.original_point_data.pop(item)
                item.setData(x=x, y=y, data=original_data)
            if rows is not None and item in self.original_rows:
                scatter = item if hasattr(item, "_selection_rows") else getattr(item, "scatter", None)
                if scatter is not None:
                    scatter._selection_rows = self.original_rows.pop(item)
            self.original_spots.pop(item, None)

    def remove(self, points, *, remember=True):
        import numpy as np

        self.prune()
        grouped = {}
        for item, index in points:
            grouped.setdefault(item, set()).add(index)
        records = (self.data.records() if remember and self.scope is not None and
                   self.data is not None and self.data.records is not None else None)
        for item, indices in grouped.items():
            if records is not None:
                marked = {key for _, key in self._identities(item, indices, records)}
                if marked:
                    self.data.removed_by_plot.setdefault(self.scope, set()).update(marked)
            x, y = self._original_values(item)
            if y is None:
                continue
            x, y, hidden, _ = self.masks.get(item, (x, y, set(), None))
            hidden = hidden | {i for i in indices if i < len(y)}
            expected = np.asarray(y, dtype=float)[
                [index for index in range(len(y)) if index not in hidden]]
            self._write(item, x, y, hidden)
            self.masks[item] = (x, y, hidden, expected)
        self.selected.difference_update(points)
        self.update_highlight()
        self._sync_shared_highlight()

    def restore(self, points=None):
        self.prune()
        records = self.data.records() if self.data is not None and self.data.records is not None else None
        if points is None:
            if self.data is not None:
                self.data.removed_by_plot.pop(self.scope, None)
            masks, self.masks = self.masks, {}
            for item, (x, y, _hidden, _masked) in masks.items():
                self._write(item, x, y)
        else:
            grouped = {}
            for item, index in points:
                grouped.setdefault(item, set()).add(index)
            for item, indices in grouped.items():
                x, y, hidden, _masked = self.masks.get(item, (None, None, set(), None))
                if x is None:
                    continue
                if records is not None and self.data is not None:
                    restored_keys = {key for _, key in self._identities(item, indices, records)}
                    target = self.data.removed_by_plot.get(self.scope)
                    if target is not None:
                        target.difference_update(restored_keys)
                        if not target:
                            self.data.removed_by_plot.pop(self.scope, None)
                hidden = hidden - set(indices)
                if hidden:
                    self._write(item, x, y, hidden)
                    expected = np.asarray(y, dtype=float)[
                        [index for index in range(len(y)) if index not in hidden]]
                    self.masks[item] = (x, y, hidden, expected)
                else:
                    self.masks.pop(item, None)
                    self._write(item, x, y)
        self.update_highlight()
        self._sync_shared_highlight()

    def update_highlight(self, *_):
        from PyQt6.QtCore import QPointF
        import numpy as np

        if not self.selected:
            if len(self.highlight.data):
                self.highlight.setData([], [])
            return
        xs, ys = [], []
        by_item = {}
        for item, index in self.selected:
            by_item.setdefault(item, []).append(index)
        for view, item in self.series():
            if item not in by_item:
                continue
            x, y = self._original_values(item)
            if x is None:
                continue
            hidden = self.masks.get(item, (None, None, set(), None))[2]
            for index in by_item[item]:
                if index < len(y) and index not in hidden and np.isfinite(y[index]):
                    point = self.primary.mapSceneToView(view.mapViewToScene(QPointF(x[index], y[index])))
                    xs.append(point.x())
                    ys.append(point.y())
        self.highlight.setData(xs, ys)


def ask_test_flag(parent):
    from PyQt6.QtWidgets import QInputDialog, QMessageBox
    from ..match_groups import flag_value

    value, accepted = QInputDialog.getText(parent, "Set Test Flag", "Integer TestFlag (blank clears it)")
    if not accepted:
        return None
    try:
        return flag_value(value)
    except ValueError as error:
        QMessageBox.warning(parent, "Invalid Test Flag", str(error))
        return None

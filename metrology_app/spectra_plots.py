"""PyQtGraph rendering widgets for the Spectra Viewer."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QByteArray, QDataStream, QEvent, QIODevice, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QMainWindow,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QVBoxLayout,
    QWidget,
)

from .sme_spectra import M_COLS, ChannelKey, natural_key
from .plotting.curve import cache_curve_image


@dataclass(frozen=True, slots=True)
class CurveSegment:
    spectrum_key: str
    x: np.ndarray
    y: np.ndarray
    spectrum_keys: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class WaferChannelKey:
    wafer: str
    channel: ChannelKey
    lot: str = ""
    pad: str = ""
    spectrum_key: str = ""
    sme_name: str = ""

    @property
    def sort_key(self):
        return (natural_key(self.wafer), natural_key(self.lot), natural_key(self.pad),
                natural_key(self.sme_name), self.spectrum_key, *self.channel.sort_key)

    @property
    def legend_label(self):
        identity = self.sme_name or " · ".join(part for part in (self.wafer, self.lot, self.pad) if part)
        return f"{identity} · {self.channel.legend_label}"


@dataclass(frozen=True, slots=True)
class CurveGroup:
    key: ChannelKey | WaferChannelKey
    color: QColor
    segments: tuple[CurveSegment, ...]


def _join_segments(segments, indices=None):
    """Copy each polyline once, separated by NaNs instead of per-line appends."""
    slices = tuple(indices) if indices is not None else tuple((0, len(s.x)) for s in segments)
    size = sum(end - start + 1 for start, end in slices)
    x, y = np.full(size, np.nan), np.full(size, np.nan)
    cursor = 0
    for segment, (start, end) in zip(segments, slices):
        count = end - start
        x[cursor:cursor + count] = segment.x[start:end]
        y[cursor:cursor + count] = segment.y[start:end]
        cursor += count + 1
    return x, y


class _ViewportCurve(pg.PlotCurveItem):
    """Clip each source spectrum independently; retain full-data auto-range bounds."""

    def __init__(self, segments, **kwargs):
        self._prepare_source(segments)
        self._clip_enabled = True
        self._clip_indices = None
        super().__init__(x=self._source_x, y=self._source_y, connect="finite", antialias=True, **kwargs)
        self.screen_cache = None

    def _prepare_source(self, segments):
        self._segments = tuple(segments)
        self._ordered_x = tuple(
            bool(np.isfinite(segment.x).all() and (np.diff(segment.x) >= 0).all())
            for segment in self._segments
        )
        self._source_x, self._source_y = _join_segments(self._segments)
        self._source_bounds = []
        valid = np.isfinite(self._source_x) & np.isfinite(self._source_y)
        for values in (self._source_x, self._source_y):
            finite = values[valid]
            self._source_bounds.append((float(finite.min()), float(finite.max())) if len(finite) else (None, None))

    def set_segments(self, segments):
        self._prepare_source(segments)
        self._clip_indices = None
        self.viewRangeChanged()

    @property
    def render_pending(self):
        return self.screen_cache is not None and self.screen_cache.render_pending

    def cache_screen_image(self):
        self.screen_cache = cache_curve_image(self, screen_error=0.25 if isinstance(self, _MulticolorViewportCurve) else 0.0)

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        if frac >= 1.0 and orthoRange is None:
            return self._source_bounds[ax]
        values, other = ((self._source_x, self._source_y) if ax == 0
                         else (self._source_y, self._source_x))
        mask = np.isfinite(values)
        if orthoRange is not None:
            mask &= (other >= orthoRange[0]) & (other <= orthoRange[1])
        values = values[mask]
        if not len(values):
            return None, None
        if frac >= 1.0:
            return float(values.min()), float(values.max())
        if frac <= 0:
            raise ValueError("frac must be positive")
        return tuple(np.percentile(values, [50 * (1 - frac), 50 * (1 + frac)]))

    def setClipToView(self, enabled):
        self._clip_enabled = bool(enabled)
        self._clip_indices = None
        self.viewRangeChanged()

    def viewRangeChanged(self, *_args):
        view = self.getViewBox()
        if not self._clip_enabled or not isinstance(view, pg.ViewBox) or view.autoRangeEnabled()[0]:
            indices = tuple((0, len(segment.x)) for segment in self._segments)
        else:
            left, right = view.viewRange()[0]
            margin = abs(view.viewPixelSize()[0]) * (self.opts["pen"].widthF() + 2)
            left, right = left - margin, right + margin
            # Include the stroke width and neighbouring samples at viewport edges.
            # Never search across wavelength resets or remove NaN separators.
            indices = tuple(
                (max(0, int(np.searchsorted(segment.x, left, side="left")) - 2),
                 min(len(segment.x), int(np.searchsorted(segment.x, right, side="right")) + 2))
                if ordered else (0, len(segment.x))
                for segment, ordered in zip(self._segments, self._ordered_x)
            )
        if indices == self._clip_indices:
            return
        self._clip_indices = indices
        if all(start == 0 and end == len(segment.x)
               for segment, (start, end) in zip(self._segments, indices)):
            x, y = self._source_x, self._source_y
        else:
            x, y = _join_segments(self._segments, indices)
        self.setData(x=x, y=y, connect="finite")


class _MulticolorViewportCurve(_ViewportCurve):
    """One scene item/image for many colors; retain native per-color export painting."""

    def __init__(self, groups, *, width):
        self._colored_groups = tuple(groups)
        self._components_cache = None
        self._native_curves = None
        self._line_width = width
        super().__init__((s for g in groups for s in g.segments), pen=pg.mkPen("black", width=width))

    def set_groups(self, groups):
        self._colored_groups = tuple(groups)
        self._components_cache = None
        self._native_curves = None
        self.set_segments(s for g in groups for s in g.segments)

    def _components(self):
        key = self._clip_indices
        if self._components_cache is not None and self._components_cache[0] == key:
            return self._components_cache[1]
        result = []
        cursor = 0
        for group in self._colored_groups:
            indices = (key[cursor:cursor + len(group.segments)] if key is not None
                       else tuple((0, len(s.x)) for s in group.segments))
            cursor += len(group.segments)
            x, y = _join_segments(group.segments, indices)
            result.append((x, y, pg.mkPen(group.color, width=self._line_width)))
        self._components_cache = key, result
        self._native_curves = None
        return result

    def raster_components(self):
        detached = []
        for x, y, pen in self._components():
            payload = QByteArray()
            stream = QDataStream(payload, QIODevice.OpenModeFlag.WriteOnly)
            stream << pen
            # _components owns these joined buffers and never mutates them.
            # Worker submissions can share that immutable snapshot; copying it
            # again for every geometry update only stalls Qt's owner thread.
            x.setflags(write=False)
            y.setflags(write=False)
            detached.append((x, y, bytes(payload)))
        return detached

    def paint(self, painter, option, widget=None):
        components = self._components()
        if self._native_curves is None:
            self._native_curves = [pg.PlotCurveItem(x=x, y=y, pen=pen, connect="finite",
                                                  antialias=self.opts["antialias"])
                                   for x, y, pen in components]
        for curve in self._native_curves:
            if isinstance(self._exportOpts, dict):
                curve.setExportMode(True, self._exportOpts)
            else:
                curve.setExportMode(False)
            curve.paint(painter, option, widget)

    def setExportMode(self, export, opts=None):
        super().setExportMode(export, opts)
        if not export:
            self._native_curves = None


class _ResetHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        if splitter is not None and splitter.count():
            splitter.reset_sizes()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizablePlotSplitter(QSplitter):
    """A plot boundary that can be dragged and reset by double-click."""

    def __init__(self, orientation, parent=None, *, default_sizes=None):
        super().__init__(orientation, parent)
        self._default_sizes = tuple(default_sizes or ())
        self._initial_sizes_applied = False
        self.setChildrenCollapsible(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setHandleWidth(6)
        self.setOpaqueResize(False)

    def reset_sizes(self):
        if not self.count():
            return
        weights = self._default_sizes if len(self._default_sizes) == self.count() else (1,) * self.count()
        extent = self.width() if self.orientation() == Qt.Orientation.Horizontal else self.height()
        extent = max(1, extent - self.handleWidth() * (self.count() - 1))
        self.setSizes([max(1, round(extent * weight / sum(weights))) for weight in weights])

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_sizes_applied:
            self._initial_sizes_applied = True
            self.reset_sizes()

    def createHandle(self):
        return _ResetHandle(self.orientation(), self)


class DecimalAxisItem(pg.AxisItem):
    """Use plain decimal/scientific labels instead of SI prefixes."""

    def __init__(self, orientation, *, max_labels=None, parent=None):
        super().__init__(orientation, parent=parent)
        self.max_labels = max_labels

    def tickStrings(self, values, scale, spacing):
        labels = [f"{value * scale:.4g}" for value in values]
        if self.max_labels is None or len(labels) <= self.max_labels:
            return labels
        keep = {
            round(index * (len(labels) - 1) / (self.max_labels - 1))
            for index in range(self.max_labels)
        }
        return [
            label if index in keep else ""
            for index, label in enumerate(labels)
        ]


class SpectrumPlotPanel(QWidget):
    """One pyqtgraph panel with one batched curve per channel identity."""

    sigDoubleClicked = pyqtSignal(object)
    spectraSelected = pyqtSignal(object)
    resizeRequested = pyqtSignal()

    def __init__(
        self,
        title,
        *,
        dual=False,
        compact=False,
        context_menu=None,
        parent=None,
    ):
        super().__init__(parent)
        self.title = title
        self._analysis_mode = "original"
        self.compact = compact
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.context_menu = context_menu
        self.groups: list[CurveGroup] = []
        self.secondary_groups: list[CurveGroup] = []
        self._all_groups: list[CurveGroup] = []
        self._all_secondary_groups: list[CurveGroup] = []
        self._hidden_keys = set()
        self._curve_items: list[pg.PlotCurveItem] = []
        self._highlight_items: list[pg.PlotCurveItem] = []
        self._group_items = {}
        self._highlight_groups = {}
        self._batch_slots = {}
        self._tight_x_range = None
        self._selected_keys: set[str] = set()
        self._navigation_click = False
        self._foreground = QColor("#2b2730")
        self._plot_background = QColor("#ffffff")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        max_labels = 4 if compact else None
        axes = {
            "left": DecimalAxisItem("left", max_labels=max_labels),
            "bottom": DecimalAxisItem(
                "bottom",
            ),
        }
        if dual:
            axes["right"] = DecimalAxisItem(
                "right",
                max_labels=4 if compact else None,
            )
        self.plot = pg.PlotWidget(axisItems=axes)
        self.plot.setMinimumSize(0, 0)
        if compact:
            # Label the uniformly spaced major ticks only; keep minor grid lines.
            axes["bottom"].setStyle(maxTextLevel=0)
        self.plot.getPlotItem().layout.setContentsMargins(0, 0, 0, 0)
        self.plot.getPlotItem().layout.setSpacing(1)
        self.plot.getPlotItem().vb.setDefaultPadding(0.01)
        self.plot.scene().sigMouseClicked.connect(self._scene_clicked)
        for axis_name in axes:
            self.plot.getAxis(axis_name).enableAutoSIPrefix(False)
        self.plot.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.plot.getPlotItem().showButtons()
        self.plot.getPlotItem().setMenuEnabled(False, True)
        self.plot.getPlotItem().vb.getMenu(None).viewAll.triggered.connect(self._auto_range_all)
        self.plot.getPlotItem().getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.plot.getPlotItem().autoBtn.clicked.connect(self._auto_range_all)
        self.plot.showGrid(x=True, y=True, alpha=0.16)
        layout.addWidget(self.plot, 1)
        self.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.plot.viewport().installEventFilter(self)
        if dual:
            self.secondary = pg.ViewBox()
            self.plot.scene().addItem(self.secondary)
            self.plot.showAxis("right")
            self.plot.getAxis("right").linkToView(self.secondary)
            self.plot.getAxis("right").setLabel("Delta (deg)")
            self.secondary.setXLink(self.plot)
            self.secondary.setMouseEnabled(x=False, y=False)
            self.secondary.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.plot.getPlotItem().vb.sigResized.connect(self._sync_secondary)
            self._sync_secondary()
        else:
            self.secondary = None

    def eventFilter(self, watched, event):
        if (watched is self.plot.viewport() and event.type() == QEvent.Type.Resize
                and any(item.xData is not None and len(item.xData) >= 2000
                        for item in (*self._curve_items, *self._highlight_items))):
            self.resizeRequested.emit()
        if watched is self.plot.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            # PyQtGraph's A button leaves its scene click unaccepted and can
            # disappear during auto-range. Record the hit before it handles it.
            button = self.plot.getPlotItem().autoBtn
            position = self.plot.mapToScene(event.position().toPoint())
            self._navigation_click = (
                event.button() == Qt.MouseButton.LeftButton
                and button.isVisible()
                and button.contains(button.mapFromScene(position))
            )
        if (
            watched is self.plot.viewport()
            and event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.sigDoubleClicked.emit(self)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _context_requested(self, position):
        if self.context_menu is not None:
            self.context_menu(self.plot.mapToGlobal(position))

    def _auto_range_all(self, *_args):
        view = self.plot.getPlotItem().getViewBox()
        view.autoRange()
        view.enableAutoRange(axis="y", enable=True)
        if self.secondary is not None:
            self.secondary.autoRange()
            self.secondary.enableAutoRange(axis="y", enable=True)
        self._fit_x_range()
        self.plot.getPlotItem().updateButtons()

    def _fit_x_range(self):
        bounds = [item.dataBounds(0) for item in self._curve_items if item.isVisible()]
        bounds = [bound for bound in bounds if bound[0] is not None]
        if bounds:
            self._tight_x_range = [min(low for low, _ in bounds), max(high for _, high in bounds)]
            self.plot.getViewBox().setXRange(*self._tight_x_range, padding=0)

    @property
    def selected_keys(self) -> set[str]:
        return set(self._selected_keys)

    @property
    def render_pending(self):
        return any(item.render_pending for item in (*self._curve_items, *self._highlight_items))

    def cancel_rendering(self):
        for item in (*self._curve_items, *self._highlight_items):
            if item.screen_cache is not None:
                item.screen_cache.cancel()

    def apply_theme(self, palette):
        self._foreground = QColor("#2b2730")
        self._plot_background = QColor("#ffffff")
        self.plot.setBackground(self._plot_background)
        self.plot.showAxis("top")
        self.plot.showAxis("right")
        for axis_name in ("left", "bottom", "top", "right"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(self._foreground)
            axis.setTextPen(self._foreground)
        left_width = 32 if self.compact else 40
        right_width = 6 if self.compact else 40
        self.plot.getAxis("left").setWidth(left_width)
        self.plot.getAxis("right").setWidth(right_width)
        self.plot.getAxis("top").setStyle(showValues=False)
        self.plot.getAxis("right").setStyle(
            showValues=self.secondary is not None,
        )
        self.plot.setTitle(self.display_title, color=self._foreground.name())
        self.plot.setLabel("bottom", "Wavelength (nm)")
        self.plot.setLabel("left", "")
        if self.secondary is not None:
            self.plot.getAxis("right").setLabel("")

    @property
    def display_title(self):
        suffix = {"original": "", "residual": " · Residual", "3sigma": " · 3σ"}[self._analysis_mode]
        return self.title + suffix

    def set_analysis_mode(self, mode):
        if mode == self._analysis_mode:
            return
        self._analysis_mode = mode
        self.plot.setTitle(self.display_title, color=self._foreground.name())
        self.plot.getViewBox().enableAutoRange(axis="y", enable=True)
        if self.secondary is not None:
            self.secondary.enableAutoRange(axis="y", enable=True)

    def _sync_secondary(self):
        if self.secondary is None:
            return
        self.secondary.setGeometry(self.plot.getPlotItem().vb.sceneBoundingRect())
        self.secondary.linkedViewChanged(
            self.plot.getPlotItem().vb,
            self.secondary.XAxis,
        )

    def set_curves(
        self,
        primary: list[CurveGroup],
        *,
        secondary: list[CurveGroup] | None = None,
        selected_keys: set[str] | None = None,
        hidden_keys=None,
    ):
        view = self.plot.getViewBox()
        fit_x = (self._tight_x_range is None or view.autoRangeEnabled()[0]
                 or view.viewRange()[0] == self._tight_x_range)
        self._selected_keys = set(selected_keys or ())
        self._all_groups = list(primary)
        self._all_secondary_groups = list(secondary or ())
        self._hidden_keys = set(hidden_keys or ())
        self._visible_groups()
        self._curve_items = self._sync_items(self._group_items)
        self._highlight_items = self._sync_items(self._highlight_groups, highlight=True)
        if fit_x:
            self._fit_x_range()

    def _visible_groups(self):
        self.groups = [g for g in self._all_groups if g.key not in self._hidden_keys]
        self.secondary_groups = [g for g in self._all_secondary_groups if g.key not in self._hidden_keys]

    def set_hidden_keys(self, keys):
        keys = set(keys)
        if keys == self._hidden_keys:
            return
        view = self.plot.getViewBox()
        fit_x = view.autoRangeEnabled()[0] or view.viewRange()[0] == self._tight_x_range
        self._hidden_keys = keys
        self._visible_groups()
        self._curve_items = self._sync_items(self._group_items)
        self._highlight_items = self._sync_items(self._highlight_groups, highlight=True)
        if fit_x:
            self._fit_x_range()

    def _sync_items(self, existing, *, highlight=False):
        desired = set()
        items = []
        for axis, view, groups in ((0, self.plot.getPlotItem(), self._all_groups),
                                   (1, self.secondary, self._all_secondary_groups)):
            if view is None:
                continue
            if groups and (len(groups) > 32 or self._batch_slots.get(axis)):
                slots = self._batch_slots.get(axis, {})
                if any(g.key not in slots for g in groups):
                    # Keep at most 16 contiguous batches, with stable slots when
                    # a file/legend disappears. Preserve the original overlap order.
                    size = max(8, (len(groups) + 15) // 16)
                    slots = {g.key: i // size for i, g in enumerate(groups)}
                    self._batch_slots[axis] = slots
                batches = {}
                for group in groups:
                    batches.setdefault(slots[group.key], []).append(group)
                for batch, members in batches.items():
                    visible = []
                    for group in members:
                        if group.key in self._hidden_keys:
                            continue
                        segments = tuple(s for s in group.segments if not highlight
                                         or s.spectrum_key in self._selected_keys or s.spectrum_keys & self._selected_keys)
                        if segments:
                            visible.append(CurveGroup(group.key, group.color, segments))
                    key = axis, ("batch", batch)
                    if highlight and not visible:
                        continue
                    signature = tuple((g.key, g.color.rgba(), tuple(
                        (s.spectrum_key, *((a.__array_interface__["data"][0], a.shape, a.strides, a.dtype.str)
                                           for a in (s.x, s.y))) for s in g.segments)) for g in visible)
                    previous = existing.get(key)
                    if previous is not None and not visible and not highlight:
                        # A hidden batch is still a cached source, not empty data.
                        # Restoring the channel can reuse its arrays and raster.
                        item = previous[1]
                        item.screen_cache.set_visible(False)
                        desired.add(key)
                        items.append(item)
                        continue
                    if previous is None:
                        item = _MulticolorViewportCurve(visible, width=5.0 if highlight else 1.8)
                        view.addItem(item, ignoreBounds=highlight)
                        item.cache_screen_image()
                    else:
                        item = previous[1]
                        if previous[0] != signature:
                            item.set_groups(visible)
                    z = (20 if highlight else 0) + batch / (max(slots.values()) + 1)
                    item.setZValue(z)
                    item.screen_cache.image_item.setZValue(z)
                    item.screen_cache.set_visible(bool(visible))
                    existing[key] = signature, item
                    desired.add(key)
                    items.append(item)
                continue
            for index, group in enumerate(groups):
                segments = tuple(s for s in group.segments
                                 if not highlight or s.spectrum_key in self._selected_keys
                                 or s.spectrum_keys & self._selected_keys)
                if not segments:
                    continue
                key = axis, group.key
                # series() returns fresh NumPy views of immutable source data.
                # Compare their backing storage, not array equality or view IDs.
                signature = (group.color.rgba(), tuple(
                    (s.spectrum_key, *((a.__array_interface__["data"][0], a.shape, a.strides, a.dtype.str)
                                       for a in (s.x, s.y))) for s in segments))
                previous = existing.get(key)
                if previous is None or previous[0] != signature:
                    if previous is not None:
                        self._remove_curve(previous[1])
                    item = self._add_group(view, CurveGroup(group.key, group.color, segments),
                                           highlight=highlight)
                    existing[key] = signature, item
                item = existing[key][1]
                # Replacing one group must not change which wafer paints on top.
                z = (20 if highlight else 0) + index / (len(groups) + 1)
                item.setZValue(z)
                item.screen_cache.image_item.setZValue(z)
                item.screen_cache.set_visible(group.key not in self._hidden_keys)
                desired.add(key)
                items.append(existing[key][1])
        for key in existing.keys() - desired:
            self._remove_curve(existing.pop(key)[1])
        return items

    def _add_group(
        self,
        view,
        group,
        *,
        pen_style=Qt.PenStyle.SolidLine,
        highlight=False,
    ):
        if not group.segments:
            return pg.PlotCurveItem()
        curve_color = QColor(group.color)
        curve_color.setAlpha(255)
        pen = pg.mkPen(curve_color, width=5.0 if highlight else 1.8, style=pen_style)
        item = _ViewportCurve(group.segments, pen=pen)
        if highlight:
            item.setZValue(20)
        view.addItem(item, ignoreBounds=highlight)
        item.cache_screen_image()
        return item

    def set_selected_keys(self, keys):
        if set(keys) == self._selected_keys:
            return
        self._selected_keys = set(keys)
        self._highlight_items = self._sync_items(self._highlight_groups, highlight=True)

    def _remove_curve(self, item):
        if item.screen_cache is not None:
            item.screen_cache.dispose()
        if self.secondary is not None and item.getViewBox() is self.secondary:
            self.secondary.removeItem(item)
        else:
            self.plot.getPlotItem().removeItem(item)

    def _scene_clicked(self, event):
        navigation_click, self._navigation_click = self._navigation_click, False
        if (event.button() != Qt.MouseButton.LeftButton or event.double()
                or event.isAccepted() or navigation_click):
            return
        scene_position = event.scenePos()
        primary = self.plot.getPlotItem().vb
        best = None
        views = [(primary, self.groups)]
        if self.secondary is not None:
            views.append((self.secondary, self.secondary_groups))
        for view, groups in views:
            if not view.sceneBoundingRect().contains(scene_position):
                continue
            position = view.mapSceneToView(scene_position)
            pixel_x, pixel_y = view.viewPixelSize()
            for group in groups:
                for segment in group.segments:
                    # Distance to the displayed polyline, in pixels. Preserve NaN gaps.
                    x = (segment.x - position.x()) / max(abs(pixel_x), 1e-15)
                    y = (segment.y - position.y()) / max(abs(pixel_y), 1e-15)
                    valid = np.isfinite(x[:-1]) & np.isfinite(y[:-1])
                    valid &= np.isfinite(x[1:]) & np.isfinite(y[1:])
                    if not valid.any():
                        continue
                    ax, ay = x[:-1][valid], y[:-1][valid]
                    dx = x[1:][valid] - ax
                    dy = y[1:][valid] - ay
                    t = np.clip(-(ax * dx + ay * dy) / np.maximum(dx * dx + dy * dy, 1e-15), 0, 1)
                    distance = float(np.min(np.hypot(ax + t * dx, ay + t * dy)))
                    if best is None or distance < best[0]:
                        best = distance, segment.spectrum_keys or frozenset((segment.spectrum_key,))
        keys = set(best[1]) if best is not None and best[0] <= 7 else set()
        if keys and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            keys ^= self._selected_keys
        elif keys and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            keys |= self._selected_keys
        self.spectraSelected.emit(keys)


class FloatingPlotWindow(QMainWindow):
    """A modeless enlarged copy of one spectrum plot."""

    def __init__(self, source: SpectrumPlotPanel):
        super().__init__(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.source = source
        self.setWindowTitle(f"{source.title} — Spectrum Plot")
        self.resize(900, 620)
        self.panel = SpectrumPlotPanel(
            source.title,
            dual=source.secondary is not None,
            compact=False,
            context_menu=source.context_menu,
        )
        self.setCentralWidget(self.panel)
        self.panel.apply_theme(source.palette())
        self.sync_from(source)
        from .floating_editor import WindowPin
        self.window_pin = WindowPin(self, source.window())

    def nativeEvent(self, event_type, message):
        result = self.window_pin.native_event(event_type, message) if hasattr(self, "window_pin") else None
        return result if result is not None else (False, 0)

    def sync_from(self, source):
        self.source = source
        self.panel.set_analysis_mode(source._analysis_mode)
        self.setWindowTitle(f"{source.display_title} — Spectrum Plot")
        self.panel.set_curves(
            source._all_groups,
            secondary=source._all_secondary_groups,
            selected_keys=source.selected_keys,
            hidden_keys=source._hidden_keys,
        )

    def closeEvent(self, event):
        self.panel.cancel_rendering()
        super().closeEvent(event)

    def apply_theme(self, palette):
        self.panel.apply_theme(palette)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "panel"):
            self.panel.apply_theme(self.palette())


class MuellerPanel(QWidget):
    def __init__(self, context_menu=None, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.plot_splitter = ResizablePlotSplitter(Qt.Orientation.Vertical)
        self.scroll_area = QScrollArea()
        self.scroll_area.setMinimumSize(0, 0)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.plot_splitter)
        layout.addWidget(self.scroll_area)
        self.mij_plots = {
            name: SpectrumPlotPanel(name, compact=True, context_menu=context_menu)
            for name in M_COLS
        }
        self.row_splitters = []
        for row in range(4):
            row_splitter = ResizablePlotSplitter(Qt.Orientation.Horizontal)
            self.row_splitters.append(row_splitter)
            self.plot_splitter.addWidget(row_splitter)
            for column in range(4):
                row_splitter.addWidget(self.mij_plots[M_COLS[row * 4 + column]])

    def apply_theme(self, palette):
        for panel in self.mij_plots.values():
            panel.apply_theme(palette)

    def set_curves(self, groups_by_metric, selected_keys):
        for name, panel in self.mij_plots.items():
            panel.set_curves(
                groups_by_metric.get(name, ()),
                selected_keys=selected_keys,
            )


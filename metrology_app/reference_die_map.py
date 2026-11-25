"""Paginated die maps for paired absolute Ref and Raw coordinates."""

from collections import defaultdict

import pyqtgraph as pg
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtWidgets import QCheckBox, QLabel, QMenu

from .bias_die_map import DieMapPoint
from .plotting.selection import add_selection_actions
from .reference_alignment import MM_PER_COORDINATE_UNIT
from .selection_script import canonical_die
from .sme_spectra import SpectrumIdentity
from .spectra_map import SpectraMapWindow, WaferPointPlot


SOURCE_COLORS = {"Ref": "#e67722", "Raw": "#2878bd"}
REF_MARKER_SIZE = 16


def _row(key):
    return int(key.partition(":")[2])


def _integer(value, default=None):
    try:
        return int(canonical_die(value))
    except ValueError:
        return default


def _paired_map_points(results, source_positions):
    wafers = defaultdict(list)
    for _, wafer, frame in results:
        unit = frame.attrs.get("unit", "mm")
        scale = MM_PER_COORDINATE_UNIT[unit]
        columns = {source: [f"{source} {axis} ({unit})" for axis in "XY"]
                   for source in SOURCE_COLORS}
        if not all(column in frame for pair in columns.values() for column in pair):
            continue
        rows = zip(frame["Raw source row"], frame["Point"],
                   frame.get("Raw Die Seq", frame["Point"]),
                   frame.get("Raw Field X", [None] * len(frame)),
                   frame.get("Raw Field Y", [None] * len(frame)),
                   *(frame[pair].to_numpy(dtype=float) * scale for pair in columns.values()))
        for row, ordinal, die, field_x, field_y, ref_xy, raw_xy in rows:
            identity = SpectrumIdentity(*wafer, _integer(die, ordinal), "",
                                        field_x=_integer(field_x), field_y=_integer(field_y))
            position = source_positions[row]
            for source, xy in (("Ref", ref_xy), ("Raw", raw_xy)):
                wafers[wafer].append(DieMapPoint(f"{source}:{position}", identity, *xy))
    return wafers


class _AlignmentWaferPlot(WaferPointPlot):
    def __init__(self, title, restore_at):
        super().__init__(title)
        self._restore_at = restore_at
        self.plot.viewport().installEventFilter(self)
        self.selection.setSize(REF_MARKER_SIZE + 4)
        self.raw_markers = pg.ScatterPlotItem(
            size=self.scatter.opts["size"], symbol="o", antialias=True,
            pen=self.scatter.opts["pen"], brush=pg.mkBrush(SOURCE_COLORS["Raw"]),
        )
        self.raw_markers.setEnabled(False)
        self.raw_markers.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.plot.addItem(self.raw_markers, ignoreBounds=True)
        self.raw_markers.stackBefore(self.selection)

    def set_checked(self, checked_keys):
        super().set_checked(checked_keys)
        raw_positions = []
        ref_brush = pg.mkBrush(SOURCE_COLORS["Ref"])
        transparent = pg.mkBrush(None)
        no_pen = pg.mkPen(None)
        for point in self.scatter.points():
            sources = {key.partition(":")[0] for key in point.data()["keys"]}
            if "Ref" in sources:
                point.setSize(REF_MARKER_SIZE)
                point.setBrush(ref_brush)
            else:
                # Keep Raw-only points selectable in the shared scatter layer.
                point.setBrush(transparent)
                point.setPen(no_pen)
            if "Raw" in sources:
                raw_positions.append((point.pos().x(), point.pos().y()))
        self.raw_markers.setData(pos=raw_positions)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._restore_at(event.position().toPoint(), shift):
                return True
        return super().eventFilter(watched, event)

    def restorable_keys_at(self, cursor, points):
        view = self.plot.getViewBox()
        if not view.sceneBoundingRect().contains(self.plot.mapToScene(cursor)):
            return set()
        keys = set()
        # Use screen-space hit boxes, like the visible scatter markers.
        radius = REF_MARKER_SIZE / 2 + 1
        for point in points:
            xy = QPointF(round(point.x_mm, 6), round(point.y_mm, 6))
            delta = self.plot.mapFromScene(view.mapViewToScene(xy)) - cursor
            if abs(delta.x()) <= radius and abs(delta.y()) <= radius:
                keys.add(point.key)
        return keys

    @staticmethod
    def _point_tip(x, y, data):
        sources = ", ".join(dict.fromkeys(key.split(":", 1)[0] for key in data["keys"]))
        return f"{data['label']} · {sources}\nX: {x:g} mm\nY: {y:g} mm"


class AlignmentDieMap(SpectraMapWindow):
    def __init__(self, results, source_positions, parent, *, data_point_edits=None):
        super().__init__(parent, read_only=True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("XY Bias · Die Map")
        self.wafers_button.show()
        self.select_out_of_range_button.hide()
        self._point_edits = data_point_edits
        self._points_by_wafer = _paired_map_points(results, source_positions)
        self._visible_points = self._points_by_wafer
        self._allowed_rows = None
        points = tuple(point for wafer in self._points_by_wafer.values() for point in wafer)
        self.set_data(points, checked_keys={point.key for point in points})

    def _add_selection_controls(self, layout):
        self.sources = {}
        for source, color in SOURCE_COLORS.items():
            swatch = QLabel("●")
            swatch.setStyleSheet(f"color: {color};")
            control = QCheckBox(source)
            control.setChecked(True)
            control.toggled.connect(self._refresh_visible_points)
            self.sources[source] = control
            layout.addSpacing(8)
            layout.addWidget(swatch)
            layout.addWidget(control)

    def _create_wafer_plot(self, title, wafer):
        plot = _AlignmentWaferPlot(title, lambda cursor, shift: self._restore_at(wafer, cursor, shift))
        gestures = "\nDouble-click to remove or restore."
        if self._point_edits is not None:
            gestures += " Shift+double-click to uncheck or restore."
        plot.plot.setToolTip(plot.plot.toolTip() + gestures)
        return plot

    def _visible_wafer_points(self, wafer):
        points = self._visible_points[wafer]
        removed = self._removed_map_keys.get(wafer)
        return tuple(point for point in points if point.key not in removed) if removed else points

    def _populate_wafer_plot(self, wafer, plot):
        plot.set_data(self._visible_wafer_points(wafer), self._selected_keys,
                      scale_spectra=self._points_by_wafer[wafer])

    def _refresh_map_point_mask(self, wafer):
        super()._refresh_map_point_mask(wafer)
        self._update_summary()

    @staticmethod
    def _rows(keys):
        return {_row(key) for key in keys}

    def _point_check_requested(self, keys, checked):
        if self._point_edits is not None and not checked:
            self._point_edits.uncheck(self._rows(keys))

    def _restore_at(self, wafer, cursor, shift):
        plot = self.wafer_plots[wafer]
        shown = self._shown_sources()
        points = (point for point in self._points_by_wafer[wafer] if point.key.startswith(shown))
        if shift:
            edits = self._point_edits
            allowed = self._allowed_rows
            if edits is None or not edits.unchecked or allowed is None:
                return False
            records = edits.records() if edits.records is not None else None
            candidates, record_keys = [], {}
            for point in points:
                row = _row(point.key)
                record = edits.record_key(row, records)
                if row not in allowed and record in edits.unchecked:
                    candidates.append(point)
                    record_keys[point.key] = record
            hits = plot.restorable_keys_at(cursor, candidates)
            return bool(edits.restore_keys({record_keys[key] for key in hits}))

        removed = self._removed_map_keys.get(wafer)
        if not removed:
            return False
        hits = plot.restorable_keys_at(cursor, (point for point in points if point.key in removed))
        if not hits:
            return False
        removed.difference_update(hits)
        if removed:
            self._refresh_map_point_mask(wafer)
        else:
            self._restore_map_points(wafer)
        return True

    def build_selection_menu(self, wafer=None):
        menu = QMenu(self)
        menu.addAction("Copy Select", self.copy_selected_dies).setEnabled(bool(self._selected_keys))
        menu.addAction("Paste Select", self.paste_selected_dies)
        wafer = wafer if wafer is not None else self._context_wafer
        if wafer in self._visible_points:
            add_selection_actions(
                menu,
                lambda: self._selected_keys & {point.key for point in self._visible_wafer_points(wafer)},
                lambda: self._removed_map_keys.get(wafer, set()),
                lambda keys: self._remove_map_points(wafer, keys),
                lambda: self._restore_map_points(wafer),
                self._rows, self._point_edits,
            )
        return menu

    @property
    def point_count(self):
        return sum(len({(round(p.x_mm, 6), round(p.y_mm, 6)) for p in self._visible_wafer_points(wafer)})
                   for wafer in self._visible_wafers)

    def set_checked_rows(self, allowed):
        if allowed != self._allowed_rows:
            self._allowed_rows = allowed
            self._refresh_visible_points()

    def _shown_sources(self):
        return tuple(f"{source}:" for source, control in self.sources.items() if control.isChecked())

    def _refresh_visible_points(self):
        sources = self._shown_sources()
        allowed = self._allowed_rows
        self._visible_points = {
            wafer: tuple(point for point in points if point.key.startswith(sources)
                         and (allowed is None or _row(point.key) in allowed))
            for wafer, points in self._points_by_wafer.items()
        }
        for wafer, plot in self.wafer_plots.items():
            self._populate_wafer_plot(wafer, plot)
        self._update_summary()

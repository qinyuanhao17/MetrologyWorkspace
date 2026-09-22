"""Numeric trends over Die Seq, grouped by Wafer ID."""

from io import BytesIO
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .appearance import configure_resolution_combo, resolution_settings, screen_render_scale
from .data import number
from .settings import get_settings


MAX_SEQUENCE_PLOTS = 30
MAX_SCREEN_PIXELS = 7_000_000
GROUP_GAP = 4


def normalized_name(value):
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def find_column(frame, aliases):
    names = {normalized_name(column): column for column in frame.columns}
    return next((names[alias] for alias in aliases if alias in names), None)


class SequencePage(QWidget):
    """One line-and-marker panel per selected numeric parameter."""

    def __init__(self):
        super().__init__(objectName="sequencePage")
        settings = get_settings()
        self.frame = pd.DataFrame()
        self.selection = {}
        self.ready = False
        self.base_size = (1100, 650)
        self.wafer_column = None
        self.die_column = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self.draw_button = QPushButton("Draw Die Seq plots", objectName="primary")
        self.draw_button.clicked.connect(self.draw_plot)
        self.export_button = QPushButton("Export PNG")
        self.export_button.clicked.connect(self.export_png)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        for control in (self.draw_button, self.export_button, self.copy_button):
            toolbar.addWidget(control)
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("Columns", objectName="muted"))
        self.columns = QComboBox()
        self.columns.addItems(["1", "2"])
        self.columns.setFixedWidth(54)
        self.columns.currentIndexChanged.connect(self.relayout)
        toolbar.addWidget(self.columns)
        toolbar.addWidget(QLabel("View", objectName="muted"))
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit width", "50%", "75%", "100%", "125%", "150%", "200%", "250%", "300%"])
        self.zoom.currentTextChanged.connect(self.resize_canvas)
        toolbar.addWidget(self.zoom)
        toolbar.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentTextChanged.connect(self.restyle)
        toolbar.addWidget(self.font_size)
        toolbar.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        toolbar.addWidget(self.resolution)
        toolbar.addStretch()
        self.summary = QLabel("Die Seq / Wafer ID", objectName="accent")
        toolbar.addWidget(self.summary)
        layout.addLayout(toolbar)

        self.figure = Figure(figsize=(11, 6.5), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.scene = QGraphicsScene(self)
        self.canvas_proxy = self.scene.addWidget(self.canvas)
        self.scroll = QGraphicsView(self.scene)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.canvas.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_png)
        self.copy_button.setToolTip("Copy the complete plot as PNG (Ctrl+C while this tab is active).")
        layout.addWidget(self.scroll, 1)
        self.status = QLabel("Select measurement sets and numeric parameters in Data, then draw.", objectName="hint")
        layout.addWidget(self.status)
        self.invalidate()

    def set_input(self, frame, selection):
        self.frame = frame
        self.selection = selection.copy()
        self.wafer_column = find_column(frame, ("waferid", "wafer", "waferno"))
        self.die_column = find_column(frame, ("dieseq", "diesequence", "diesequenceno", "dieid"))
        count = len(selection.get("metrics", []))
        self.summary.setText(f"{count} numeric plots · Die Seq / Wafer ID")
        self.invalidate()

    def draw_canvas_message(self, message):
        size = max(15, int(self.font_size.currentText()) + 3)
        self.figure.text(.5, .5, message, ha="center", va="center", color="#746b7e", fontsize=size)

    def invalidate(self):
        self.ready = False
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.draw_canvas_message("Choose numeric parameters in Data, then click Draw Die Seq plots")
        self.canvas.draw_idle()

    def _parts(self):
        wafers = self.selection.get("wafers", [])
        if "groups" in self.selection:
            return [(key, self.frame.iloc[list(self.selection["groups"].get(key, ()))]) for key in wafers]
        ids = self.frame[self.selection["wafer_column"]].astype(str).str.strip()
        return [(key, self.frame[ids == key]) for key in wafers]

    def _sequence_groups(self):
        groups, cursor = [], 0
        labels = self.selection.get("labels", {})
        for key, part in self._parts():
            if part.empty:
                continue
            ordered = part.assign(__die=number(part[self.die_column])).dropna(subset=["__die"])
            ordered = ordered.sort_values("__die", kind="stable")
            if ordered.empty:
                continue
            positions = np.arange(cursor, cursor + len(ordered), dtype=float)
            wafer_values = ordered[self.wafer_column].fillna("").astype(str).str.strip()
            wafer_id = next((value for value in wafer_values if value), "")
            if not wafer_id:
                wafer_id = str(labels.get(key, key)).splitlines()[0]
            groups.append({"key": key, "wafer": wafer_id, "frame": ordered,
                           "positions": positions, "center": float(positions.mean())})
            cursor += len(ordered) + GROUP_GAP
        return groups, max(0, cursor - GROUP_GAP)

    @staticmethod
    def _format_die(value):
        return f"{value:g}" if np.isfinite(value) else ""

    def draw_plot(self, *_):
        try:
            metrics = self.selection.get("metrics", [])
            wafers = self.selection.get("wafers", [])
            if self.frame.empty:
                raise ValueError("Load or paste a table in Data first.")
            if not wafers or not metrics:
                raise ValueError("Select at least one measurement set and one numeric parameter in Data.")
            if len(metrics) > MAX_SEQUENCE_PLOTS:
                raise ValueError(f"Select up to {MAX_SEQUENCE_PLOTS} numeric parameters for Die Seq plots.")
            if not self.wafer_column:
                raise ValueError("A Wafer ID column is required for this plot.")
            if not self.die_column:
                raise ValueError("A Die Seq column is required for this plot.")
            groups, extent = self._sequence_groups()
            if not groups:
                raise ValueError("The selected measurement sets contain no valid Die Seq values.")

            columns = min(int(self.columns.currentText()), len(metrics))
            rows = ceil(len(metrics) / columns)
            panel_width = max(900, min(1900, 180 + 6 * sum(len(group["frame"]) for group in groups)))
            width, height = columns * panel_width, rows * 350 + 30
            self.figure.clear()
            axes = self.figure.subplots(rows, columns, squeeze=False)
            base = int(self.font_size.currentText())
            total_points = sum(len(group["frame"]) for group in groups)
            tick_step = max(1, ceil(total_points / 65))

            for ax, metric in zip(axes.flat, metrics):
                tick_positions, tick_labels, wafer_texts = [], [], []
                plotted = 0
                for group_index, group in enumerate(groups):
                    values = number(group["frame"][metric]).to_numpy(float)
                    valid = np.isfinite(values)
                    if valid.any():
                        ax.plot(group["positions"][valid], values[valid], color="#4472c4", linewidth=1.35,
                                marker="o", markersize=3.8, markerfacecolor="#4472c4")
                        plotted += int(valid.sum())
                    die_values = group["frame"]["__die"].to_numpy(float)
                    local = set(range(0, len(die_values), tick_step)) | {0, len(die_values) - 1}
                    for index in sorted(local):
                        tick_positions.append(group["positions"][index])
                        tick_labels.append(self._format_die(die_values[index]))
                    wafer_texts.append(ax.text(group["center"], -.18, group["wafer"],
                                                transform=ax.get_xaxis_transform(), ha="center", va="top",
                                                fontsize=max(6, base - 2), color="#5f6368", clip_on=False))
                    if group_index:
                        ax.axvline(group["positions"][0] - GROUP_GAP / 2,
                                   color="#d4d7dc", linewidth=.8, zorder=0)
                if not plotted:
                    ax.text(.5, .5, "No valid numeric values", transform=ax.transAxes,
                            ha="center", va="center", fontsize=max(11, base))
                ax.set_title(str(metric), fontsize=base + 1, fontweight="semibold", pad=8)
                ax.set_ylabel("Value", fontsize=max(7, base - 1))
                ax.set_xlabel("Die Seq", fontsize=max(7, base - 1), labelpad=30)
                ax.set_xlim(-1, max(1, extent))
                ax.set_xticks(tick_positions, tick_labels, fontsize=max(6, base - 2))
                ax.tick_params(axis="y", labelsize=max(6, base - 2))
                ax.grid(axis="y", color="#d6d8dc", linewidth=.7)
                ax.set_axisbelow(True)
                ax._wafer_group_labels = wafer_texts
                ax._die_sequence_values = [group["frame"]["__die"].tolist() for group in groups]
                ax._wafer_ids = [group["wafer"] for group in groups]
                for spine in ax.spines.values():
                    spine.set_color("#c9ccd1")
            for ax in axes.flat[len(metrics):]:
                ax.set_axis_off()

            self.figure.subplots_adjust(left=.065, right=.985, top=.965, bottom=.09,
                                        hspace=.64, wspace=.18)
            self.base_size = width, height
            self.ready = True
            self.refresh_canvas()
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.status.setText(f"{len(metrics)} numeric plots · {len(groups)} measurement sets · "
                                f"{total_points} Die Seq positions.")
        except (ValueError, KeyError) as error:
            self.ready = False
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.status.setText(str(error))

    def relayout(self, *_):
        if self.ready:
            self.draw_plot()

    def restyle(self, *_):
        base = int(self.font_size.currentText())
        if not self.ready:
            for text in self.figure.texts:
                text.set_fontsize(max(15, base + 3))
            self.canvas.draw_idle()
            return
        for ax in self.figure.axes:
            ax.title.set_fontsize(base + 1)
            ax.xaxis.label.set_fontsize(max(7, base - 1))
            ax.yaxis.label.set_fontsize(max(7, base - 1))
            ax.tick_params(labelsize=max(6, base - 2))
            for text in getattr(ax, "_wafer_group_labels", []):
                text.set_fontsize(max(6, base - 2))
        self.canvas.draw_idle()
        QTimer.singleShot(0, self.center_canvas)

    def refresh_canvas(self):
        if not self.ready:
            return
        width, height = self.base_size
        requested_scale, _dpi = resolution_settings(self.resolution)
        render_scale = screen_render_scale(width, height, requested_scale, MAX_SCREEN_PIXELS)
        self.figure.set_dpi(100 * render_scale)
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        self.canvas.setFixedSize(round(width * render_scale), round(height * render_scale))
        self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()

    def resize_canvas(self, *_):
        if not self.ready:
            return
        width, _height = self.base_size
        text = self.zoom.currentText()
        display = (min(1, max(280, self.scroll.viewport().width() - 20) / width)
                   if text == "Fit width" else int(text[:-1]) / 100)
        render_scale = self.figure.dpi / 100
        self.scroll.resetTransform()
        self.scroll.scale(max(.5, display) / render_scale, max(.5, display) / render_scale)
        QTimer.singleShot(0, self.center_canvas)

    def center_canvas(self):
        if not self.ready:
            return
        viewport_center = self.scroll.mapToScene(self.scroll.viewport().rect().center())
        canvas_center = self.canvas_proxy.sceneBoundingRect().center()
        self.scroll.centerOn(canvas_center.x(), viewport_center.y())

    def change_resolution(self, *_):
        if self.ready:
            self.refresh_canvas()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.ready:
            delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.zoom_by_wheel(delta.y() or event.pixelDelta().y(), watched, event.position().toPoint())
            else:
                horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or abs(delta.x()) > abs(delta.y())
                bar = self.scroll.horizontalScrollBar() if horizontal else self.scroll.verticalScrollBar()
                amount = delta.x() if abs(delta.x()) > abs(delta.y()) else delta.y()
                if not amount:
                    pixel = event.pixelDelta()
                    amount = pixel.x() if horizontal else pixel.y()
                bar.setValue(bar.value() - round(np.sign(amount) * max(bar.singleStep() * 3, 36)))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def zoom_by_wheel(self, delta, watched=None, position=None):
        if not delta or not self.ready:
            return
        render_scale = self.figure.dpi / 100
        current = round(100 * self.scroll.transform().m11() * render_scale)
        steps = [50, 75, 100, 125, 150, 200, 250, 300]
        target = (next((value for value in steps if value > current), steps[-1]) if delta > 0 else
                  next((value for value in reversed(steps) if value < current), steps[0]))
        viewport = self.scroll.viewport()
        if position is None:
            viewport_pos = viewport.rect().center()
            scene_pos = self.scroll.mapToScene(viewport_pos)
        elif watched is self.canvas:
            scene_pos = QPointF(position)
            viewport_pos = self.scroll.mapFromScene(scene_pos)
        else:
            viewport_pos = position
            scene_pos = self.scroll.mapToScene(viewport_pos)
        hbar, vbar = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        self.zoom.setCurrentText(f"{target}%")

        def restore_anchor():
            moved = self.scroll.mapFromScene(scene_pos)
            hbar.setValue(hbar.value() + moved.x() - viewport_pos.x())
            vbar.setValue(vbar.value() + moved.y() - viewport_pos.y())

        QTimer.singleShot(0, restore_anchor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.resize_canvas)

    def export_png(self):
        if not self.ready:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Die Seq plots", "die_seq_plots.png", "PNG (*.png)")
        if path:
            path = str(Path(path).with_suffix(".png"))
            _scale, dpi = resolution_settings(self.resolution)
            self.figure.savefig(path, dpi=dpi, facecolor="white")
            self.status.setText(f"Exported ({dpi} dpi): {path}")

    def copy_png(self):
        if not self.ready:
            return
        buffer = BytesIO()
        _scale, dpi = resolution_settings(self.resolution)
        self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        image = QImage.fromData(buffer.getvalue(), "PNG")
        QApplication.clipboard().setImage(image)
        self.status.setText(f"Copied Die Seq plots ({dpi} dpi) · {image.width()} × {image.height()} px")

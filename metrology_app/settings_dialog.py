"""Small settings dialog for persistent application preferences."""

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .appearance import COLOR_MAP_OPTIONS
from .settings import get_settings, save_settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(360)

        form = QFormLayout()
        form.setContentsMargins(20, 18, 20, 12)
        form.setSpacing(10)

        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        form.addRow("Theme", self.theme)

        self.resolution = QComboBox()
        self.resolution.addItems(["Standard", "High", "Ultra"])
        form.addRow("Default resolution", self.resolution)

        self.color_map = QComboBox()
        for title, name in COLOR_MAP_OPTIONS:
            self.color_map.addItem(title, name)
        form.addRow("Default color map", self.color_map)

        self.color_low, self.color_high = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (self.color_low, self.color_high):
            control.setRange(0, 100)
            control.setDecimals(1)
            control.setSingleStep(1)
            control.setSuffix("%")
        range_widget = QWidget()
        range_layout = QHBoxLayout(range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(self.color_low)
        range_layout.addWidget(QLabel("to"))
        range_layout.addWidget(self.color_high)
        form.addRow("Default color range", range_widget)

        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        form.addRow("Default font size", self.font_size)

        self.smoothing = QComboBox()
        for title, value in (("Off (exact)", 0.0), ("Light", 0.02), ("Medium", 0.06), ("Strong", 0.12)):
            self.smoothing.addItem(title, value)
        self.smoothing.setToolTip(
            "Interpolation smoothing. Exact passes through every measured point; a light value "
            "calms the contour wiggles an exact spline produces between sparse samples."
        )
        form.addRow("Interpolation smoothing", self.smoothing)

        self.opacity = QComboBox()
        for percent in (100, 90, 80, 70, 60, 50):
            self.opacity.addItem(f"{percent}%", percent)
        self.opacity.setToolTip("Default fill opacity of the wafer maps.")
        form.addRow("Map opacity", self.opacity)

        self.min_rsq = QDoubleSpinBox()
        self.min_rsq.setRange(0, 1)
        self.min_rsq.setDecimals(2)
        self.min_rsq.setSingleStep(0.05)
        form.addRow("Minimum R²", self.min_rsq)

        self.recovery_interval = QDoubleSpinBox()
        self.recovery_interval.setDecimals(0)
        self.recovery_interval.setRange(30, 1800)
        self.recovery_interval.setSingleStep(30)
        self.recovery_interval.setSuffix(" s")
        self.recovery_interval.setKeyboardTracking(False)
        self.recovery_interval.setToolTip(
            "Interval between recovery draft checks (30 seconds to 30 minutes). "
            "This does not save the original file. A longer interval can lose more recent edits after a crash."
        )
        form.addRow("Recovery interval", self.recovery_interval)

        self.point_values = QCheckBox("Show point values by default")
        self.measurement_points = QCheckBox("Show measurement points by default")
        self.fill_edge = QCheckBox("Fill edge by default")
        self.shared_scale = QCheckBox("Shared scale by default")
        self.scale_bar = QCheckBox("Scale bar by default")
        self.contour = QCheckBox("Contour lines by default")
        self.point_outline = QCheckBox("Outline measured points by default")
        for control in (self.point_values, self.measurement_points, self.fill_edge,
                        self.shared_scale, self.scale_bar, self.contour, self.point_outline):
            form.addRow(control)

        buttons = QHBoxLayout()
        save = QPushButton("Save", objectName="primary")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)
        self._update_from(get_settings())

    def _update_from(self, settings):
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.get("theme", "dark"))))
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.color_map.setCurrentIndex(max(0, self.color_map.findData(settings.get("color_map", "turbo"))))
        self.color_low.setValue(100 * float(settings.get("color_range_low", 0.0)))
        self.color_high.setValue(100 * float(settings.get("color_range_high", 1.0)))
        self.font_size.setCurrentIndex(max(0, self.font_size.findText(str(settings.get("font_size", 10)))))
        self.smoothing.setCurrentIndex(max(0, self.smoothing.findData(float(settings.get("smoothing", 0.06)))))
        self.opacity.setCurrentIndex(max(0, self.opacity.findData(int(settings.get("opacity", 100)))))
        self.min_rsq.setValue(float(settings.get("min_rsq", 0.50)))
        self.recovery_interval.setValue(settings.get("recovery_interval_seconds", 120))
        self.point_values.setChecked(bool(settings.get("point_values", True)))
        self.measurement_points.setChecked(bool(settings.get("measurement_points", True)))
        self.fill_edge.setChecked(bool(settings.get("fill_edge", True)))
        self.shared_scale.setChecked(bool(settings.get("shared_scale", False)))
        self.scale_bar.setChecked(bool(settings.get("scale_bar", True)))
        self.contour.setChecked(bool(settings.get("contour", False)))
        self.point_outline.setChecked(bool(settings.get("point_outline", False)))

    def _collect(self):
        low = self.color_low.value() / 100
        high = self.color_high.value() / 100
        if high - low < 0.03:
            high = min(1.0, low + 0.03)
            low = max(0.0, high - 0.03)
        return {
            "theme": self.theme.currentData(),
            "resolution": self.resolution.currentText(),
            "color_map": self.color_map.currentData(),
            "color_range_low": round(low, 4),
            "color_range_high": round(high, 4),
            "font_size": int(self.font_size.currentText()),
            "smoothing": float(self.smoothing.currentData()),
            "opacity": int(self.opacity.currentData()),
            "min_rsq": round(self.min_rsq.value(), 2),
            "recovery_interval_seconds": int(self.recovery_interval.value()),
            "point_values": self.point_values.isChecked(),
            "measurement_points": self.measurement_points.isChecked(),
            "fill_edge": self.fill_edge.isChecked(),
            "shared_scale": self.shared_scale.isChecked(),
            "scale_bar": self.scale_bar.isChecked(),
            "contour": self.contour.isChecked(),
            "point_outline": self.point_outline.isChecked(),
        }

    def save(self):
        save_settings(self._collect())
        from .workspace_document import apply_recovery_settings
        apply_recovery_settings()
        self.accept()


__all__ = ["SettingsDialog"]

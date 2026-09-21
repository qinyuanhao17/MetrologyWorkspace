"""Small settings dialog for persistent application preferences."""

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QPushButton, QVBoxLayout,
)

from .settings import get_settings, load_settings, save_settings


COLOR_MAPS = [
    ("Viridis", "viridis"),
    ("Turbo", "turbo"),
    ("Plasma", "plasma"),
    ("Jet", "jet"),
    ("Coolwarm", "coolwarm"),
    ("Spectral", "Spectral_r"),
]


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
        for title, name in COLOR_MAPS:
            self.color_map.addItem(title, name)
        form.addRow("Default color map", self.color_map)

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
        load = QPushButton("Load from YAML")
        save = QPushButton("Save", objectName="primary")
        cancel = QPushButton("Cancel")
        load.clicked.connect(self.load_from_yaml)
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(load)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)
        self.load_from_yaml()

    def _update_from(self, settings):
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.get("theme", "dark"))))
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.color_map.setCurrentIndex(max(0, self.color_map.findData(settings.get("color_map", "turbo"))))
        self.font_size.setCurrentIndex(max(0, self.font_size.findText(str(settings.get("font_size", 10)))))
        self.smoothing.setCurrentIndex(max(0, self.smoothing.findData(float(settings.get("smoothing", 0.06)))))
        self.opacity.setCurrentIndex(max(0, self.opacity.findData(int(settings.get("opacity", 100)))))
        self.min_rsq.setValue(float(settings.get("min_rsq", 0.50)))
        self.point_values.setChecked(bool(settings.get("point_values", True)))
        self.measurement_points.setChecked(bool(settings.get("measurement_points", True)))
        self.fill_edge.setChecked(bool(settings.get("fill_edge", True)))
        self.shared_scale.setChecked(bool(settings.get("shared_scale", False)))
        self.scale_bar.setChecked(bool(settings.get("scale_bar", True)))
        self.contour.setChecked(bool(settings.get("contour", False)))
        self.point_outline.setChecked(bool(settings.get("point_outline", False)))

    def _collect(self):
        return {
            "theme": self.theme.currentData(),
            "resolution": self.resolution.currentText(),
            "color_map": self.color_map.currentData(),
            "font_size": int(self.font_size.currentText()),
            "smoothing": float(self.smoothing.currentData()),
            "opacity": int(self.opacity.currentData()),
            "min_rsq": round(self.min_rsq.value(), 2),
            "point_values": self.point_values.isChecked(),
            "measurement_points": self.measurement_points.isChecked(),
            "fill_edge": self.fill_edge.isChecked(),
            "shared_scale": self.shared_scale.isChecked(),
            "scale_bar": self.scale_bar.isChecked(),
            "contour": self.contour.isChecked(),
            "point_outline": self.point_outline.isChecked(),
        }

    def load_from_yaml(self):
        self._update_from(load_settings())

    def save(self):
        save_settings(self._collect())
        self.accept()


__all__ = ["SettingsDialog"]

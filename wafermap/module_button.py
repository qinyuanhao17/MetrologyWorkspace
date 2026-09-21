"""Module button with a compact instance-count badge."""

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton


class ModuleButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("moduleButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)
        self.title_label = QLabel()
        self.title_label.setObjectName("moduleTitle")
        self.state_label = QLabel()
        self.state_label.setObjectName("moduleStateBadge")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setMinimumSize(78, 26)
        for child in (self.title_label, self.state_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.state_label)
        self.glow = QGraphicsDropShadowEffect(self)
        self.glow.setColor(QColor(180, 117, 243, 105))
        self.glow.setOffset(0, 0)
        self.glow.setBlurRadius(0)
        self.setGraphicsEffect(self.glow)
        self.animation = QPropertyAnimation(self.glow, b"blurRadius", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_content(self, title, count=0):
        self.title_label.setText(title)
        self.state_label.setText("UNLOADED" if count == 0 else f"{count} OPEN")
        self.state_label.setProperty("loaded", count > 0)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.setAccessibleName(f"{title}, {count} open" if count else f"{title}, unloaded")

    def animate_glow(self, target):
        self.animation.stop()
        self.animation.setStartValue(self.glow.blurRadius())
        self.animation.setEndValue(float(target))
        self.animation.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.animate_glow(10)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.animate_glow(0)

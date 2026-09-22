"""Typography, theme palette and native Windows frame; no custom window controls."""
import ctypes
import math
import sys
from ctypes import wintypes
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication


# Shared by the live plot control and the persistent Settings dialog.  Keeping
# one list prevents a saved palette from disappearing in one of the two places.
COLOR_MAP_OPTIONS = (
    ("Turbo", "turbo"),
    ("Viridis", "viridis"),
    ("Plasma", "plasma"),
    ("Inferno", "inferno"),
    ("Magma", "magma"),
    ("Cividis", "cividis"),
    ("Rainbow", "rainbow"),
    ("Jet", "jet"),
    ("Coolwarm", "coolwarm"),
    ("Spectral", "Spectral_r"),
    ("Red–Yellow–Blue", "RdYlBu_r"),
    ("Red–Yellow–Green", "RdYlGn"),
    ("Seismic", "seismic"),
)


def configure_fonts(app):
    # Explicit registration also keeps offscreen renders consistent with Windows.
    for name in ("SegUIVar.ttf", "segoeui.ttf", "msyh.ttc"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI Variable", 10))
    set_theme_palette("dark")


def set_theme_palette(theme="dark"):
    """Install a light or dark application palette for widget chrome."""
    app = QApplication.instance()
    if app is None:
        return
    if theme == "light":
        colors = {
            "Window": "#f7f5f9", "WindowText": "#211c26",
            "Base": "#ffffff", "Text": "#211c26",
            "Button": "#ece8f0", "ButtonText": "#211c26",
            "Light": "#ffffff", "Mid": "#c9c0d2", "Dark": "#d8d2e0",
            "Highlight": "#6f3fa0", "HighlightedText": "#ffffff",
        }
    else:
        colors = {
            "Window": "#0d0814", "WindowText": "#e7e0eb",
            "Base": "#100b17", "Text": "#e7e0eb",
            "Button": "#160e21", "ButtonText": "#f4f0f7",
            "Light": "#847392", "Mid": "#51415f", "Dark": "#302538",
            "Highlight": "#6f3fa0", "HighlightedText": "#ffffff",
        }
    palette = QPalette()
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    app.setPalette(palette)


def configure_resolution_combo(combo):
    """Populate the shared screen-supersampling and PNG-resolution control."""
    combo.addItem("Standard", (1.0, 200))
    combo.addItem("High", (1.5, 300))
    combo.addItem("Ultra", (2.0, 400))
    combo.setCurrentIndex(1)
    combo.setFixedWidth(88)
    combo.setToolTip(
        "Standard: 100% screen render / 200 dpi PNG\n"
        "High: 150% screen render / 300 dpi PNG (default)\n"
        "Ultra: 200% screen render / 400 dpi PNG"
    )


def resolution_settings(combo):
    value = combo.currentData()
    return value if isinstance(value, tuple) and len(value) == 2 else (1.5, 300)


def screen_render_scale(width, height, requested, max_pixels=8_000_000):
    """Cap large interactive canvases without changing PNG export resolution."""
    pixels = max(1.0, float(width) * float(height))
    return min(float(requested), max(1.0, math.sqrt(max_pixels / pixels)))


def style_titlebar(window, theme="dark"):
    if sys.platform != "win32":
        return
    try:
        function = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        function.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD]
        function.restype = ctypes.c_long
        if theme == "light":
            # Immersive dark mode off; light caption/border with near-black text.
            attributes = ((20, 0), (34, 0x00F8F7F7), (35, 0x00E6E3E3), (36, 0x001F1F1F))
        else:
            attributes = ((20, 1), (34, 0x34222C), (35, 0x14080D), (36, 0xF7F0F4))
        for attribute, value in attributes:
            data = wintypes.DWORD(value)
            function(wintypes.HWND(int(window.winId())), attribute, ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, AttributeError):
        pass

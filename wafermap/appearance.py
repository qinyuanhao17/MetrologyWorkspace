"""Typography, theme palette and native Windows frame; no custom window controls."""
import ctypes
import math
import sys
from ctypes import wintypes
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QLabel


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


def screen_render_scale(width, height, requested, max_pixels=8_000_000,
                        max_scale=None):
    """Cap large interactive canvases without changing PNG export resolution."""
    pixels = max(1.0, float(width) * float(height))
    # Supersampling keeps zoomed-in maps crisp; the checkbox toggles no longer
    # repaint the whole canvas, so the extra pixels only cost on full redraws.
    limit = float(requested) if max_scale is None else min(float(requested), float(max_scale))
    return min(limit, max(1.0, math.sqrt(max_pixels / pixels)))


MAX_COPY_PIXELS = 25_000_000    # clipboard images must stay pasteable
MAX_EXPORT_PIXELS = 64_000_000  # files may be larger, but not unlimited


def export_dpi(figure, requested_dpi, max_pixels=MAX_EXPORT_PIXELS, min_dpi=100):
    """Lower the DPI when a figure would otherwise become impractically large.

    A fifteen panel Die Seq array covers roughly a thousand square inches; at
    400 dpi that is a 160 megapixel image, which froze (and sometimes failed)
    the copy and export paths. The DPI is scaled down until the raster fits the
    budget, never below ``min_dpi``.
    """
    width, height = figure.get_size_inches()
    pixels = max(1.0, float(width) * float(height) * float(requested_dpi) ** 2)
    if pixels <= max_pixels:
        return int(requested_dpi)
    scale = math.sqrt(float(max_pixels) / pixels)
    return max(int(min_dpi), int(requested_dpi * scale))


def widget_to_qimage(widget, requested_scale, max_pixels=MAX_COPY_PIXELS):
    """Render a complete Qt plot grid directly into a high-resolution image.

    Correlation and Trend already own a vector-sharp PyQtGraph grid containing
    every panel, including the rows outside the scroll viewport.  Rendering
    that widget avoids building a second Matplotlib figure, PNG-compressing it,
    and immediately decoding the PNG for the clipboard.  The returned scale is
    capped by the same pixel budget used by the other Copy PNG paths.
    """
    width, height = max(1, widget.width()), max(1, widget.height())
    pixels = float(width) * float(height)
    scale = min(float(requested_scale), math.sqrt(float(max_pixels) / pixels))
    scale = max(0.1, scale)
    target_width = max(1, round(width * scale))
    target_height = max(1, round(height * scale))
    image = QImage(target_width, target_height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        painter.setRenderHints(QPainter.RenderHint.Antialiasing |
                               QPainter.RenderHint.TextAntialiasing |
                               QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(scale, scale)
        widget.render(painter)
    finally:
        painter.end()
    if image.isNull():
        raise ValueError("unable to build the clipboard image")
    return image, scale


def panel_title_label(html, base_size=10):
    """Centred multi-line title for a PyQtGraph panel.

    A plain QLabel above the plot replaces ``PlotItem.setTitle``: Qt's own title
    label reserves a single line of height (so a two-line title printed over the
    plot area) and shrinks a text block to its longest line (so a short heading
    looked off-centre). A QLabel centres every line and keeps its own space.
    """
    label = QLabel(objectName="panelTitle")
    label.setText(html)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    label.setWordWrap(False)
    label.setStyleSheet(f"color: #20242a; font-size: {base_size}pt;")
    return label


def frame_plot_axes(plot_item, tick_length=0, colour="#30343b"):
    """Show the top and right axes so a panel keeps the export's four-sided frame."""
    for name in ("top", "right"):
        axis = plot_item.getAxis(name)
        axis.setStyle(showValues=False, tickLength=tick_length)
        axis.setPen(pg.mkPen(colour))
        axis.setTextPen(pg.mkPen(colour))
        plot_item.showAxis(name)


def fit_window_to_screen(window, preferred, minimum=None, margin=28, offset=(0, 0), screen=None):
    """Size and centre a window inside the part of the display the taskbar leaves free.

    ``preferred`` is the ideal size; it is clamped to the current screen's
    available geometry so the window is never wider than the display or hidden
    behind the taskbar on a smaller or high-DPI screen. The minimum size is
    lowered by the same amount, otherwise Qt would refuse the clamp.
    """
    screen = screen or window.screen() or QApplication.primaryScreen()
    if screen is None:
        window.resize(*preferred)
        return window.geometry()
    area = screen.availableGeometry()
    width = max(420, min(int(preferred[0]), area.width() - 2 * margin))
    height = max(320, min(int(preferred[1]), area.height() - 2 * margin))
    if minimum:
        window.setMinimumSize(min(int(minimum[0]), width), min(int(minimum[1]), height))
    window.resize(width, height)
    x = area.x() + (area.width() - width) // 2 + offset[0]
    y = area.y() + (area.height() - height) // 2 + offset[1]
    window.move(max(area.x(), min(x, area.right() - width + 1)),
                max(area.y(), min(y, area.bottom() - height + 1)))
    return window.geometry()


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

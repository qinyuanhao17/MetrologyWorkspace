"""Persistent application settings loaded from and saved to a YAML file."""

from pathlib import Path
import sys

import yaml


APP_DIRECTORY = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                 else Path(__file__).resolve().parent.parent)
SETTINGS_PATH = APP_DIRECTORY / "settings.yaml"

DEFAULTS = {
    "theme": "dark",
    "resolution": "High",
    "color_map": "turbo",
    "color_range_low": 0.1019607843,
    "color_range_high": 0.8627450980,
    "font_size": 10,
    "fill_edge": True,
    "shared_scale": False,
    "point_values": True,
    "measurement_points": True,
    "scale_bar": True,
    "contour": False,
    "point_outline": False,
    "smoothing": 0.06,
    "opacity": 100,
    "min_rsq": 0.50,
}

_current = dict(DEFAULTS)


def load_settings(path=SETTINGS_PATH):
    """Read settings from YAML, keeping unknown or missing keys at their defaults."""
    _current.clear()
    _current.update(DEFAULTS)
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                _current.update({key: value for key, value in data.items() if key in DEFAULTS})
        except (OSError, yaml.YAMLError):
            pass
    return dict(_current)


def save_settings(data, path=SETTINGS_PATH):
    """Validate, persist and activate a settings mapping."""
    for key in DEFAULTS:
        if key in data:
            _current[key] = data[key]
    path.write_text(yaml.safe_dump(_current, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dict(_current)


def get_settings():
    """Return the in-memory settings, loading defaults if none were loaded yet."""
    if not _current:
        return load_settings()
    return dict(_current)


def theme_stylesheet(theme=None):
    """Return the Qt stylesheet for the requested theme."""
    theme = theme or get_settings()["theme"]
    folder = Path(__file__).parent
    filename = "theme_light.qss" if theme == "light" else "theme.qss"
    style = (folder / filename).read_text(encoding="utf-8")
    assets = folder / "assets"
    replacements = {
        "__ARROW_DOWN__": (assets / f"arrow_down_{theme}.png").as_posix(),
        "__ARROW_UP__": (assets / f"arrow_up_{theme}.png").as_posix(),
        "__CHECK__": (assets / "check_white.png").as_posix(),
    }
    if theme != "light":
        replacements["__ATMOSPHERE__"] = (assets / "atmosphere.png").as_posix()
    for token, value in replacements.items():
        style = style.replace(token, value)
    return style


def apply_theme(widget, theme=None):
    """Apply the current or requested theme stylesheet to a top-level widget."""
    widget.setStyleSheet(theme_stylesheet(theme))


__all__ = [
    "DEFAULTS", "SETTINGS_PATH", "get_settings", "load_settings", "save_settings",
    "theme_stylesheet", "apply_theme",
]

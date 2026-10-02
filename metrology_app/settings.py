"""Persistent application settings loaded from and saved to a YAML file."""

from pathlib import Path
import os
import sys

import yaml


APP_DIRECTORY = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                 else Path(__file__).resolve().parent.parent / "config")
# The settings file holds user state (theme, recent workbooks). Tooling and the
# test suite point METROLOGY_SETTINGS_PATH at a scratch copy so a run can never
# rewrite the file the application is using.
SETTINGS_PATH = (Path(os.environ["METROLOGY_SETTINGS_PATH"]).expanduser()
                 if os.environ.get("METROLOGY_SETTINGS_PATH")
                 else APP_DIRECTORY / "settings.yaml")
MAX_RECENT_WKBS = 10

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
    "shell_splitter_sizes": None,
    "recent_wkbs": [],
    "trend_overlay": {},
}

_current = dict(DEFAULTS)
# Which file _current actually came from. Saving writes the whole mapping, so a
# process that never loaded a file must load it before its first save; otherwise
# a helper script or a test would replace the saved theme and recent WKB list
# with defaults.
_loaded_path = None


def load_settings(path=SETTINGS_PATH):
    """Read settings from YAML, keeping unknown or missing keys at their defaults."""
    global _loaded_path
    path = Path(path)
    _current.clear()
    _current.update(DEFAULTS)
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                _current.update({key: value for key, value in data.items() if key in DEFAULTS})
        except (OSError, yaml.YAMLError):
            pass
    _loaded_path = path
    return dict(_current)


def save_settings(data, path=SETTINGS_PATH):
    """Validate, persist and activate a settings mapping."""
    path = Path(path)
    if _loaded_path != path:
        load_settings(path)
    for key in DEFAULTS:
        if key in data:
            _current[key] = data[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_current, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dict(_current)


def get_settings():
    """Return the in-memory settings, loading defaults if none were loaded yet."""
    if not _current:
        return load_settings()
    return dict(_current)


def _normalized_recent_wkbs(values, limit=MAX_RECENT_WKBS):
    """Return unique absolute WKB paths while preserving recency order."""
    paths = []
    seen = set()
    for value in values or ():
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            continue
        path = Path(value).expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
        if len(paths) >= limit:
            break
    return tuple(paths)


def recent_wkb_paths(settings_path=SETTINGS_PATH):
    """Load the persisted recent WKB list, newest first."""
    settings = load_settings(settings_path)
    return _normalized_recent_wkbs(settings.get("recent_wkbs"))


def remember_recent_wkb(path, *, settings_path=SETTINGS_PATH, limit=MAX_RECENT_WKBS):
    """Move a WKB path to the front of the persisted recent-file list."""
    settings = load_settings(settings_path)
    recent = _normalized_recent_wkbs(
        (path, *settings.get("recent_wkbs", ())), limit=limit
    )
    settings["recent_wkbs"] = [str(item) for item in recent]
    save_settings(settings, settings_path)
    return recent


def forget_recent_wkb(path, *, settings_path=SETTINGS_PATH):
    """Remove one WKB path from the persisted recent-file list."""
    settings = load_settings(settings_path)
    target = os.path.normcase(str(Path(path).expanduser().resolve()))
    recent = tuple(
        item
        for item in _normalized_recent_wkbs(settings.get("recent_wkbs"))
        if os.path.normcase(str(item)) != target
    )
    settings["recent_wkbs"] = [str(item) for item in recent]
    save_settings(settings, settings_path)
    return recent


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
    "DEFAULTS", "MAX_RECENT_WKBS", "SETTINGS_PATH", "forget_recent_wkb",
    "get_settings", "load_settings", "recent_wkb_paths", "remember_recent_wkb",
    "save_settings", "theme_stylesheet", "apply_theme",
]

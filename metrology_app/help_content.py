"""Editable, local Markdown help with an independently maintained YAML tree."""
from dataclasses import dataclass
from pathlib import Path
import sys

import yaml


def help_directory():
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / "help"
        if external.is_dir():
            return external
    return Path(__file__).resolve().parent.parent / "help"


def resolve_help_file(root, filename):
    """Resolve portable links relative to the help folder, never the process cwd."""
    root = Path(root).resolve()
    if not isinstance(filename, str) or not filename.strip() or Path(filename).is_absolute():
        raise ValueError("Help file paths must be non-empty paths relative to the help folder.")
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Help file is outside the help folder: {filename}")
    if path.suffix.lower() not in {".md", ".markdown", ".mkd", ".html", ".htm"}:
        raise ValueError(f"Unsupported help page format: {filename}")
    return path


@dataclass(frozen=True)
class HelpTopic:
    title: str
    file: Path | None
    children: tuple


@dataclass(frozen=True)
class HelpContents:
    root: Path
    home: Path
    topics: tuple


def load_help_contents(directory=None):
    root = Path(directory if directory is not None else help_directory()).resolve()
    try:
        state = yaml.safe_load((root / "toc.yaml").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot read {root / 'toc.yaml'}:\n{error}") from error
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("toc.yaml must contain version: 1 and a topics list.")

    def topics(values, depth=0):
        if not isinstance(values, list) or depth > 32:
            raise ValueError("Help topics/children must be lists, with at most 32 nested levels.")
        result = []
        for value in values:
            if (not isinstance(value, dict) or not isinstance(value.get("title"), str)
                    or not value["title"].strip()):
                raise ValueError("Each Help topic needs a non-empty title.")
            page = resolve_help_file(root, value["file"]) if value.get("file") is not None else None
            result.append(HelpTopic(value["title"].strip(), page,
                                    topics(value.get("children", []), depth + 1)))
        return tuple(result)

    home = resolve_help_file(root, state.get("home", "pages/welcome.md"))
    return HelpContents(root, home, topics(state.get("topics", [])))

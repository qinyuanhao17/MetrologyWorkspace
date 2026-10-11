"""Named child identities, independent of display names and Qt widgets."""
import re

LABELS = {"correlation": "Correlation and Trend", "dynamic": "Dynamic", "map": "Wafer Map / Radius"}


def scope_parts(scope):
    parts = str(scope).split(".")
    if (len(parts) not in (2, 3) or parts[0] not in LABELS or parts[-1] not in ("preview", "final")
            or (len(parts) == 3 and re.fullmatch(r"[0-9a-f]{32}", parts[1]) is None)):
        raise ValueError("Invalid named analysis window identity.")
    return parts[0], parts[-1]


def window_metadata(scope, state):
    kind, _stage = scope_parts(scope)
    metadata = state.get("window", {"name": LABELS[kind] + " 1", "checked": True})
    if (not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str)
            or not metadata["name"].strip() or any(char in metadata["name"] for char in "\r\n\0")
            or type(metadata.get("checked")) is not bool):
        raise ValueError("Invalid named analysis window settings.")
    return metadata


def window_entries(states, kind, stage):
    return [(scope, window_metadata(scope, state)) for scope, state in states.items()
            if scope.startswith(kind + ".") and scope_parts(scope) == (kind, stage)]


def validate_windows(states):
    seen = set()
    for scope, state in states.items():
        if "window" not in state:
            continue
        kind, stage = scope_parts(scope)
        metadata = window_metadata(scope, state)
        key = kind, stage, metadata["name"].strip().casefold()
        if key in seen:
            raise ValueError("Analysis window names must be unique within each tool and stage.")
        seen.add(key)

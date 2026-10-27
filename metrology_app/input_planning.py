"""Pure measurement/group preparation for owned linked-source snapshots."""
from .data import inspect_table
from .measurements import default_identity_columns, detect_measurements


def prepare_measurement_choices(frame, reset=True, previous_groups=(), *, include_fit_quality=True):
    detected_wafer, counts, metrics = inspect_table(
        frame, include_fit_quality=include_fit_quality
    )
    normalize = lambda name: "".join(ch.lower() for ch in str(name) if ch.isalnum())
    excluded = {"fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey",
                "dieseq", "diesequence", "diesequenceno"}
    hints = ("wafer", "lot", "pad", "sample", "id", "name", "tool", "recipe", "group", "run", "batch")
    candidates = [c for c in frame if (c not in metrics or any(h in normalize(c) for h in hints))
                  and normalize(c) not in excluded and "path" not in c.lower()]
    if reset:
        defaults = {"waferid", "wafer", "waferno", "lotid", "lot", "lotno", "padname", "pad"}
        lot_column = next((c for c in candidates if normalize(c) in {"lotid", "lot", "lotno"}), None)
        pad_column = next((c for c in candidates if normalize(c) in {"padname", "pad"}), None)
        identity = default_identity_columns(frame, detected_wafer, lot_column, pad_column)
        if identity:
            # One wafer ID is enough when PAD/Lot stay constant; PAD joins
            # the identity only when it really splits the same wafer.
            chosen_groups = [c for c in candidates if c in identity]
        else:
            chosen_groups = [c for c in candidates if normalize(c) in defaults]
        if detected_wafer and detected_wafer not in chosen_groups:
            chosen_groups.insert(0, detected_wafer)
    else:
        chosen_groups = [c for c in candidates if c in previous_groups]
    primary = next((c for c in chosen_groups if normalize(c) in {"waferid", "wafer", "waferno"}),
                   chosen_groups[0] if chosen_groups else None)
    if not primary:
        counts = {}
    elif primary != detected_wafer:
        _, counts, _ = inspect_table(frame, primary)
    measurements = detect_measurements(frame, primary, chosen_groups, use_die_seq=False)
    return counts, metrics, candidates, chosen_groups, primary, measurements

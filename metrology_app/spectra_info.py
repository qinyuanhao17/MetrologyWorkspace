"""Pair SME metadata to original Workbook rows without changing source data."""
from collections import defaultdict
from dataclasses import dataclass
import re

import pandas as pd

from .match_groups import normalized
from .selection_script import canonical_die


INFO_COLUMNS = ("Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq",
                "Relative Column", "Relative Row", "Time", "Type")


@dataclass(frozen=True)
class SpectraInfo:
    with_flags: pd.DataFrame
    source_rows: tuple[int, ...]
    issues: tuple[str, ...]

    @property
    def without_flags(self):
        return self.with_flags.drop(columns="Test Flag")


def spectrum_time(spectrum):
    """Use the time read from SME metadata, never its external file's mtime."""
    text = str(spectrum.identity.timestamp or "").strip()
    if re.fullmatch(r"\d{17}", text):
        return text
    if re.fullmatch(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d{1,3})?", text):
        return re.sub(r"\D", "", text).ljust(17, "0")
    return text


def _filename_time(value):
    name = re.split(r"[/\\]", str(value))[-1]
    match = re.search(r"(\d{17})(?:\(\d+\))?\.sme$", name, re.I)
    return match[1] if match else ""


def _text(value):
    return "" if pd.isna(value) else str(value).strip()


def build_spectra_info(raw, reference, spectra, *, checked_keys, visible_keys=None,
                       verify_timestamp=True, flags=None):
    """Return export-ready visible rows and all selected-source pairing errors.

    Matching uses Wafer/Lot/PAD/Die/FIELD X/FIELD Y, optionally disambiguated by
    the filename time from Raw Data. Each required SME must match exactly one
    raw row and no two required SMEs may consume the same row.
    """
    spectra = tuple(spectra)
    visible = {s.key for s in spectra} if visible_keys is None else set(visible_keys)
    required = set(checked_keys) | visible
    flags = flags or {}
    columns = {normalized(c): c for c in raw}
    names = ("waferid", "lotid", "padname", "dieseq", "fieldx", "fieldy")
    missing = [name for name in names if name not in columns]
    if missing:
        raise ValueError("Raw Data is missing matching columns: " + ", ".join(missing))
    index = defaultdict(list)
    for row, values in enumerate(raw[[columns[name] for name in names]].itertuples(index=False, name=None)):
        key = tuple(_text(v) if i < 3 else canonical_die(_text(v)) for i, v in enumerate(values))
        index[key].append(row)
    paths = raw[columns["cursmefilepath"]].tolist() if "cursmefilepath" in columns else [""] * len(raw)
    pairs, issues = defaultdict(list), []
    for source in spectra:
        if source.key not in required:
            continue
        identity = source.identity
        label = f"{identity.wafer} / {identity.lot} / {identity.pad} / Die {identity.die_seq} ({source.path.name})"
        key = (identity.wafer.strip(), identity.lot.strip(), identity.pad.strip(),
               canonical_die(identity.die_seq), canonical_die(identity.field_x), canonical_die(identity.field_y))
        candidates = index.get(key, ())
        if not candidates:
            issues.append(f"No Raw Data match: {label}; check Wafer/Lot/PAD/Die/FIELD X/FIELD Y.")
            continue
        if verify_timestamp:
            time = spectrum_time(source)
            candidates = [row for row in candidates if re.fullmatch(r"\d{17}", time) and _filename_time(paths[row]) == time]
            if not candidates:
                issues.append(f"Timestamp mismatch or missing timestamp: {label}; SME time {time or '(missing)' }.")
                continue
        if len(candidates) != 1:
            issues.append(f"Ambiguous Raw Data match ({len(candidates)} rows): {label}.")
            continue
        pairs[candidates[0]].append(source)
    records, rows = [], []
    ref_columns = list(reference.columns)
    for row, sources in sorted(pairs.items()):
        if len(sources) != 1:
            issues.append(f"Ambiguous spectra: {len(sources)} files match Raw Data row {row + 1}; select one measurement.")
            continue
        source = sources[0]
        if source.key not in visible:
            continue
        identity = source.identity
        records.append([identity.wafer, identity.lot, identity.tool_sn, identity.pad, identity.die_seq,
                        identity.field_x, identity.field_y, spectrum_time(source), "Accuracy",
                        *[reference.iat[row, i] if row < len(reference) else "" for i in range(len(ref_columns))],
                        flags.get(source.key, 0)])
        rows.append(row)
    return SpectraInfo(pd.DataFrame(records, columns=[*INFO_COLUMNS, *ref_columns, "Test Flag"]),
                       tuple(rows), tuple(issues))

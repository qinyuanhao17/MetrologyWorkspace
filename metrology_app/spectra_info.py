"""Pair SME metadata to original Workbook rows without changing source data."""
from collections import defaultdict
from dataclasses import dataclass
import re

import pandas as pd

from .match_groups import normalized
from .selection_script import canonical_die


INFO_COLUMNS = ("Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq",
                "Relative Column", "Relative Row", "Time", "Type")
XY_COLUMNS = ("Wafer ID", "Lot ID", "PAD Name", "Die Seq", "FIELD X", "FIELD Y", "X(mm)", "Y(mm)")
REQUIRED_REPORT_COLUMNS = frozenset((*INFO_COLUMNS, "Test Flag"))
_REPORT_FIELD_KEYS = {normalized(name) for name in REQUIRED_REPORT_COLUMNS} | {
    "wafer", "waferno", "wafernumber", "lot", "lotno", "lotnumber", "toolserialnumber", "pad",
    "seq", "diesequence", "diesequenceno", "dieid", "fieldx", "fieldy", "colx", "rowy", "refdiecol", "refdierow",
}


def normalize_info_column_choices(hidden, included=()):
    """Keep the Spectra Info projection authoritative for both report variants."""
    report = set(hidden[0]) - REQUIRED_REPORT_COLUMNS
    return ([report, set(report), set(hidden[2]) - REQUIRED_REPORT_COLUMNS],
            set(included) - REQUIRED_REPORT_COLUMNS - report)


@dataclass(frozen=True)
class SpectraInfo:
    with_flags: pd.DataFrame
    source_rows: tuple[int, ...]
    issues: tuple[str, ...]
    xy: pd.DataFrame
    raw_order: bool = True
    spectrum_keys: tuple[str, ...] = ()
    available_reference_columns: tuple[str, ...] = ()

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


def _raw_pairs(raw, spectra, required, verify_timestamp, *, coordinates=True):
    """Pair each selected SME once, retaining original Raw Data row positions."""
    columns = {normalized(c): c for c in raw}
    if "dieseq" not in columns and "seq" in columns:
        columns["dieseq"] = columns["seq"]
    names = ("waferid", "lotid", "padname", "dieseq")
    if coordinates:
        names += ("fieldx", "fieldy")
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
               canonical_die(identity.die_seq))
        if coordinates:
            key += (canonical_die(identity.field_x), canonical_die(identity.field_y))
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
    return sorted(pairs.items()), issues


def group_rows_in_raw_order(raw, spectra, *, verify_timestamp=True):
    """Project matched spectra onto Raw order and retain all remaining spectra."""
    if raw is None or raw.empty or not raw.columns.is_unique or not spectra:
        return None
    columns = {normalized(column) for column in raw}
    positions = {source.key: row for row, source in enumerate(spectra)}
    try:
        pairs, _ = _raw_pairs(raw, spectra, positions, verify_timestamp and "cursmefilepath" in columns,
                              coordinates={"fieldx", "fieldy"} <= columns)
    except ValueError:
        return None
    ordered = [positions[sources[0].key] for _, sources in pairs if len(sources) == 1]
    if not ordered:
        return None
    matched = set(ordered)
    return (*ordered, *(row for row in range(len(spectra)) if row not in matched))


def build_spectra_info(raw, reference, spectra, *, checked_keys, visible_keys=None,
                       verify_timestamp=True, flags=None, reference_columns=None):
    """Return original Raw-order tables, or natural SME order without Raw Data.

    Matching uses Wafer/Lot/PAD/Die/FIELD X/FIELD Y, optionally disambiguated by
    the filename time from Raw Data. Each required SME must match exactly one
    raw row and no two required SMEs may consume the same row. With no Raw Data,
    source_rows refers to the input spectra positions; Reference is not paired.
    XY always comes from SME coordinates, with missing values left empty.
    """
    spectra = tuple(spectra)
    visible = {s.key for s in spectra} if visible_keys is None else set(visible_keys)
    required = set(checked_keys) | visible
    flags = flags or {}
    raw_order = raw is not None and not raw.empty
    if raw_order:
        pairs, issues = _raw_pairs(raw, spectra, required, verify_timestamp)
    else:
        pairs = [(row, [source]) for row, source in sorted(enumerate(spectra), key=lambda item: item[1].sort_key)
                 if source.key in required]
        issues, reference = [], pd.DataFrame()
    records, rows, coordinates, keys = [], [], [], []
    # SME metadata owns these report fields even when Reference supplies aliases.
    ref_positions = []
    for column, name in enumerate(reference.columns):
        key = normalized(name)
        if key not in _REPORT_FIELD_KEYS and key.removeprefix("ref") not in _REPORT_FIELD_KEYS:
            ref_positions.append(column)
    available_reference_columns = tuple(reference.columns[column] for column in ref_positions)
    if reference_columns is not None:
        ref_positions = [column for column in ref_positions if reference.columns[column] in reference_columns]
    reference = reference.iloc[:, ref_positions]
    ref_columns = list(reference.columns)
    for row, sources in pairs:
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
        coordinates.append([identity.wafer, identity.lot, identity.pad, identity.die_seq,
                            identity.field_x, identity.field_y, source.x_mm, source.y_mm])
        rows.append(row)
        keys.append(source.key)
    return SpectraInfo(pd.DataFrame(records, columns=[*INFO_COLUMNS, *ref_columns, "Test Flag"]),
                       tuple(rows), tuple(issues), pd.DataFrame(coordinates, columns=XY_COLUMNS),
                       raw_order, tuple(keys), available_reference_columns)

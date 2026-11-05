"""Source-preserving REF aggregation and Excel export without Qt dependencies."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile

import pandas as pd

from .ref_parsers import PARSER_MAP


@dataclass(frozen=True)
class RefSummary:
    vendor: str
    directory: str
    file_count: int
    successful_files: int
    errors: tuple
    frame: pd.DataFrame
    by_pad: dict | None

    @property
    def wafer_count(self):
        column = next((name for name in ("WaferID", "Wafer_ID", "Wafer ID") if name in self.frame), None)
        if column is None:
            return 0
        values = self.frame[column].fillna("").astype(str).str.strip()
        return int(values[values.ne("")].nunique())


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError("Cancelled")


def scan_data_files(directory, *, cancelled=None):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("Choose an existing REF data folder.")
    def scan_error(error):
        raise error
    files = []
    for root, _directories, names in os.walk(directory, onerror=scan_error):
        _check_cancelled(cancelled)
        files.extend(Path(root) / name for name in names if Path(name).suffix.lower() in {".csv", ".txt"})
    return sorted(files)


def summarize_ref(directory, vendor, *, cancelled=None, progress=None):
    """Concatenate files in source order, retaining the example's PAD grouping."""
    if vendor not in PARSER_MAP:
        raise ValueError(f"Unknown REF vendor: {vendor}")
    files = scan_data_files(directory, cancelled=cancelled)
    if not files:
        raise ValueError("No CSV or TXT data files were found in this folder or its subfolders.")
    if progress:
        progress(0, len(files), f"Found {len(files):,} files · parsing {vendor}…")
    frames, pads, errors = [], {}, []
    successful = 0
    for index, path in enumerate(files, 1):
        _check_cancelled(cancelled)
        try:
            result = PARSER_MAP[vendor](str(path))
            tables = result if isinstance(result, dict) else {None: result}
            usable = {pad: table for pad, table in tables.items()
                      if table is not None and not table.empty}
            if not usable:
                raise ValueError("No data records found")
            for table in usable.values():
                if not table.columns.is_unique:
                    raise ValueError("Duplicate column names after removing header units")
            for pad, table in usable.items():
                if isinstance(result, dict):
                    pads.setdefault(pad, []).append(table)
                else:
                    frames.append(table)
            successful += 1
            message = f"Parsed · {path}"
        except Exception as error:
            message = f"Skipped · {path}: {error}"
            errors.append(message)
        if progress:
            progress(index, len(files), message)
    _check_cancelled(cancelled)
    by_pad = {pad: pd.concat(tables, ignore_index=True) for pad, tables in pads.items()} if pads else None
    sources = list(by_pad.values()) if by_pad is not None else frames
    frame = pd.concat(sources, ignore_index=True) if sources else pd.DataFrame()
    return RefSummary(vendor, str(directory), len(files), successful, tuple(errors), frame, by_pad)


def _sheet_title(value, used):
    title = re.sub(r"[\[\]:*?/\\\x00-\x1f]", "_", str(value)).strip().strip("'")[:31] or "Unnamed PAD"
    candidate, index = title, 2
    while candidate.casefold() in used:
        suffix = f" ({index})"
        candidate = title[:31 - len(suffix)] + suffix
        index += 1
    used.add(candidate.casefold())
    return candidate


def _export_tables(summary):
    if summary.by_pad is not None:
        return list(summary.by_pad.items())
    frame = summary.frame
    pad_column = next((name for name in ("Pad name", "PadName") if name in frame), None)
    if summary.vendor in {"KLA", "PMISH"} and pad_column:
        tables = []
        for pad, subset in frame.groupby(pad_column, sort=False, dropna=False):
            present = subset.notna() & subset.fillna("").astype(str).ne("")
            tables.append((pad, subset.loc[:, present.any(axis=0)]))
        return tables
    return [("Summary", frame)]


def export_ref_summary(summary, path, *, cancelled=None, progress=None):
    """Write a complete candidate before replacing any existing destination."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    if summary is None or summary.frame.empty:
        raise ValueError("Parse REF data successfully before exporting.")
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    _check_cancelled(cancelled)
    tables, used = _export_tables(summary), set()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            border = Border(**{edge: Side(style="thin") for edge in ("left", "right", "top", "bottom")})
            header_font = Font(size=10, bold=True, color="FFFFFF")
            data_font = Font(size=10, color="000000")
            header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
            header_alignment = Alignment(horizontal="center", vertical="center")
            for index, (name, frame) in enumerate(tables, 1):
                _check_cancelled(cancelled)
                title = _sheet_title(name, used)
                frame.to_excel(writer, sheet_name=title, index=False)
                sheet = writer.sheets[title]
                sheet.freeze_panes = "A2"
                for row_number, row in enumerate(sheet, 1):
                    if row_number % 1000 == 0:
                        _check_cancelled(cancelled)
                    for cell in row:
                        if isinstance(cell.value, str):
                            cell.data_type = "s"
                            cell.number_format = "@"
                        cell.font = header_font if row_number == 1 else data_font
                        if row_number == 1:
                            cell.fill = header_fill
                            cell.alignment = header_alignment
                            cell.border = border
                for position, column in enumerate(frame.columns, 1):
                    longest = max(len(str(column)), int(frame[column].fillna("").astype(str).str.len().max()) if len(frame) else 0)
                    sheet.column_dimensions[get_column_letter(position)].width = min(longest + 2, 30)
                if progress:
                    progress(index, len(tables), f"Exported worksheet · {title}")
        _check_cancelled(cancelled)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path

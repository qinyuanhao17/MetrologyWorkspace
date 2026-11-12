"""Reference Summary - Pandas-first NOVA/PMISH/KLA CSV/Excel batch merging.

Public interface:
    scan_reference_files(folder)
    scan_csv(folder)  # legacy CSV-only discovery
    parse_file(path, vendor, cancelled=None) -> ParsedFile
    merge(vendor, files, output_parent, cancelled=None, progress=None) -> MergeResult

The csv module only locates multi-section boundaries; Pandas reads each data
block (pd.read_csv(StringIO(...))) and does all merging and deduplication.
No source file is modified. Intended for integration in PyQt6 and a tester GUI.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import pandas as pd
from .file_paths import filesystem_path
from .reference_input import SOURCE_EXTENSIONS, check_cancel, decode_csv, reference_text

OUTPUT_FOLDER = "Reference_Summary_Output"
CHANNEL_FIELDS = {
    "NOVA": (),
    "PMISH": ("Recipe", "Metrology unit", "AzimuthAngle"),
    "KLA": ("TestID", "TestLabel"),
}
IDENTITY_FIELDS = ("WaferID", "LotID", "ToolSN", "Recipe", "Slot")
CANONICAL = {
    "waferid": "WaferID", "wafernumber": "WaferID",
    "lotid": "LotID", "lotnumber": "LotID", "toolsn": "ToolSN",
    "toolserialnumber": "ToolSN", "recipe": "Recipe", "slot": "Slot",
    "slotnumber": "Slot", "testid": "TestID", "testnumber": "TestID",
    "testlabel": "TestLabel", "padname": "PadName", "pad": "PadName",
    "metrologyunit": "Metrology unit", "azimuthangle": "AzimuthAngle",
}
SITE_ALIASES = {"site", "siteno", "sitenumber", "sitenum", "siteindex", "siteid"}
SUMMARY_ALIASES = {
    "resulttype", "mean", "min", "max", "average", "stddev", "stdev",
    "std", "standarddeviation", "3sigma", "6sigma", "range", "uniformity",
    "percentstd", "median", "count", "sig", "sigma",
}
PAIR_PATTERN = re.compile(r"^\s*(.+?)\s*[:=]\s*(\S.*?)\s*$")
MISSING = {"", "none", "null", "na", "n/a"}


def compact(text: object) -> str:
    return "".join(ch.casefold() for ch in str(text) if ch.isalnum())


def column_name(text: str, vendor: str) -> str:
    raw = str(text).strip().lstrip("\ufeff")
    if vendor == "KLA" and compact(raw) in SITE_ALIASES:
        return "Site #"
    # Preserve all actual measurement column names and their unit suffixes.
    return CANONICAL.get(compact(raw), raw)


def row_error(path: Path, line: object, kind: str, detail: str) -> dict:
    return {"File": str(path), "CSV line": line, "Kind": kind, "Detail": detail}


def normalized_angle(text: str) -> str:
    value = str(text).strip()
    if value.endswith("°"):
        value = value[:-1].strip()
    if value.casefold().endswith("deg"):
        value = value[:-3].strip()
    try:
        d = Decimal(value)
        if d.is_finite():
            return format(d.normalize(), "f")
    except InvalidOperation:
        pass
    return value




def tokenize_csv(text: str, source_lines=None) -> list[tuple[int, list[str]]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    return [((source_lines or {}).get(reader.line_num,reader.line_num), [cell.strip() for cell in record]) for record in reader]


def metadata_pairs(cells: list[str]) -> dict[str, str]:
    """Extract only known identity/channel keys (not arbitrary numeric data)."""
    result: dict[str, str] = {}
    for index, cell in enumerate(cells):
        token = cell.strip()
        if not token:
            continue
        m = PAIR_PATTERN.match(token)
        if m:
            canonical = CANONICAL.get(compact(m.group(1)))
            if canonical and m.group(2).strip():
                result[canonical] = m.group(2).strip()
        canonical = CANONICAL.get(compact(token.rstrip(":")))
        if canonical and index + 1 < len(cells) and cells[index + 1].strip():
            result[canonical] = cells[index + 1].strip()
    return result


def is_kla_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and compact(cells[0]) in SITE_ALIASES and sum(bool(v) for v in cells) >= 2


def is_pmish_header(cells: list[str]) -> bool:
    keys = {compact(v) for v in cells}
    return (len(cells) >= 4 and "seq" in keys and
            len(keys & {"num", "padname", "refdiecol", "refdierow", "recipe", "metrologyunit", "azimuthangle"}) >= 2)


def is_summary_row(cells: list[str]) -> bool:
    return bool(cells) and compact(cells[0]) in SUMMARY_ALIASES


def number_like(text: str) -> bool:
    try:
        d = Decimal(text)
        return d.is_finite() and d >= 0 and d == d.to_integral_value()
    except InvalidOperation:
        return False


@dataclass
class ParsedFile:
    records: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    blocks: int = 0
    total_measurement_rows: int = 0


@dataclass
class MergeResult:
    output_dir: Path
    channel_count: int
    input_rows: int
    kept_rows: int
    duplicates: int
    error_count: int
    parsed_files: int


class BlockCollector:
    """Collect a contiguous data block and parse with pd.read_csv exactly once."""
    def __init__(self, path: Path, vendor: str, issues: list[dict]):
        self.path, self.vendor, self.issues = path, vendor, issues
        self.header: list[str] | None = None
        self.rows: list[list[str]] = []
        self.lines: list[int] = []
        self.metadata: dict[str, str] = {}
        self.header_line = 0

    def begin(self, columns: list[str], line: int, metadata: dict[str, str]):
        # A trailing empty CSV field is allowed after the table header.
        while columns and not columns[-1].strip():
            columns = columns[:-1]
        self.header = [column_name(c, self.vendor) for c in columns]
        self.rows, self.lines = [], []
        self.metadata, self.header_line = dict(metadata), line
        if not self.header or not all(self.header) or len(self.header) != len(set(self.header)):
            self.issues.append(row_error(self.path, line, "HEADER", "Duplicate or empty header; block rejected"))
            self.header = None

    def add_row(self, cells: list[str], line: int):
        if self.header is None:
            return
        if len(cells) > len(self.header):
            if any(cells[len(self.header):]):
                self.issues.append(row_error(self.path, line, "WIDTH", f"Extra nonempty fields ({len(cells)} vs {len(self.header)}); skipped"))
                return
            cells = cells[:len(self.header)]
        if len(cells) < len(self.header):
            self.issues.append(row_error(self.path, line, "WIDTH", f"Short row ({len(cells)} vs {len(self.header)}); skipped"))
            return
        self.rows.append(cells)
        self.lines.append(line)

    def finish(self, cancelled=None) -> list[tuple[int, dict, tuple]]:
        if not self.header or not self.rows:
            self.header = None
            self.rows, self.lines = [], []
            return []
        check_cancel(cancelled)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(self.header)
        writer.writerows(self.rows)
        stream.seek(0)
        # Data parsing happens in Pandas, unlike the old csv-only implementation.
        frame = pd.read_csv(stream, dtype=str, keep_default_na=False,
                            index_col=False, on_bad_lines="error", encoding="utf-8")
        if len(frame) != len(self.lines):
            raise ValueError("Pandas block row count mismatch")
        schema = tuple(frame.columns)
        results = []
        for line, values in zip(self.lines, frame.itertuples(index=False, name=None)):
            row = dict(zip(frame.columns, values))
            for field, value in self.metadata.items():
                old = row.get(field, "").strip()
                if not old:
                    row[field] = value
                elif value and old != value:
                    self.issues.append(row_error(self.path, line, "CONFLICT", f"Head {field}={value!r}, data={old!r}; data wins"))
            results.append((line, row, schema))
        self.header = None
        self.rows, self.lines = [], []
        return results


def parse_nova(path: Path, cancelled=None) -> ParsedFile:
    result = ParsedFile()
    check_cancel(cancelled)
    text, source_lines = reference_text(path,cancelled)
    # Validate physical CSV record widths first: Pandas with index_col=False
    # may otherwise warn and truncate surplus columns in some inputs.
    tokenized = tokenize_csv(text,source_lines)
    nonempty = [(line, cells) for line, cells in tokenized if any(cells)]
    if not nonempty:
        raise ValueError("Empty NOVA file")
    header_cells = nonempty[0][1]
    width = len(header_cells)
    widths = [(line, len(cells)) for line, cells in nonempty[1:]
              if len(cells) < width or any(cells[width:])]
    if widths:
        line, actual = widths[0]
        raise ValueError(f"NOVA CSV width mismatch at physical line {line}: "
                         f"{actual} fields vs {len(header_cells)} in header")
    if any(len(cells) > width for _, cells in nonempty[1:]):
        # Re-serialize parsed records, preserving quoted commas, whitespace and
        # empty declared columns. Only surplus empty fields are discarded.
        normalized = io.StringIO(newline="")
        csv.writer(normalized).writerows(row[:width] for row in csv.reader(io.StringIO(text, newline="")))
        text = normalized.getvalue()
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False,
                        index_col=False, on_bad_lines="error")
    header = [str(c).strip().lstrip("\ufeff") for c in frame.columns]
    if not header or len(header) != len(set(header)):
        raise ValueError("Invalid or duplicate NOVA header")
    frame.columns = header
    result.blocks = 1
    # With no blank data records, row identity agrees with the csv.reader
    # physical line number even if quoted cells contain embedded newlines.
    source_lines = [line for line, _ in nonempty[1:]]
    if len(frame) != len(source_lines):
        raise ValueError("NOVA pandas/csv row count mismatch")
    repeated = frame.astype(str).apply(lambda col: col.str.strip().eq(col.name)).all(axis=1)
    for row_idx in frame.index[repeated]:
        result.issues.append(row_error(path, source_lines[int(row_idx)],
                                       "HEADER", "Repeated NOVA column header removed"))
    frame = frame.loc[~repeated]
    result.total_measurement_rows = len(frame)
    for i, values in zip(frame.index, frame.itertuples(index=False, name=None)):
        row = collapse_lbh(dict(zip(frame.columns, values)))
        result.records.append({"channel": (), "data": row,
                               "path": str(path), "line": source_lines[int(i)],
                               "schema": tuple(row)})
    return result


def collapse_lbh(row):
    """Collapse flags: any value other than NO_LBH (including empty) is 1."""
    columns = [name for name in row if name.upper().endswith("_LBH")]
    if not columns:
        return row
    flag = "1" if any(str(row[name]).strip().upper() != "NO_LBH" for name in columns) else "0"
    return {**{name: value for name, value in row.items() if name not in columns}, "LBH": flag}


def parse_sectioned(path: Path, vendor: str, cancelled=None) -> ParsedFile:
    result = ParsedFile()
    text, source_lines = reference_text(path,cancelled)
    rows = tokenize_csv(text,source_lines)
    collector = BlockCollector(path, vendor, result.issues)
    inherited: dict[str, str] = {}
    active_meta: dict[str, str] = {}
    pending: dict[str, str] = {}
    explicit_head = False
    captured: list[tuple[int, dict, tuple]] = []

    def flush():
        nonlocal captured
        captured.extend(collector.finish(cancelled))

    for line, cells in rows:
        check_cancel(cancelled)
        if not any(cells):
            flush()
            continue
        header_found = is_kla_header(cells) if vendor == "KLA" else is_pmish_header(cells)
        if header_found:
            flush()
            result.blocks += 1
            if vendor == "KLA":
                if result.blocks == 1 or explicit_head:
                    # Only stable identities can carry across an explicit new Head.
                    changed_identity = ((pending.get("WaferID") and inherited.get("WaferID") and pending["WaferID"] != inherited["WaferID"]) or
                                        (pending.get("LotID") and inherited.get("LotID") and pending["LotID"] != inherited["LotID"]))
                    base = {k: v for k, v in inherited.items() if k in {"ToolSN"}} if changed_identity else dict(inherited)
                    active_meta = {**base, **pending}
                # A repeated Site header without a new Head keeps active metadata.
                inherited = {k: v for k, v in active_meta.items() if k in IDENTITY_FIELDS}
            else:
                # PMISH may repeat the title with no intervening Head.
                if pending:
                    active_meta = {**active_meta, **pending}
            collector.begin(cells, line, active_meta)
            pending = {}
            explicit_head = False
            continue
        if is_summary_row(cells):
            flush()
            continue
        # Head lines may have variable count and may precede each Block.
        found = metadata_pairs(cells)
        if found:
            flush()
            # With a new KLA Head, channel values never silently persist.
            if vendor == "KLA":
                if not explicit_head:
                    pending = {}
                    explicit_head = True
            pending.update(found)
            continue
        if vendor == "KLA" and re.match(r"^\s*HEAD(?:ER)?(?:\s*\d+)?\s*$", cells[0], re.I):
            flush()
            pending = metadata_pairs(cells[1:])
            explicit_head = True
            continue
        if collector.header is None:
            # Not silently imported as a measurement record.
            continue
        if vendor == "KLA":
            # Site # header is always in first column.
            site_value = cells[0] if cells else ""
            if not number_like(site_value):
                result.issues.append(row_error(path, line, "DATA", "Non-numeric Site #; block ended"))
                flush()
                continue
        else:
            header = collector.header
            num_at = header.index("Num") if "Num" in header else None
            if num_at is not None and (len(cells) <= num_at or not number_like(cells[num_at])):
                result.issues.append(row_error(path, line, "DATA", "Non-numeric Num; block ended"))
                flush()
                continue
            seq_at = header.index("Seq")
            if seq_at >= len(cells) or not cells[seq_at].strip():
                result.issues.append(row_error(path, line, "DATA", "Missing Seq; row skipped"))
                continue
        collector.add_row(cells, line)
    flush()

    for line, row, schema in captured:
        if vendor == "KLA":
            # 用户指定的跨厂商字段映射：KLA SLOT 对应 PMISH Pad name。
            # TEST LABEL 是另一项元数据，必须单独保存，不能覆盖 PadName。
            # 使用 TestID + TestLabel 识别测试 Channel，避免同名 TestID
            # 在不同测量目标下被误合并；不同 Slot 属于不同 Wafer/PAD 记录。
            slot = str(row.get("Slot", "")).strip()
            original_pad = str(row.get("PadName", "")).strip()
            if slot and original_pad and slot != original_pad:
                result.issues.append(row_error(path, line, "CONFLICT",
                   f"KLA Slot={slot!r} differs from original PadName={original_pad!r}; data column retained"))
            elif slot and not original_pad:
                row["PadName"] = slot
            if row.get("WaferID", "").casefold() == "nowaferid":
                lot, slot = row.get("LotID", ""), row.get("Slot", "")
                if lot and slot:
                    row["WaferID"] = lot + "#" + (slot.zfill(2) if slot.isdigit() else slot)
        else:
            if "AzimuthAngle" in row:
                row["AzimuthAngle"] = normalized_angle(row["AzimuthAngle"])
        row = collapse_lbh(row)
        missing = [c for c in CHANNEL_FIELDS[vendor] if str(row.get(c, "")).strip().casefold() in MISSING]
        if missing:
            result.issues.append(row_error(path, line, "CHANNEL", "Missing: " + ", ".join(missing)))
            continue
        channel = tuple(row[k].strip() for k in CHANNEL_FIELDS[vendor])
        result.records.append({"channel": channel, "data": row,
                               "path": str(path), "line": line, "schema": schema})
    result.total_measurement_rows = len(captured)
    if not result.blocks:
        result.issues.append(row_error(path, "", "HEADER", "No recognized data blocks"))
    return result


def parse_file(path: str | Path, vendor: str, cancelled=None) -> ParsedFile:
    vendor = vendor.upper()
    path = Path(path)
    if vendor == "NOVA":
        return parse_nova(path, cancelled)
    if vendor in {"PMISH", "KLA"}:
        return parse_sectioned(path, vendor, cancelled)
    raise ValueError(f"Unknown vendor: {vendor}")


def scan_reference_files(folder: str | Path, extensions=SOURCE_EXTENSIONS) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(x for x in dirs if x.casefold() != OUTPUT_FOLDER.casefold())
        files.extend(Path(root) / n for n in names if Path(n).suffix.casefold() in extensions and not n.startswith('~$'))
    return sorted(files, key=lambda p: str(p).casefold())


def scan_csv(folder: str | Path) -> list[Path]:
    return scan_reference_files(folder,extensions={'.csv'})


def channel_filename(vendor: str, channel: tuple[str, ...]) -> str:
    if vendor == "NOVA":
        return "NOVA_merged.csv"
    fields = CHANNEL_FIELDS[vendor]
    chunks = []
    for key, value in zip(fields, channel):
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in value).strip("_")
        chunks.append(f"{key.replace(' ', '')}-{(safe or 'EMPTY')[:32]}")
    digest = hashlib.sha256("\x1f".join(channel).encode("utf-8")).hexdigest()[:10]
    return f"{vendor}_{'_'.join(chunks)}_{digest}.csv"


def merge(vendor: str, files: list[str | Path], output_parent: str | Path,
          cancelled=None, progress: Callable[[int, int, str], None] | None = None) -> MergeResult:
    vendor = vendor.upper()
    if vendor not in CHANNEL_FIELDS:
        raise ValueError(f"Unknown vendor: {vendor}")
    if not files:
        raise ValueError("No reference source files selected")
    files = sorted(dict.fromkeys(Path(p).resolve() for p in files), key=lambda p: str(p).casefold())
    base = Path(output_parent).resolve() / OUTPUT_FOLDER
    filesystem_path(base).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    final = base / f"{vendor}_{stamp}"
    tmp = filesystem_path(base / f".processing_{uuid.uuid4().hex}")
    tmp.mkdir()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    issues: list[dict] = []
    stats: list[dict] = []
    try:
        for index, path in enumerate(files, 1):
            check_cancel(cancelled)
            try:
                parsed = parse_file(path, vendor, cancelled)
                for record in parsed.records:
                    groups[record["channel"]].append(record)
                issues.extend(parsed.issues)
                stats.append({"File": str(path), "Blocks": parsed.blocks,
                              "Data rows found": parsed.total_measurement_rows,
                              "Accepted rows": len(parsed.records), "Issues": len(parsed.issues),
                              "Status": "OK" if parsed.blocks else "NO_HEADER"})
            except InterruptedError:
                raise
            except Exception as exc:
                issues.append(row_error(path, "", "FILE", str(exc)))
                stats.append({"File": str(path), "Blocks": 0, "Data rows found": 0,
                              "Accepted rows": 0, "Issues": 1, "Status": "FAILED"})
            if progress:
                progress(index, len(files), f"Read {path.name}")
        overviews, schemas, origins = [], [], []
        total_before = total_after = 0
        for n, (channel, entries) in enumerate(sorted(groups.items()), 1):
            check_cancel(cancelled)
            data = pd.DataFrame([r["data"] for r in entries]).fillna("")
            count = len(data)
            # Use the complete post-merge schema, never a subset of die coordinates.
            mask = ~data.duplicated(keep="first")
            selected = [item for item, ok in zip(entries, mask.tolist()) if ok]
            data = data.loc[mask].reset_index(drop=True)
            front = [c for c in ("WaferID", "LotID", "PadName", "Slot", "TestID", "TestLabel", "Recipe", "Metrology unit", "AzimuthAngle", "ToolSN") if c in data]
            data = data[front + [c for c in data.columns if c not in front]]
            filename = channel_filename(vendor, channel)
            data.to_csv(tmp / filename, index=False, encoding="utf-8-sig")
            total_before += count
            total_after += len(data)
            overviews.append({**dict(zip(CHANNEL_FIELDS[vendor], channel)),
                              "Input rows": count, "Duplicates removed": count - len(data),
                              "Output rows": len(data), "Source files": len({e["path"] for e in entries}),
                              "Output file": filename})
            for csv_line, item in enumerate(selected, 2):
                origins.append({"Output file": filename, "Output line": csv_line,
                                "Source file": item["path"], "Source line": item["line"]})
            schema_counts = defaultdict(int)
            for entry in entries:
                schema_counts[entry["schema"]] += 1
            for schema, qty in schema_counts.items():
                schemas.append({"Output file": filename, "Rows": qty, "Original data header": " | ".join(schema)})
            if progress:
                progress(n, len(groups), f"Exported {filename}")
        report_specs = {
            "_channels.csv": (overviews, [*CHANNEL_FIELDS[vendor], "Input rows", "Duplicates removed", "Output rows", "Source files", "Output file"]),
            "_files.csv": (stats, ["File", "Blocks", "Data rows found", "Accepted rows", "Issues", "Status"]),
            "_issues.csv": (issues, ["File", "CSV line", "Kind", "Detail"]),
            "_schemas.csv": (schemas, ["Output file", "Rows", "Original data header"]),
            "_provenance.csv": (origins, ["Output file", "Output line", "Source file", "Source line"]),
        }
        for report, (items, columns) in report_specs.items():
            check_cancel(cancelled)
            pd.DataFrame(items, columns=columns).to_csv(tmp / report, index=False, encoding="utf-8-sig")
        check_cancel(cancelled)
        os.replace(tmp, filesystem_path(final))
        return MergeResult(final, len(groups), total_before, total_after, total_before - total_after,
                           len(issues), sum(s["Status"] == "OK" for s in stats))
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)

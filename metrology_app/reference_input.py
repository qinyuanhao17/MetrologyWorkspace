"""Read-only CSV / first-sheet OOXML transport shared by Reference Summary vendors."""
from __future__ import annotations
import csv
import io
from pathlib import Path
from posixpath import normpath
import zipfile
import xml.etree.ElementTree as ET
from .file_paths import filesystem_path

EXCEL_EXTENSIONS = frozenset({".xlsx", ".xlsm"})
SOURCE_EXTENSIONS = EXCEL_EXTENSIONS | {".csv"}
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
TAG = lambda name: "{" + NS + "}" + name

def check_cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("Cancelled by user")

def decode_csv(path: Path) -> str:
    raw = filesystem_path(path.resolve()).read_bytes()
    encodings = ["utf-16"] if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    last_exc = None
    for codec in encodings:
        try:
            return raw.decode(codec)
        except UnicodeDecodeError as exc:
            last_exc = exc
    raise ValueError(f"Cannot decode CSV: {last_exc}")


def _first_sheet_path(z: zipfile.ZipFile) -> tuple[str, str]:
    root = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = root.find(TAG("sheets"))
    if sheets is None or not list(sheets):
        raise ValueError("Excel workbook does not contain a worksheet")
    first = sheets[0]
    rel_id = first.get("{" + REL + "}id")
    relationship = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for link in relationship.findall("{" + PKG + "}Relationship"):
        if link.get("Id") == rel_id:
            if link.get("TargetMode") == "External":
                raise ValueError("First worksheet points to an external resource")
            target = link.get("Target", "").lstrip("/")
            member = target if target.startswith("xl/") else normpath("xl/" + target)
            if not member.startswith("xl/worksheets/") or member not in z.namelist():
                raise ValueError("First worksheet XML not found")
            return first.get("name", "Sheet1"), member
    raise ValueError("First worksheet relationship not found")


def _col_index(cell_address: str) -> int:
    n = 0
    for ch in cell_address.upper():
        if not "A" <= ch <= "Z":
            break
        n = n * 26 + ord(ch) - ord("A") + 1
    return n - 1


def iter_first_sheet(path: str | Path, cancelled=None):
    """Yield (sheet_name, Excel_row_number, {column_index: raw_value})."""
    with zipfile.ZipFile(filesystem_path(Path(path).resolve())) as z:
        name, member = _first_sheet_path(z)
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                for _, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == TAG("si"):
                        shared.append("".join(t.text or "" for t in elem.iter(TAG("t"))))
                        elem.clear()
        with z.open(member) as stream:
            for _, elem in ET.iterparse(stream, events=("end",)):
                if elem.tag != TAG("row"):
                    continue
                check_cancel(cancelled)
                values = {}
                for cell in elem.findall(TAG("c")):
                    index = _col_index(cell.get("r", ""))
                    if index < 0:
                        continue
                    typ = cell.get("t", "")
                    val = cell.find(TAG("v"))
                    if val is not None:
                        raw = val.text or ""
                        if typ == "s" and raw:
                            raw = shared[int(raw)]
                    else:
                        inline = cell.find(TAG("is"))
                        raw = "".join(t.text or "" for t in inline.iter(TAG("t"))) if inline is not None else ""
                    values[index] = raw
                yield name, int(elem.get("r", "0")), values
                elem.clear()



def iter_source_rows(path, cancelled=None):
    """Yield source sheet/name, original row number and raw sparse cell values."""
    path = Path(path)
    if path.suffix.casefold() in EXCEL_EXTENSIONS:
        yield from iter_first_sheet(path, cancelled=cancelled)
    elif path.suffix.casefold() == ".csv":
        reader = csv.reader(io.StringIO(decode_csv(path), newline=""), strict=True)
        for record in reader:
            check_cancel(cancelled)
            yield "CSV", reader.line_num, dict(enumerate(record))
    else:
        raise ValueError(f"Unsupported reference format: {path.suffix}; use .csv, .xlsx or .xlsm")


def reference_text(path, cancelled=None):
    """Adapt Excel transport to existing vendor CSV grammars, retaining row provenance."""
    path = Path(path)
    if path.suffix.casefold() == ".csv":
        return decode_csv(path), None
    fragments, lines = [], {}
    width = csv_line = previous = 0
    for _sheet, source_line, cells in iter_source_rows(path, cancelled):
        if source_line > previous + 1:
            gaps = source_line - previous - 1
            fragments.append("\n" * gaps)
            csv_line += gaps
        width = max(width, max(cells, default=-1) + 1)
        stream = io.StringIO(newline="")
        values = (cells.get(i,"") for i in range(width)) if any(value.strip() for value in cells.values()) else []
        csv.writer(stream, lineterminator="\n").writerow(values)
        record = stream.getvalue()
        fragments.append(record)
        csv_line += record.count("\n")
        lines[csv_line] = source_line
        previous = source_line
    return "".join(fragments), lines


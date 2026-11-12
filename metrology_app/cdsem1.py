"""CDSEM1: CSV / first-sheet Excel CD parser and MP_Name pivot.

No Excel SDK dependency: source worksheet is streamed from OOXML; pandas performs
filtering/validation; output is written as standards-compliant OOXML by stdlib.
This deliberately leaves the existing NOVA/PMISH/KLA engine untouched.
"""
from __future__ import annotations

import csv
import os
import shutil
import uuid
import zipfile
from collections import OrderedDict, Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd

from .reference_merge import OUTPUT_FOLDER, check_cancel
from .reference_input import SOURCE_EXTENSIONS, iter_first_sheet, iter_source_rows

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
TAG = lambda name: "{" + NS + "}" + name
EXTS = {".xlsx", ".xlsm"}

# The same field grouping as the previously approved CDSEM pivot.
COMMON = [
    "Lot_ID", "Wafer_ID", "Slot_No", "Chip_X", "Chip_Y", "File_Name",
    "Date", "Device", "Class", "Recipe_Name", "ACD_No",
]
LOCAL = [
    "SourceRow", "No", "Seq_No", "P_No", "D_No", "Wafer_X", "Wafer_Y",
    "R", "Field_X", "Field_Y", "Die_X", "Die_Y", "Multi_Measure",
    "Measurement", "Object", "Kind", "Data", "Result", "Mean", "Mean'",
    "Maximum", "Minimum", "3Sigma", "3Sigma'", "Max-Min", "3Sigma(L.E.)",
    "3Sigma'(L.E.)", "Max-Min(L.E.)", "3Sigma(R.E.)", "3Sigma'(R.E.)",
    "Max-Min(R.E.)", "Method", "Formula", "Enhanced_Formula",
]
IDENTITY = ["Lot_ID", "Wafer_ID", "Chip_X", "Chip_Y"]
INTEGER_FIELDS = {"Chip_X", "Chip_Y", "Wafer_X", "Wafer_Y", "SourceRow", "No", "Field_X", "Field_Y", "Die_X", "Die_Y"}
DECIMAL_FIELDS = {"Result", "R"}


@dataclass
class CDSEM1Result:
    output_dir: Path
    channel_count: int
    input_rows: int
    kept_rows: int
    duplicates: int
    error_count: int
    parsed_files: int
    site_count: int
    mp_count: int


def scan_workbooks(folder: str | Path) -> list[Path]:
    base = Path(folder)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    files = []
    for root, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d.casefold() != OUTPUT_FOLDER.casefold())
        files.extend(Path(root) / n for n in names
                     if Path(n).suffix.casefold() in EXTS and not n.startswith("~$"))
    return sorted(files, key=lambda p: str(p).casefold())




def read_cd_rows(path: str | Path, cancelled=None) -> tuple[str, int, list[dict]]:
    columns, data, total, sheet = None, [], 0, ""
    for name, line, cells in iter_source_rows(path, cancelled=cancelled):
        if columns is None:
            sheet = name
            if not cells:
                continue
            columns = [cells.get(i, "").strip() for i in range(max(cells) + 1)]
            if len(set(columns)) != len(columns) or not all(columns):
                raise ValueError(f"First sheet has empty/duplicate header fields: {name}")
            required = {"ACD_No", "MP_Name", "Chip_X", "Chip_Y", "Result"}
            missing = required - set(columns)
            if missing:
                raise ValueError("Missing CDSEM1 columns: " + ", ".join(sorted(missing)))
            index = {c: i for i, c in enumerate(columns)}
            continue
        total += 1
        if cells.get(index["ACD_No"], "").strip().casefold() != "cd":
            continue
        row = {col: cells.get(i, "") for i, col in enumerate(columns)}
        row.setdefault('Wafer_ID','')
        row.setdefault('Lot_ID','')
        row["SourceRow"] = str(line)
        for field in ('MP_Name','Chip_X','Chip_Y'):
            if not row[field].strip():
                raise ValueError(f"{field} missing at source row {line}")
        data.append(row)
    if columns is None:
        raise ValueError("First worksheet is empty")
    if not data:
        raise ValueError("No ACD_No=CD rows found in the first worksheet")
    return sheet, total, data


def pivot_cd_rows(rows: list[dict], sheet_name: str, source_name: str, *, source_rows=None) -> dict:
    """Use Pandas for duplicate detection; create one chip row per MP group."""
    frame = pd.DataFrame(rows).fillna("")
    for field in ('Lot_ID','Wafer_ID'):
        if field not in frame:
            frame[field] = ''
    for field in ('MP_Name','Chip_X','Chip_Y'):
        if field not in frame:
            raise ValueError(f'{field} is missing')
        missing = frame[field].astype(str).str.strip().eq('')
        if missing.any():
            source_rows = frame.loc[missing,'SourceRow'].tolist() if 'SourceRow' in frame else frame.index[missing].tolist()
            raise ValueError(f'{field} missing at source rows {source_rows[:8]}')
    original = len(frame)
    # Exact duplicates are measured without SourceRow, which is provenance only.
    subset = [col for col in frame if col != "SourceRow"]
    is_duplicate = frame.duplicated(subset=subset, keep="first")
    duplicate_count = int(is_duplicate.sum())
    frame = frame.loc[~is_duplicate].copy()
    for key in IDENTITY:
        if key not in frame.columns:
            raise ValueError(f"Identity field is missing: {key}")
    collision = frame.duplicated(subset=IDENTITY + ["MP_Name"], keep=False)
    if collision.any():
        bad = frame.loc[collision, IDENTITY + ["MP_Name", "SourceRow"]].head(8)
        raise ValueError("Same chip + MP_Name has conflicting records (not identical).\n" + bad.to_string(index=False))
    mps = list(dict.fromkeys(frame["MP_Name"].astype(str)))
    sites: OrderedDict[tuple[str, ...], dict[str, dict]] = OrderedDict()
    for record in frame.to_dict(orient="records"):
        chip = tuple(str(record.get(k, "")) for k in IDENTITY)
        mp = str(record["MP_Name"])
        site_data = sites.setdefault(chip, {})
        if site_data:
            first = next(iter(site_data.values()))
            for col in COMMON:
                current, previous = str(record.get(col, "")), str(first.get(col, ""))
                if col == 'ACD_No':
                    current, previous = current.strip().casefold(), previous.strip().casefold()
                if current != previous:
                    raise ValueError(f"Conflicting shared {col}: wafer/chip={chip}, MP={mp}, SourceRow={record['SourceRow']}")
        site_data[mp] = record
    expected = len(sites) * len(mps)
    missing = expected - len(frame)
    counts = Counter(str(v) for v in frame["MP_Name"])
    return {"sheet": sheet_name, "source": source_name,
            "source_rows": original if source_rows is None else source_rows,
            "input_rows": original, "unique_cd_rows": len(frame), "duplicates": duplicate_count,
            "sites": sites, "mps": mps, "mp_counts": counts,
            "missing": missing}


def excel_column(index: int) -> str:
    value = ""
    while index:
        index, residue = divmod(index - 1, 26)
        value = chr(65 + residue) + value
    return value


def _safe_text(value) -> str:
    # XML 1.0 illegal control characters must be dropped.
    return "".join(c for c in str(value) if ord(c) >= 32 or c in "\t\n\r")[:32767]


def _cell_xml(col_num: int, row_num: int, field: str, value, style: int) -> str:
    if value is None or value == "":
        return ""
    addr = excel_column(col_num) + str(row_num)
    raw = str(value)
    if field in INTEGER_FIELDS or field in DECIMAL_FIELDS:
        try:
            n = Decimal(raw)
            if n.is_finite() and (field in DECIMAL_FIELDS or n == n.to_integral_value()):
                return f'<c r="{addr}" s="{style}"><v>{n}</v></c>'
        except (InvalidOperation, ValueError):
            pass
    return (f'<c r="{addr}" s="{style}" t="inlineStr"><is><t xml:space="preserve">'
            + escape(_safe_text(value)) + '</t></is></c>')


def _xml_sheet(rows, header_rows: int, cols: int, *, merges: list[str] | None = None, common: int = 0):
    # rows is an iterable of (values, fields), generated one row at a time.
    yield '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    yield f'<worksheet xmlns="{NS}">'
    freeze = header_rows
    yield f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze+1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
    yield f'<sheetFormatPr defaultRowHeight="17"/><cols><col min="1" max="{max(1,cols)}" width="16" customWidth="1"/></cols><sheetData>'
    for r, (values, fields) in enumerate(rows, 1):
        height = ' ht="27" customHeight="1"' if r <= header_rows else ''
        yield f'<row r="{r}"{height}>'
        for col, (value, field) in enumerate(zip(values, fields), 1):
            style = (3 if col <= common else 2) if r == 1 and header_rows == 2 else (1 if r <= header_rows else 0)
            cell = _cell_xml(col, r, field, value, style)
            if cell:
                yield cell
        yield '</row>'
    yield '</sheetData>'
    if merges:
        yield f'<mergeCells count="{len(merges)}">'
        for rng in merges:
            yield f'<mergeCell ref="{rng}"/>'
        yield '</mergeCells>'
    yield '</worksheet>'


def _style_xml() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<styleSheet xmlns="{NS}">'
            '<fonts count="2"><font><sz val="10"/><name val="Aptos"/></font>'
            '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font></fonts>'
            '<fills count="5"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF174B69"/><bgColor indexed="64"/></patternFill></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF1F776F"/><bgColor indexed="64"/></patternFill></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF233A59"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/>'
            '<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFill="1" applyFont="1"/>'
            '<xf numFmtId="0" fontId="1" fillId="4" borderId="0" xfId="0" applyFill="1" applyFont="1"/>'
            '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _write_xml_entry(z: zipfile.ZipFile, path: str, sections):
    with z.open(path, 'w', force_zip64=True) as handle:
        for section in sections:
            handle.write(section.encode('utf-8'))


def _write_workbook(path: Path, sheets):
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets>'
                + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_,_,_,_,_) in enumerate(sheets,1))
                + '</sheets></workbook>')
    relationships = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     f'<Relationships xmlns="{PKG}">'
                     + ''.join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                               for i in range(1,len(sheets)+1))
                     + f'<Relationship Id="rId{len(sheets)+1}" Type="{REL}/styles" Target="styles.xml"/>'
                     '</Relationships>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                     + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                               for i in range(1,len(sheets)+1))
                     + '</Types>')
    top_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', top_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', relationships)
        z.writestr('xl/styles.xml', _style_xml())
        for i, (_name, rows, header_rows, cols, merges, common) in enumerate(sheets,1):
            _write_xml_entry(z, f'xl/worksheets/sheet{i}.xml',
                             _xml_sheet(rows, header_rows, cols, merges=merges, common=common))


def export_cdsem1(book: dict, output_xlsx: Path, output_csv: Path, *, cancelled=None):
    check_cancel(cancelled)
    sites, mps = book['sites'], book['mps']
    width = len(COMMON) + len(LOCAL) * len(mps)
    if width > 16384:
        raise ValueError(f'Too many MP parameters for one XLSX: {width} columns')
    # Always preserve the requested two-level header: MP_Name over No and measurements.
    top = [''] * width
    top[0] = 'COMMON'
    merges = [f'A1:{excel_column(len(COMMON))}1']
    for i, mp in enumerate(mps):
        first = len(COMMON) + i*len(LOCAL)
        top[first] = mp
        merges.append(f'{excel_column(first+1)}1:{excel_column(first+len(LOCAL))}1')
    secondary = COMMON + LOCAL*len(mps)

    def wide_rows():
        yield top, ['']*width
        yield secondary, ['']*width
        for mp_rows in sites.values():
            check_cancel(cancelled)
            first = next(iter(mp_rows.values()))
            values = [first.get(col,'') for col in COMMON]
            for mp in mps:
                rec = mp_rows.get(mp)
                values.extend((rec.get(col,'') for col in LOCAL) if rec else ['']*len(LOCAL))
            yield values, secondary

    def compact_rows():
        headers = COMMON + mps
        yield headers, ['']*len(headers)
        for mp_rows in sites.values():
            check_cancel(cancelled)
            first = next(iter(mp_rows.values()))
            values = [first.get(col,'') for col in COMMON]
            values.extend(mp_rows.get(mp,{}).get('Result','') for mp in mps)
            yield values, COMMON + ['Result']*len(mps)

    checks = [
        ['Check', 'Value', 'Notes'],
        ['Input file',book['source'],'One output workbook per source'],
        ['Source first worksheet',book['sheet'],'Only the FIRST worksheet is parsed'],
        ['Source rows',book.get('source_rows',book['input_rows']),'All source data rows before ACD_No selection'],
        ['ACD_No=CD rows',book['input_rows'],'Rows selected before de-duplication'],
        ['Unique CD rows',book['unique_cd_rows'],'Identical records counted once'],
        ['Identical duplicates',book['duplicates'],'Compared without SourceRow'],
        ['Unique chip sites',len(sites),'Lot_ID + Wafer_ID + Chip_X + Chip_Y'],
        ['MP_Name count',len(mps),'One grouped section per MP_Name'],
        ['Missing chip+MP pairs',book['missing'],'If nonzero, blank cells are expected'],
        ['Coordinate treatment','Chip_X/Y common','Wafer_X/Y retained beneath each MP_Name'],
        ['Wafer identity','Blank' if all(not str(key[1]).strip() for key in sites) else 'From source',
         'Blank Wafer_ID: confirm the source contains only one wafer; no Wafer_ID is generated.' if all(not str(key[1]).strip() for key in sites) else 'Source identities retained'],
        ['', '', ''],
        ['MP_Name', 'Measurement rows', 'Missing sites'],
    ]
    for mp in mps:
        checks.append([mp, book['mp_counts'][mp], len(sites) - book['mp_counts'][mp]])

    def checks_rows():
        for line in checks:
            yield line, ['']*3

    _write_workbook(output_xlsx, [
        ('CD Pivot', wide_rows(), 2, width, merges, len(COMMON)),
        ('CD Results', compact_rows(), 1, len(COMMON)+len(mps), [], 0),
        ('Checks', checks_rows(), 1, 3, [], 0),
    ])
    # Flat analysis CSV: a single header row, common fields + MP Result values.
    columns = COMMON + mps
    with output_csv.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for mp_rows in sites.values():
            first = next(iter(mp_rows.values()))
            writer.writerow([first.get(c,'') for c in COMMON] +
                            [mp_rows.get(mp,{}).get('Result','') for mp in mps])


def merge_cdsem1(files: list[str | Path], output_parent: str | Path,
                 *, cancelled=None, progress=None) -> CDSEM1Result:
    files = sorted({Path(x).resolve() for x in files}, key=lambda x: str(x).casefold())
    if not files:
        raise ValueError('CDSEM1: no source files selected')
    for file in files:
        if file.suffix.casefold() not in SOURCE_EXTENSIONS:
            raise ValueError(f'CDSEM1 accepts .csv, .xlsx or .xlsm: {file}')
    base = Path(output_parent) / OUTPUT_FOLDER
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output = base / f'CDSEM1_{stamp}'
    temp = base / f'.processing_{uuid.uuid4().hex}'
    temp.mkdir()
    stats, issues = [], []
    total_rows = total_kept = total_dupes = total_sites = total_mps = successful = 0
    try:
        for index, file in enumerate(files, 1):
            check_cancel(cancelled)
            try:
                sheet, total, rows = read_cd_rows(file, cancelled=cancelled)
                book = pivot_cd_rows(rows, sheet, file.name, source_rows=total)
                # Use a short hash to distinguish identical base filenames from different folders.
                stem = ''.join(c if c.isalnum() or c in '-_' else '_' for c in file.stem)[:62]
                import hashlib
                digest = hashlib.sha256(str(file).encode('utf-8')).hexdigest()[:8]
                basename = f'CDSEM1_{stem}_{digest}'
                export_cdsem1(book, temp / (basename + '.xlsx'),
                              temp / (basename + '_Results.csv'), cancelled=cancelled)
                successful += 1
                total_rows += book['input_rows']
                total_kept += book['unique_cd_rows']
                total_dupes += book['duplicates']
                total_sites += len(book['sites'])
                total_mps += len(book['mps'])
                stats.append({'File': str(file),'First Sheet':sheet,'Source Rows':total,
                              'CD Rows':book['input_rows'],'Duplicates':book['duplicates'],
                              'Chip Sites':len(book['sites']),'MP_Name Count':len(book['mps']),
                              'Status':'OK'})
                if progress:
                    progress(index, len(files), f'CDSEM1: {file.name} — {len(book["sites"])} chips, {len(book["mps"])} MP')
            except InterruptedError:
                raise
            except Exception as exc:
                issues.append({'File':str(file),'Issue':str(exc)})
                stats.append({'File':str(file),'First Sheet':'','Source Rows':0,
                              'CD Rows':0,'Duplicates':0,'Chip Sites':0,'MP_Name Count':0,'Status':'FAILED'})
                if progress:
                    progress(index, len(files), f'CDSEM1 FAILED: {file.name}: {exc}')
        if not successful:
            raise ValueError('CDSEM1: all input files failed: ' + '; '.join(i['Issue'] for i in issues))
        pd.DataFrame(stats).to_csv(temp/'_files.csv', index=False, encoding='utf-8-sig')
        pd.DataFrame(issues, columns=['File','Issue']).to_csv(temp/'_issues.csv', index=False, encoding='utf-8-sig')
        check_cancel(cancelled)
        os.replace(temp, output)
        return CDSEM1Result(output, total_mps, total_rows, total_kept, total_dupes,
                            len(issues), successful, total_sites, total_mps)
    finally:
        if temp.exists():
            shutil.rmtree(temp)

"""Preserve vendor identifiers for Reference workspace names and HTML summaries."""

import csv
from datetime import datetime
from html import escape
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from .file_paths import filesystem_path
from .reference_input import check_cancel, iter_source_rows
from .reference_merge import compact, is_kla_header, is_pmish_header, is_summary_row


FIELDS = {
    'NOVA': ('ToolName', 'ToolSN', 'ModuleName', 'RecipePath', 'RecipeTag', 'Recipe',
             'MARS_Library_Name', 'DateTime', 'Date', 'WaferID', 'LotID', 'Slot', 'SiteName', 'PAD Name'),
    'PMISH': ('ToolSN', 'RcpName', 'PPID', 'Recipe', 'Recipe type', 'Metrology unit',
              'AzimuthAngle', 'Date', 'Start', 'End', 'DateTime', 'WaferID', 'LotID', 'Slot', 'Pad name'),
    'KLA': ('TOOL ID', 'MACHINE TYPE', 'SOFTWARE VERSION', 'RECIPE', 'TEST ID', 'TEST LABEL',
            'DATE/TIME', 'WAFER ID', 'LOT ID', 'WAFER #', 'SLOT', 'PAD NAME'),
    'CDSEM1': ('Device', 'Tool ID', 'Recipe_Name', 'Class', 'ACD_No',
               'Date', 'DateTime', 'Wafer_ID', 'Lot_ID', 'Slot_No', 'PAD Name', 'File_Name'),
}
ALIASES = {'wafernumber': 'waferid', 'waferno': 'waferid', 'lotno': 'lotid',
           'lotnumber': 'lotid', 'toolserialnumber': 'toolsn', 'pad': 'padname'}
MARKER = '<!doctype html><!-- Metrology Workspace Reference Summary -->'
BATCH_SUMMARY = '_summary.html'
TIME_FIELDS = {'date', 'datetime', 'start', 'end'}
WAFER_FIELDS = {'waferid', 'lotid', 'sitename', 'padname', 'slot', 'slotno', 'waferslot'}


def field_key(label):
    if label.strip().rstrip(':').upper() == 'WAFER #':
        return 'waferslot'
    key = compact(label)
    return ALIASES.get(key, key)


def _append(fields, name, value):
    value = str(value).strip()
    if value and value.casefold() not in ('nan', 'none', '<na>', 'na', 'n/a'):
        fields.setdefault(name.strip(), {}).setdefault(value, None)


def frame_metadata(vendor, frame):
    accepted = {field_key(name) for name in FIELDS[vendor]}
    fields = {}
    for label, values in frame.items():
        if field_key(str(label)) in accepted:
            for value in values.dropna().unique():
                _append(fields, str(label), value)
    return {name: list(values) for name, values in fields.items()}


def source_metadata(vendor, path, cancelled=None):
    """Read metadata from original preambles as well as measurement columns."""
    accepted = {field_key(name) for name in FIELDS[vendor]}
    fields, columns, cd_type_column = {}, {}, None
    sectioned = vendor in ('KLA', 'PMISH')
    for _, _, source in iter_source_rows(path, cancelled):
        cells = [source.get(index, '').strip() for index in range(max(source, default=-1) + 1)]
        if not any(cells):
            continue
        recognized = {index: name for index, name in enumerate(cells) if field_key(name) in accepted}
        if vendor == 'KLA':
            header = is_kla_header(cells)
        elif vendor == 'PMISH':
            header = is_pmish_header(cells)
        else:
            header = len(recognized) > 1 or (not columns and bool(recognized))
        if header:
            columns = recognized
            if vendor == 'CDSEM1':
                cd_type_column = next((index for index, name in columns.items() if field_key(name) == 'acdno'), None)
            continue
        if cd_type_column is not None and source.get(cd_type_column, '').strip().casefold() != 'cd':
            continue
        if sectioned:
            # A preamble may be a single KLA pair or a sequence of PMISH pairs.
            if recognized and (0 in recognized or any(name.endswith(':') for name in recognized.values())):
                for index, name in recognized.items():
                    if index + 1 < len(cells) and index + 1 not in recognized:
                        _append(fields, name, cells[index + 1])
                columns = {}
                continue
            if is_summary_row(cells):
                continue
        for index, name in columns.items():
            if index < len(cells):
                _append(fields, name, cells[index])
    return {name: list(values) for name, values in fields.items()}


def collect_sources(vendor, paths, cached, cancelled=None):
    records = {}
    for path in paths:
        check_cancel(cancelled)
        name = str(path)
        if name in cached:
            records[name] = cached[name]
            continue
        try:
            records[name] = source_metadata(vendor, path, cancelled)
        except InterruptedError:
            raise
        except (OSError, ValueError, csv.Error, BadZipFile, ParseError, KeyError, IndexError):
            # Older workspaces may embed their Ref tables after source files moved.
            records[name] = {}
    return records


def _values(records, keys):
    return list(dict.fromkeys(value for fields in records for name, values in fields.items()
                              if field_key(name) in keys for value in values))


def _date_token(value):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y %I:%M:%S %p',
                '%m/%d/%Y %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d_%H:%M:%S', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y%m%d_%H%M%S' if '%H' in fmt or '%I' in fmt else '%Y%m%d')
        except ValueError:
            continue
    return value


def _safe_name(value):
    return re.sub(r'[<>:"/\\|?*\s\x00-\x1f]+', '-', value).strip(' .-')


def _wafer_parts(active, records, other=(), *, show_total=False):
    parts = []
    for label, keys in (('Wafer', {'waferid'}), ('Lot', {'lotid'}),
                        ('PAD', {'padname', 'sitename'}), ('Slot', {'slot', 'slotno', 'waferslot'})):
        for fields in ([active], records, other):
            values = [value for value in _values(fields, keys)
                      if label != 'Wafer' or compact(value) != 'nowaferid']
            if values:
                break
        if not values:
            continue
        token = _safe_name(values[0])[:32]
        if token:
            part = f'{label}-{token}'
            if len(values) > 1:
                part += f'({len(values)})' if show_total else f'+{len(values)-1}'
            parts.append(part)
    return parts


def _date_part(*record_groups):
    for fields in record_groups:
        dates = next((values for key in ('datetime', 'start', 'date', 'end') if (values := _values(fields, {key}))), [])
        if dates and (token := _safe_name(_date_token(dates[0]))[:32]):
            return token + (f'+{len(dates)-1}' if len(dates) > 1 else '')
    return ''


def suggested_filename(vendor, active, sources, other=(), *, include_date=True):
    """Use the active Ref output first and keep long multi-wafer names bounded."""
    records = list(sources.values()) or list(other)
    parts = [vendor, *_wafer_parts(active, records, other)]
    if include_date and (date := _date_part([active], records, other)):
        parts.append(date)
    if len(parts) == 1:
        parts.append('Reference')
    return '_'.join(parts) + '.ref'


def measurement_stem(vendor, fields, sources):
    if vendor == 'KLA':
        original_wafers = _values(sources, {'waferid'})
        if original_wafers and all(compact(value) == 'nowaferid' for value in original_wafers):
            fields = {name: values for name, values in fields.items() if field_key(name) != 'waferid'}
    parts = _wafer_parts(fields, sources, show_total=True)
    return '_'.join([vendor, *(parts or ['Reference'])])


def batch_directory_name(vendor, stamp, outputs, sources):
    used_sources = dict.fromkeys(path for _, _, paths in outputs for path in paths)
    date = _date_part([fields for _, fields, _ in outputs],
                      [sources[path] for path in used_sources] if used_sources else sources.values())
    return '_'.join(part for part in (vendor, date, stamp) if part)


def _field_table(vendor, fields):
    order = {field_key(name): index for index, name in enumerate(FIELDS[vendor])}
    rows = sorted(fields.items(), key=lambda entry: order.get(field_key(entry[0]), len(order)))
    return ('<table width="100%" cellspacing="0" cellpadding="5">'
            + ''.join(f'<tr><th scope="row" width="38%" align="left">{escape(name)}</th>'
                      f'<td>{"<br>".join(map(escape, values))}</td></tr>' for name, values in rows)
            + '</table>')


def summary_html(vendor, output, output_fields, sources, *, counts=None):
    title = f'{vendor} reference summary'
    sections = [f'<h1>{escape(title)}</h1>', f'<p>{escape(output.name)}</p>']
    combined = {}
    labels = {}
    accepted = {field_key(field) for field in FIELDS[vendor]}
    original = {field_key(name) for fields in sources.values() for name in fields}
    missing = {name: values for name, values in output_fields.items() if field_key(name) not in original}
    for fields in (*sources.values(), missing):
        for name, values in fields.items():
            if field_key(name) in accepted:
                label = labels.setdefault(field_key(name), name)
                for value in values:
                    _append(combined, label, value)
    for name, values in output_fields.items():
        label = labels.get(field_key(name))
        if label in combined:
            matching = combined[label].keys() & set(values)
            if matching:
                combined[label] = {value: None for value in combined[label] if value in matching}
    field_groups = {
        'Instrument and recipe': {name: values for name, values in combined.items()
                                  if field_key(name) not in TIME_FIELDS | WAFER_FIELDS},
        'Measurement time': {name: values for name, values in combined.items() if field_key(name) in TIME_FIELDS},
        'Wafer and site': {name: values for name, values in combined.items() if field_key(name) in WAFER_FIELDS},
    }
    for heading, fields in field_groups.items():
        if fields:
            sections.extend([f'<h2>{heading}</h2>', _field_table(vendor, fields)])
    if not combined:
        sections.append('<p>No recognized vendor metadata is available.</p>')
    if counts:
        sections.extend(['<h2>Batch results</h2>', _field_table(vendor, counts)])
    if sources:
        sections.append('<h2>Original sources</h2>')
        for label, fields in sources.items():
            sections.append(f'<p>{escape(label)}</p>')
            if len(sources) > 1 and fields:
                sections.append(_field_table(vendor, fields))
    return f'''{MARKER}
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; max-width: 56rem; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  th, td {{ border-bottom: 1px solid GrayText; vertical-align: top; overflow-wrap: anywhere; }}
  p {{ overflow-wrap: anywhere; }}
</style>
</head>
<body>{''.join(sections)}</body>
</html>
'''


def write_batch_summary(vendor, staging, batch, outputs, sources, counts, cancelled=None):
    if not outputs:
        html = summary_html(vendor, batch, {}, sources, counts=counts)
        (staging / BATCH_SUMMARY).write_text(html, encoding='utf-8')
    for name, fields, used_files in outputs:
        check_cancel(cancelled)
        output = staging / name
        selected_sources = {path: sources[path] for path in used_files}
        html = summary_html(vendor, output, fields, selected_sources, counts=counts)
        output.with_suffix('.summary.html').write_text(html, encoding='utf-8')


def _marked_summary(target):
    with filesystem_path(target).open(encoding='utf-8', errors='replace') as stream:
        return stream.readline(len(MARKER) + 2).strip() == MARKER


def output_summary_path(output_path):
    """Keep unrelated HTML files even when they share the export's basename."""
    target = output_path.with_suffix('.summary.html')
    suffix = 1
    while filesystem_path(target).exists():
        if _marked_summary(target):
            break
        suffix += 1
        target = output_path.with_suffix(f'.summary{suffix}.html')
    return target


def measurement_csv_path(output_path):
    if output_path.suffix.casefold() == '.xlsx':  # CDSEM1's matching Results CSV
        return output_path.with_name(output_path.stem + '_Results.csv')
    return output_path


def find_output_summary(output_path):
    target = output_summary_path(measurement_csv_path(output_path))
    if filesystem_path(target).is_file():
        return target
    return None


def write_output_summary(output_path, html):
    target = output_summary_path(output_path)
    native_target = filesystem_path(target)
    output = NamedTemporaryFile(dir=native_target.parent, prefix='.summary-', delete=False)
    try:
        with output:
            output.write(html.encode('utf-8'))
        os.replace(output.name, native_target)
    finally:
        Path(output.name).unlink(missing_ok=True)
    return target

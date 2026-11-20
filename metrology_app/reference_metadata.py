"""Preserve vendor identifiers for Reference workspace names and text summaries."""

import csv
from datetime import datetime
from pathlib import Path
import re
from textwrap import wrap
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from PyQt6.QtCore import QIODevice, QSaveFile

from .reference_input import iter_source_rows
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
MARKER = 'REFERENCE WORKSPACE SUMMARY'


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


def source_metadata(vendor, path):
    """Read metadata from original preambles as well as measurement columns."""
    accepted = {field_key(name) for name in FIELDS[vendor]}
    fields, columns, cd_type_column = {}, {}, None
    sectioned = vendor in ('KLA', 'PMISH')
    for _, _, source in iter_source_rows(path):
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


def collect_sources(vendor, paths, cached):
    records = {}
    for path in paths:
        name = str(path)
        if name in cached:
            records[name] = cached[name]
            continue
        try:
            records[name] = source_metadata(vendor, path)
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


def suggested_filename(vendor, active, sources, other=()):
    """Use the active Ref output first and keep long multi-wafer names bounded."""
    records = list(sources.values()) or list(other)
    parts = [vendor]
    for label, keys in (('Wafer', {'waferid'}), ('Lot', {'lotid'}),
                        ('PAD', {'padname', 'sitename'}), ('Slot', {'slot', 'slotno', 'waferslot'})):
        values = _values([active], keys) or _values(records, keys) or _values(other, keys)
        if label == 'Wafer':
            values = [value for value in values if compact(value) != 'nowaferid']
        if not values:
            continue
        token = _safe_name(values[0])[:32]
        if token:
            parts.append(f'{label}-{token}' + (f'+{len(values)-1}' if len(values) > 1 else ''))
    for fields in ([active], records, other):
        dates = next((values for key in ('datetime', 'start', 'date') if (values := _values(fields, {key}))), [])
        if dates and (token := _safe_name(_date_token(dates[0]))[:32]):
            parts.append(token + (f'+{len(dates)-1}' if len(dates) > 1 else ''))
            break
    if len(parts) == 1:
        parts.append('Reference')
    return '_'.join(parts) + '.ref'


def _field_lines(vendor, fields):
    order = {field_key(name): index for index, name in enumerate(FIELDS[vendor])}
    lines = []
    for name, values in sorted(fields.items(), key=lambda entry: order.get(field_key(entry[0]), len(order))):
        lines.extend(wrap(' | '.join(values), width=100, initial_indent=f'{name}  ',
                          subsequent_indent=' ' * min(len(name) + 2, 30), break_long_words=False,
                          break_on_hyphens=False))
    return lines


def summary_text(vendor, workspace, outputs, sources):
    lines = [MARKER, f'Workspace  {workspace.name}', f'Vendor  {vendor}']
    combined = {}
    labels = {}
    accepted = {field_key(field) for field in FIELDS[vendor]}
    original = {field_key(name) for fields in sources.values() for name in fields}
    output_fields = ({name: values for name, values in fields.items() if field_key(name) not in original}
                     for _, fields in outputs)
    for fields in (*sources.values(), *output_fields):
        for name, values in fields.items():
            if field_key(name) in accepted:
                label = labels.setdefault(field_key(name), name)
                for value in values:
                    _append(combined, label, value)
    if combined:
        lines.extend(['', 'Instrument, recipe and wafer metadata', *_field_lines(vendor, combined)])
    if outputs:
        lines.extend(['', 'Reference outputs', *(f'  {Path(label).name}' for label, _ in outputs)])
    if sources:
        lines.extend(['', 'Original sources'])
        for label, fields in sources.items():
            lines.append(f'  {label}')
            if len(sources) > 1:
                lines.extend(f'    {line}' for line in _field_lines(vendor, fields))
    if not combined:
        lines.extend(['', 'No recognized vendor metadata is available in this workspace.'])
    return '\n'.join(lines) + '\n'


def write_summary(workspace, text):
    target = workspace.with_suffix('.txt')
    suffix = 0
    while target.exists():
        with target.open(encoding='utf-8-sig', errors='replace') as stream:
            if stream.readline().strip() == MARKER:
                break
        suffix += 1
        target = workspace.with_suffix(f'.summary{suffix if suffix > 1 else ""}.txt')
    output = QSaveFile(str(target))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    data = text.replace('\n', '\r\n').encode('utf-8-sig')
    if output.write(data) != len(data) or not output.commit():
        raise OSError(output.errorString())
    return target

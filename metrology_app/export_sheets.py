"""Report sheet names and formula-safe selection over a newly built workbook."""
from openpyxl.formula import Tokenizer

from .wafer_metrics import METRICS_SHEET_TITLE


def report_sheet_bases(report):
    if report.get('kind') == 'dynamic' or any(name.startswith('Pivot ') for name in report['frames']):
        return ('Dynamic',)
    if 'fullmap_parameters' in report:
        return ('FullMap',)
    return (*report['frames'], *dict.fromkeys(plot['sheet'] for plot in report['plots']),
            *(name for name, _contents, _note in report['pictures']))


def export_sheet_names(snapshot, *, matching, native=True, report_outputs=None, frame_outputs=None):
    """Plan the writer's visible names without rendering charts or writing cells."""
    from .excel_export import (
        group_show_wafer_sheet_title, sheet_title, stage_suffix)
    names, used = [], set()
    def add(title, suffix=''):
        names.append(sheet_title(title, used, suffix))
    def report_names(report, prefix=''):
        for name in report_sheet_bases(report):
            add(prefix + name, report['suffix'])
    if not matching:
        report_names(snapshot)
        return names
    sheet_title('_Plot data', used)
    metrics_title = sheet_title(METRICS_SHEET_TITLE, used) if native and snapshot.get('metrics') else None
    reports = snapshot.get('reports', ())
    scopes = set()
    for workbook, result, _raw, stage_frames in snapshot['stages']:
        suffix = stage_suffix(result.result_mode)
        add('Match Original', suffix)
        if result.group_plan.enabled:
            add('Match Group', suffix)
            shown = set(result.group_plan.state.get(
                'show_wafer_groups', ()))
            if shown.intersection(result.group_plan.row_groups[row] for row in result.source_rows):
                names.append(
                    group_show_wafer_sheet_title(used, suffix))
        add('Match Wafer', suffix)
        if result.group_plan.enabled:
            for key in result.group_plan.group_keys:
                add('Match ' + result.group_plan.label(key), suffix)
        if str(workbook.match_type).upper() in {'NOVA', 'KLA'}:
            for parameter in result.parameter_names:
                try:
                    present = len(result.wafer_summary(parameter))
                except ValueError:
                    present = False
                if present:
                    add('RSQ', suffix)
                    break
        scope = f'map.{workbook.result_mode}'
        scopes.add(scope)
        frames = [name for name, _frame in stage_frames]
        map_index = next((index for index, (_prefix, report) in enumerate(reports)
                          if report.get('scope') == scope), None)
        if map_index is not None and 'FullMap' not in frames:
            frames.append('FullMap')
        for index, name in enumerate(frames):
            add(sheet_title(name, set(), suffix))
            if index < len(stage_frames) and frame_outputs is not None:
                frame_outputs[workbook.result_mode, index] = names[-1]
            if name == 'FullMap' and map_index is not None and report_outputs is not None:
                report_outputs[map_index] = (names[-1],)
    if metrics_title:
        names.append(metrics_title)
    for index, (name, _frame) in enumerate(snapshot.get('extra_frames', ())):
        add(name)
        if frame_outputs is not None:
            frame_outputs[None, index] = names[-1]
    for index, (prefix, report) in enumerate(reports):
        if report.get('scope') not in scopes:
            start = len(names)
            report_names(report, prefix)
            if report_outputs is not None:
                report_outputs[index] = tuple(names[start:])
    return names


def _references(expression, available):
    for token in Tokenizer('=' + expression.lstrip('=')).items:
        if token.type == 'OPERAND' and token.subtype == 'RANGE' and '!' in token.value:
            name = token.value.rsplit('!', 1)[0]
            if name.startswith("'") and name.endswith("'"):
                name = name[1:-1].replace("''", "'")
            if name in available:
                yield name


def select_export_sheets(book, selected):
    """Drop unused outputs; keep required formula sources hidden and editable."""
    if selected is None:
        return
    selected = set(selected)
    available = set(book.sheetnames)
    if not selected or selected - available:
        raise ValueError('Select at least one available output sheet.')
    required, pending = set(selected), list(selected)
    while pending:
        sheet = book[pending.pop()]
        references = set()
        for cell in sheet._cells.values():
            if cell.data_type == 'f':
                references.update(_references(cell.value, available))
        if sheet.title in selected:
            for chart in sheet._charts:
                for child in chart._charts:
                    for series in child.series:
                        for node in series.to_tree().iter():
                            if node.tag.rsplit('}', 1)[-1] == 'f' and node.text:
                                references.update(_references(node.text, available))
                for caption in getattr(chart, '_identity_captions', ()) or ():
                    references.update(_references(caption['source'], available))
        for name in references - required:
            required.add(name)
            pending.append(name)
    for sheet in list(book):
        if sheet.title not in required:
            book.remove(sheet)
        elif sheet.title in selected:
            sheet.sheet_state = 'visible'
        else:
            sheet.sheet_state = 'hidden'
            sheet._charts.clear()
            sheet._images.clear()
    book.active = next(index for index, sheet in enumerate(book) if sheet.title in selected)

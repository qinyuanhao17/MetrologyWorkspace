"""Report sheet names and formula-safe selection over a newly built workbook."""
from openpyxl.formula import Tokenizer


def export_sheet_names(snapshot, *, matching):
    """Plan the writer's visible names without rendering charts or writing cells."""
    from .excel_export import (
        group_show_wafer_sheet_title, sheet_title, stage_suffix)
    names, used = [], set()
    def add(title, suffix=''):
        names.append(sheet_title(title, used, suffix))
    def report_names(report, prefix=''):
        suffix = report['suffix']
        if report.get('kind') == 'dynamic' or any(name.startswith('Pivot ') for name in report['frames']):
            add(prefix + 'Dynamic', suffix)
        elif 'fullmap_parameters' in report:
            add(prefix + 'FullMap', suffix)
        else:
            for name in report['frames']:
                add(prefix + name, suffix)
            for name in dict.fromkeys(plot['sheet'] for plot in report['plots']):
                add(prefix + name, suffix)
            for name, _contents, _note in report['pictures']:
                add(prefix + name, suffix)
    if not matching:
        report_names(snapshot)
        return names
    sheet_title('_Plot data', used)
    reports = snapshot.get('reports', ())
    scopes = set()
    for workbook, result, _raw, stage_frames in snapshot['stages']:
        suffix = stage_suffix(result.result_mode)
        add('Match Original', suffix)
        if result.group_plan.enabled:
            add('Match Group', suffix)
            shown = set(result.group_plan.state.get(
                'show_wafer_groups', ()))
            if shown.intersection(result.group_plan.group_keys):
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
        if any(report.get('scope') == scope for _prefix, report in reports) and 'FullMap' not in frames:
            frames.append('FullMap')
        for name in frames:
            add(sheet_title(name, set(), suffix))
    for name, _frame in snapshot.get('extra_frames', ()):
        add(name)
    for prefix, report in reports:
        if report.get('scope') not in scopes:
            report_names(report, prefix)
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

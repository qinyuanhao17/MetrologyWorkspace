"""Literal, reviewable screenshot transcriptions, independent of Qt and OCR.

Blank observed cells are different from cells outside the captured viewport.
Constraints are data, never executable code. Merging never overwrites a value.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
import ast
import csv
import io
import os
from pathlib import Path
import re
import tempfile


BASE_COLUMNS = ['Name', 'Nominal', 'Min', 'Max']
MODES = ('Float', 'Fix', 'Constrain')
MAX_STEPS = 20


def step_columns(count=5):
    return ['Name'] + [f'Step{step} {part}' for step in range(1, count + 1) for part in ('Mode', 'Value')]


@dataclass
class Cell:
    text: str = ''
    source: str = ''
    bbox: tuple = ()
    confidence: float = 1.0
    collected: bool = True
    reviewed: bool = False
    raw: str | None = None
    alternatives: list = field(default_factory=list)
    history: list = field(default_factory=list)

    def __post_init__(self):
        if self.raw is None:
            self.raw = self.text

    @property
    def status(self):
        return 'uncollected' if not self.collected else ('visible_blank' if not self.text else 'value')

    def to_dict(self):
        # Most table cells contain only immutable scalars and empty review
        # lists. Preserve asdict's output and detachment without recursively
        # inspecting the same nine dataclass fields for every plain cell.
        if (type(self) is Cell and type(self.text) is str and type(self.source) is str
                and type(self.raw) is str and type(self.confidence) in (float, int)
                and type(self.collected) is bool and type(self.reviewed) is bool
                and type(self.bbox) is tuple and all(type(v) is int for v in self.bbox)
                and type(self.alternatives) is list and not self.alternatives
                and type(self.history) is list and not self.history):
            return {'text': self.text, 'source': self.source, 'bbox': self.bbox,
                    'confidence': self.confidence, 'collected': self.collected,
                    'reviewed': self.reviewed, 'raw': self.raw,
                    'alternatives': [], 'history': []}
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if (cls is Cell and type(value) is dict and value.keys() == Cell.__dataclass_fields__.keys()
                and type(value['text']) is str and type(value['source']) is str
                and type(value['raw']) is str and type(value['confidence']) in (float, int)
                and type(value['collected']) is bool and type(value['reviewed']) is bool
                and type(value['bbox']) is tuple and all(type(v) is int for v in value['bbox'])
                and type(value['alternatives']) is list and not value['alternatives']
                and type(value['history']) is list and not value['history']
                and value['alternatives'] is not value['history']):
            detached = dict(value, alternatives=[], history=[])
        else:
            detached = deepcopy(value)
        cell = cls(**detached)
        if (not isinstance(cell.text, str) or not isinstance(cell.raw, str)
                or not isinstance(cell.source, str) or not isinstance(cell.collected, bool)
                or not isinstance(cell.reviewed, bool)
                or not isinstance(cell.confidence, (int, float)) or not 0 <= cell.confidence <= 1
                or len(cell.bbox) not in (0, 4)
                or any(not isinstance(v, int) or not 0 <= v <= 100000 for v in cell.bbox)
                or not isinstance(cell.alternatives, list) or not isinstance(cell.history, list)):
            raise ValueError('Invalid transcription cell.')
        cell.bbox = tuple(cell.bbox)
        return cell


@dataclass
class RecognizedTable:
    kind: str
    columns: list
    rows: list
    warnings: list = field(default_factory=list)


def number(text):
    # Do not repair O/0, I/1, missing signs, decimal points or Unicode operators.
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text):
        raise ValueError('Not a finite numeric literal')
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError('Not a finite numeric literal') from error
    if not value.is_finite():
        raise ValueError('Not a finite numeric literal')
    return value


def expression_issues(text, names):
    if not text:
        return ['Empty constraint; check the source.']
    try:
        root = ast.parse(text, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        return ['Invalid or truncated constraint; retained literally.']
    functions = {'tan', 'sin', 'cos', 'atan', 'sqrt', 'abs', 'exp', 'log', 'log10'}
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
               ast.Div, ast.Pow, ast.Mod, ast.UAdd, ast.USub, ast.Name, ast.Load, ast.Constant, ast.Call)
    for node in ast.walk(root):
        if (not isinstance(node, allowed)
                or isinstance(node, ast.Constant) and (type(node.value) not in (int, float))
                or isinstance(node, ast.Name) and node.id.startswith('_')
                or isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name)
                    or node.func.id not in functions or node.keywords)):
            return ['Unsupported constraint syntax; never executed.']
    unknown = {node.id for node in ast.walk(root) if isinstance(node, ast.Name)} - functions - set(names)
    return [f'Uncollected or misrecognized parameter reference: {name}' for name in sorted(unknown)]


class WriterDocument:
    def __init__(self):
        self.columns = {'parameters': list(BASE_COLUMNS), 'steps': step_columns()}
        self.tables = {'parameters': [], 'steps': []}
        self.sources = {}

    def get(self, kind, name, column):
        position = self.columns[kind].index(column)
        return next(row[position] for row in self.tables[kind] if row[0].text == name)

    def merge(self, result):
        """Validate and prepare the entire merge before changing the document."""
        if result.kind not in self.tables or not result.rows:
            raise ValueError('No parameter rows were recognized.')
        if (result.columns != BASE_COLUMNS if result.kind == 'parameters' else
                result.columns != step_columns((len(result.columns) - 1) // 2)
                or not 1 <= (len(result.columns) - 1) // 2 <= MAX_STEPS):
            raise ValueError('Unsupported table columns.')
        names = [row[0].text.strip() for row in result.rows]
        if any(not name for name in names) or any(len(row) != len(result.columns) for row in result.rows):
            raise ValueError('Each recognized row needs a Name and all visible columns.')
        if len(set(names)) != len(names):
            raise ValueError('Duplicate parameter names in one screenshot; correct the candidate first.')
        if any(name != row[0].text for name, row in zip(names, result.rows)):
            raise ValueError('Remove leading/trailing spaces from parameter Names before merging.')
        kind = result.kind
        columns = list(self.columns[kind])
        if len(result.columns) > len(columns):
            columns = list(result.columns)
        rows = deepcopy(self.tables[kind])
        for row in rows:
            row.extend(Cell(collected=False) for _ in range(len(columns) - len(row)))
        positions = {row[0].text: i for i, row in enumerate(rows)}
        overlap = [positions[name] for name in names if name in positions]
        if overlap != sorted(overlap):
            raise ValueError('Overlapping parameter order differs; correct the names/order before merging.')
        anchors = [(index, positions[name]) for index, name in enumerate(names) if name in positions]
        offsets = {old-new for new, old in anchors}
        aligned_names = list(names)
        if len(anchors) >= 2 and len(offsets) == 1:
            offset = next(iter(offsets))
            for index in range(anchors[0][0], anchors[-1][0]+1):
                if names[index] not in positions:
                    # A consistent run of exact anchors establishes row identity.
                    # Preserve disagreement in Name as a conflict, never fuzzy-correct it.
                    aligned_names[index] = rows[index+offset][0].text
        for source_row, name in zip(result.rows, aligned_names):
            incoming = deepcopy(source_row)
            if name not in positions:
                # Insert above the next shared row (also supports bottom-first imports).
                following = next((n for n in aligned_names[aligned_names.index(name)+1:] if n in positions), None)
                index = positions[following] if following else len(rows)
                incoming.extend(Cell(collected=False) for _ in range(len(columns)-len(incoming)))
                rows.insert(index, incoming)
                positions = {row[0].text: i for i, row in enumerate(rows)}
                continue
            existing = rows[positions[name]]
            for col, cell in enumerate(incoming):
                old = existing[col]
                if not old.collected:
                    existing[col] = cell
                elif cell.collected and old.text != cell.text:
                    candidate = cell.to_dict()
                    if not any(alt['text'] == cell.text for alt in old.alternatives):
                        old.alternatives.append(candidate)
                    old.reviewed = False
        self.columns[kind], self.tables[kind] = columns, rows

    def edit(self, kind, row, col, text):
        cell = self.tables[kind][row][col]
        previous = cell.to_dict()
        previous.pop('history')
        cell.history.append(previous)
        cell.text, cell.collected, cell.reviewed = str(text), True, True
        cell.alternatives = []

    def resolve(self, kind, row, col, index):
        old = self.tables[kind][row][col]
        candidates = [old.to_dict()] + old.alternatives
        selected = Cell.from_dict(candidates[index])
        previous = old.to_dict()
        previous.pop('history')
        selected.history = deepcopy(old.history) + [previous]
        selected.alternatives = []
        selected.reviewed = True
        self.tables[kind][row][col] = selected

    def issues(self, kind, row, col):
        cells = self.tables[kind][row]
        cell = cells[col]
        issues = []
        if not cell.collected:
            return ['Not collected in the screenshots.']
        if cell.alternatives:
            issues.append('Recognition conflict; original value kept. Review both source crops.')
        if cell.source and not cell.reviewed:
            issues.append(f'Unreviewed OCR candidate ({cell.confidence:.1%}); verify against source.')
        if col == 0:
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', cell.text):
                issues.append('Invalid or incomplete parameter name.')
            names = [r[0].text for r in self.tables[kind]]
            if names.count(cell.text) > 1:
                issues.append('Duplicate parameter name.')
            elif any(n != cell.text and n.casefold() == cell.text.casefold() for n in names):
                issues.append('Similar name with different letter case; check before merging.')
        elif kind == 'parameters':
            try:
                values = [number(c.text) for c in cells[1:]]
                if not values[1] <= values[0] <= values[2]:
                    issues.append('Nominal is outside the Min/Max bounds, or bounds are reversed.')
            except ValueError:
                if not cell.text:
                    issues.append('Visible empty parameter value; not replaced with zero.')
                else:
                    try:
                        number(cell.text)
                    except ValueError:
                        issues.append('Invalid numeric literal; no automatic character repair.')
        elif col % 2:
            if cell.text not in MODES:
                issues.append('Unknown mode; use Float, Fix or Constrain.')
        else:
            mode = cells[col-1].text
            if mode == 'Constrain':
                names = {r[0].text for rows in self.tables.values() for r in rows}
                issues.extend(expression_issues(cell.text, names))
            elif cell.text:
                try:
                    number(cell.text)
                except ValueError:
                    issues.append('Invalid numeric literal; retained literally.')
        return issues

    def to_dict(self):
        return {'version': 1, 'columns': deepcopy(self.columns), 'sources': deepcopy(self.sources),
                'tables': {kind: [[cell.to_dict() for cell in row] for row in rows]
                           for kind, rows in self.tables.items()}}

    @classmethod
    def from_dict(cls, state):
        doc = cls()
        try:
            if state['version'] != 1 or set(state['tables']) != set(doc.tables):
                raise ValueError('Unsupported AutoWeighting document version.')
            columns = state['columns']
            if columns['parameters'] != BASE_COLUMNS or columns['steps'] != step_columns((len(columns['steps'])-1)//2):
                raise ValueError('Invalid AutoWeighting document columns.')
            if not 1 <= (len(columns['steps'])-1)//2 <= MAX_STEPS:
                raise ValueError('Too many steps.')
            doc.columns = deepcopy(columns)
            doc.sources = deepcopy(state['sources'])
            if not isinstance(doc.sources, dict) or any(not isinstance(s, dict) or not isinstance(s.get('png'), str)
                    or not isinstance(s.get('name'), str) for s in doc.sources.values()):
                raise ValueError('Invalid screenshot sources.')
            for kind, rows in state['tables'].items():
                if len(rows) > 10000 or any(len(row) != len(columns[kind]) for row in rows):
                    raise ValueError('Invalid AutoWeighting table dimensions.')
                doc.tables[kind] = [[Cell.from_dict(cell) for cell in row] for row in rows]
            return doc
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('Invalid AutoWeighting document.') from error

    def tsv(self, kind):
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter='\t', lineterminator='\n')
        writer.writerow(self.columns[kind])
        writer.writerows([cell.text for cell in row] for row in self.tables[kind])
        return output.getvalue()


def export_excel(doc, path):
    """Export literal strings, with explicit collection/review metadata.

    Never let OCR text become an Excel formula. Atomic replacement also keeps an
    existing export intact when Excel has the destination locked.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook()
    book.remove(book.active)
    for kind, title in [('parameters', 'Parameters'), ('steps', 'Multiple Step')]:
        sheet = book.create_sheet(title)
        sheet.append(doc.columns[kind])
        for row in doc.tables[kind]:
            sheet.append([cell.text for cell in row])
    combined = book.create_sheet('Combined')
    combined.append(BASE_COLUMNS + doc.columns['steps'][1:])
    names = list(dict.fromkeys(row[0].text for kind in doc.tables for row in doc.tables[kind]))
    review = book.create_sheet('Collection & Review')
    review.append(['Name', 'Table', 'Field', 'Text', 'Collection', 'Reviewed', 'Issues', 'Source',
                   'OCR text', 'Confidence', 'Source rectangle', 'Conflict candidates'])
    for name in names:
        wide = [name]
        for kind in ('parameters', 'steps'):
            row = next((r for r in doc.tables[kind] if r[0].text == name), None)
            row_index = doc.tables[kind].index(row) if row is not None else None
            for col, header in enumerate(doc.columns[kind]):
                cell = row[col] if row is not None else Cell(collected=False)
                if col:
                    wide.append(cell.text)
                issues = doc.issues(kind, row_index, col) if row_index is not None else ['Not collected.']
                review.append([name, kind, header, cell.text, cell.status, str(cell.reviewed),
                    '\n'.join(issues), cell.source, cell.raw, str(cell.confidence), str(cell.bbox),
                    '\n'.join(str(a['text']) for a in cell.alternatives)])
        combined.append(wide)
    for sheet in book:
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet:
            for cell in row:
                # openpyxl auto-detects '=' formulas: override even those strings.
                cell.data_type = 's'
                cell.number_format = '@'
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='DCE6F1')
        for col in range(1, sheet.max_column+1):
            sheet.column_dimensions[get_column_letter(col)].width = 25 if col == 1 else 22
    target = Path(path)
    handle = tempfile.NamedTemporaryFile(prefix='.autoweighting-', suffix='.xlsx', dir=target.parent, delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        book.save(temporary)
        os.replace(temporary, target)
    finally:
        book.close()
        temporary.unlink(missing_ok=True)

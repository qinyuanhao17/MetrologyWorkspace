"""Chart-owned DrawingML captions, separate from Excel's category-axis brackets.

Labels stay linked to their visible worksheet cells. Positions may fan out to
avoid overlap; leader lines retain the actual ordinal position of each span.
"""
from pathlib import PurePosixPath
import shutil
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
D = 'http://schemas.openxmlformats.org/drawingml/2006/chartDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
T = 'http://schemas.openxmlformats.org/package/2006/content-types'


def _child(parent, namespace, tag, text=None, **attributes):
    element = ET.SubElement(parent, f'{{{namespace}}}{tag}', attributes)
    element.text = text
    return element


def _shape(root, index, name, start, end, *, text=None, source=None):
    anchor = _child(root, D, 'relSizeAnchor')
    corners = ((min(start[0], end[0]), start[1]), (max(start[0], end[0]), end[1]))
    for corner_name, point in zip(('from', 'to'), corners):
        corner = _child(anchor, D, corner_name)
        _child(corner, D, 'x', str(point[0]))
        _child(corner, D, 'y', str(point[1]))
    shape = _child(anchor, D, 'sp', **({'textlink': source} if source else {}))
    nonvisual = _child(shape, D, 'nvSpPr')
    _child(nonvisual, D, 'cNvPr', id=str(index), name=f'{name} {index}')
    _child(nonvisual, D, 'cNvSpPr', **({'txBox': '1'} if text is not None else {}))
    properties = _child(shape, D, 'spPr')
    if start[0] > end[0]:
        _child(properties, A, 'xfrm', flipH='1')
    geometry = _child(properties, A, 'prstGeom', prst='rect' if text is not None else 'line')
    _child(geometry, A, 'avLst')
    _child(properties, A, 'noFill')
    line = _child(properties, A, 'ln', w='9525')
    if text is not None:
        _child(line, A, 'noFill')
        body = _child(shape, D, 'txBody')
        _child(body, A, 'bodyPr', wrap='square', anchor='t', lIns='0', rIns='0', tIns='0', bIns='0')
        _child(body, A, 'lstStyle')
        for value in str(text).splitlines():
            paragraph = _child(body, A, 'p')
            _child(paragraph, A, 'pPr', algn='ctr')
            run = _child(paragraph, A, 'r')
            style = _child(run, A, 'rPr', sz='1100')
            _child(style, A, 'latin', typeface='Times New Roman')
            _child(run, A, 't', value)
    else:
        fill = _child(line, A, 'solidFill')
        _child(fill, A, 'srgbClr', val='595959')
    return shape


def _drawing(labels):
    root = ET.Element(f'{{{C}}}userShapes')
    available = .90 / max(1, len(labels)) - .012
    widths = [min(.22, available, max(.07, .009 * max(map(len, item['text'].splitlines()), default=1))) for item in labels]
    centers = [.10 + .85 * item['center'] for item in labels]
    if centers:
        centers[0] = max(centers[0], .04 + widths[0] / 2)
    for index in range(1, len(centers)):
        centers[index] = max(centers[index], centers[index - 1] + (widths[index - 1] + widths[index]) / 2 + .012)
    if centers:
        centers[-1] = min(centers[-1], .97 - widths[-1] / 2)
        for index in range(len(centers) - 2, -1, -1):
            centers[index] = min(centers[index], centers[index + 1] - (widths[index + 1] + widths[index]) / 2 - .012)
    index = 1
    for item, center, width in zip(labels, centers, widths):
        actual = .10 + .85 * item['center']
        if abs(actual - center) > .005:
            # Both coordinates are true chart fractions. The connector explains
            # a displaced caption without moving or resampling observations.
            _shape(root, index, 'Leader', (actual, .78), (center, .81))
            index += 1
        _shape(root, index, 'Caption', (center - width / 2, .82), (center + width / 2, .95),
               text=item['text'], source=item['source'])
        index += 1
    boundaries = sorted({item['start'] for item in labels} | {item['end'] for item in labels})
    for value in boundaries:
        x = .10 + .85 * value
        _shape(root, index, 'Boundary', (x, .76), (x, .81))
        index += 1
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def write_identity_drawings(book, path, checkpoint):
    """Extend only the unpublished temporary XLSX; existing parts stay intact."""
    charts = [(chart, chart._identity_captions) for sheet in book for chart in sheet._charts
              if getattr(chart, '_identity_captions', None)]
    if not charts:
        return
    replacements, additions = {}, {}
    with ZipFile(path) as source:
        content_types = ET.fromstring(source.read('[Content_Types].xml'))
        for chart, labels in charts:
            checkpoint()
            chart_path = chart.path.lstrip('/')
            drawing_path = f'xl/drawings/identity-{chart._id}.xml'
            root = ET.fromstring(source.read(chart_path))
            rel_id = 'rIdIdentityLabels'
            _child(root, C, 'userShapes', **{f'{{{R}}}id': rel_id})
            replacements[chart_path] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            rels_path = str(PurePosixPath(chart_path).parent / '_rels' / (PurePosixPath(chart_path).name + '.rels'))
            relationships = ET.fromstring(source.read(rels_path)) if rels_path in source.namelist() else ET.Element(f'{{{P}}}Relationships')
            _child(relationships, P, 'Relationship', Id=rel_id, Target='/' + drawing_path,
                   Type=R + '/chartUserShapes')
            replacements[rels_path] = ET.tostring(relationships, encoding='utf-8', xml_declaration=True)
            additions[drawing_path] = _drawing(labels)
            _child(content_types, T, 'Override', PartName='/' + drawing_path,
                   ContentType='application/vnd.openxmlformats-officedocument.drawingml.chartshapes+xml')
        replacements['[Content_Types].xml'] = ET.tostring(content_types, encoding='utf-8', xml_declaration=True)
        with tempfile.TemporaryFile(dir=path.parent) as staged:
            with ZipFile(staged, 'w') as output:
                for item in source.infolist():
                    checkpoint()
                    output.writestr(item, replacements.pop(item.filename, None) or source.read(item.filename))
                for name, contents in {**replacements, **additions}.items():
                    output.writestr(name, contents)
            source.close()
            staged.seek(0)
            with path.open('wb') as output:
                shutil.copyfileobj(staged, output)

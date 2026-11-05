"""Chart-owned DrawingML captions, separate from Excel's category-axis brackets.

Labels stay linked to their visible worksheet cells. Positions may fan out to
avoid overlap; leader lines retain the actual ordinal position of each span.
"""
from pathlib import PurePosixPath
import shutil
import tempfile
from uuid import uuid4
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


def _shape(root, index, name, start, end, *, text=None, source=None, color='000000', width=19050, dashed=False, rotation=0):
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
    if text is None:
        _child(properties, A, 'noFill')
    else:
        _child(properties, A, 'noFill')
    line = _child(properties, A, 'ln', w=str(width))
    if text is not None:
        _child(line, A, 'noFill')
        body = _child(shape, D, 'txBody')
        _child(
            body, A, 'bodyPr', wrap='none', anchor='t',
            lIns='0', rIns='0', tIns='0', bIns='0',
            horzOverflow='overflow', vertOverflow='overflow', rot=str(rotation))
        _child(body, A, 'lstStyle')
        for value in ([str(text)] if source else str(text).splitlines()):
            paragraph = _child(body, A, 'p')
            _child(paragraph, A, 'pPr', algn='ctr')
            # Excel recognizes textlink alone in the formula bar, but only a
            # TxLink field updates its cached text when the source cell changes.
            run = (_child(paragraph, A, 'fld', id='{' + str(uuid4()).upper() + '}', type='TxLink')
                   if source else _child(paragraph, A, 'r'))
            style = _child(run, A, 'rPr', sz='1100')
            _child(style, A, 'latin', typeface='Times New Roman')
            _child(run, A, 't', value)
    else:
        fill = _child(line, A, 'solidFill')
        _child(fill, A, 'srgbClr', val=color)
        if dashed:
            _child(line, A, 'prstDash', val='dash')
    return shape


def footer_geometry(labels):
    """Reserve full-height Wafer/Group strips below the Die Seq title."""
    if labels and labels[0].get('role') == 'mark2':
        levels = sorted({item['level'] for item in labels})
        heights = {level: .11 if level == 0 else .055 for level in levels}
        top = .95 - sum(heights.values())
        cursor, rows = top, {}
        for level in levels:
            rows[level] = (cursor, cursor + heights[level])
            cursor += heights[level]
        return top - .02, rows
    levels = sorted({item.get('level', 0) for item in labels})
    heights = {level: .04 * max(len(item['text'].splitlines()) or 1 for item in labels
                               if item.get('level', 0) == level) for level in levels}
    top = .95 - sum(heights.values()) - .02 * max(0, len(levels) - 1)
    cursor, rows = top, {}
    for level in levels:
        rows[level] = (cursor, cursor + heights[level])
        cursor += heights[level] + .02
    return top - .14, rows


def _drawing(
        labels, geometry=(.10, .85), width_px=None, *,
        axis_ticks=(), axis_range=None):
    root = ET.Element(f'{{{C}}}userShapes')
    left, width = geometry
    plot_bottom, rows = footer_geometry(labels)
    if labels and labels[0].get('role') == 'mark2':
        from .mark2_plotting import visible_labels
        from matplotlib.font_manager import FontProperties
        from matplotlib.backends.backend_agg import RendererAgg
        renderer = RendererAgg(1, 1, 96)
        font = FontProperties(family='Times New Roman', size=11)
        pixels = float(width_px or 945)
        measure = lambda text: renderer.get_text_width_height_descent(text, font, False)[0]
        spans = [{**item, 'text': str(item['text'])} for item in labels]
        index = 1
        for level, (_top, bottom) in rows.items():
            if level == 0:
                continue
            previous = -1e9
            for edge in sorted({v for item in spans if item['level'] == level for v in (item['start'], item['end'])}):
                if edge * width * pixels - previous < 4:
                    continue
                x = left + width * edge
                _shape(root, index, 'Mark2 boundary', (x, plot_bottom + .005), (x, bottom), color='B8B8B8', width=9525)
                previous = edge * width * pixels
                index += 1
        for item, center in visible_labels(spans, (0, 1), width * pixels, measure):
            top, bottom = rows[item['level']]
            center = left + width * center
            size = (18 if item['level'] == 0 else measure(item['text']) + 10) / pixels
            _shape(root, index, 'Mark2 caption', (center - size / 2, top), (center + size / 2, bottom),
                   text=item['text'], source=item['source'], rotation=5400000 if item['level'] == 0 else 0)
            index += 1
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    index = 1
    group_edges = {item['start'] for item in labels if item.get('role') == 'group'}
    for role in ('wafer', 'group'):
        edges = {item['start'] for item in labels if item.get('role', 'wafer') == role and item['start'] > 0}
        for edge in sorted(edges - group_edges if role == 'wafer' else edges):
            x = left + width * edge
            _shape(root, index, f'{role.title()} plot divider', (x, .15), (x, plot_bottom),
                   color='C8C8C8' if role == 'wafer' else '000000', width=9525 if role == 'wafer' else 19050,
                   dashed=True)
            index += 1
    for level, (top, bottom) in rows.items():
        entries = [item for item in labels if item.get('level', 0) == level]
        dense_wafers = entries[0].get('role', 'wafer') == 'wafer' and len(entries) > 12
        boundaries = sorted({v for item in entries if not dense_wafers or item.get('show', True)
                             for v in (item['start'], item['end'])})
        boundary_top = min(v[0] for v in rows.values()) if entries[0].get('role') == 'group' else top
        for value in boundaries:
            x = left + width * value
            _shape(root, index, f"{entries[0].get('role', 'wafer').title()} boundary",
                   (x, boundary_top - .015), (x, bottom + .015),
                   color='929292' if dense_wafers else '000000', width=9525 if dense_wafers else 19050)
            index += 1
        visible = [item for item in entries if item.get('show', True)]
        index = _captions(
            root, visible, top, bottom, index, geometry, width_px)
    if axis_ticks and axis_range is not None:
        index = _axis_tick_labels(
            root, labels, geometry, width_px, index,
            axis_ticks, axis_range)
    # Group boundaries span both footer levels. Paint every caption last so
    # those later structural lines cannot cross the Wafer text above it.
    captions = [anchor for anchor in root if anchor.find(f'{{{D}}}sp/{{{D}}}txBody') is not None]
    for anchor in captions:
        root.remove(anchor)
        root.append(anchor)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def caption_boxes(labels, geometry=(.10, .85), *, width_px=None):
    """Non-overlapping normalized caption boxes shared by both report renderers."""
    left, width = geometry
    # Group/Wafer span sizing already reserves 16 px around each measured
    # caption. Adding a chart-relative gap here pushed correctly centred
    # labels across unrelated spans: 0.012 of a 160 cm chart is about 130 px.
    # Collision handling therefore separates boxes only when they would
    # actually overlap; it never inflates the spacing of an aligned layout.
    gap = 0.
    available = width / max(1, len(labels))
    if width_px:
        from matplotlib.backends.backend_agg import RendererAgg
        from matplotlib.font_manager import FontProperties
        renderer = RendererAgg(1, 1, 96)
        font = FontProperties(family='Times New Roman', size=11)
        measured = [
            max((
                renderer.get_text_width_height_descent(
                    line, font, False)[0]
                for line in item['text'].splitlines()),
                default=0) + 8
            for item in labels]
        widths = [
            min(.22, available, max(1. / width_px,
                                   pixel_width / width_px))
            for pixel_width in measured]
    else:
        widths = [
            min(.22, available, max(
                .07, .009 * max(
                    map(len, item['text'].splitlines()),
                    default=1)))
            for item in labels]
    centers = [left + width * item['center'] for item in labels]
    if centers:
        centers[0] = max(centers[0], left + widths[0] / 2)
    for position in range(1, len(centers)):
        centers[position] = max(
            centers[position],
            centers[position - 1]
            + (widths[position - 1] + widths[position]) / 2
            + gap)
    if centers:
        centers[-1] = min(
            centers[-1], left + width - widths[-1] / 2)
        for position in range(len(centers) - 2, -1, -1):
            centers[position] = min(
                centers[position],
                centers[position + 1]
                - (widths[position + 1] + widths[position]) / 2
                - gap)
    return list(zip(centers, widths))


def _axis_tick_labels(
        root, labels, geometry, width_px, index, axis_ticks, axis_range):
    """Cell-linked, sparse Die Seq ticks beneath a numeric chart axis."""
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties
    left, plot_width = geometry
    width_px = float(width_px or 3000.)
    renderer = RendererAgg(1, 1, 96)
    font = FontProperties(family='Times New Roman', size=11)
    title_font = FontProperties(family='Times New Roman', size=12)
    low, high = (float(value) for value in axis_range)
    span = max(1e-12, high - low)
    plot_bottom, rows = footer_geometry(labels)
    footer_top = min(top for top, _bottom in rows.values())
    tick_top, tick_bottom = plot_bottom + .01, plot_bottom + .045
    title_top = tick_bottom + .008
    title_bottom = min(footer_top - .006, title_top + .04)
    selected, last_right = [], -1e9
    for tick_index, (position, label, source) in enumerate(axis_ticks):
        lines = str(label).splitlines() or ['']
        measure = max(
            (renderer.get_text_width_height_descent(
                line, font, False)[0]
             for line in lines),
            default=0) + 8
        fraction = min(1., max(0., (position - low) / span))
        center_px = (left + plot_width * fraction) * width_px
        if tick_index == 0 or center_px - measure / 2 > last_right + 4:
            selected.append((fraction, measure / width_px, label, source))
            last_right = center_px + measure / 2
    for fraction, label_width, label, source in selected:
        center = left + plot_width * fraction
        _shape(
            root, index, 'Die Seq tick',
            (center - label_width / 2, tick_top),
            (center + label_width / 2, tick_bottom),
            text=label, source=source)
        index += 1
    title = 'Die Seq'
    title_width = (
        renderer.get_text_width_height_descent(
            title, title_font, False)[0] + 12) / width_px
    center = left + plot_width / 2
    _shape(
        root, index, 'Die Seq axis title',
        (center - title_width / 2, title_top),
        (center + title_width / 2, title_bottom),
        text=title)
    return index + 1


def _captions(
        root, labels, top, bottom, index, geometry=(.10, .85),
        width_px=None):
    for item, (center, width) in zip(
            labels, caption_boxes(
                labels, geometry, width_px=width_px)):
        _shape(root, index, 'Caption', (center - width / 2, top), (center + width / 2, bottom),
               text=item['text'], source=item['source'])
        index += 1
    return index


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
            additions[drawing_path] = _drawing(
                labels,
                getattr(chart, '_identity_geometry', (.10, .85)),
                chart.width * 96 / 2.54,
                axis_ticks=getattr(chart, '_identity_axis_ticks', ()),
                axis_range=getattr(chart, '_identity_axis_range', None))
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

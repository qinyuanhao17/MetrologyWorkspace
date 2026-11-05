"""Excel export: source tables, numeric plot areas and native Excel charts.

Charts are written straight into the workbook (no desktop Excel, no COM): every
series points at the numeric plot area next to its parameter block, so the file
opens with ordinary, movable Excel charts that follow cell edits. Fitted Cards
stay the software result. Native Match trendlines independently refit the
visible measurements when their cells are edited in Excel.
"""
from pathlib import Path
from io import BytesIO
from copy import copy
from math import ceil
import os
import tempfile

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference, ScatterChart, Series
from openpyxl.chart.marker import Marker
from openpyxl.chart.data_source import (AxDataSource, StrRef, StrData, MultiLevelStrRef,
                                        MultiLevelStrData, Level, StrVal, NumData, NumVal,
                                        NumDataSource, NumRef)
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Font, NamedStyle, PatternFill
from openpyxl.styles.fonts import DEFAULT_FONT
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import quote_sheetname
from openpyxl.drawing.image import Image
from openpyxl.chart.text import RichText
from openpyxl.chart.series import XYSeries, Series as SeriesObject, SeriesLabel
from openpyxl.chart.trendline import Trendline, TrendlineLabel
from openpyxl.drawing.text import CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties

from .appearance import TREND_LINE_WIDTH, TREND_MARKER_SIZE

MAX_TITLE = 31
_INVALID_TITLE = set('[]:*?/\\')
BLOCK_MIN_ROWS = 30
INFO_LABELS = (
    "Parameter", "Reference column", "Raw column", "Slope", "Intercept", "R²",
    "Valid pairs", "Bias limit", "Unit", "Card source", "Stage", "Scope", "Rows",
    "Fit",
)
SLOPE_OFFSET = INFO_LABELS.index("Slope")
INTERCEPT_OFFSET = INFO_LABELS.index("Intercept")
EXPORT_FONT = "Times New Roman"
PLOT_COLORS = ("5B9BD5", "ED7D31", "70AD47", "A879C2", "DD5965", "4FADB5")
PANEL_HEIGHT_CM = 11
MATCH_WIDTH_CM = 15
TREND_WIDTH_CM = 25
DYNAMIC_WIDTH_CM = 18
CHART_HORIZONTAL_GAP_CM = 1.0
CHART_VERTICAL_GAP_CM = 0.5
MATCH_CHART_LEFT_MARGIN_CM = 3.0
MATCH_CHART_RIGHT_MARGIN_CM = 0.7
MARKER_HEADROOM = .03
FM_PICTURE_HEIGHT_CM = 30
FM_PICTURE_WIDTH_CM = 72
WAFER_MAP_CELL_HEIGHT_CM = 8


def _match_chart_margins(width_cm):
    """Preferred physical margins, capped so a tiny Group keeps a plot area."""
    width_cm = max(.1, float(width_cm))
    return (
        min(MATCH_CHART_LEFT_MARGIN_CM, width_cm * .35),
        min(MATCH_CHART_RIGHT_MARGIN_CM, width_cm * .15),
    )


def _checkpoint(book, message=None):
    cancelled = getattr(book, '_export_cancelled', None)
    if cancelled is not None and cancelled():
        raise InterruptedError('Export cancelled')
    progress = getattr(book, '_export_progress', None)
    if message and progress is not None:
        progress(message)
    if cancelled is not None and cancelled():
        raise InterruptedError('Export cancelled')


def _column_width_pixels(width):
    width = 13. if width is None else float(width)
    return int(width * 12 + .5) if width < 1 else int(width * 7 + 5)


def _column_left_cm(worksheet, column):
    return sum(
        _column_width_pixels(worksheet.column_dimensions[get_column_letter(index)].width)
        for index in range(1, column)
    ) * 2.54 / 96


def _row_top_cm(worksheet, row):
    return sum(
        worksheet.row_dimensions[index].height or 15.
        for index in range(1, row)
    ) * 2.54 / 72


def _position_targeted_drawings(book):
    """Place Match charts and pictures at their exact physical grid coordinates."""
    from openpyxl.drawing.spreadsheet_drawing import AbsoluteAnchor
    from openpyxl.drawing.xdr import XDRPoint2D, XDRPositiveSize2D
    from openpyxl.utils.units import cm_to_EMU, pixels_to_EMU
    for worksheet in book:
        drawings = [*worksheet._charts, *worksheet._images]
        for drawing in drawings:
            target = getattr(drawing, '_export_position_cm', None)
            if target is None:
                continue
            if isinstance(drawing, Image):
                width, height = (
                    pixels_to_EMU(float(drawing.width)),
                    pixels_to_EMU(float(drawing.height)))
            else:
                width, height = (
                    cm_to_EMU(float(drawing.width)),
                    cm_to_EMU(float(drawing.height)))
            x_emu, y_emu = (cm_to_EMU(value) for value in target)
            drawing.anchor = AbsoluteAnchor(
                pos=XDRPoint2D(x_emu, y_emu),
                ext=XDRPositiveSize2D(width, height))


def plot_scale(values, *, tight=False, symmetric=False, headroom=0.):
    """Data-derived bounds; continuous X keeps padding instead of outer rounding."""
    finite = np.asarray(values, dtype=float).ravel()
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return None
    low, high = float(finite.min()), float(finite.max())
    if symmetric:
        high = max(abs(low), abs(high))
        low = -high
    fraction = .025 if tight else .05
    pad = (high - low) * fraction if high > low else (abs(low) * (.01 if tight else .05) or .5)
    low, high = low - pad, high + pad
    requested = (high - low) / 5
    power = 10. ** np.floor(np.log10(requested))
    step = min((1, 2, 2.5, 5, 10), key=lambda value: abs(value * power - requested)) * power
    if not tight:
        low, high = np.floor(low / step) * step, np.ceil(high / step) * step
        if headroom:
            margin = max((high - low) * headroom, step * .05)
            low, high = low - margin, high + margin
    return float(low), float(high), float(step)


def plot_axis_limits(axis, y, x=None, *, bars=False, symmetric=False):
    from matplotlib.ticker import MultipleLocator
    for name, values in (("y", y), ("x", x)):
        if values is None:
            continue
        scaled_values = np.r_[0., values] if bars and name == 'y' else values
        scale = plot_scale(
            scaled_values, tight=name == "x", symmetric=symmetric and name == "y",
            headroom=MARKER_HEADROOM if name == "y" and not bars else 0.)
        if scale:
            low, high, step = scale
            if name == "y" and bars:
                low, high = 0, max(high, step)
            getattr(axis, f"set_{name}lim")((low, high))
            getattr(axis, f"{name}axis").set_major_locator(MultipleLocator(step))


def style_native_series(series, index, *, markers=True, color=None, marker_size=4,
                        line_width=22860):
    color = color or PLOT_COLORS[index % len(PLOT_COLORS)]
    series.marker = Marker(symbol="circle" if markers else None,
                           size=marker_size if markers else None)
    series.marker.graphicalProperties = GraphicalProperties(solidFill=color,
        ln=LineProperties(noFill=True))
    if not series.graphicalProperties.line.noFill:
        series.graphicalProperties.line = LineProperties(
            solidFill=color, w=line_width, prstDash="solid")


def _chart_point_count(chart):
    """Count bound observations without loading or reducing their measurements."""
    from openpyxl.utils.cell import range_boundaries
    count = getattr(chart, '_identity_count', 0)
    for series in chart.series:
        values = series.yVal if isinstance(chart, ScatterChart) else series.val
        if values is not None and values.numRef is not None:
            bounds = range_boundaries(values.numRef.f.rsplit('!', 1)[-1])
            count = max(count, bounds[3] - bounds[1] + 1, bounds[2] - bounds[0] + 1)
    return count


def _equation_width(equation, chart_width):
    """Initial native equation extent; Excel auto-sizes trendline label boxes."""
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties
    # Excel General displays roughly four significant digits in its native
    # trendline equation. Measure that label, not the software Card's precision.
    import re
    text = re.sub(r'\d+(?:\.\d+)?(?:e[+-]?\d+)?',
                  lambda match: format(float(match.group()), '.4g'), equation, flags=re.I)
    renderer = RendererAgg(1, 1, 96)
    font = FontProperties(family=EXPORT_FONT, size=11)
    pixels = max((renderer.get_text_width_height_descent(line, font, False)[0]
                  for line in text.split(' · ')), default=0) + 6
    return min(.90, pixels / (chart_width * 96 / 2.54))


def chart_limits(chart, y, x=None, *, bars=False, symmetric=False):
    bounds = plot_scale(
        np.r_[0., y] if bars else y, symmetric=symmetric,
        headroom=0. if bars else MARKER_HEADROOM)
    if bounds:
        chart.y_axis.scaling.min = 0 if bars else bounds[0]
        chart.y_axis.scaling.max = max(bounds[1], bounds[2]) if bars else bounds[1]
        chart.y_axis.majorUnit = bounds[2]
    if x is not None:
        bounds = plot_scale(x, tight=True)
        if bounds:
            chart.x_axis.scaling.min, chart.x_axis.scaling.max = bounds[:2]
            chart.x_axis.majorUnit = bounds[2]


def style_plot_axis(axis, *, title, xlabel, ylabel):
    """Shared compact report frame; style only this figure, never global rcParams."""
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    axis.set_title(title, fontsize=16, fontweight="bold", pad=32)
    axis.set_xlabel(xlabel, fontsize=12, labelpad=8)
    axis.set_ylabel(ylabel, fontsize=12, labelpad=8)
    axis.set_facecolor("white")
    axis.set_axisbelow(True)
    axis.grid(True, which="major", color="#DFE3E8", linewidth=.6)
    axis.tick_params(axis="both", labelsize=10, colors="#334155", length=3, width=1.2)
    for spine in axis.spines.values():
        spine.set_color("#64748B")
        spine.set_linewidth(1.2)
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5))
    axis.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    axis.ticklabel_format(axis="y", style="plain", useOffset=False)


def plot_legend(axis, handles=None, labels=None, *, columns=3):
    if handles is None:
        handles, labels = axis.get_legend_handles_labels()
    axis.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.015),
                ncol=min(columns, len(labels)),
                fontsize=11, frameon=False, borderaxespad=0, handlelength=2, columnspacing=1.4)


def stage_suffix(stage):
    return " (W Card)" if str(stage).lower() == "final" else " (WO Card)"


def _value(value):
    """Convert pandas/numpy scalars to values openpyxl can write."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return value
    if isinstance(missing, bool) and missing:
        return None
    return value


def sheet_title(base, used, suffix=""):
    """Excel-legal, unique sheet name: 31 characters, no []:*?/\\."""
    text = "".join(" " if character in _INVALID_TITLE else character
                   for character in str(base)).strip() or "Sheet"
    text = text[:MAX_TITLE - len(suffix)]
    candidate, index = text + suffix, 2
    while candidate.casefold() in used:
        number = f"_{index}"
        candidate = text[:MAX_TITLE - len(number) - len(suffix)] + number + suffix
        index += 1
    used.add(candidate.casefold())
    return candidate


def group_show_wafer_sheet_title(used, suffix=""):
    """Keep every stage term inside Excel's 31-character sheet limit."""
    base = 'Match Group show Wafer'
    if len(base + suffix) > MAX_TITLE:
        suffix = suffix.lstrip()
    return sheet_title(base, used, suffix)


def _write_frame(worksheet, frame, *, start_column=1):
    _checkpoint(worksheet.parent, f'Writing {worksheet.title}')
    if frame is None or not len(frame.columns):
        return
    # Explicit coordinates: styling cells first must not shift the table down.
    for index, name in enumerate(frame.columns):
        column = start_column + index
        cell = worksheet.cell(row=1, column=column, value=str(name))
        cell.data_type = "s"
        cell.font = Font(name=EXPORT_FONT, bold=True)
        samples = [len(str(name)), *(len(str(value)) for value in frame.iloc[:100, index] if value is not None)]
        worksheet.column_dimensions[get_column_letter(column)].width = max(12, min(36, max(samples) + 2))
    for offset, row in enumerate(frame.itertuples(index=False, name=None), start=2):
        if offset % 256 == 0:
            _checkpoint(worksheet.parent)
        for column, item in enumerate(row, start=start_column):
            cell = worksheet.cell(row=offset, column=column, value=_value(item))
            if isinstance(item, str):
                cell.data_type = "s"  # Source measurement text is never an Excel formula.


def _fill_title(worksheet):
    worksheet["A1"].font = Font(bold=True)
    worksheet.freeze_panes = worksheet["A2"]


def _label_spans(labels, limit=5):
    """Representative contiguous spans, separated by their actual plot positions."""
    runs = []
    for index, label in enumerate(labels):
        if runs and runs[-1][2] == label:
            runs[-1] = (runs[-1][0], index, label)
        else:
            runs.append((index, index, label))
    if len(runs) <= 1 or limit is None:
        return runs
    centers = np.array([(start + end) / 2 for start, end, _ in runs])
    count = min(limit, len(runs))
    indices = sorted(set(int(np.abs(centers - target).argmin())
                         for target in np.linspace(centers[0], centers[-1], count)))
    spacing = .85 * (centers[-1] - centers[0]) / (count - 1)
    selected = [indices[0]]
    for index in indices[1:]:
        if centers[index] - centers[selected[-1]] >= spacing:
            selected.append(index)
        elif index == indices[-1] and len(selected) > 1:
            selected[-1] = index
    return [runs[index] for index in selected]


def sequence_layout(labels, *, name="Wafer", cache=None):
    """Reserve measured caption widths without changing observations or row order.

    Coordinates are ordinal display positions, not Die Seq measurement values.
    PNG spacing is locally expanded; ordinary Excel category charts instead
    receive enough physical width to keep the same captions readable.
    """
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties
    from .plotting.sequence_axis import WaferSpacing
    labels = list(labels)
    key = (name, tuple(labels)) if cache is not None else None
    if cache is not None and key in cache:
        return dict(cache[key])
    count = len(labels)
    limits = (.5, max(1, count) + .5)
    if not count:
        return {"name": name, "x": np.array([]), "ticks": [], "width": TREND_WIDTH_CM,
                "native_width": TREND_WIDTH_CM, "limits": limits}
    renderer, font = RendererAgg(1, 1, 96), FontProperties(family=EXPORT_FONT, size=11)
    from functools import cache as memoize
    @memoize
    def measure(text):
        return renderer.get_text_width_height_descent(text, font, False)[0]
    runs = _label_spans(labels, limit=None)
    # A dense single Wafer still fits the 25 cm base panel. Only captions that
    # genuinely need more room add width, rather than two pixels per source row.
    factor = min(1., (TREND_WIDTH_CM * 96 / 2.54 - 110) / (2 * count))
    spans = [((start + .5) * factor, (end + 1.5) * factor, label) for start, end, label in runs]
    spacing = WaferSpacing(spans, tuple(value * factor for value in limits), measure)
    ticks = [(float(spacing.forward((start + end + 2) / 2 * factor)) / factor, label)
             for start, end, label in runs]
    centers = np.array([(start + end + 2) / 2 for start, end, _ in runs])
    widths = np.array([max((measure(line) for line in text.splitlines()), default=0) + 16 for _, _, text in runs])
    required = max(widths[0] * count / (2 * (centers[0] - .5)),
                   widths[-1] * count / (2 * (count + .5 - centers[-1])))
    if len(runs) > 1:
        required = max(required, float(np.max((widths[1:] + widths[:-1]) / 2 * count / np.diff(centers))))
    layout = {"name": name, "x": spacing.forward(np.arange(1, count + 1) * factor) / factor,
            "source": spacing.source / factor, "display": spacing.display / factor,
            "native_width": max(TREND_WIDTH_CM, (required + 110) * 2.54 / 96),
            "ticks": ticks, "width": max(TREND_WIDTH_CM, (spacing.width + 110) * 2.54 / 96), "limits": limits}
    if cache is not None:
        cache[key] = layout
    return dict(layout)


def native_categories(sheet, first, last, identities):
    """Ordinary local multi-level categories, editable with Excel range handles."""
    levels = []
    for column, values in reversed(identities):
        points = [StrVal(idx=index, v=str(value)) for index, value in enumerate(values)
                  if index == 0 or (len(identities) > 1 and column == identities[-1][0]) or value != values[index - 1]]
        levels.append(Level(pt=points))
    return AxDataSource(multiLvlStrRef=MultiLevelStrRef(
        f=str(Reference(sheet, min_col=identities[0][0], max_col=identities[-1][0], min_row=first, max_row=last)),
        # ptCount is optional in OOXML; openpyxl 3.1 cannot serialize its
        # plain-integer descriptor here. The complete inner level sets depth.
        multiLvlStrCache=MultiLevelStrData(lvl=levels)))


def identity_captions(sheet, first, labels, keys, column, *, limit=6, role='wafer', level=0):
    """Sparse, cell-linked captions; all observations and identities stay in the table."""
    count = len(labels)
    spans = _label_spans(keys, limit=None)
    shown = (set(np.linspace(0, len(spans) - 1, limit).round().astype(int))
             if limit is not None and len(spans) > limit else set(range(len(spans))))
    return [{'text': str(labels[start]),
             'source': f'{quote_sheetname(sheet.title)}!${get_column_letter(column)}${first + start}',
             'start': start / count, 'end': (end + 1) / count,
             'center': (start + end + 1) / (2 * count),
             'role': role, 'level': level, 'show': index in shown}
            for index, (start, end, _) in enumerate(spans)] if count else []


def report_sequence_layout(dies, captions=(), *, name='Wafer'):
    """Tight observation ordinals; physical width follows visible label demand."""
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties
    layout = sequence_layout([''] * len(dies), name=name)
    renderer, font = RendererAgg(1, 1, 96), FontProperties(family=EXPORT_FONT, size=11)
    def measure(text):
        return max((renderer.get_text_width_height_descent(line, font, False)[0]
                    for line in str(text).splitlines()), default=0)
    ticks = [dies[i] for i in range(0, len(dies), max(1, int(np.ceil(len(dies) / 18))))]
    needed = sum(measure(value) + 12 for value in ticks)
    for level in sorted({item.get('level', 0) for item in captions}):
        entries = [item for item in captions if item.get('level', 0) == level and item.get('show', True)]
        for left, right in zip(entries, entries[1:]):
            # Very short adjacent segments may fan their captions out with a
            # leader. Do not create metre-wide charts for one-point wafers.
            distance = max(.04, right['center'] - left['center'])
            needed = max(needed, ((measure(left['text']) + measure(right['text'])) / 2 + 16) / distance)
    layout['width'] = layout['native_width'] = max(TREND_WIDTH_CM, (needed / .85 + 110) * 2.54 / 96)
    if captions:
        layout['captions'] = captions
    return layout


def _tight_span_widths(counts, labels, measure):
    """Smallest span sets the scale; larger spans grow with their point count."""
    counts = np.asarray(counts, dtype=float)
    counts = np.where(np.isfinite(counts) & (counts > 0), counts, 1)
    minimums = np.asarray([
        max((measure(line) for line in str(label).splitlines()), default=0) + 16
        for label in labels
    ], dtype=float)
    least = counts.min()
    base = max(minimums[counts == least] / least)
    return np.maximum(minimums, base * counts)


def sequence_export_layout(data, *, mode, captions=()):
    """Tight Group/Wafer export geometry, with no artificial maximum width.

    Group mode handles mixed Show wafer choices independently: hidden-wafer
    groups use the group-only proportional layout, while visible-wafer groups
    use the sum of their wafer label widths. Wafer mode applies the same wafer
    rule across the whole sheet.
    """
    from functools import cache as memoize
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties

    frame = pd.DataFrame(data)
    count = len(frame)
    name = 'Wafer' if mode == 'wafer' else 'Group'
    empty = {"name": name, "x": np.array([]), "ticks": [], "limits": (0., 1.),
             "width": 0., "native_width": 0., "group_only_widths": {},
             "group_widths": {}, "wafer_widths": {}, "captions": list(captions),
             "native_captions": list(captions), "tick_indices": []}
    if not count:
        return empty

    group_labels = (frame.get('Group label', frame.get('Group caption',
                    frame.get('Group', pd.Series([''] * count)))).astype(str).tolist())
    group_keys = frame.get('Group', pd.Series(group_labels)).astype(str).tolist()
    wafer_labels = frame.get('Wafer', frame.get('Label',
                   pd.Series([''] * count))).astype(str).tolist()
    wafer_keys = frame.get('Wafer key', pd.Series(wafer_labels)).map(
        lambda value: repr(tuple(value)) if isinstance(value, (tuple, list)) else str(value)
    ).tolist()
    shown = frame.get('Show wafer', pd.Series([False] * count)).fillna(False).astype(bool).tolist()
    raw = pd.to_numeric(frame.get('Raw', pd.Series(np.ones(count))), errors='coerce').to_numpy(float)
    reference = pd.to_numeric(frame.get('Reference', pd.Series(np.ones(count))), errors='coerce').to_numpy(float)
    drawable = np.isfinite(raw) & np.isfinite(reference)

    renderer = RendererAgg(1, 1, 96)
    font = FontProperties(family=EXPORT_FONT, size=11)
    @memoize
    def measure(text):
        return renderer.get_text_width_height_descent(str(text), font, False)[0]

    group_spans = _label_spans(group_keys, limit=None)
    group_counts = [max(1, int(drawable[start:end + 1].sum()))
                    for start, end, _key in group_spans]
    group_only_widths_array = _tight_span_widths(
        group_counts, [group_labels[start] for start, _end, _key in group_spans], measure)
    group_only = {key: float(width) for (_start, _end, key), width
                  in zip(group_spans, group_only_widths_array)}

    segments = []
    edge_pairs = [(0, 0.)]
    group_widths = {}
    wafer_widths = {}
    cursor = 0.
    if mode == 'wafer':
        wafer_spans = _label_spans(wafer_keys, limit=None)
        counts = [max(1, int(drawable[start:end + 1].sum())) for start, end, _key in wafer_spans]
        widths = _tight_span_widths(
            counts, [wafer_labels[start] for start, _end, _key in wafer_spans], measure)
        for (start, end, key), width in zip(wafer_spans, widths):
            segments.append([(start, end, cursor, float(width))])
            wafer_widths[key] = float(width)
            edge_pairs.extend(((float(start), cursor),
                               (float(end + 1), cursor + float(width))))
            cursor += float(width)
    else:
        for (start, end, group_key), group_width in zip(group_spans, group_only_widths_array):
            pieces = []
            if any(shown[start:end + 1]):
                local_wafers = _label_spans(wafer_keys[start:end + 1], limit=None)
                local_wafers = [(first + start, last + start, key)
                                for first, last, key in local_wafers]
                counts = [max(1, int(drawable[first:last + 1].sum()))
                          for first, last, _key in local_wafers]
                widths = _tight_span_widths(
                    counts, [wafer_labels[first] for first, _last, _key in local_wafers],
                    measure)
                total = float(widths.sum())
                group_label_min = max(
                    measure(line) for line in group_labels[start].splitlines()) + 16
                if total < group_label_min:
                    widths *= group_label_min / total
                    total = group_label_min
                piece_cursor = cursor
                for (first, last, key), width in zip(local_wafers, widths):
                    pieces.append((first, last, piece_cursor, float(width)))
                    wafer_widths.setdefault(group_key, {})[key] = float(width)
                    edge_pairs.extend(((float(first), piece_cursor),
                                       (float(last + 1), piece_cursor + float(width))))
                    piece_cursor += float(width)
                group_width = total
            else:
                pieces.append((start, end, cursor, float(group_width)))
                edge_pairs.extend(((float(start), cursor),
                                   (float(end + 1), cursor + float(group_width))))
            segments.append(pieces)
            group_widths[group_key] = float(group_width)
            cursor += float(group_width)

    if not segments:
        return empty
    edge_map = {}
    for source, display in sorted(edge_pairs):
        edge_map[source] = display
    source_edges = list(edge_map)
    display_edges = [edge_map[source] for source in source_edges]
    x = np.zeros(count, dtype=float)
    for pieces in segments:
        for first, last, piece_start, width in pieces:
            x[first:last + 1] = piece_start + width * (
                np.arange(1, last - first + 2, dtype=float) - .5) / (last - first + 1)

    total_width = max(1., float(cursor))
    remapped = []
    for item in captions:
        mapped = dict(item)
        for field in ('start', 'end', 'center'):
            source = float(item.get(field, 0.)) * count
            display = float(np.interp(source, source_edges, display_edges)) / total_width
            mapped[field] = display
        remapped.append(mapped)
    width_cm = (total_width + 110) * 2.54 / 96
    plot_pixels = max(1., width_cm * 96 / 2.54 - 110)
    # Sample inside each Group/Wafer span instead of stepping through the
    # concatenated rows. A global step skips whole wafers and produces labels
    # such as 1, 12, 3, 14, which no longer read as Die Seq. Span-local
    # candidates keep every visible segment represented and let the renderer
    # retain as many as its measured width can accommodate.
    tick_indices = []
    for pieces in segments:
        for first, last, _piece_start, piece_width in pieces:
            local_count = last - first + 1
            piece_pixels = plot_pixels * piece_width / total_width
            capacity = max(1, min(
                local_count, int(piece_pixels / 32)))
            offsets = np.linspace(
                0, local_count - 1, capacity).round().astype(int)
            tick_indices.extend(first + int(offset) for offset in offsets)
    tick_indices = sorted(set(tick_indices))
    die_values = frame.get(
        'Die Seq', pd.Series([''] * count)).tolist()
    ticks = [(float(x[index]), str(die_values[index]))
             for index in tick_indices]
    layout = {
        "name": name, "x": x, "ticks": ticks, "limits": (0., total_width),
        "source": np.asarray(source_edges), "display": np.asarray(display_edges),
        "width": width_cm, "native_width": width_cm,
        "group_only_widths": group_only, "group_widths": group_widths,
        "wafer_widths": wafer_widths, "captions": remapped,
        "native_captions": list(captions), "captions_are_display": True,
        "tick_indices": tick_indices,
    }
    return dict(layout)


def _native_die_axis_eligible(data, layout, mode):
    """Use native categories only when their centres preserve all geometry."""
    count = len(data)
    if not count or 'Die Seq' not in data:
        return False
    if mode == 'group':
        shown = data.get('Show wafer', pd.Series([False] * count)).fillna(False).astype(bool).tolist()
        groups = data.get('Group', pd.Series([''] * count)).astype(str).tolist()
        expanded = [any(shown[first:last + 1])
                    for first, last, _key in _label_spans(groups, limit=None)]
        if any(expanded) and not all(expanded):
            return False
    x = np.asarray(layout['x'], dtype=float)
    limits = np.asarray(layout['limits'], dtype=float)
    if (x.shape != (count,) or limits.shape != (2,)
            or not np.isfinite(x).all() or not np.isfinite(limits).all()
            or limits[1] <= limits[0]):
        return False
    span = limits[1] - limits[0]
    if not np.allclose((x - limits[0]) / span,
                       (np.arange(count) + .5) / count, rtol=0, atol=1e-12):
        return False
    # Boundary/caption equivalence is independent of point equivalence when
    # spans contain a single observation or labels impose a minimum width.
    if not np.allclose((np.asarray(layout['display']) - limits[0]) / span,
                       np.asarray(layout['source']) / count, rtol=0, atol=1e-12):
        return False
    captions, originals = layout.get('captions', ()), layout.get('native_captions', ())
    if len(captions) != len(originals):
        return False
    return all(np.allclose([caption[field] for field in ('start', 'end', 'center')],
                           [original[field] for field in ('start', 'end', 'center')],
                           rtol=0, atol=1e-12)
               for caption, original in zip(captions, originals))


def _native_identity_categories(helper, helper_row, layout, *, start=0):
    """Cell-bound numeric x values shared by data, captions and dividers."""
    values = np.asarray(layout["x"], dtype=float)
    for offset, value in enumerate(values):
        helper.cell(
            row=helper_row + start + offset, column=3,
            value=float(value))
    last = helper_row + start + len(values) - 1
    return AxDataSource(numRef=NumRef(
        f=str(Reference(
            helper, min_col=3, min_row=helper_row + start,
            max_row=last)),
        numCache=NumData(
            formatCode="General", ptCount=len(values),
            pt=[NumVal(idx=index, v=float(value))
                for index, value in enumerate(values)])))


def parameter_footer(sheet, first, data, columns, mode):
    """One wafer strip and, when grouped, a separate outer Group strip."""
    if data.attrs.get("mark2"):
        from .mark2_export import captions
        fields = data.attrs["mark2"]["columns"]
        values = data[[f"Mark2 · {name}" for name in fields]].values.tolist()
        return captions(fields, values, lambda row, field:
                        f"{quote_sheetname(sheet.title)}!${get_column_letter(columns[f'Mark2 · {field}'])}${first + row}")
    grouped = mode == 'group' and 'Group' in columns
    groups = data['Group'].tolist() if grouped else [''] * len(data)
    keys = list(zip(groups, data['Wafer key']))
    wafers = identity_captions(
        sheet, first, data['Wafer'].tolist(), keys, columns['Wafer'], limit=None)
    if grouped:
        show = data.get('Show wafer', pd.Series([False] * len(data))).tolist()
        wafers = [item for item in wafers if show[round(item['start'] * len(data))]]
        labels = data.get('Group label', data.get('Group caption',
                        data['Group'])).tolist()
        return wafers + identity_captions(
            sheet, first, labels, groups, columns['Group'],
            limit=None, role='group', level=int(bool(wafers)))
    return wafers


def footer_boundaries(captions):
    """True segment edges, independent of which caption text can be displayed."""
    return {role: sorted({item['start'] for item in captions if item['role'] == role and item['start'] > 0})
            for role in ('wafer', 'group')}


def footer_margin(captions):
    levels = sorted({item['level'] for item in captions})
    lines = sum(max(len(item['text'].splitlines()) or 1 for item in captions if item['level'] == level)
                for level in levels)
    return 1.6 + .5 * (lines + max(0, len(levels) - 1))


def draw_sequence_axis(axis, sequence, dies=(), *, boundary_gap=0.0):
    """The WKB hierarchy: real Die Seq ticks, then one caption per span."""
    if sequence.get("mode") == "mark2":
        from .mark2_plotting import draw_hierarchy
        axis.set_xlim(sequence["limits"])
        draw_hierarchy(axis, **sequence["mark2"])
        return
    from matplotlib.font_manager import FontProperties
    from matplotlib.backends.backend_agg import RendererAgg
    from .plotting.sequence_axis import fit_tick_labels
    selected = sequence['ticks']
    axis.set_xlim(sequence['limits'])
    if not len(dies):
        axis.set_xticks([x for x, _ in selected], [label for _, label in selected], fontsize=10)
        axis.set_xlabel(sequence['name'], fontsize=12, labelpad=8)
        return
    font = FontProperties(family=EXPORT_FONT, size=10)
    renderer = RendererAgg(1, 1, axis.figure.dpi)
    measure = lambda text: renderer.get_text_width_height_descent(str(text), font, False)[0]
    ticks = fit_tick_labels(list(zip(sequence['x'], map(str, dies))), sequence['limits'],
                            axis.bbox.width, measure)
    axis.set_xticks([x for x, _ in ticks], [label for _, label in ticks], fontsize=10)
    axis.set_xlabel('Die Seq', fontsize=12, labelpad=6)
    if sequence.get('mode') == 'die':
        return
    if 'captions' in sequence:
        captions = sequence['captions']
        count = len(dies)
        if sequence.get('captions_are_display'):
            low, high = sequence['limits']
            project = lambda fraction: float(low + fraction * (high - low))
        else:
            project = lambda fraction: float(np.interp(
                .5 + fraction * count, sequence['source'], sequence['display']))
        height_points = axis.bbox.height * 72 / axis.figure.dpi
        offset = 42
        first_top = 34
        for level in sorted({item['level'] for item in captions}):
            from .native_chart_labels import caption_boxes
            entries = [item for item in captions if item['level'] == level]
            lines = max((len(item['text'].splitlines()) for item in entries), default=1)
            end = offset + lines * 12 + 4
            visible = [item for item in entries if item['show']]
            boxes = caption_boxes(
                visible, (0., 1.), width_px=axis.bbox.width)
            for item, (center, _width) in zip(visible, boxes):
                fraction = center
                axis.annotate(item['text'], (project(fraction), 0), xycoords=('data', 'axes fraction'),
                              xytext=(0, -offset), textcoords='offset points', ha='center', va='top',
                              fontsize=11, annotation_clip=False,
                              bbox=dict(facecolor='none', edgecolor='none', pad=1), zorder=5)
            top = first_top if entries[0]['role'] == 'group' else offset - 8
            dense_wafers = entries[0]['role'] == 'wafer' and len(entries) > 12
            for boundary in sorted({v for item in entries if not dense_wafers or item['show']
                                    for v in (item['start'], item['end'])}):
                x = project(boundary)
                axis.plot([x, x], [-top / height_points, -end / height_points],
                          transform=axis.get_xaxis_transform(), color='#929292' if dense_wafers else 'black',
                          linewidth=.75 if dense_wafers else 1.5, clip_on=False)
            offset = end + 6
        for role, positions in footer_boundaries(captions).items():
            group_edges = set(footer_boundaries(captions)['group'])
            for position in positions:
                if role == 'wafer' and position in group_edges:
                    continue
                axis.axvline(project(position), ymin=boundary_gap, color='#000000' if role == 'group' else '#929292',
                             linewidth=1.5 if role == 'group' else .75, linestyle='--', zorder=0)
        return
    for x, label in selected:
        axis.annotate(label, (x, 0), xycoords=('data', 'axes fraction'), xytext=(0, -40),
                      textcoords='offset points', ha='center', va='top', fontsize=11,
                      annotation_clip=False)
    lines = max((len(label.splitlines()) for _, label in selected), default=1)
    for x, label in sequence.get('group_ticks', ()):
        axis.annotate(label, (x, 0), xycoords=('data', 'axes fraction'), xytext=(0, -50 - 12 * lines),
                      textcoords='offset points', ha='center', va='top', fontsize=11,
                      annotation_clip=False)
    for x in sequence.get('boundaries', ()):
        axis.axvline(x, ymin=boundary_gap, ymax=1, color='#000000',
                     linewidth=2, linestyle='--', zorder=0)
    if sequence.get('mode') in ('group', 'wafer'):
        for x in (sequence['limits'][0], *sequence.get('boundaries', ()), sequence['limits'][1]):
            axis.plot([x, x], [-.14, -.31], transform=axis.get_xaxis_transform(),
                      clip_on=False, color='#000000', linewidth=2)
        if sequence.get('mode') == 'wafer':
            axis.set_xlabel('')


def _next_plot_column(sheet, column, pixels):
    """Leave a gutter after a drawing, accounting for this sheet's real widths."""
    pixels += 24
    while pixels > 0:
        if column > 16384:
            raise ValueError("Repeated identity captions exceed Excel's worksheet width. Collect rows by Wafer before exporting.")
        width = sheet.column_dimensions[get_column_letter(column)].width
        pixels -= (width or 13) * 7 + 5
        column += 1
    return column


def _original_value(original, column, source_row):
    source = f"'{original.title}'!${column}${int(source_row) + 2}"
    return f'=IF({source}="",NA(),IFERROR({source}*1,NA()))'


def _write_parameter_block(worksheet, row, parameter, mapping, data, card,
                           card_source, scope, stage, *, native=True, images=None, show_percent=False, reference_label="REF", original=None, wafer_only=False, axis_mode=None, panel_widths=None,
                           start_column=1, chart_row=None, chart_column=None,
                           chart_index=0, chart_top_cm=None):
    """Compact visible measurements; chart labels/fit provenance stay internal."""
    _checkpoint(worksheet.parent, f'{stage}: {scope} — {parameter}')
    reference = data["Reference"].to_numpy(float)
    raw = data["Raw"].to_numpy(float)
    count = len(data)
    slope = float(card.slope) if card is not None and np.isfinite(card.slope) else None
    intercept = (float(card.intercept)
                 if card is not None and np.isfinite(card.intercept) else None)
    equation = ""
    if slope is not None and intercept is not None:
        sign = "+" if intercept >= 0 else "-"
        equation = f"y = {slope:.6g}x {sign} {abs(intercept):.6g}"
        if card is not None and np.isfinite(card.r_squared):
            equation += f" · R² = {card.r_squared:.6g}"
    facts = (
        parameter,
        "" if mapping is None else mapping.reference_column,
        parameter if mapping is None else mapping.raw_column,
        slope,
        intercept,
        None if card is None or not np.isfinite(card.r_squared) else float(card.r_squared),
        None if card is None else int(card.valid_pairs),
        "" if mapping is None or mapping.bias_limit is None else float(mapping.bias_limit),
        "" if mapping is None else _unit(mapping.reference_column),
        card_source,
        stage,
        scope,
        count,
        equation,
    )
    helper = worksheet.parent["_Plot data"]
    helper_row = helper.max_row + 3
    for column, text in enumerate(("Source row", "Axis label", "Plot X", "Fit Y"), 1):
        helper.cell(row=helper_row - 1, column=column, value=text)
    for offset, (label, value) in enumerate(zip(INFO_LABELS, facts)):
        helper.cell(row=helper_row + offset, column=10, value=label)
        helper.cell(row=helper_row + offset, column=11, value=_value(value))
    slope_cell = f"'{helper.title}'!$K${helper_row + SLOPE_OFFSET}"
    intercept_cell = f"'{helper.title}'!$K${helper_row + INTERCEPT_OFFSET}"
    final = stage.lower() == "final"
    fit = slope is not None and intercept is not None
    identities = (["Group"] if "Group label" in data else []) + ["Wafer", "Die Seq"]
    if data.attrs.get("mark2"):
        identities += [f"Mark2 · {name}" for name in data.attrs["mark2"]["columns"]]
    headers = identities + ["PMISH"] + ([] if final else ["PMISH+Card"]) + [reference_label, "Bias", "Bias %"]
    columns = {name: index for index, name in enumerate(headers, start_column)}
    if (chart_row is None and count and worksheet.title.startswith('Match Original (')
            and worksheet.sheet_view.pane.topLeftCell.startswith('A')):
        first_plot = f'A{row}'
        worksheet.sheet_view.topLeftCell = 'A1'
        worksheet.sheet_view.pane.topLeftCell = first_plot
        worksheet.sheet_view.selection[-1].activeCell = first_plot
        worksheet.sheet_view.selection[-1].sqref = first_plot
    worksheet.merge_cells(start_row=row, start_column=start_column,
                          end_row=row, end_column=start_column + len(headers) - 1)
    title = worksheet.cell(row=row, column=start_column, value=parameter)
    title.font = Font(name=EXPORT_FONT, size=14, bold=True)
    title.alignment = Alignment(horizontal="center", vertical="center")
    worksheet.row_dimensions[row].height = 22
    worksheet.row_dimensions[row + 1].height = 20
    header_row = row + 1
    for column, text in enumerate(headers, start=start_column):
        cell = worksheet.cell(row=header_row, column=column, value=text)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="EEF2F7")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        letter = get_column_letter(column)
        worksheet.column_dimensions[letter].width = max(worksheet.column_dimensions[letter].width,
                                                        30 if text == "Wafer" else 16 if text == "Group" else 14)
    first_row = header_row + 1
    primary_labels = data["Wafer"] if wafer_only else data.get("Group label", data.get("Wafer", data.get("Label", pd.Series([""] * count))))
    axis_labels = {(start + end) // 2: label for start, end, label in _label_spans(primary_labels, limit=None)}
    source_column = (next(cell.column_letter for cell in original[1]
                         if cell.column >= getattr(original, '_source_start_column', 1) and cell.value == mapping.raw_column)
                     if original is not None and mapping is not None else None)
    # Register common styles once. Rebuilding and hashing an Alignment for
    # every measurement cell dominated large reports; NamedStyle copies keep
    # later merged-caption edits isolated from the numeric cells.
    for name, alignment in (('Export value', Alignment(vertical='center')),
                            ('Export label', Alignment(wrap_text=True, vertical='center'))):
        if name not in worksheet.parent.named_styles:
            font = copy(DEFAULT_FONT)
            font.name, font.scheme = EXPORT_FONT, None
            worksheet.parent.add_named_style(NamedStyle(name=name,
                font=font, alignment=alignment))
    value_style = worksheet.parent._named_styles['Export value'].as_tuple()
    label_style = worksheet.parent._named_styles['Export label'].as_tuple()
    identity_values = {name: data['Group caption' if name == 'Group' and 'Group caption' in data
                               else 'Group label' if name == 'Group' else name].tolist()
                       if ('Group label' if name == 'Group' else name) in data else [''] * count
                       for name in identities}
    source_rows = data['Source row'].tolist() if 'Source row' in data else data.index.tolist()
    keys = data['Wafer key'].tolist() if wafer_only else list(zip(data['Group'], data['Wafer key']))
    wafer_spans = _label_spans(keys, limit=None)
    wafer_starts = {start for start, _end, _key in wafer_spans}
    group_spans = _label_spans(identity_values['Group'], limit=None) if 'Group' in columns else []
    group_starts = {start for start, _end, _key in group_spans}
    for index in range(count):
        if index % 256 == 0:
            _checkpoint(worksheet.parent)
        target = first_row + index
        for name in identities:
            if name == 'Wafer' and index not in wafer_starts:
                continue
            if name == 'Group' and index not in group_starts:
                continue
            value = identity_values[name][index]
            cell = worksheet.cell(row=target, column=columns[name], value=_value(value))
            if isinstance(value, str):
                cell.data_type = "s"
                cell._style = copy(label_style)
        worksheet.row_dimensions[target].height = 15
        raw_cell = f"{get_column_letter(columns['PMISH'])}{target}"
        raw_value = _value(raw[index])
        if source_column is not None:
            raw_value = _original_value(original, source_column, source_rows[index])
        worksheet.cell(row=target, column=columns["PMISH"], value=raw_value)
        # Final Raw Data is already the accepted post-Card source. Applying
        # the fitted Card here a second time would disagree with the software.
        if not final:
            worksheet.cell(row=target, column=columns["PMISH+Card"],
                           value=f'=IF(ISNUMBER({raw_cell}),{slope_cell}*{raw_cell}+{intercept_cell},NA())' if fit else None)
        evaluated_cell = f"{get_column_letter(columns['PMISH' if final else 'PMISH+Card'])}{target}"
        ref_cell = f"{get_column_letter(columns[reference_label])}{target}"
        reference_value = _value(reference[index])
        if original is worksheet:
            if not hasattr(original, '_reference_cells'):
                original._reference_cells = {}
            original._reference_cells[parameter, int(source_rows[index])] = f'${get_column_letter(columns[reference_label])}${target}'
        elif original is not None:
            source = getattr(original, '_reference_cells', {}).get((parameter, int(source_rows[index])))
            if source is not None:
                source = f'{quote_sheetname(original.title)}!{source}'
                reference_value = f'=IF(ISNUMBER({source}),{source},NA())'
        worksheet.cell(row=target, column=columns[reference_label], value=reference_value)
        worksheet.cell(row=target, column=columns["Bias"],
                       value=f'=IF(AND(ISNUMBER({evaluated_cell}),ISNUMBER({ref_cell})),{evaluated_cell}-{ref_cell},NA())')
        worksheet.cell(row=target, column=columns["Bias %"],
                       value=(f'=IF(AND(ISNUMBER({evaluated_cell}),ISNUMBER({ref_cell})),'
                              f'IF({ref_cell}=0,NA(),({evaluated_cell}-{ref_cell})/{ref_cell}*100),NA())'))
        for column in range(start_column + len(identities), start_column + len(headers)):
            worksheet.cell(row=target, column=column)._style = copy(value_style)
        source_row = source_rows[index]
        helper.cell(row=helper_row + index, column=1, value=int(source_row) + 1)
        cell = helper.cell(row=helper_row + index, column=2, value=axis_labels.get(index, ""))
        cell.data_type = "s"
    # Merge only the derived presentation column. A hidden Lot/PAD caption must
    # never merge different measurement identities, or cross a Group boundary.
    for start, end, _key in wafer_spans:
        if end > start:
            # These fresh, borderless captions have no interior cells. Register
            # the range directly instead of creating/discarding every repeated
            # label and then styling hundreds of thousands of merged cells.
            column = get_column_letter(columns['Wafer'])
            worksheet.merged_cells.add(f'{column}{first_row + start}:{column}{first_row + end}')
        cell = worksheet.cell(first_row + start, columns["Wafer"])
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if end == start:
            worksheet.row_dimensions[first_row + start].height = 15 * max(1, len(str(cell.value).splitlines()))
    for start, end, _key in group_spans:
        if end > start:
            column = get_column_letter(columns['Group'])
            worksheet.merged_cells.add(f'{column}{first_row + start}:{column}{first_row + end}')
        worksheet.cell(first_row + start, columns['Group']).alignment = Alignment(
            horizontal='center', vertical='center', wrap_text=True)
    last_row = first_row + count - 1
    evaluated_values = raw if stage.lower() == "final" else (slope * raw + intercept if fit else np.full(count, np.nan))
    percentages = np.full(count, np.nan)
    np.divide((evaluated_values - reference) * 100, reference, out=percentages,
              where=np.isfinite(reference) & (reference != 0))
    if not hasattr(worksheet.parent, '_export_layouts'):
        worksheet.parent._export_layouts = {}
    layout_cache = worksheet.parent._export_layouts
    layouts = [sequence_layout(primary_labels, name="Group" if "Group label" in data and not wafer_only else "Wafer", cache=layout_cache)]
    if "Group label" in data and not wafer_only:
        labels = [f"{group}\n{wafer}" for group, wafer in zip(data["Group label"], data["Wafer"])]
        detail = sequence_layout(labels, cache=layout_cache)
        detail['ticks'] = [(position, label.split('\n', 1)[1]) for position, label in detail['ticks']]
        detail['group_ticks'] = [(float(np.interp((start + end + 2) / 2, detail['source'], detail['display'])), label)
                                 for start, end, label in _label_spans(data['Group label'], limit=None)]
        layouts.append(detail)
    for layout in layouts:
        layout['boundaries'] = [float(np.interp(start + .5, layout['source'], layout['display']))
                                 for start, _end, _label in _label_spans(primary_labels if layout['name'] == 'Group'
                                     else list(zip(data.get('Group label', [''] * count), data['Wafer key'])), limit=None)[1:]]
    if axis_mode == 'die':
        layouts = [report_sequence_layout(data['Die Seq'].tolist(), name='Die')]
        layouts[0]['ticks'] = []
        layouts[0]['mode'] = 'die'
    elif axis_mode == 'group':
        layouts = [layouts[0]]
        layouts[0]['mode'] = 'group'
    elif axis_mode == 'wafer':
        layouts = [layouts[0]]
        layouts[0]['mode'] = 'wafer'
    if panel_widths is not None:
        for layout in layouts:
            layout['native_width'] = max(layout['native_width'], panel_widths[0])
            layout['width'] = max(layout['width'], panel_widths[1])
    if axis_mode in ('group', 'wafer'):
        captions = parameter_footer(worksheet, first_row, data, columns, axis_mode)
        layout = sequence_export_layout(data, mode=axis_mode, captions=captions)
        layout['mode'] = axis_mode
        layouts = [layout]
    if data.attrs.get("mark2"):
        from .mark2_export import layout as mark2_layout
        axis_mode = "mark2"
        fields = data.attrs["mark2"]["columns"]
        values = data[[f"Mark2 · {name}" for name in fields]].values.tolist()
        footer = parameter_footer(worksheet, first_row, data, columns, axis_mode)
        layouts = [mark2_layout(fields, values, footer)]
    panel_rows = max(
        1, len(layouts) * (2 + int(bool(show_percent))))
    category_columns = [(columns["Group"], data["Group label"].tolist())] if "Group" in columns and not wafer_only else None
    detailed_columns = ([(columns["Group"], data["Group label"].tolist())] if "Group" in columns and not wafer_only else []) + [
        (columns["Wafer"], data["Wafer"].tolist()), (columns["Die Seq"], data["Die Seq"].tolist())]
    for layout in layouts:
        if axis_mode in ('group', 'wafer', 'mark2') and count:
            layout['native_die_axis'] = native and axis_mode != 'mark2' and _native_die_axis_eligible(data, layout, axis_mode)
            # Keep source/helper cells identical across native and Matplotlib
            # reports, even if the native chart no longer needs numeric X.
            categories = _native_identity_categories(helper, helper_row, layout)
            if native and not layout['native_die_axis']:
                layout['categories'] = categories
    if native:
        for index, layout in enumerate(layouts):
            categories = (
                category_columns if index == 0 and category_columns
                else detailed_columns)
            if axis_mode == 'group' and category_columns:
                categories = category_columns + [
                    (columns['Die Seq'], data['Die Seq'].tolist())]
            if axis_mode == 'die' or layout.get('native_die_axis'):
                layout['categories'] = AxDataSource(strRef=StrRef(
                    f=str(Reference(
                        worksheet, min_col=columns['Die Seq'],
                        min_row=first_row, max_row=last_row)),
                    strCache=StrData(
                        ptCount=count,
                        pt=[StrVal(idx=i, v=str(value))
                            for i, value in enumerate(data['Die Seq'])])))
            elif axis_mode not in ('group', 'wafer', 'mark2'):
                layout["categories"] = native_categories(
                    worksheet, first_row, last_row, categories)
    if count and native:
        chart_left = _column_left_cm(
            worksheet, chart_column if chart_column is not None else len(headers) + 2)
        chart_top = (
            _row_top_cm(worksheet, chart_row if chart_row is None else chart_row)
            + chart_index * panel_rows * (
                PANEL_HEIGHT_CM + CHART_VERTICAL_GAP_CM)
            if chart_top_cm is None else chart_top_cm)
        _add_charts(worksheet, row if chart_row is None else chart_row, first_row, last_row, parameter, fit, show_percent=show_percent,
                    raw=raw, reference=reference, evaluated=evaluated_values, equation=equation,
                    reference_label=reference_label, unit="" if mapping is None else _unit(mapping.reference_column),
                    columns=columns, helper=helper, helper_row=helper_row, final=final,
                    layouts=layouts, anchor_column=chart_column,
                    chart_left_cm=chart_left, chart_top_cm=chart_top,
                    page_label="",
                    bias_limit=None if mapping is None or mapping.bias_limit is None
                    else float(mapping.bias_limit),
                    show_bias_limit=bool(mapping is not None and mapping.show_bias_limit))
    elif count:
        from .export_rendering import embed_parameter
        anchor = chart_column if chart_column is not None else len(headers) + 2
        chart_left = _column_left_cm(worksheet, anchor)
        chart_top = (
            _row_top_cm(worksheet, chart_row if chart_row is None else chart_row)
            + chart_index * panel_rows * (
                PANEL_HEIGHT_CM + CHART_VERTICAL_GAP_CM)
            if chart_top_cm is None else chart_top_cm)
        panels = [("Match", None)] + [(panel, layout) for layout in layouts
            for panel in ("Trend", "Bias", *(("Bias %",) if show_percent else ()))]
        right_row = 0
        for panel, layout in panels:
            if panel == 'Match':
                position = (chart_left, chart_top)
            else:
                position = (
                    chart_left + MATCH_WIDTH_CM
                    + CHART_HORIZONTAL_GAP_CM,
                    chart_top + right_row * (
                        PANEL_HEIGHT_CM + CHART_VERTICAL_GAP_CM))
                right_row += 1
            embed_parameter(worksheet, f"{get_column_letter(anchor)}{row if chart_row is None else chart_row}",
                f"{parameter} {panel} {layout['name'] if layout else ''} {scope} {stage}{stage_suffix(stage)}",
                images, parameter, data, card, stage, scope, panel=panel, reference_label=reference_label,
                unit="" if mapping is None else _unit(mapping.reference_column), sequence=layout,
                page_label="",
                bias_limit=None if mapping is None or mapping.bias_limit is None
                else float(mapping.bias_limit),
                show_bias_limit=bool(mapping is not None and mapping.show_bias_limit),
                position_cm=position)
    return 1


def _add_charts(worksheet, row, first_row, last_row, parameter, fit, *, show_percent=False,
                raw, reference, evaluated, equation, reference_label, unit, columns, helper, helper_row,
                final, layouts, anchor_column=None, chart_left_cm=None, chart_top_cm=None,
                bias_limit=None, show_bias_limit=False, page_label=""):
    anchor = len(columns) + 2 if anchor_column is None else anchor_column
    left_cm = (_column_left_cm(worksheet, anchor)
               if chart_left_cm is None else chart_left_cm)
    top_cm = _row_top_cm(worksheet, row) if chart_top_cm is None else chart_top_cm

    right_left_cm = (
        left_cm + MATCH_WIDTH_CM + CHART_HORIZONTAL_GAP_CM)
    right_row = 0

    def add(chart, left, top):
        chart.visible_cells_only = False  # Keep every charted range visible for Excel's source outlines.
        worksheet.add_chart(chart, f"{get_column_letter(anchor)}{row}")
        worksheet._charts[-1]._export_position_cm = (left, top)
    match = ScatterChart()
    match.scatterStyle = 'marker'
    match.title = f"{parameter} ({page_label})" if page_label else parameter
    match.x_axis.title = "PMISH"
    match.y_axis.title = reference_label
    match.height, match.width = PANEL_HEIGHT_CM, MATCH_WIDTH_CM
    match.legend = None
    match.x_axis.delete = False
    match.y_axis.delete = False
    points = Series(Reference(worksheet, min_col=columns[reference_label], min_row=first_row, max_row=last_row),
                    Reference(worksheet, min_col=columns["PMISH"], min_row=first_row, max_row=last_row),
                    title=reference_label)
    points.marker = Marker(symbol="circle", size=5)
    points.tx = SeriesLabel(strRef=StrRef(f=f"{quote_sheetname(worksheet.title)}!{get_column_letter(columns[reference_label])}{first_row - 1}"))
    points.graphicalProperties.line.noFill = True
    style_native_series(points, 0, color="4F8BD6", marker_size=5)
    match.series.append(points)
    if fit and np.count_nonzero(np.isfinite(raw) & np.isfinite(reference)) >= 2:
        from openpyxl.chart.layout import Layout, ManualLayout
        label_width = _equation_width(equation, match.width)
        points.trendline = Trendline(trendlineType='linear', dispEq=True, dispRSqr=True,
            spPr=GraphicalProperties(ln=LineProperties(solidFill='E09F3E', w=22860, prstDash='solid')),
            trendlineLbl=TrendlineLabel(layout=Layout(manualLayout=ManualLayout(
                xMode='edge', yMode='edge', x=.5 - label_width / 2, y=.08, w=label_width, h=.12))))
        match.layout = Layout(manualLayout=ManualLayout(
            layoutTarget='inner', xMode='edge', yMode='edge', x=.13, y=.24, w=.81, h=.60))
    add(match, left_cm, top_cm)
    valid = np.isfinite(raw) & np.isfinite(reference)
    chart_limits(match, reference[valid], raw[valid])

    percentages = np.full(len(reference), np.nan)
    np.divide((evaluated - reference) * 100, reference, out=percentages,
              where=np.isfinite(reference) & (reference != 0))
    for layout in layouts:
        panels = [("Trend", ("PMISH" if final else "PMISH+Card", reference_label), np.concatenate((evaluated, reference)), 3),
                  ("Bias", ("Bias",), evaluated - reference, 4)]
        if show_percent:
            panels.append(("Bias %", ("Bias %",), percentages, 5))
        for panel, names, values, _baseline_column in panels:
            panel_top = top_cm + right_row * (
                PANEL_HEIGHT_CM + CHART_VERTICAL_GAP_CM)
            # Categories expose the local Die Seq range when positions and
            # boundaries are affine. Other layouts retain the numeric X scale.
            numeric_identity = getattr(
                layout.get("categories"), "numRef", None) is not None
            identity_overlay = layout.get('mode') in ('group', 'wafer', 'mark2')
            chart = ScatterChart() if numeric_identity else LineChart()
            if numeric_identity:
                chart.scatterStyle = "lineMarker"
            elif layout.get('native_die_axis'):
                chart.y_axis.crossBetween = 'between'
            chart._identity_count = last_row - first_row + 1
            chart.title = (
                f"{parameter} ({page_label})"
                if panel == "Trend" and page_label
                else f"{panel} ({page_label})" if page_label else
                parameter if panel == "Trend" else panel)
            chart.y_axis.title = parameter if panel == "Trend" else f"Bias ({unit})" if panel == "Bias" and unit and unit != "1" else panel
            chart.height, chart.width = PANEL_HEIGHT_CM, layout["native_width"]
            chart._identity_captions = layout.get(
                'captions', layout.get('native_captions'))
            if numeric_identity:
                chart._numeric_identity_axis = True
                chart.x_axis.scaling.min, chart.x_axis.scaling.max = (
                    layout["limits"])
            if identity_overlay:
                # Preserve existing sparse ticks/title and footer pixel layout
                # even when the editable native X source becomes categorical.
                chart._identity_axis_overlay = True
                tick_indices = layout.get(
                    "tick_indices", range(len(layout.get("ticks", ()))))
                die_column = get_column_letter(columns['Die Seq'])
                chart._identity_axis_ticks = [
                    (
                        float(position),
                        str(label),
                        f"{quote_sheetname(worksheet.title)}!"
                        f"${die_column}${first_row + source_index}",
                    )
                    for (position, label), source_index
                    in zip(layout.get("ticks", ()), tick_indices)
                ]
                chart._identity_axis_range = layout["limits"]
            chart.x_axis.title = None
            if isinstance(chart, LineChart):
                chart.x_axis.tickLblSkip = max(
                    1, int(np.ceil(len(raw) / 18)))
            if (not identity_overlay and not numeric_identity
                    and (layout.get('mode') == 'die'
                         or layout.get('captions'))):
                chart.x_axis.title = 'Die Seq'
                if isinstance(chart, LineChart):
                    chart.x_axis.tickLblSkip = max(
                        1, int(np.ceil(len(raw) / 18)))
            if panel != "Trend":
                chart.legend = None
            for name in names:
                yvalues = Reference(
                    worksheet, min_col=columns[name],
                    min_row=first_row - 1, max_row=last_row)
                if numeric_identity:
                    xvalues = Reference(
                        range_string=layout["categories"].numRef.f)
                    chart.series.append(Series(
                        yvalues, xvalues, title_from_data=True))
                    chart.series[-1].xVal = layout["categories"]
                else:
                    chart.add_data(yvalues, titles_from_data=True)
                    chart.series[-1].cat = layout["categories"]
                if name == 'PMISH+Card':
                    chart.series[-1].tx = SeriesLabel(v='PMISH')
                if name == reference_label:
                    style_native_series(
                        chart.series[-1], 1, color="ED7D31",
                        marker_size=TREND_MARKER_SIZE,
                        line_width=int(TREND_LINE_WIDTH * 12700))
                else:
                    style_native_series(
                        chart.series[-1], len(chart.series) - 1,
                        marker_size=TREND_MARKER_SIZE,
                        line_width=int(TREND_LINE_WIDTH * 12700))
            if panel == "Bias" and show_bias_limit and bias_limit is not None:
                count = last_row - first_row + 1
                for label, value in (("Bias limit +", bias_limit), ("Bias limit -", -bias_limit)):
                    limit_series = SeriesObject()
                    limit_series.tx = SeriesLabel(v=label)
                    limit_series.val = NumDataSource(numLit=NumData(
                        formatCode="General", ptCount=count,
                        pt=[NumVal(idx=index, v=value) for index in range(count)]))
                    if numeric_identity:
                        numeric_limit = XYSeries()
                        numeric_limit.tx = limit_series.tx
                        numeric_limit.yVal = limit_series.val
                        numeric_limit.xVal = layout["categories"]
                        limit_series = numeric_limit
                    else:
                        limit_series.cat = layout["categories"]
                    limit_series.marker = Marker(symbol=None)
                    limit_series.graphicalProperties.line = LineProperties(
                        solidFill="DC2626", w=19050, prstDash="dash")
                    chart.series.append(limit_series)
            chart_limits(chart, values, symmetric=panel != "Trend")
            add(chart, right_left_cm, panel_top)
            right_row += 1


def _unit(reference_column):
    from .trend import parse_unit
    return parse_unit(reference_column)


def _parameter_data(result, parameter, key="all", labels=None, *, order="group"):
    from .match_groups import normalized, wafer_identity_keys
    labels = labels or {"pad": True, "lot": True}
    data = result.group_series(parameter, key, trend=True, card_mode="group" if key != "all" else "raw")
    raw = result.group_plan.raw
    identities = wafer_identity_keys(raw)
    die_column = next((column for column in raw if normalized(column) in ("dieseq", "dieid", "diesequence")), None)
    captions, dies, wafer_captions = [], [], []
    die_values = raw[die_column].tolist() if die_column is not None else None
    for row, group in zip(data["Source row"], data["Group"]):
        wafer, lot, pad = identities[row] if identities is not None else (f"Row {row + 1}", "", "")
        text = [wafer]
        if lot and labels.get("lot"):
            text.append(f"LOT: {lot}")
        if pad and labels.get("pad"):
            text.append(f"PAD: {pad}")
        wafer_captions.append("\n".join(text))
        if result.group_plan.enabled:
            group_label = result.group_plan.label(group)
            text = ([group_label, *text] if group in result.group_plan.state.get("show_wafer_groups", ()) else [group_label])
        captions.append("\n".join(text))
        dies.append(str(die_values[row]) if die_values is not None else "")
    data["Label"], data["Die Seq"] = captions, dies
    data["Wafer"] = wafer_captions
    data["Wafer key"] = [identities[row] if identities is not None else (f"Row {row + 1}", "", "")
                         for row in data["Source row"]]
    if result.group_plan.enabled:
        data["Group label"] = data["Group"].map(result.group_plan.label)
        data['Group caption'] = data['Group'].map(lambda group: result.group_plan.label(group, multiline=True))
        visible = result.group_plan.state.get('show_wafer_groups', ())
        data['Show wafer'] = [group in visible or key in visible for group in data['Group']]
    if result.group_plan.mark2_enabled:
        fields = result.group_plan.state["mark2"]["selected"]
        for i, field in enumerate(fields):
            data[f"Mark2 · {field}"] = [result.group_plan.mark2_labels[row][i] for row in data["Source row"]]
        data.attrs["mark2"] = {"columns": fields}
    elif order == "wafer":
        # First appearance in the Original source, independent of Group order
        # or the UI's selected trend order. Keep original rows within a Wafer.
        wafer_ranks = {}
        for identity in identities if identities is not None else data["Wafer key"]:
            wafer_ranks.setdefault(identity, len(wafer_ranks))
        ranks = [(wafer_ranks[identity], int(row)) for identity, row in zip(data["Wafer key"], data["Source row"])]
        data = data.iloc[sorted(range(len(data)), key=ranks.__getitem__)].copy()
    elif order == 'original':
        data = data.sort_values('Source row', kind='stable').copy()
    elif result.group_plan.enabled:
        # Only the grouped export projection is collected. Source row IDs stay
        # attached to every observation and Original retains the untouched order.
        group_ranks = {key: index for index, key in enumerate(result.group_plan.group_keys)}
        measurement_ranks = {}
        ranks = []
        for group, identity in zip(data["Group"], data["Wafer key"]):
            group_ranks.setdefault(group, len(group_ranks))
            key = group, identity
            measurement_ranks.setdefault(key, len(measurement_ranks))
            ranks.append((group_ranks[group], measurement_ranks[key]))
        data = data.iloc[sorted(range(len(data)), key=ranks.__getitem__)].copy()
    return data


def write_parameter_sheets(book, used_titles, result, workbook, *, native=True, images=None, plot_labels=None, raw=None):
    """Original measurements and plots together, plus Wafer and Group views."""
    stage = result.result_mode.title()
    suffix = stage_suffix(stage)
    original = book.create_sheet(sheet_title("Match Original", used_titles, suffix))
    _fill_title(original)
    original_raw = (raw if raw is not None else result.group_plan.raw).reset_index(drop=True)
    # Keep literal Raw Data intact. Reference inputs live in the visible
    # parameter tables themselves, not a second duplicate source area.
    grouped_data = {parameter: _parameter_data(result, parameter, labels=plot_labels)
                    for parameter in result.parameter_names} if result.group_plan.enabled else {}
    shared_widths = {}
    for parameter, data in grouped_data.items():
        layout = sequence_layout(data['Group label'], name='Group')
        shared_widths[parameter] = (layout['width'], layout['width'])
    block_width = (7 if result.result_mode == 'preview' else 6) + int(result.group_plan.enabled)
    if result.group_plan.mark2_enabled:
        block_width += len(result.group_plan.state["mark2"]["selected"])
    # Horizontal parameter tables, then source measurements to their right.
    # Keep one literal source table to the right of the prepared parameter tables.
    trend_width = max((widths[0] for widths in shared_widths.values()), default=TREND_WIDTH_CM)
    chart_pixels = (
        MATCH_WIDTH_CM + CHART_HORIZONTAL_GAP_CM + trend_width
    ) * 96 / 2.54
    source_column = max(len(result.parameter_names) * (block_width + 1) + 1,
                        _next_plot_column(original, 1, chart_pixels + 120))
    original._source_start_column = source_column
    _write_frame(original, original_raw, start_column=source_column)
    sheet = original
    row = 1
    # Charts intentionally overlay the editable tables, opening at row five.
    chart_start = 5
    original.freeze_panes = 'A3'
    for index, parameter in enumerate(result.parameter_names):
        mapping = next((item for item in workbook.mappings if item.name == parameter), None)
        _write_parameter_block(
            sheet, row, parameter, mapping, _parameter_data(result, parameter, labels=plot_labels, order='original'),
            result.card(parameter), "Overall", "All", stage, native=native, images=images,
            show_percent="percent" in workbook.bias_views, reference_label=workbook.match_type, original=original,
            axis_mode='die', panel_widths=shared_widths.get(parameter),
            start_column=1 + index * (block_width + 1),
            chart_row=chart_start, chart_index=index,
            chart_column=1)
    if result.group_plan.enabled:
        group_views = [(
            'Match Group',
            'Group',
            {
                parameter: data.assign(**{'Show wafer': False})
                for parameter, data in grouped_data.items()
            },
        )]
        if any(data['Show wafer'].any() for data in grouped_data.values()):
            group_views.append(
                ('Match Group show Wafer', 'Group show Wafer', grouped_data))
        for title, view_scope, view_data in group_views:
            grouped = book.create_sheet(
                group_show_wafer_sheet_title(used_titles, suffix)
                if title == 'Match Group show Wafer'
                else sheet_title(title, used_titles, suffix))
            _fill_title(grouped)
            group_row = 1
            chart_start = 5
            grouped.freeze_panes = 'A3'
            for index, parameter in enumerate(result.parameter_names):
                mapping = next(
                    (item for item in workbook.mappings
                     if item.name == parameter), None)
                _write_parameter_block(
                    grouped, group_row, parameter, mapping,
                    view_data[parameter], result.card(parameter),
                    'Overall', view_scope, stage, native=native, images=images,
                    show_percent='percent' in workbook.bias_views,
                    reference_label=workbook.match_type,
                    original=original, axis_mode='group',
                    start_column=1 + index * (block_width + 1),
                    chart_row=chart_start, chart_index=index,
                    chart_column=1)
    wafer = book.create_sheet(sheet_title("Match Wafer", used_titles, suffix))
    _fill_title(wafer)
    row = 1
    wafer_data = {p: _parameter_data(result, p, labels=plot_labels, order='wafer') for p in result.parameter_names}
    chart_start = 5
    chart_top_cm = None
    wafer_panel_rows = 2 + int('percent' in workbook.bias_views)
    wafer.freeze_panes = 'A3'
    for index, parameter in enumerate(result.parameter_names):
        mapping = next((item for item in workbook.mappings if item.name == parameter), None)
        page_count = _write_parameter_block(
            wafer, row, parameter, mapping, wafer_data[parameter],
            result.card(parameter), "Overall", "Wafer", stage, native=native, images=images,
            show_percent="percent" in workbook.bias_views, reference_label=workbook.match_type,
            original=original, wafer_only=True, axis_mode='wafer',
            start_column=1 + index * (block_width + 1),
            chart_row=chart_start, chart_index=index,
            chart_top_cm=chart_top_cm,
            chart_column=1)
        if chart_top_cm is None:
            chart_top_cm = _row_top_cm(wafer, chart_start)
        chart_top_cm += page_count * wafer_panel_rows * (
            PANEL_HEIGHT_CM + CHART_VERTICAL_GAP_CM)
    plan = result.group_plan
    if not plan.enabled:
        return sheet
    for key in plan.group_keys:
        label = plan.label(key)
        sheet = book.create_sheet(sheet_title(f"Match {label}", used_titles, suffix))
        _fill_title(sheet)
        row = 1
        # A single-Group report is the canonical Wafer view for that Group.
        # Its detail always includes every Wafer; the Show wafer setting only
        # chooses which of these detail segments appear in the combined
        # Match Group show Wafer report.
        group_data = {
            parameter: _parameter_data(
                result, parameter, key, plot_labels
            ).assign(**{'Show wafer': True})
            for parameter in result.parameter_names
        }
        chart_start = 5
        sheet.freeze_panes = 'A3'
        for index, parameter in enumerate(result.parameter_names):
            mapping = next((item for item in workbook.mappings if item.name == parameter), None)
            card = result.group_card(parameter, key)
            _write_parameter_block(
                sheet, row, parameter, mapping,
                group_data[parameter],
                card if card is not None else result.card(parameter),
                "Group" if card is not None else "Overall", label, stage,
                native=native, images=images, show_percent="percent" in workbook.bias_views,
                reference_label=workbook.match_type, original=original, axis_mode='group',
                start_column=1 + index * (block_width + 1),
                chart_row=chart_start, chart_index=index,
                chart_column=1)
    return sheet


def _wafer_label(text):
    return " / ".join(str(text).splitlines())


def write_rsq_sheet(book, used_titles, result, *, native=True, images=None):
    """One row per Wafer, one R² column per parameter, plus a chart per parameter."""
    summaries = {}
    for parameter in result.parameter_names:
        try:
            summary = result.wafer_summary(parameter)
        except ValueError:
            summary = pd.DataFrame()
        if len(summary):
            summaries[parameter] = summary
    if not summaries:
        return None
    order, groups = [], {}
    for parameter, summary in summaries.items():
        for wafer, group in zip(summary["Wafer"], summary["Group"]):
            label = _wafer_label(wafer)
            if label not in groups:
                order.append(label)
                groups[label] = group
    sheet = book.create_sheet(sheet_title("RSQ", used_titles, stage_suffix(result.result_mode)))
    _fill_title(sheet)
    sheet.cell(row=1, column=1, value="Row")
    sheet.cell(row=1, column=2, value="Wafer")
    sheet.cell(row=1, column=3, value="Group")
    for index, parameter in enumerate(summaries, start=4):
        cell = sheet.cell(row=1, column=index, value=f"{parameter} R²")
        cell.font = Font(bold=True)
    row_of = {}
    for offset, label in enumerate(order, start=2):
        row_of[label] = offset
        sheet.cell(row=offset, column=1, value=offset - 1)
        sheet.cell(row=offset, column=2, value=label)
        sheet.cell(row=offset, column=3, value=groups[label])
    for index, (parameter, summary) in enumerate(summaries.items(), start=4):
        for wafer, r_squared in zip(summary["Wafer"], summary["R²"]):
            row = row_of[_wafer_label(wafer)]
            sheet.cell(row=row, column=index, value=_value(r_squared))
    last = max(row_of.values()) if row_of else 1
    anchor_row = 5
    anchor_column = 'A'
    for index, parameter in enumerate(summaries, start=4) if native else ():
        chart = LineChart()
        chart.title = f"{parameter} R² by Wafer"
        chart.y_axis.title = "R²"
        chart.x_axis.title = 'Row'
        chart.height, chart.width = 8.0, 16.0
        chart.add_data(Reference(sheet, min_col=index, min_row=1, max_row=last),
                       titles_from_data=True)
        chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=last))
        chart_limits(chart, [sheet.cell(row=row, column=index).value for row in range(2, last + 1)])
        sheet.add_chart(chart, f"{anchor_column}{anchor_row + (index - 4) * 25}")
    if not native:
        from .analysis_export import _series, plot_figure
        for index, (parameter, summary) in enumerate(summaries.items()):
            plot = {"title": f"{parameter} R² by Wafer", "x": "Row", "y": "R²",
                    "series": [_series(parameter, np.arange(1, len(summary) + 1), summary["R²"].to_numpy(float))],
                    "labels": [str(index + 1) for index in range(len(summary))]}
            from .export_rendering import embed_plot
            embed_plot(sheet, plot, f"{anchor_column}{anchor_row + index * 25}",
                          plot["title"] + stage_suffix(result.result_mode), images)
    return sheet


def write_all_trend_sheet(book, used_titles, result, workbook, *, native=True, images=None):
    """Per parameter: each Group keeps its own ordinals, PMISH, REF and Bias."""
    plan = result.group_plan
    if not plan.enabled:
        return None
    sheet = book.create_sheet(sheet_title("All Trend", used_titles, stage_suffix(result.result_mode)))
    original = book["Match Original" + stage_suffix(result.result_mode)]
    _fill_title(sheet)
    row = 1
    for parameter in result.parameter_names:
        _checkpoint(book, f'{result.result_mode.title()}: All Trend — {parameter}')
        series = []
        mapping = next(item for item in workbook.mappings if item.name == parameter)
        source_column = next(cell.column_letter for cell in original[1] if cell.value == mapping.raw_column)
        for key in plan.group_keys:
            card = result.group_card(parameter, key)
            series.append((plan.label(key), key,
                           _parameter_data(result, parameter, key),
                           card if card is not None else result.card(parameter)))
        data_base = 2
        info_base = data_base + 4 * len(series) + 1
        sheet.cell(row=row, column=1, value="Parameter").font = Font(bold=True)
        sheet.cell(row=row, column=2, value=parameter)
        for slot, (label, _key, _data, card) in enumerate(series):
            column = info_base + slot * 2
            sheet.cell(row=row, column=column, value=f"{label} slope").font = Font(bold=True)
            sheet.cell(row=row, column=column + 1,
                       value=None if card is None or not np.isfinite(card.slope)
                       else float(card.slope))
            sheet.cell(row=row + 1, column=column,
                       value=f"{label} intercept").font = Font(bold=True)
            sheet.cell(row=row + 1, column=column + 1,
                       value=None if card is None or not np.isfinite(card.intercept)
                       else float(card.intercept))
        header_row = row + 2
        first_row = header_row + 1
        sheet.cell(row=header_row, column=1, value="Row").font = Font(bold=True)
        for slot, (label, _key, _data, _card) in enumerate(series):
            base = data_base + slot * 4
            for offset, name in enumerate(("Raw value", "PMISH", "REF", "Bias")):
                cell = sheet.cell(row=header_row, column=base + offset,
                                  value=f"{label} {name}")
                cell.font = Font(bold=True)
        depth = max((len(data) for _label, _key, data, _card in series), default=0)
        for index in range(depth):
            if index % 256 == 0:
                _checkpoint(book)
            target = first_row + index
            sheet.cell(row=target, column=1, value=index + 1)
            for slot, (label, _key, data, _card) in enumerate(series):
                if index >= len(data):
                    continue
                base = data_base + slot * 4
                slope_cell = f"${get_column_letter(info_base + slot * 2 + 1)}${row}"
                intercept_cell = f"${get_column_letter(info_base + slot * 2 + 1)}${row + 1}"
                source_row = data["Source row"].iloc[index]
                sheet.cell(row=target, column=base, value=_original_value(original, source_column, source_row))
                raw_cell = f"{get_column_letter(base)}{target}"
                evaluated = (raw_cell if result.result_mode == "final" else
                             f"{slope_cell}*{raw_cell}+{intercept_cell}")
                sheet.cell(row=target, column=base + 1, value=f'=IF(ISNUMBER({raw_cell}),{evaluated},NA())')
                reference_cell = original._reference_cells[parameter, int(source_row)]
                reference_source = f'{quote_sheetname(original.title)}!{reference_cell}'
                sheet.cell(row=target, column=base + 2,
                           value=f'=IF(ISNUMBER({reference_source}),{reference_source},NA())')
                pmish_cell, ref_cell = f"{get_column_letter(base + 1)}{target}", f"{get_column_letter(base + 2)}{target}"
                sheet.cell(row=target, column=base + 3,
                           value=f'=IF(AND(ISNUMBER({pmish_cell}),ISNUMBER({ref_cell})),{pmish_cell}-{ref_cell},NA())')
        last_row = first_row + depth - 1
        if depth and native:
            chart = LineChart()
            chart.title = parameter
            chart.y_axis.title = parameter
            chart.height, chart.width = PANEL_HEIGHT_CM, TREND_WIDTH_CM
            for slot, (label, _key, data, _card) in enumerate(series):
                if not len(data):
                    continue
                base = data_base + slot * 4
                for offset in (1, 2):
                    chart.add_data(
                        Reference(sheet, min_col=base + offset, min_row=header_row,
                                  max_row=first_row + len(data) - 1),
                        titles_from_data=True)
                    chart.series[-1].tx = SeriesLabel(v=f"{label} {'PMISH' if offset == 1 else workbook.match_type}")
                    style_native_series(
                        chart.series[-1], len(chart.series) - 1,
                        marker_size=TREND_MARKER_SIZE,
                        line_width=int(TREND_LINE_WIDTH * 12700))
            chart.series = chart.series[::2] + chart.series[1::2]
            chart_limits(chart, np.concatenate([
                array for _label, _key, data, card in series
                for array in ((data["Raw"].to_numpy(float) if result.result_mode == "final" else
                               card.slope * data["Raw"].to_numpy(float) + card.intercept), data["Reference"].to_numpy(float))]))
            chart.set_categories(
                Reference(sheet, min_col=1, min_row=first_row, max_row=last_row))
            sheet.add_chart(chart, f"{get_column_letter(info_base + len(series) * 2 + 2)}{row}")
        elif depth:
            from .analysis_export import _series, plot_figure
            curves = []
            for label, _key, data, card in series:
                raw = data["Raw"].to_numpy(float)
                evaluated = raw if result.result_mode == "final" else card.slope * raw + card.intercept
                curves.extend([_series(f"{label} PMISH", np.arange(1, len(data) + 1), evaluated),
                               _series(f"{label} {workbook.match_type}", np.arange(1, len(data) + 1), data["Reference"].to_numpy(float))])
                curves[-1]['reference'] = True
            plot = {"title": f"{parameter} Group trends", "x": "Row", "y": parameter, "series": curves}
            from .export_rendering import embed_plot
            embed_plot(sheet, plot, f"{get_column_letter(info_base + len(series) * 2 + 2)}{row}",
                          plot["title"] + stage_suffix(result.result_mode), images)
        row = first_row + max(depth, 18) + 22
    return sheet


def write_workbook(path, *, reference, stages, native=True, images=None, reports=(), extra_frames=(), plot_labels=None, fullmap_parameters=(), cancelled=lambda: False, progress=None, selected_sheets=None):
    """Write the workbook export: data sheets plus native-chart Match sheets."""
    book = Workbook()
    from .export_rendering import rendering_session
    with rendering_session(book, native=native):
        return _write_workbook(book, path, reference=reference, stages=stages, native=native,
            images=images, reports=reports, extra_frames=extra_frames, plot_labels=plot_labels,
            fullmap_parameters=fullmap_parameters, cancelled=cancelled, progress=progress, selected_sheets=selected_sheets)


def _write_workbook(book, path, *, reference, stages, native, images, reports, extra_frames, plot_labels, fullmap_parameters, cancelled, progress, selected_sheets):
    book._export_cancelled = cancelled
    book._export_progress = progress
    book.remove(book.active)
    used = set()

    def data_sheet(title, frame):
        sheet = book.create_sheet(sheet_title(title, used))
        _fill_title(sheet)
        _write_frame(sheet, frame)
        return sheet

    helper = book.create_sheet(sheet_title("_Plot data", used))
    helper.sheet_state = "hidden"
    _write_frame(helper, reference)  # Preserve original Reference names and measurement strings.
    for workbook, result, raw, stage_frames in stages:
        if cancelled():
            raise InterruptedError("Export cancelled")
        suffix = stage_suffix(workbook.result_mode)
        write_parameter_sheets(book, used, result, workbook, native=native, images=images, plot_labels=plot_labels, raw=raw)
        if workbook.workbook_type == "type2" or str(workbook.match_type).upper() in {"NOVA", "KLA"}:
            write_rsq_sheet(book, used, result, native=native, images=images)
        fullmap_report = next((report for _prefix, report in reports
            if report.get("scope") == f"map.{workbook.result_mode}"), None)
        frames = list(stage_frames)
        if fullmap_report and not any(name == "FullMap" for name, _frame in frames):
            frames.append(("FullMap", fullmap_report["frames"]["Data"]))
        for name, frame in frames:
            if name == "FullMap":
                sheet = book.create_sheet(sheet_title(name, used, suffix))
                _fill_title(sheet)
                write_fullmap(sheet, fullmap_report["frames"]["Data"] if fullmap_report else frame,
                              [mapping.name for mapping in workbook.mappings], native=native, images=images,
                              plot_labels=plot_labels, pictures=fullmap_report["pictures"] if fullmap_report else (),
                              include_trends=str(workbook.match_type).upper() == 'TEM',
                              picture_shapes=fullmap_report.get('picture_shapes', {}) if fullmap_report else {})
            else:
                data_sheet(sheet_title(name, set(), suffix), frame)
    for name, frame in extra_frames:
        if name.startswith("FullMap"):
            write_fullmap(book.create_sheet(sheet_title(name, used)), frame, fullmap_parameters,
                          native=native, images=images, plot_labels=plot_labels)
        else:
            data_sheet(name, frame)
    if reports:
        from .analysis_export import append_report
        for prefix, report in reports:
            if report.get("scope") in {f"map.{workbook.result_mode}" for workbook, _result, _raw, _frames in stages}:
                continue
            append_report(book, used, report, prefix=prefix, native=native, images=images)
    from .export_sheets import select_export_sheets
    from .export_rendering import flush_pictures
    flush_pictures(book)
    select_export_sheets(book, selected_sheets)
    style_workbook(book)
    _position_targeted_drawings(book)
    if selected_sheets is None:
        book.active = next((index for index, sheet in enumerate(book) if sheet.title.startswith("Match Original (")),
                           next(index for index, sheet in enumerate(book) if sheet.sheet_state == "visible"))
    return save_atomic(book, path, cancelled=cancelled)


def style_workbook(book):
    """Use the Excel theme for charts, with one explicit default typeface."""
    from copy import copy
    from openpyxl.drawing.colors import ColorChoice
    properties = CharacterProperties(latin=DrawingFont(typeface=EXPORT_FONT), sz=1400)
    def chart_text():
        tick_properties = CharacterProperties(latin=DrawingFont(typeface=EXPORT_FONT), sz=1100)
        return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=tick_properties), endParaRPr=tick_properties)])
    def hidden_chart_text():
        tick_properties = CharacterProperties(
            latin=DrawingFont(typeface=EXPORT_FONT), sz=100,
            solidFill=ColorChoice(srgbClr='FFFFFF'))
        return RichText(p=[Paragraph(
            pPr=ParagraphProperties(defRPr=tick_properties),
            endParaRPr=tick_properties)])
    # Font IDs are shared by every cell in this newly authored workbook.
    # Change their definitions once, retaining bold/size/colour. Iterating a
    # large worksheet also materializes all blank cells between plot blocks.
    for index, original in enumerate(book._fonts):
        font = copy(original)
        font.name = EXPORT_FONT
        font.scheme = None
        book._fonts[index] = font
    for sheet in book:
        for chart in [child for root in sheet._charts for child in root._charts]:
            count = _chart_point_count(chart)
            if isinstance(chart, LineChart):
                chart.marker = True
            chart.style = 2
            chart.varyColors = False
            if hasattr(chart, "smooth"):
                chart.smooth = False
            for series in chart.series:
                series.smooth = False
            for index, series in enumerate(chart.series):
                if (series.graphicalProperties.line.solidFill is None
                        and (series.marker is None or series.marker.graphicalProperties.solidFill is None)):
                    style_native_series(series, index)
                if getattr(chart, "type", None) in ("col", "bar"):
                    series.graphicalProperties.solidFill = PLOT_COLORS[index % len(PLOT_COLORS)]
            chart.x_axis.axPos = "b"
            chart.y_axis.axPos = "r" if chart.y_axis.axId == 200 else "l"
            chart.roundedCorners = False
            chart.plot_area.spPr = GraphicalProperties(
                ln=LineProperties(solidFill="595959", w=15240, prstDash="solid"))
            # set_categories() also emits numRef for ordinary Row/Die charts.
            # Only reports with explicit replacement drawings hide their axis.
            numeric_identity = bool(getattr(chart, "_numeric_identity_axis", False))
            identity_overlay = numeric_identity or bool(getattr(chart, '_identity_axis_overlay', False))
            chart.x_axis.delete = identity_overlay
            chart.y_axis.delete = False
            chart.x_axis.tickLblPos = (
                "none" if identity_overlay else "low")
            chart.y_axis.tickLblPos = "nextTo"
            if hasattr(chart.x_axis, "noMultiLvlLbl"):
                separate_captions = bool(getattr(
                    chart, '_identity_captions', None))
                chart.x_axis.noMultiLvlLbl = separate_captions
                if any(series.cat is not None and series.cat.multiLvlStrRef is not None for series in chart.series):
                    # Row-based skipping also skips whole outer Wafer/Group
                    # captions in Excel, even when there is room for them.
                    chart.x_axis.tickLblSkip = 1
                    count = getattr(chart, '_identity_count', 0)
                    if count > 18:
                        selected = set(np.linspace(0, count - 1, 18).round().astype(int))
                        for series in chart.series:
                            if series.cat is not None and series.cat.multiLvlStrRef is not None:
                                levels = series.cat.multiLvlStrRef.multiLvlStrCache.lvl
                                if len(levels) > 1:
                                    for point in levels[0].pt:
                                        if point.idx not in selected:
                                            point.v = ''
                chart.x_axis.tickLblSkip = chart.x_axis.tickLblSkip or max(1, int(np.ceil(count / 18)))
                chart.x_axis.tickMarkSkip = chart.x_axis.tickLblSkip
            if getattr(chart, '_identity_captions', None):
                from openpyxl.chart.layout import Layout, ManualLayout
                from .native_chart_labels import footer_geometry
                bottom, _rows = footer_geometry(chart._identity_captions)
                left_cm, right_cm = _match_chart_margins(chart.width)
                left = left_cm / chart.width
                right = right_cm / chart.width
                chart._identity_geometry = (left, 1 - left - right)
                chart.layout = Layout(manualLayout=ManualLayout(
                    layoutTarget='inner', xMode='edge', yMode='edge',
                    x=left, y=.15, w=1 - left - right,
                    h=bottom - .15))
            # Use Excel's own chart theme rather than copying Matplotlib's frame.
            chart.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(
                ln=LineProperties(solidFill="D9D9D9", w=9525)))
            chart.x_axis.majorGridlines = None
            chart.display_blanks = "gap"
            chart.txPr = chart_text()
            if chart.legend is not None:
                chart.legend.position = "t"
                chart.legend.overlay = False
                chart.legend.txPr = chart_text()
            if chart.title is not None:
                chart.title.overlay = False
            for series in chart.series:
                if series.trendline is not None and series.trendline.trendlineLbl is not None:
                    from openpyxl.chart.data_source import NumFmt
                    label = series.trendline.trendlineLbl
                    label.txPr = chart_text()
                    label.txPr.p[0].pPr.algn = 'ctr'
                    label.numFmt = NumFmt(formatCode='General', sourceLinked=False)
            for axis in (chart.x_axis, chart.y_axis):
                axis.majorTickMark = (
                    "none" if identity_overlay and axis is chart.x_axis
                    else "out")
                axis.minorTickMark = "none"
                if axis.crosses != "max":
                    axis.crosses = "min"
                axis.spPr = GraphicalProperties(
                    ln=LineProperties(solidFill="595959", w=15240, prstDash="solid"))
                axis.txPr = (
                    hidden_chart_text()
                    if identity_overlay and axis is chart.x_axis
                    else chart_text())
                axis.txPr.bodyPr.rot = 0
                axis.txPr.bodyPr.horzOverflow = "overflow"
                axis.txPr.bodyPr.vertOverflow = "overflow"
                # openpyxl's NoneSet converts the valid OOXML literal "none"
                # to Python None. Preserve it explicitly to prevent Excel
                # wrapping a Wafer caption into the width of one data point.
                axis.txPr.bodyPr.__dict__["wrap"] = "none"
                step = getattr(axis, "majorUnit", None)
                if step is not None:
                    decimals = max(0, int(-np.floor(np.log10(step))))
                    if not np.isclose(step / (10. ** -decimals), round(step / (10. ** -decimals))):
                        decimals += 1
                    minimum = axis.scaling.min
                    if minimum is not None and not np.isclose(minimum / step, round(minimum / step), rtol=0, atol=1e-8):
                        # Excel starts its ticks at the fixed minimum, not at
                        # a zero-based locator. Keep that offset in the labels.
                        decimals = max(2, decimals + 1)
                    axis.numFmt = "0.00E+00" if decimals > 4 else "0" + ("." + "0" * decimals if decimals else "")
                else:
                    axis.numFmt = "General"
                if axis.title is not None:
                    axis.title.overlay = False
                if axis.title and axis.title.tx and axis.title.tx.rich:
                    for paragraph in axis.title.tx.rich.p:
                        paragraph.pPr = ParagraphProperties(defRPr=properties)
            if chart.title and chart.title.tx and chart.title.tx.rich:
                rich = chart.title.tx.rich
                lines = "\n".join(run.t for paragraph in rich.p for run in paragraph.r).splitlines()
                if len(lines) > 1:
                    from openpyxl.drawing.text import RegularTextRun
                    rich.p = [Paragraph(r=[RegularTextRun(t=line)]) for line in lines]
                for index, paragraph in enumerate(rich.p):
                    title_properties = CharacterProperties(latin=DrawingFont(typeface=EXPORT_FONT),
                        sz=1400 if index == 0 else 1100, b=index == 0)
                    paragraph.pPr = ParagraphProperties(defRPr=title_properties, algn='ctr')
                    for run in paragraph.r:
                        run.rPr = title_properties


def _embed_figure(sheet, figure, anchor, title, images):
    _checkpoint(sheet.parent, f'Rendering {title}')
    from .appearance import export_dpi, MAX_EXPORT_PIXELS
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=export_dpi(figure, 150, MAX_EXPORT_PIXELS),
                   facecolor="white", metadata={"Title": title})
    buffer.seek(0)
    picture = Image(buffer)
    picture.width = figure.get_figwidth() * 96
    picture.height = picture.width * figure.get_figheight() / figure.get_figwidth()
    sheet.add_image(picture, anchor)
    if images is not None:
        images.append((title, buffer.getvalue()))
    # Pictures own their PNG bytes, not the Agg canvas. Release its potentially
    # very wide raster before rendering the next panel; no pyplot state exists.
    figure.clear()
    figure.set_canvas(None)
    _checkpoint(sheet.parent)


def picture_ratio(title, picture, shapes):
    """Whole-page PNG scaling, with an eight-centimetre Wafer Map row pitch."""
    if title.startswith(('Wafer Map', 'Radius')):
        visual_rows = [
            shape[0] for name, shape in shapes.items()
            if name.startswith(('Wafer Map', 'Radius'))
        ]
        rows = max(visual_rows, default=1)
        return max(1, rows) * WAFER_MAP_CELL_HEIGHT_CM * 96 / 2.54 / picture.height
    return min(FM_PICTURE_HEIGHT_CM * 96 / 2.54 / picture.height,
               FM_PICTURE_WIDTH_CM * 96 / 2.54 / picture.width)


def write_fullmap(sheet, frame, parameters, *, native=True, images=None, plot_labels=None, pictures=(), include_trends=True, picture_shapes=None):
    """FullMap's own measurements and mapped Trends; software Map/Radius PNGs."""
    from .analysis_export import _series, plot_figure
    from .measurements import wafer_identity_labels
    from .export_rendering import embed_plot, flush_pictures
    flush_pictures(sheet.parent)
    labels = plot_labels or {"pad": True, "lot": True}
    captions = wafer_identity_labels(frame, [[row] for row in range(len(frame))],
                                    show_pad=labels.get("pad", True), show_lot=labels.get("lot", True)) if len(frame) else []
    picture_shapes = picture_shapes or {}
    mapped = list(dict.fromkeys(parameter for parameter in parameters if parameter in frame))
    def picture_width(kind):
        widths = []
        for title, contents, _note in pictures:
            if title.startswith(kind):
                image = Image(BytesIO(contents))
                ratio = picture_ratio(title, image, picture_shapes)
                widths.append(image.width * ratio)
        return max(widths, default=0)
    map_width, radius_width = picture_width('Wafer Map'), picture_width('Radius')
    trend_column = plot_column = 1
    # Prepared report first, then one gutter, then the untouched source table.
    source_column = plot_column + len(mapped) + 3
    sheet._source_start_column = source_column
    _write_frame(sheet, frame, start_column=source_column)
    from .match_groups import normalized, wafer_identity_keys
    from openpyxl.styles import Alignment
    die = next((column for column in frame if normalized(column) in ("dieseq", "dieid", "diesequence")), None)
    dies = frame[die].astype(str).tolist() if die is not None else [""] * len(frame)
    for offset, header in enumerate(["Wafer", "Die Seq", *mapped]):
        sheet.cell(1, plot_column + offset, header).font = Font(name=EXPORT_FONT, bold=True)
        sheet.column_dimensions[get_column_letter(plot_column + offset)].width = 30 if offset == 0 else 16
    for index, (caption, die_label) in enumerate(zip(captions, dies), 2):
        sheet.cell(index, plot_column, caption).data_type = "s"
        sheet.cell(index, plot_column + 1, die_label).data_type = "s"
    keys = wafer_identity_keys(frame)
    for start, end, _key in _label_spans(keys if keys is not None else captions, limit=None):
        if start != end:
            sheet.merge_cells(start_row=start + 2, end_row=end + 2, start_column=plot_column, end_column=plot_column)
        sheet.cell(start + 2, plot_column).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    def software_pictures(kind, column):
        cursor, width = 5, 0
        for title, contents, _note in pictures:
            if not title.startswith(kind):
                continue
            picture = Image(BytesIO(contents))
            ratio = picture_ratio(title, picture, picture_shapes)
            picture.width, picture.height = picture.width * ratio, picture.height * ratio
            sheet.add_image(picture, f"{get_column_letter(column)}{cursor}")
            cursor += int(np.ceil(picture.height / 20)) + 3
            width = max(width, picture.width)
            if images is not None:
                images.append((sheet.title + " " + title, contents))
        return cursor
    # Place the visual strip after setting table column widths so its three
    # panels do not overlap each other; covering data beneath them is intended.
    captions_for_plot = identity_captions(sheet, 2, captions,
        keys if keys is not None else captions, plot_column, limit=4)
    layout = report_sequence_layout(dies, captions_for_plot)
    map_column = _next_plot_column(sheet, 1, layout['width'] * 96 / 2.54) if mapped and include_trends else 1
    radius_column = _next_plot_column(sheet, map_column, map_width) if map_width else map_column
    software_pictures("Wafer Map", map_column)
    anchor = get_column_letter(trend_column)
    # Trend, Wafer Map and Radius share the same row-five opening baseline.
    software_pictures("Radius", radius_column)
    cursor = 5
    if frame.empty:
        return
    categories = AxDataSource(strRef=StrRef(
        f=str(Reference(sheet, min_col=plot_column + 1, min_row=2, max_row=len(frame) + 1)),
        strCache=StrData(ptCount=len(dies), pt=[StrVal(idx=i, v=str(value)) for i, value in enumerate(dies)])))
    for slot, parameter in enumerate(mapped, plot_column + 2):
        values = pd.to_numeric(frame[parameter], errors="coerce").to_numpy(float)
        for index, value in enumerate(values):
            source = f"{get_column_letter(source_column + frame.columns.get_loc(parameter))}{index + 2}"
            sheet.cell(row=index + 2, column=slot,
                        value=f'=IFERROR(IF({source}="",NA(),{source}*1),NA())')
        if not include_trends:
            continue
        if native:
            chart = LineChart()
            chart._identity_count = len(frame)
            chart.title = chart.y_axis.title = parameter
            chart.x_axis.title = 'Die Seq'
            chart.width, chart.height = layout['width'], PANEL_HEIGHT_CM
            chart.x_axis.tickLblSkip = max(1, int(np.ceil(len(frame) / 18)))
            chart.visible_cells_only = False
            chart.add_data(Reference(sheet, min_col=slot, min_row=1, max_row=len(frame) + 1), titles_from_data=True)
            chart.series[0].cat = categories
            style_native_series(
                chart.series[0], 0, marker_size=TREND_MARKER_SIZE,
                line_width=int(TREND_LINE_WIDTH * 12700))
            chart._identity_captions = captions_for_plot
            chart_limits(chart, values)
            sheet.add_chart(chart, f"{anchor}{cursor}")
        else:
            plot = {"title": parameter, "x": "", "y": parameter,
                    "labels": captions, "dies": dies, "captions": captions_for_plot,
                    "series": [_series(parameter, np.arange(1, len(frame) + 1), values)]}
            embed_plot(sheet, plot, f"{anchor}{cursor}", sheet.title + " " + parameter, images)
        cursor += 30


def save_atomic(book, path, *, cancelled=lambda: False):
    """Publish only a complete xlsx; a failed export leaves an existing file intact."""
    target = Path(path)
    from .export_rendering import flush_pictures
    flush_pictures(book)
    _checkpoint(book, 'Saving XLSX file…')
    handle = tempfile.NamedTemporaryFile(dir=target.parent, suffix=".xlsx", prefix=".export-", delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        if cancelled():
            raise InterruptedError("Export cancelled")
        from .xlsx_serialization import save_workbook
        save_workbook(book, temporary, lambda message=None: _checkpoint(book, message))
        from .native_chart_labels import write_identity_drawings
        write_identity_drawings(book, temporary, lambda: _checkpoint(book))
        if cancelled():
            raise InterruptedError("Export cancelled")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def set_export_font(figure):
    from matplotlib.text import Text
    for text in figure.findobj(match=Text):
        text.set_fontfamily(EXPORT_FONT)


def parameter_figure(parameter, data, card, stage, scope, *, panel="Match", reference_label="REF", unit="",
                     sequence=None, bias_limit=None, show_bias_limit=False,
                     page_label=""):
    """Matplotlib report from the same software values used in the Excel areas."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    width = MATCH_WIDTH_CM if panel == "Match" else TREND_WIDTH_CM if sequence is None else sequence["width"]
    left_cm, right_cm = _match_chart_margins(width)
    figure = Figure(figsize=(width / 2.54, PANEL_HEIGHT_CM / 2.54), facecolor="white")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    raw, reference = data["Raw"].to_numpy(float), data["Reference"].to_numpy(float)
    values = (raw if stage.lower() == "final" else
              card.slope * raw + card.intercept if card is not None else np.full(len(raw), np.nan))
    valid = np.isfinite(raw) & np.isfinite(reference)
    if panel == "Match":
        title = f"{parameter} ({page_label})" if page_label else parameter
        style_plot_axis(axis, title=title, xlabel="PMISH", ylabel=reference_label)
        axis.scatter(raw[valid], reference[valid], s=25, color="#4F8BD6", edgecolors="none")
        if valid.any() and card is not None and np.isfinite(card.slope) and np.isfinite(card.intercept):
            ends = np.array([raw[valid].min(), raw[valid].max()])
            axis.plot(ends, card.slope * ends + card.intercept, color="#E09F3E", linewidth=1.8)
            axis.set_title(title, fontsize=16, fontweight='bold', pad=44)
            sign = '+' if card.intercept >= 0 else '-'
            axis.text(.5, 1.02, f"y = {card.slope:.6g}x {sign} {abs(card.intercept):.6g}\nR² = {card.r_squared:.6g}",
                transform=axis.transAxes, va="bottom", ha="center", fontsize=10, color="#334155")
        if valid.any():
            plot_axis_limits(axis, reference[valid], raw[valid])
        bottom = 1.5
    else:
        rows = np.arange(1, len(data) + 1) if sequence is None else sequence["x"]
        marker_size, line_width = TREND_MARKER_SIZE, TREND_LINE_WIDTH
        ylabel = parameter if panel == "Trend" else f"Bias ({unit})" if panel == "Bias" and unit and unit != "1" else panel
        title = f"{parameter} ({page_label})" if panel == "Trend" and page_label else (
            f"{panel} ({page_label})" if page_label else
            parameter if panel == "Trend" else panel)
        style_plot_axis(axis, title=title, xlabel="", ylabel=ylabel)
        if panel == "Trend":
            axis.plot(rows, values, marker="o", markersize=marker_size, color="#5B9BD5", linewidth=line_width, zorder=2,
                      label="PMISH")
            axis.plot(rows, reference, marker="o", markersize=marker_size, color="#ED7D31", linewidth=line_width,
                      linestyle="-", zorder=3, label=reference_label)
            plot_legend(axis)
            plot_axis_limits(axis, np.concatenate((values, reference)))
        else:
            bias = values - reference
            if panel == "Bias %":
                percent = np.full(len(reference), np.nan)
                np.divide(bias * 100, reference, out=percent, where=np.isfinite(reference) & (reference != 0))
                bias = percent
            axis.plot(rows, bias, marker="o", markersize=marker_size, color="#4F8BD6", linewidth=line_width)
            axis.axhline(0, color="#8A8F98", linewidth=.7, linestyle="--")
            limit = (None if panel != "Bias" or bias_limit is None or not show_bias_limit
                     else abs(float(bias_limit)))
            if limit is not None:
                for value in (-limit, limit):
                    axis.axhline(value, color="#DC2626", linewidth=1.8,
                                 linestyle="--", zorder=4)
            plot_axis_limits(axis, bias if limit is None else np.concatenate((bias, [-limit, limit])),
                             symmetric=True)
        selected = ([(float((start + end) / 2 + 1), label) for start, end, label in _label_spans(data["Label"])]
                    if sequence is None and "Label" in data else [] if sequence is None else sequence["ticks"])
        bottom = .8 + .45 * max((len(label.splitlines()) for _position, label in selected), default=1)
        if sequence is not None and 'Die Seq' in data:
            bottom += .9 + .45 * max((len(label.splitlines()) for _, label in sequence.get('group_ticks', ())), default=0)
            if 'captions' in sequence:
                bottom = footer_margin(sequence['captions'])
            if sequence.get('mode') == 'mark2':
                bottom = .5 + (55 + 25 * (len(sequence['mark2']['columns']) - 1)) * 2.54 / 96
        else:
            axis.set_xticks([position for position, _label in selected], [label for _position, label in selected], fontsize=10)
            axis.set_xlim(.5, max(1, len(data)) + .5)
    figure.subplots_adjust(
        left=left_cm / width,
        right=1 - right_cm / width,
        bottom=bottom / PANEL_HEIGHT_CM, top=.81)
    if panel != 'Match' and sequence is not None and 'Die Seq' in data:
        draw_sequence_axis(axis, sequence, data['Die Seq'].tolist(), boundary_gap=0.035)
    if axis.get_xlabel() == "Wafer":
        axis.set_xlabel("")
    set_export_font(figure)
    return figure

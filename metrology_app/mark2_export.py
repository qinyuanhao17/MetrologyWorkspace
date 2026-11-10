"""Mark2 sequence axes for Excel and image reports."""
import numpy as np

from .mark2 import hierarchy, text


def native_categories(sheet, first, column, fields, values, dies=None):
    """Write one shared label range, optionally ending in the source Die Seq."""
    from openpyxl.chart import Reference
    from openpyxl.chart.data_source import AxDataSource, Level, StrData, StrRef, StrVal
    from .xlsx_serialization import MultiLevelCategoryCache, MultiLevelCategoryRef

    rows = (tuple(map(text, row)) for row in values)
    if dies is not None:
        fields = [*fields, "Die Seq"]
        rows = ((*row, die) for row, die in zip(rows, dies, strict=True))
    levels = [[] for _ in fields]
    for offset, field in enumerate(fields):
        sheet.cell(first - 1, column + offset, field).data_type = "s"

    previous = None
    for index, row in enumerate(rows):
        changed = previous is None
        for level, value in enumerate(row):
            changed = changed or value != previous[level]
            if changed or level == len(fields) - 1:
                # A changed outer label starts a new span on all inner levels.
                # An empty cell extends the previous span. A space starts a
                # visually blank span when the source label itself is missing.
                label = value or " "
                sheet.cell(first + index, column + level, label).data_type = "s"
                levels[level].append(StrVal(idx=index, v=label))
        previous = row

    source = Reference(sheet, min_col=column, max_col=column + len(fields) - 1,
                       min_row=first, max_row=first + len(values) - 1)
    if len(fields) == 1:
        return AxDataSource(strRef=StrRef(f=str(source), strCache=StrData(ptCount=len(values), pt=levels[0])))
    cache = MultiLevelCategoryCache(ptCount=len(values), lvl=[Level(pt=points) for points in reversed(levels)])
    return AxDataSource(multiLvlStrRef=MultiLevelCategoryRef(f=str(source), multiLvlStrCache=cache))


def captions(columns, values, source, *, origin=1):
    count = len(values)
    return [{**span, "start": (span["start"] - origin + .5) / count,
             "end": (span["end"] - origin + .5) / count,
             "center": ((span["start"] + span["end"]) / 2 - origin + .5) / count,
             "source": source(span["row"], span["field"]), "role": "mark2"}
            for span in hierarchy(columns, values, origin=origin)] if count else []


def layout(columns, values, footer, *, width=25, origin=1):
    return {"name": "Mark2", "mode": "mark2", "x": np.arange(origin, origin + len(values), dtype=float),
            "limits": (origin - .5, max(origin, origin + len(values) - 1) + .5),
            "ticks": [], "width": width, "native_width": width, "captions": footer,
            "mark2": {"columns": columns, "values": values, "origin": origin}}


def attach_native(chart, footer, limits):
    chart._identity_captions = footer
    chart._identity_axis_overlay = True
    chart._numeric_identity_axis = True
    chart._identity_axis_range = limits
    chart._identity_axis_ticks = []
    chart.x_axis.title = None
    chart.x_axis.scaling.min, chart.x_axis.scaling.max = limits

"""Editable, cell-linked Mark2 chart footers on the shared ordinal domain."""
import numpy as np

from .mark2 import hierarchy


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

"""Prepare row-by-wafer arrays; keep numerical work independent of Qt."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import number
from .plot import PlotOptions, WaferPlot, infer_geometry, infer_wafer_geometry, prepare_surfaces


@dataclass
class ArrayOptions:
    x: str
    y: str
    diameter: float | None = None
    center_x: float = 0
    center_y: float = 0
    labels: bool = True
    points: bool = True
    fill_edge: bool = True
    shared_scale: bool = False
    cmap: str = "turbo"
    show_colorbar: bool = True
    contour: bool = False
    point_outline: bool = False
    smoothing: float = 0.0
    limits: tuple | None = None
    opacity: float = 1.0
    cmap_range: tuple | None = None


def prepare_array(frame, selection, options, progress=lambda *_: None, cancelled=lambda: False):
    wafers, metrics = selection["wafers"], selection["metrics"]
    if not wafers or not metrics:
        raise ValueError("Select at least one wafer and one parameter in the Data tab.")
    if len(wafers) * len(metrics) > 120:
        raise ValueError("Select up to 120 maps per array; split larger selections into batches.")
    selected = set(map(tuple, selection.get("cells", [(w, m) for w in wafers for m in metrics])))
    selected &= {(w, m) for w in wafers for m in metrics}
    if not selected:
        raise ValueError("Select at least one map box before drawing.")
    if options.x == options.y:
        raise ValueError("Choose different X and Y coordinate columns.")
    if options.diameter is not None and (not np.isfinite(options.diameter) or options.diameter <= 0):
        raise ValueError("Diameter must be a finite positive number, or Auto.")
    if "groups" in selection:
        parts = {key: frame.iloc[list(selection["groups"][key])] for key in wafers}
    else:
        ids = frame[selection["wafer_column"]].astype(str).str.strip()
        parts = {key: frame[ids == key] for key in wafers}
    rows = pd.concat([parts[key] for key in wafers if key in {w for w, _ in selected}])
    points = pd.DataFrame({"x": number(rows[options.x]), "y": number(rows[options.y])}).dropna().drop_duplicates()
    if points.empty:
        raise ValueError("No valid coordinates in the selected wafers.")
    geometry = (infer_geometry(points.to_numpy()) if options.diameter is None else
                (options.center_x, options.center_y, options.diameter / 2))
    per_wafer = {}
    if options.diameter is None:
        for wafer in wafers:
            if wafer not in {w for w, _ in selected}:
                continue
            part = parts[wafer]
            xy = pd.DataFrame({"x": number(part[options.x]), "y": number(part[options.y])}).dropna().drop_duplicates()
            per_wafer[wafer] = (infer_wafer_geometry(xy.to_numpy(), (options.x, options.y))
                                if not xy.empty else (geometry, None))
    scenes = []
    pending = []
    # Small arrays can afford a near screen-resolution grid, which keeps the
    # displayed surface crisp; large arrays fall back to the cheaper grid.
    grid_resolution = 400 if len(selected) <= 12 else 300 if len(selected) <= 48 else 200
    for wafer in wafers:
        part = parts[wafer]
        for metric in metrics:
            if cancelled():
                return None
            if (wafer, metric) not in selected:
                scenes.append({"wafer": wafer, "metric": metric, "skip": True, "error": ""})
                continue
            layer = pd.DataFrame({"x": number(part[options.x]), "y": number(part[options.y]),
                                  "value": number(part[metric])}).dropna(subset=["x", "y"])
            wafer_geometry, standard = per_wafer.get(wafer, (geometry, None))
            plot_options = PlotOptions(*wafer_geometry, labels=options.labels, points=options.points,
                                       fill_edge=options.fill_edge, resolution=grid_resolution,
                                       contour=options.contour, point_outline=options.point_outline,
                                       smoothing=options.smoothing, limits=options.limits,
                                       opacity=options.opacity, cmap_range=options.cmap_range,
                                       cmap=options.cmap, show_colorbar=options.show_colorbar)
            scene = {"wafer": wafer, "label": selection.get("labels", {}).get(wafer, wafer),
                     "metric": metric, "layer": layer, "options": plot_options, "error": "",
                     "standard_mm": standard, "size_note": f"≈{standard} mm" if standard else ""}
            try:
                if layer.duplicated(["x", "y"]).any():
                    raise ValueError("Duplicate coordinates in this measurement set.\nCheck the selected identity fields and input rows.")
                scene["layer"] = layer.dropna(subset=["value"]).reset_index(drop=True)
                pending.append(scene)
            except ValueError as error:
                scene["error"] = str(error)
            scenes.append(scene)
    batches = {}
    for scene in pending:
        coordinates = tuple(map(tuple, scene["layer"][["x", "y"]].to_numpy(float)))
        batches.setdefault((scene["wafer"], coordinates), []).append(scene)
    completed = sum(bool(scene["error"]) for scene in scenes)
    for batch in batches.values():
        if cancelled():
            return None
        try:
            values = np.column_stack([scene["layer"]["value"].to_numpy(float) for scene in batch])
            surfaces = prepare_surfaces(batch[0]["layer"][["x", "y"]].to_numpy(float),
                                        values, batch[0]["options"])
            for scene, surface in zip(batch, surfaces):
                scene["surface"] = surface
        except ValueError as error:
            for scene in batch:
                scene["error"] = str(error)
        completed += len(batch)
        progress(completed, len(selected))
    if options.shared_scale and not options.limits:
        for metric in metrics:
            valid = [s for s in scenes if s["metric"] == metric and not s["error"] and not s.get("skip")]
            if valid:
                bounds = min(s["layer"].value.min() for s in valid), max(s["layer"].value.max() for s in valid)
                for scene in valid:
                    scene["options"].limits = bounds
    standards = sorted({s[1] for s in per_wafer.values() if s[1]})
    if options.diameter is None:
        inches = {100: 4, 200: 8, 300: 12}
        sizes = " / ".join(f"{d} mm ({inches[d]} in)" for d in standards)
        if standards and len(standards) == len(per_wafer) or len(standards) == 1 and all(s[1] for s in per_wafer.values()):
            size_summary = f"Auto ≈{sizes}; estimated from XY"
        elif standards:
            size_summary = f"Auto ≈{sizes}; other maps: size unknown"
        else:
            size_summary = "Auto extent only; physical size unknown"
    else:
        size_summary = f"Manual diameter {options.diameter:g} coordinate units"
    return {"scenes": scenes, "shape": (len(wafers), len(metrics)), "settings": options,
            "geometry": geometry, "selected_count": len(selected), "size_summary": size_summary}


def drawn_axes(wafers, metrics, cells):
    """Keep only the array rows and columns that contain at least one drawn cell.

    The canvas is sized from this trimmed pair, so a 2 x 2 box selection inside a
    6 x 20 grid produces a 2 x 2 canvas instead of a mostly empty one. Rows and
    columns keep their original order, so boxes that are still drawn stay
    aligned with each other.
    """
    chosen = {(wafer, metric) for wafer, metric in cells}
    kept_wafers = [wafer for wafer in wafers
                   if any((wafer, metric) in chosen for metric in metrics)]
    kept_metrics = [metric for metric in metrics
                    if any((wafer, metric) in chosen for wafer in wafers)]
    return kept_wafers, kept_metrics


def draw_array(figure, result, font_size=10):
    """All Matplotlib mutations stay on the calling (GUI) thread."""
    figure.clear()
    rows, columns = result["shape"]
    settings = result["settings"]
    axes = figure.subplots(rows, columns, squeeze=False)
    # Fixed panel spacing avoids constrained-layout solving hundreds of text bounds
    # on every zoom, font change and window resize. The margins still have to grow
    # with the plot font, otherwise larger tick labels push the outer Y label off
    # the canvas and the whole array looks off-centre.
    base_width, base_height = columns * 460, rows * 420 + 30
    grow = max(0, font_size - 10)
    left, right = 58 + 9 * grow, 78 + 6 * grow
    # Bottom margin only needs to hold ticks and the X-axis label. Interpolation
    # details remain internal metadata rather than consuming plot space.
    top, bottom = 70 + 9 * grow, 42 + 9 * grow
    figure.subplots_adjust(left=left / base_width, right=1 - right / base_width,
                           top=1 - top / base_height, bottom=bottom / base_height,
                           # The row titles sit above their axes, so larger fonts
                           # need a taller gap or they print over the axis label
                           # of the row above (visible in exported copies).
                           wspace=.42 + .02 * grow, hspace=.28 + .055 * grow)
    artists = []
    for ax, scene in zip(axes.flat, result["scenes"]):
        if scene.get("skip"):
            ax.set_axis_off()
            continue
        if scene["error"]:
            ax.set_title(f'{scene["metric"]}\n{scene["label"]}', fontsize=font_size)
            ax.text(.5, .5, scene["error"], ha="center", va="center", transform=ax.transAxes,
                    fontsize=8, color="#985126", wrap=True)
            ax.set(xticks=[], yticks=[])
            continue
        plot = WaferPlot()
        plot.draw(scene["layer"], scene["metric"], scene["label"], scene["options"],
                  (settings.x, settings.y), axes=ax, prepared=scene["surface"], compact=True,
                  size_note=scene["size_note"], font_size=font_size)
        artists.append((plot, scene))
    return artists

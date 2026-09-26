"""Scientific wafer rendering, independent of Qt; also usable for batch export."""

from dataclasses import dataclass

import numpy as np
from matplotlib.artist import Artist
from matplotlib import rcParams
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_rgba
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.path import Path
from matplotlib.patches import Circle
from matplotlib.textpath import TextPath, TextToPath
from matplotlib.ticker import MaxNLocator
from matplotlib.transforms import IdentityTransform
from scipy.interpolate import RBFInterpolator, griddata
from scipy.spatial import QhullError


# Panels are rasterised above screen resolution and then scaled by the Qt view,
# so grid-fitted hinting would make the downsampled glyphs uneven.
rcParams["text.hinting"] = "no_hinting"
rcParams["text.antialiased"] = True


@dataclass
class PlotOptions:
    center_x: float = 0
    center_y: float = 0
    radius: float = 1
    labels: bool = True
    points: bool = True
    fill_edge: bool = True
    rotation: int = 0
    flip: bool = False
    limits: tuple | None = None
    difference: bool = False
    resolution: int = 400
    cmap: str = "turbo"
    show_colorbar: bool = True
    contour: bool = False
    point_outline: bool = False
    smoothing: float = 0.0
    opacity: float = 1.0
    cmap_range: tuple | None = None


class ValueLabels(Artist):
    """Draw all point values as one compound vector path instead of many Text artists."""

    _font = FontProperties(family="DejaVu Sans", size=1)
    _text_to_path = TextToPath()
    _glyphs = {}
    _top = 0.

    def __init__(self, positions, values, fontsize):
        super().__init__()
        self.positions = np.asarray(positions, dtype=float)
        self.fontsize = fontsize
        self.labels = [f"{value:.4g}" for value in values]
        self.drawn_indices = []
        self.drawn_boxes = []
        for character in set("".join(self.labels)):
            if character not in self._glyphs:
                glyph = TextPath((0, 0), character, size=1, prop=self._font)
                advance = self._text_to_path.get_text_width_height_descent(character, self._font, False)[0]
                self._glyphs[character] = glyph, advance
                self.__class__._top = max(self._top, glyph.get_extents().y1)

    def set_fontsize(self, size):
        self.fontsize = size
        self.stale = True

    def draw(self, renderer):
        if not self.get_visible() or not self.labels:
            return
        scale = renderer.points_to_pixels(self.fontsize)
        offsets = self.axes.transData.transform(self.positions)
        vertices, codes = [], []
        accepted_boxes = []
        accepted_indices = []
        # Keep labels at their measured coordinates, but omit labels that would
        # collide at the current panel size. Moving a value would imply a false
        # coordinate; deterministic thinning is honest and keeps arrays legible.
        gap = max(1.5, scale * .12)
        for index, (label, (x, y)) in enumerate(zip(self.labels, offsets)):
            width = sum(self._glyphs[character][1] for character in label) * scale
            baseline = y - (self._top + .75) * scale
            box = (x - width / 2 - gap, baseline - gap,
                   x + width / 2 + gap, baseline + self._top * scale + gap)
            if any(box[0] < other[2] and box[2] > other[0]
                   and box[1] < other[3] and box[3] > other[1]
                   for other in accepted_boxes):
                continue
            accepted_boxes.append(box)
            accepted_indices.append(index)
            cursor = x - width / 2
            for character in label:
                glyph, advance = self._glyphs[character]
                vertices.append(glyph.vertices * scale + (cursor, baseline))
                codes.append(glyph.codes)
                cursor += advance * scale
        self.drawn_indices = accepted_indices
        self.drawn_boxes = accepted_boxes
        if not vertices:
            return
        compound = Path(np.concatenate(vertices), np.concatenate(codes))
        gc = renderer.new_gc()
        self._set_gc_clip(gc)
        gc.set_foreground("#101820")
        gc.set_linewidth(0)
        renderer.draw_path(gc, compound, IdentityTransform(), to_rgba("#101820"))
        gc.restore()
        self.stale = False


def set_panel_title(ax, metric, classification, stats, font_size=10):
    """Draw a centered three-line panel heading with an emphasized metric name."""
    detail_size = max(6, font_size - 1)
    lower_offset = 5
    middle_offset = lower_offset + detail_size * 1.45
    title_pad = middle_offset + detail_size * 1.45
    title = ax.set_title(metric, loc="center", fontsize=font_size, pad=title_pad,
                         color="#17202a", fontweight="bold")
    details = [
        ax.annotate(classification, (.5, 1), xytext=(0, middle_offset),
                    xycoords="axes fraction", textcoords="offset points",
                    ha="center", va="bottom", annotation_clip=False,
                    fontsize=detail_size, color="#17202a"),
        ax.annotate(stats, (.5, 1), xytext=(0, lower_offset),
                    xycoords="axes fraction", textcoords="offset points",
                    ha="center", va="bottom", annotation_clip=False,
                    fontsize=detail_size, color="#17202a"),
    ]
    ax._wafer_title_details = details
    return title, details


def restyle_panel_title(ax, font_size):
    """Resize a panel heading while keeping its three centered lines separated."""
    details = getattr(ax, "_wafer_title_details", ())
    if len(details) != 2:
        return
    detail_size = max(6, font_size - 1)
    lower_offset = 5
    middle_offset = lower_offset + detail_size * 1.45
    title_pad = middle_offset + detail_size * 1.45
    ax.set_title(ax.get_title(loc="center"), loc="center", fontsize=font_size,
                 pad=title_pad, color="#17202a", fontweight="bold")
    details[0].set_fontsize(detail_size)
    details[0].xyann = (0, middle_offset)
    details[1].set_fontsize(detail_size)
    details[1].xyann = (0, lower_offset)


_DISPLAY_CMAPS = {}


def auto_cmap_range(name, min_luminance=0.38):
    """Default slice of ``name`` that skips the near-black ends."""
    # Rainbow's red and violet endpoints are intentionally darker hues, not
    # near-black padding. Preserve its full spectrum instead of clipping them.
    if name == "rainbow":
        return 0.0, 1.0
    samples = colormaps[name](np.linspace(0.0, 1.0, 256))
    luminance = 0.299 * samples[:, 0] + 0.587 * samples[:, 1] + 0.114 * samples[:, 2]
    bright = np.flatnonzero(luminance >= min_luminance)
    if len(bright) < 32:
        return 0.0, 1.0
    low, high = int(bright[0]), int(bright[-1])
    if high - low < 32:
        return 0.0, 1.0
    return low / 255.0, high / 255.0


def display_colormap(name, low=None, high=None, lighten=0.16):
    """The palette with its near-black ends trimmed off.

    Turbo and Viridis fade to almost black at one or both ends, which makes the
    outer wafer ring look burnt and hides the contour lines drawn on top. Cutting
    only the shades below ``min_luminance`` keeps the palette identity, and a
    small blend towards white keeps the whole map soft instead of heavy.

    ``low`` / ``high`` come from the draggable colour-range bar; ``None`` keeps
    the automatic slice so callers that never touch it see the default look.
    """
    if low is None or high is None:
        auto_low, auto_high = auto_cmap_range(name)
        low = auto_low if low is None else low
        high = auto_high if high is None else high
    low = min(max(float(low), 0.0), 1.0)
    high = min(max(float(high), 0.0), 1.0)
    if high - low < 0.02:
        high = min(1.0, low + 0.02)
    key = (name, round(low, 4), round(high, 4), round(lighten, 4))
    if key in _DISPLAY_CMAPS:
        return _DISPLAY_CMAPS[key]
    base = colormaps[name]
    colours = base(np.linspace(low, high, 256))
    if lighten > 0:
        colours = colours * (1.0 - lighten) + lighten
        colours[:, 3] = 1.0
    result = LinearSegmentedColormap.from_list(f"{name}_display", colours)
    _DISPLAY_CMAPS[key] = result
    return result


def contour_colour(cmap, low, high, level):
    """Line colour that stays readable on the filled surface at this level."""
    red, green, blue, _ = cmap(Normalize(low, high)(level))
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#f2f2f2" if luminance < 0.45 else "#1b1b1b"


def infer_geometry(points):
    """Estimate a display circle in the input coordinate units."""
    xy = np.asarray(points, dtype=float)
    if not len(xy):
        raise ValueError("没有有效的坐标。")
    center = (xy.min(axis=0) + xy.max(axis=0)) / 2
    gaps = np.concatenate([np.diff(np.unique(xy[:, i])) for i in (0, 1)])
    padding = float(np.median(gaps[gaps > 0])) / 2 if np.any(gaps > 0) else 0.5
    radius = float(np.linalg.norm(xy - center, axis=1).max()) + padding
    return float(center[0]), float(center[1]), radius


def infer_wafer_geometry(points, axis_names):
    """Snap well-covered mm coordinates to a common wafer diameter; otherwise keep extent."""
    xy = np.asarray(points, dtype=float)
    geometry = infer_geometry(xy)
    names = ["".join(c.lower() for c in name if c.isalnum()) for name in axis_names]
    if not all(name.endswith("mm") for name in names) or len(xy) < 8:
        return geometry, None
    estimated_center = np.array(geometry[:2])
    for diameter in sorted((100, 200, 300), key=lambda d: abs(geometry[2] - d / 2)):
        radius = diameter / 2
        # Wafer-relative millimetre coordinates normally use (0, 0). Small
        # apparent offsets come from incomplete edge sampling, not a shifted wafer.
        center = np.zeros(2) if np.linalg.norm(estimated_center) <= .1 * radius else estimated_center
        distances = np.linalg.norm(xy - center, axis=1)
        outer = xy[distances >= 0.65 * radius] - center
        quadrants = {(x >= 0, y >= 0) for x, y in outer}
        if (abs(geometry[2] - radius) <= 0.15 * radius
                and distances.max() <= radius * 1.005
                and np.ptp(xy, axis=0).min() >= 1.2 * radius
                and len(quadrants) == 4):
            return (float(center[0]), float(center[1]), radius), diameter
    return geometry, None


def mirror_across_edge(points, values, geometry, inner_fraction=0.5):
    """Reflect the outer samples across the wafer edge as virtual samples.

    A single global spline through the measured points plus their images covers
    the whole disk: there is no convex-hull seam, and the unsampled rim keeps the
    measured radial trend instead of being flattened by a zero-flux boundary.
    Only the outer samples are mirrored so interior outliers are not projected
    onto the edge, and each image stays within one wafer radius of the rim.
    """
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    center = np.array([geometry[0], geometry[1]], dtype=float)
    radius = float(geometry[2])
    offsets = points - center
    distance = np.linalg.norm(offsets, axis=1)
    selected = distance >= inner_fraction * radius
    if not selected.any():
        return points, values
    scale = (2 * radius - distance[selected]) / distance[selected]
    images = center + offsets[selected] * scale[:, None]
    return np.vstack([points, images]), np.vstack([values, values[selected]])


def interpolate_many(points, values, geometry, fill_edge=True, resolution=400, smoothing=0.0):
    """Interpolate one or more value columns while sharing the same RBF solve."""
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    cx, cy, radius = geometry
    if not np.isfinite([cx, cy, radius]).all() or radius <= 0:
        raise ValueError("圆心必须为有限数值，半径必须大于 0。")
    if len(points) < 3 or np.linalg.matrix_rank(points - points.mean(axis=0)) < 2:
        raise ValueError("连续图至少需要 3 个不共线的有效坐标。")
    xs = np.linspace(cx - radius, cx + radius, resolution)
    ys = np.linspace(cy - radius, cy + radius, resolution)
    gx, gy = np.meshgrid(xs, ys)
    try:
        if fill_edge:
            # One continuous spline over the whole wafer: the mirrored collar
            # continues the measured trend to the edge, so no seam or flat ring.
            modelled_points, modelled_values = mirror_across_edge(points, values, geometry)
        else:
            modelled_points, modelled_values = points, values
        # Normalise the coordinates by the wafer radius: the thin-plate kernel is
        # scale sensitive, and the smoothing term must not depend on mm vs units.
        unit_points = (modelled_points - np.array([cx, cy])) / radius
        # ``smoothing`` is the accepted residual as a fraction of each parameter's
        # own range. Standardising every column keeps that meaning when parameters
        # with very different magnitudes share one solve; otherwise the widest
        # column would flatten the narrow ones.
        column_mean = np.nanmean(values, axis=0)
        column_span = np.nanmax(values, axis=0) - np.nanmin(values, axis=0)
        column_span = np.where(column_span > 0, column_span, 1.0)
        normalised = (modelled_values - column_mean) / column_span
        regularisation = float(smoothing) ** 2
        model = RBFInterpolator(unit_points, normalised, kernel="thin_plate_spline",
                                smoothing=regularisation,
                                neighbors=64 if len(modelled_points) > 300 else None)
        unit_grid = np.column_stack(((gx.ravel() - cx) / radius, (gy.ravel() - cy) / radius))
        surface = (model(unit_grid).reshape(*gx.shape, values.shape[1])
                   * column_span + column_mean)
        outside_hull = ~np.isfinite(griddata(points, np.ones(len(points)), (gx, gy), method="linear"))
    except (QhullError, np.linalg.LinAlgError) as error:
        raise ValueError("坐标无法组成二维插值网格，请检查数据。") from error
    outside_circle = (gx - cx) ** 2 + (gy - cy) ** 2 > radius ** 2
    if not fill_edge:
        surface[outside_hull, :] = np.nan
    # The mirrored spline can undershoot slightly between samples; clipping keeps
    # every displayed value inside the measured range.
    surface = np.clip(surface, values.min(axis=0), values.max(axis=0))
    masked = [np.ma.array(surface[..., index], mask=outside_circle | ~np.isfinite(surface[..., index]))
              for index in range(values.shape[1])]
    return gx, gy, masked, outside_hull & ~outside_circle


def interpolate(points, values, geometry, fill_edge=True, resolution=400, smoothing=0.0):
    """Smooth thin-plate RBF surface; values outside the sample hull are estimates."""
    gx, gy, surfaces, edge = interpolate_many(points, values, geometry, fill_edge, resolution, smoothing)
    return gx, gy, surfaces[0], edge


def prepare_surfaces(points, values, options):
    """Prepare several parameters with identical coordinates in one numerical pass."""
    xy = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    if not len(values):
        raise ValueError("No valid numeric samples for this wafer / parameter.")
    center = np.array([options.center_x, options.center_y])
    angle = np.deg2rad(options.rotation)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    positions = (xy - center) @ rotation.T
    if options.flip:
        positions[:, 0] *= -1
    positions += center
    if np.any(np.linalg.norm(positions - center, axis=1) > options.radius + 1e-9):
        raise ValueError("Wafer boundary excludes samples. Increase diameter or adjust center.")
    gx, gy, surfaces, edge = interpolate_many(positions, values, (*center, options.radius),
                                               options.fill_edge, options.resolution, options.smoothing)
    return [(positions, gx, gy, surface, edge) for surface in surfaces]


def prepare_surface(layer, options):
    """Numerical work only; safe to run outside the GUI thread."""
    return prepare_surfaces(layer[["x", "y"]].to_numpy(float), layer["value"].to_numpy(float), options)[0]


class WaferPlot:
    def __init__(self):
        self.figure = Figure(figsize=(7.7, 6.5), facecolor="white", layout="constrained")
        self.axes = None
        self.colorbar = None
        self.image = None
        self.marker = None
        self.value_labels = None
        self.point_markers = None
        self.contours = None
        self.circle = None
        self.positions = np.empty((0, 2))

    def clear(self, message="Open CSV / XLSX or paste a table to begin"):
        self.figure.clear()
        self.axes = None
        self.colorbar = self.marker = None
        self.image = None
        self.point_markers = None
        self.contours = None
        self.circle = None
        self.positions = np.empty((0, 2))
        self.figure.text(0.5, 0.5, message, ha="center", va="center", color="#746b7e")

    def draw(self, layer, metric, subtitle, options, axis_names=("FIELD X", "FIELD Y"),
             *, axes=None, prepared=None, compact=False, size_note="", font_size=10):
        values = layer["value"].to_numpy(float)
        center = np.array([options.center_x, options.center_y])
        radius = options.radius
        positions, gx, gy, surface, edge = prepared if prepared is not None else prepare_surface(layer, options)
        data_low, data_high = float(values.min()), float(values.max())
        manual = options.limits or (None, None)
        low = data_low if manual[0] is None else float(manual[0])
        high = data_high if manual[1] is None else float(manual[1])
        if options.difference and manual == (None, None):
            bound = max(abs(data_low), abs(data_high), 1e-9)
            low, high = -bound, bound
        if high <= low:
            margin = max(abs(low) * 0.01, 0.01)
            low, high = low - margin, high + margin
        if not np.isfinite([low, high]).all():
            raise ValueError("色阶上下限必须为有限数值。")

        if axes is None:
            self.figure.clear()
            axes = self.figure.add_subplot(111)
        else:
            self.figure = axes.figure
        self.positions = positions
        self.marker = None
        self.value_labels = None
        self.point_markers = None
        self.contours = None
        ax = axes
        self.axes = ax
        palette = "coolwarm" if options.difference else options.cmap
        cmap = display_colormap(palette, *(options.cmap_range or (None, None)))
        # imshow gives a smooth surface; the mask and circle clip define the wafer.
        image = ax.imshow(np.ma.masked_invalid(surface.data), origin="lower", cmap=cmap, norm=Normalize(low, high),
                          extent=(gx.min(), gx.max(), gy.min(), gy.max()), interpolation="bilinear",
                          alpha=float(options.opacity))
        self.image = image
        circle = Circle(center, radius, facecolor="none", edgecolor="#343b45", linewidth=0.8)
        ax.add_patch(circle)
        image.set_clip_path(circle)
        self.circle = circle
        # Iso-lines make the interpolated surface readable as a topography. They
        # are built for every map and only toggled, so the Contour lines checkbox
        # repaints the overlays instead of rebuilding all maps.
        levels = MaxNLocator(nbins=9).tick_values(low, high)
        levels = levels[(levels >= low) & (levels <= high)]
        if len(levels) >= 2:
            # Pick each line's own shade from the fill underneath it, so the
            # contours stay visible on the dark and the light ends of the map.
            colours = [contour_colour(cmap, low, high, level) for level in levels]
            self.contours = ax.contour(gx, gy, surface, levels=levels, colors=colours,
                                       linewidths=0.5, alpha=0.9, zorder=2)
            self.contours.set_visible(bool(options.contour))
        if options.point_outline:
            # A light ring keeps the measured symbols readable on the dark parts
            # of the map; colouring them with the map palette would just hide them.
            self.point_markers = ax.scatter(*positions.T, c="#101820", s=13,
                                            linewidths=0.9, edgecolors="#f5f5f5", zorder=3)
        else:
            self.point_markers = ax.scatter(*positions.T, c="#101820", s=5, linewidths=0, zorder=3)
        self.point_markers.set_visible(options.points)
        size = max(4.5, font_size * (0.55 if compact else 0.65))
        if len(values) > 100:
            size = max(4.5, size - 1)
        self.value_labels = ValueLabels(positions, values, size)
        self.value_labels.set_visible(options.labels)
        self.value_labels.set_zorder(4)
        self.value_labels.set_clip_path(ax.patch)
        ax.add_artist(self.value_labels)
        # The coordinate frame represents the detected wafer diameter exactly.
        # Extra visual padding made a 300 mm wafer appear to span roughly 320 mm.
        margin = radius
        ax.set(xlim=(center[0] - margin, center[0] + margin),
               ylim=(center[1] - margin, center[1] + margin), aspect="equal")
        transformed = options.rotation != 0 or options.flip
        label_size = max(6, font_size - 1)
        tick_size = max(5, font_size - 2)
        ax.set_xlabel(axis_names[0] + (" (view)" if transformed else ""), fontsize=label_size)
        ax.set_ylabel(axis_names[1] + (" (view)" if transformed else ""), fontsize=label_size)
        classification = " · ".join(subtitle.splitlines())
        stats = f"Min {values.min():.5g}   Max {values.max():.5g}   Mean {values.mean():.5g}"
        heading = metric + ("  [A - B]" if options.difference else "")
        set_panel_title(ax, heading, classification, stats, font_size)
        ax.tick_params(direction="out", top=True, right=True, labelsize=tick_size, length=3)
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("#303030")
        normalized_axes = ["".join(ch.lower() for ch in name if ch.isalnum()) for name in axis_names]
        standard_radius = next((value for value in (50, 100, 150) if np.isclose(radius, value)), None)
        if standard_radius and all(name.endswith("mm") for name in normalized_axes):
            step = 25 if standard_radius == 50 else 50
            offsets = np.arange(-standard_radius, standard_radius + step / 2, step)
            ax.set_xticks(center[0] + offsets)
            ax.set_yticks(center[1] + offsets)
        else:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=5 if compact else 7))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5 if compact else 7))
        self.colorbar = None
        if options.show_colorbar:
            self.colorbar = self.figure.colorbar(image, ax=ax, fraction=0.045, pad=0.045, shrink=0.86)
            # Array titles already name every parameter; repeating it vertically beside
            # each colorbar crowds the next subplot's Y label.
            if not compact:
                self.colorbar.set_label(metric + (" (A - B)" if options.difference else ""), fontsize=label_size)
            self.colorbar.ax.tick_params(labelsize=tick_size)
            self.colorbar.outline.set_linewidth(0.6)
            if size_note:
                self.colorbar.ax.set_title(size_note, fontsize=tick_size, pad=5)
        note = ("Spline over mirrored samples; no edge seam" if options.fill_edge else
                "RBF interpolation; outside hull = no data")
        if not compact:
            ax.text(0, -0.13, note, transform=ax.transAxes, fontsize=tick_size, color="#666666")
        return int(edge.sum()), (low, high)

    def select(self, index):
        if self.marker is not None:
            self.marker.remove()
        self.marker = self.axes.scatter(*self.positions[index], s=110, facecolors="none",
                                        edgecolors="#111111", linewidths=1.4, zorder=5)

    def save(self, path):
        self.figure.savefig(path, dpi=300, facecolor="white")

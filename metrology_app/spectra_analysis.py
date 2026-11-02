"""Source-preserving spectral calculations, independent of Qt and rendering."""
from dataclasses import dataclass

import numpy as np

from .sme_spectra import SpectrumChannel


@dataclass(frozen=True, slots=True)
class SpectralSeries:
    wavelength: np.ndarray
    values: np.ndarray
    counts: np.ndarray | None = None


def _unique_wavelengths(x):
    finite = x[np.isfinite(x)]
    if len(np.unique(finite)) != len(finite):
        raise ValueError("Repeated wavelengths are ambiguous; this channel was excluded.")


def residual_series(channel: SpectrumChannel, baselines, metric: str) -> SpectralSeries:
    """Measured minus BSL at exactly equal wavelengths; never interpolate or wrap phase."""
    values = channel.series(metric)
    candidates = [c for c in baselines if c.key == channel.key and c.series(metric) is not None]
    if not candidates and channel.key.aoi_deg is not None and channel.key.azi_deg is not None:
        candidates = [c for c in baselines
                      if (c.key.aoi_deg, c.key.azi_deg) == (channel.key.aoi_deg, channel.key.azi_deg)
                      and c.series(metric) is not None]
    if values is None or len(candidates) != 1:
        raise ValueError("BSL needs one matching channel/metric (exact AOI/AZI); none or multiple found.")
    baseline = candidates[0]
    _unique_wavelengths(baseline.wavelength)
    finite = np.isfinite(baseline.wavelength)
    order = np.argsort(baseline.wavelength[finite])
    bx = baseline.wavelength[finite][order]
    by = baseline.series(metric)[finite][order]
    result = np.full(len(values), np.nan)
    if len(bx):
        index = np.searchsorted(bx, channel.wavelength)
        safe = np.minimum(index, len(bx) - 1)
        valid = (index < len(bx)) & (bx[safe] == channel.wavelength)
        valid &= np.isfinite(values) & np.isfinite(by[safe])
        result[valid] = values[valid] - by[safe[valid]]
    if not np.isfinite(result).any():
        raise ValueError("No exactly matching finite wavelengths with BSL; no interpolation was applied.")
    return SpectralSeries(channel.wavelength, result)


def three_sigma_series(sources) -> SpectralSeries:
    """3 × sample SD (n−1), using only finite observations at identical wavelengths.

    Call separately for each wafer/channel. At least two observations are
    required per wavelength; missing values remain gaps, never artificial zero.
    """
    sources = tuple(sources)
    if len(sources) < 2:
        raise ValueError("3σ needs at least two checked spectra per wafer/channel.")
    for source in sources:
        _unique_wavelengths(source.wavelength)
    x = np.unique(np.concatenate([s.wavelength[np.isfinite(s.wavelength)] for s in sources]))
    counts = np.zeros(len(x), dtype=np.int64)
    mean = np.zeros(len(x))
    m2 = np.zeros(len(x))
    # Welford accumulation avoids a large sample × wavelength matrix and
    # cancellation when small GRR variation sits on a large signal offset.
    for source in sources:
        valid = np.isfinite(source.wavelength) & np.isfinite(source.values)
        index = np.searchsorted(x, source.wavelength[valid])
        values = source.values[valid]
        counts[index] += 1
        delta = values - mean[index]
        mean[index] += delta / counts[index]
        m2[index] += delta * (values - mean[index])
    enough = counts >= 2
    if not enough.any():
        raise ValueError("No exact wavelength has at least two finite observations for 3σ.")
    result = np.full(len(x), np.nan)
    result[enough] = 3 * np.sqrt(np.maximum(m2[enough], 0) / (counts[enough] - 1))
    return SpectralSeries(x, result, counts)

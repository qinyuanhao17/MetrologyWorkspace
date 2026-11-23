"""Fit and validate optional Dynamic trends without changing measurement data."""

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares


METHODS = {
    "raw": "None / Raw",
    "linear": "Linear Detrend",
    "exponential": "Exponential Detrend",
    "common_linear": "Common-mode Linear Detrend",
    "common_exponential": "Common-mode Exponential Detrend",
}

MIN_LINEAR_CYCLES = 4
MIN_EXPONENTIAL_CYCLES = 6
MIN_PEERS = 3
MIN_R_SQUARED = .5
MIN_AMPLITUDE_TO_NOISE = 2
MIN_EXPONENTIAL_IMPROVEMENT = .1

VALIDATION_HELP = (
    f"Linear requires {MIN_LINEAR_CYCLES} finite Cycles and exponential requires {MIN_EXPONENTIAL_CYCLES}.\n"
    "Trend amplitude is the signed fitted change over the measured Cycles.\n"
    f"A fit needs R² at or above the configured minimum (default {MIN_R_SQUARED:g}) "
    f"and an absolute change ≥ {MIN_AMPLITUDE_TO_NOISE} × residual sample SD.\n"
    "Exponential fits must converge with tau between half the smallest Cycle gap and 10 × the Cycle span.\n"
    f"They must also reduce squared error by at least {MIN_EXPONENTIAL_IMPROVEMENT:.0%} versus linear.\n"
    f"Common-mode excludes the current Die and requires at least {MIN_PEERS} peers per fitted Cycle.\n"
    "At least two thirds of eligible peers must show 50–150% of the shared drift on overlapping Cycles.\n"
    "The held-out Die must also agree with the drift and have lower scatter after correction.\n"
    "R² measures the fitted input, which is the peer median for common-mode."
)


@dataclass(frozen=True)
class DetrendResult:
    method: str
    raw_sigma: float | None
    status: str
    sigma: float | None = None
    amplitude: float | None = None
    r_squared: float | None = None
    parameters: dict = field(default_factory=dict)
    fitted: np.ndarray | None = None
    corrected: np.ndarray | None = None

    @property
    def valid(self):
        return self.corrected is not None


def _linear_fit(x, y):
    x_centered = x - x.mean()
    slope = np.dot(x_centered, y - y.mean()) / np.dot(x_centered, x_centered)
    return y.mean() - slope * x.mean(), slope


def _saturation(x, initial, amplitude, tau):
    return initial - amplitude * np.expm1(-x / tau)


def _exponential_fit(x, y, linear_residual):
    """Fit on normalized axes so the optimizer does not depend on measurement units."""
    span = x[-1]
    scale = np.ptp(y)
    time = x / span
    values = (y - y[0]) / scale
    lower_tau = np.min(np.diff(time)) / 2
    upper_tau = 10.0
    residual_mad = np.median(np.abs(linear_residual - np.median(linear_residual)))
    try:
        fit = least_squares(
            lambda params: _saturation(time, *params) - values,
            [0, values[-1], 1 / 3], bounds=([-np.inf, -np.inf, lower_tau], [np.inf, np.inf, upper_tau]),
            loss="soft_l1", f_scale=max(.01, 1.4826 * residual_mad / scale), x_scale="jac",
            max_nfev=200,
        )
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return None, "Fit failed"
    if not fit.success or not np.isfinite(fit.x).all():
        return None, "Fit did not converge"
    initial, amplitude, tau = fit.x
    coefficients = (y[0] + initial * scale, amplitude * scale, tau * span)
    if (tau <= 1.01 * lower_tau or tau >= .99 * upper_tau
            or np.linalg.matrix_rank(fit.jac) < 3):
        return coefficients, "Unresolved exponential time constant"
    return coefficients, ""


def _fit_trend(x, y, exponential, min_r_squared):
    """Return fitted values on the input Cycle grid plus the validation diagnostics."""
    observed = np.isfinite(y)
    cycles, values = x[observed], y[observed]
    minimum = MIN_EXPONENTIAL_CYCLES if exponential else MIN_LINEAR_CYCLES
    if len(cycles) < minimum:
        return None, {}, None, f"Fewer than {minimum} fit cycles"
    if np.ptp(values) <= np.finfo(float).eps * np.max(np.abs(values)) * 8:
        return None, {}, None, "No measurable trend"

    start = cycles[0]
    shifted = cycles - start
    initial, slope = _linear_fit(shifted, values)
    linear_residual = values - (initial + slope * shifted)
    parameters = {"x0": start, "y0": initial, "slope": slope}
    fitted = initial + slope * (x - start)
    status = ""
    if exponential:
        coefficients, status = _exponential_fit(shifted, values, linear_residual)
        if coefficients is None:
            return None, {}, None, status
        initial, amplitude, tau = coefficients
        parameters = {"x0": start, "y0": initial, "A": amplitude, "tau": tau}
        fitted = _saturation(np.maximum(x - start, 0), initial, amplitude, tau)

    fitted[(x < start) | (x > cycles[-1])] = np.nan
    fitted_observed = fitted[observed]
    residual = values - fitted_observed
    sse = np.dot(residual, residual)
    centered = values - values.mean()
    r_squared = 1 - sse / np.dot(centered, centered)
    amplitude = abs(fitted_observed[-1] - fitted_observed[0])
    if not status:
        if r_squared < min_r_squared:
            status = f"Fit R² below {min_r_squared:.2f}"
        elif amplitude < MIN_AMPLITUDE_TO_NOISE * residual.std(ddof=1):
            status = "Weak trend relative to scatter"
        elif exponential and sse >= (1 - MIN_EXPONENTIAL_IMPROVEMENT) * np.dot(linear_residual, linear_residual):
            status = "Exponential fit does not improve on linear"
    return fitted, parameters, float(r_squared), status


def _agrees(values, fitted, minimum):
    overlap = np.isfinite(values) & np.isfinite(fitted)
    if np.count_nonzero(overlap) < minimum:
        return None
    trend = fitted[overlap] - fitted[overlap].mean()
    observations = values[overlap] - values[overlap].mean()
    variance = np.dot(trend, trend)
    return bool(variance > 0 and .5 <= np.dot(observations, trend) / variance <= 1.5)


def _common_values(centered, die_column):
    peers = np.delete(centered, die_column, axis=1)
    covered = np.count_nonzero(np.isfinite(peers), axis=1) >= MIN_PEERS
    trend = np.full(len(peers), np.nan)
    trend[covered] = np.nanmedian(peers[covered], axis=1)
    return trend, peers


def _die_result(method, x, values, training, peers, min_r_squared):
    observed = np.isfinite(values)
    raw_sigma = float(3 * values[observed].std(ddof=1)) if observed.sum() > 1 else None
    exponential = method.endswith("exponential")
    minimum = MIN_EXPONENTIAL_CYCLES if exponential else MIN_LINEAR_CYCLES
    diagnostics = {}
    if observed.sum() < minimum:
        status = f"Fewer than {minimum} measurement cycles"
    elif peers is not None and peers.shape[1] < MIN_PEERS:
        status = f"Fewer than {MIN_PEERS} other Dies"
    else:
        fitted, parameters, r_squared, status = _fit_trend(x, training, exponential, min_r_squared)
        diagnostics.update(parameters=parameters, r_squared=r_squared)
        if fitted is not None:
            usable = fitted[observed & np.isfinite(fitted)]
            if len(usable):
                diagnostics["amplitude"] = float(usable[-1] - usable[0])
            if not status and peers is not None:
                peer_fit = np.where(np.isfinite(training), fitted, np.nan)
                agreement = [agrees for peer in peers.T
                             if (agrees := _agrees(peer, peer_fit, minimum)) is not None]
                if len(agreement) < MIN_PEERS or sum(agreement) * 3 < len(agreement) * 2:
                    status = "Peer Dies disagree on the shared trend"
                elif len(usable) != observed.sum() or not _agrees(values, fitted, minimum):
                    status = "Shared trend does not match the held-out Die"
            if not status:
                drift = usable - usable.mean()
                corrected = np.full(len(x), np.nan)
                corrected[observed] = values[observed] - drift
                sigma = float(3 * corrected[observed].std(ddof=1))
                if peers is None or sigma < raw_sigma:
                    display_fit = np.full(len(x), np.nan)
                    display_fit[observed] = usable if peers is None else values[observed].mean() + drift
                    return DetrendResult(method, raw_sigma, "Valid", sigma=sigma,
                                         fitted=display_fit, corrected=corrected, **diagnostics)
                status = "Shared trend does not improve the held-out Die"
    return DetrendResult(method, raw_sigma, status, **diagnostics)


def detrend(table, method, *, min_r_squared=MIN_R_SQUARED):
    """Compute one result per Die from a numeric Cycle × Die table in Cycle order."""
    if method == "raw":
        return {}
    if method not in METHODS:
        raise ValueError(f"Unknown Dynamic detrend method: {method}")
    if not 0 <= min_r_squared <= 1:
        raise ValueError("Detrend minimum R² must be between 0 and 1.")
    x = table.index.to_numpy(dtype=float)
    if not np.isfinite(x).all() or (np.diff(x) <= 0).any():
        raise ValueError("Detrend requires unique, increasing numeric Cycle values.")
    values = table.to_numpy(dtype=float, copy=True)
    values[~np.isfinite(values)] = np.nan
    common = method.startswith("common_")
    if common:
        counts = np.count_nonzero(np.isfinite(values), axis=0)
        centered = values - np.nansum(values, axis=0) / np.maximum(counts, 1)
        minimum = MIN_EXPONENTIAL_CYCLES if method.endswith("exponential") else MIN_LINEAR_CYCLES
        centered[:, counts < minimum] = np.nan
    results = {}
    for column, die in enumerate(table.columns):
        observed = values[:, column]
        training, peers = _common_values(centered, column) if common else (observed, None)
        results[die] = _die_result(method, x, observed, training, peers, min_r_squared)
    return results

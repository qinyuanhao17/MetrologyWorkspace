"""Shared series definitions for single-wafer statistics and Excel reports."""

METRICS_SHEET_TITLE = "Mean&STD"
METRIC_PLOTS = {
    "wafer_r2": ("R²", ("R²",), ("#4f8bd6",)),
    "wafer_slope": ("Slope", ("Slope",), ("#e09f3e",)),
    "wafer_mean": ("Mean", ("Mean", "Reference Mean"), ("#4f8bd6", "#e09f3e")),
    "wafer_mean_bias": ("Mean Bias", ("Mean Bias",), ("#4f8bd6",)),
    "wafer_std": ("STD", ("STD", "Reference STD"), ("#4f8bd6", "#e09f3e")),
}
DEFAULT_METRIC_PLOTS = ("wafer_r2", "wafer_slope")

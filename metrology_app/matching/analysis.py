"""Deep module for row-aligned Reference/Raw card matching workflows."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from copy import copy
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from ..measurements import default_identity_columns, detect_measurements, wafer_identity_label
from ..trend import parse_unit


SCHEMA_VERSION = 10
MAX_ROWS = 100_000
MAX_PARAMETERS = 50
_ALLOWED_MATCH_TYPES = {"TEM", "NOVA", "KLA"}
_ALLOWED_RESULT_MODES = {"preview", "final"}
_ALLOWED_BIAS_MODES = {"absolute", "percent"}
_ROW_COLUMN = "__wkb_row__"
_WORKSPACE_KINDS = ("map", "dynamic")
_WORKSPACE_STAGES = ("preview", "final")


def _normalized_workspace_selections(selections):
    """Return the durable Map/Dynamic selection shape used by WKB files."""
    normalized = {
        kind: {stage: None for stage in _WORKSPACE_STAGES}
        for kind in _WORKSPACE_KINDS
    }
    if selections is None:
        return normalized
    if not isinstance(selections, dict):
        raise TypeError("Workspace selections must be a mapping.")
    unknown_kinds = set(selections) - set(_WORKSPACE_KINDS)
    if unknown_kinds:
        raise ValueError("Unknown workspace selection kind.")
    for kind, stages in selections.items():
        if stages is None:
            continue
        if not isinstance(stages, dict):
            raise TypeError("Workspace selection stages must be a mapping.")
        unknown_stages = set(stages) - set(_WORKSPACE_STAGES)
        if unknown_stages:
            raise ValueError("Unknown workspace selection stage.")
        for stage, state in stages.items():
            if state is None:
                continue
            if not isinstance(state, dict):
                raise TypeError("Each workspace selection must be a mapping.")
            saved = {}
            for field in ("wafers", "metrics"):
                values = state.get(field, ())
                if isinstance(values, (str, bytes)):
                    raise TypeError(
                        f"Workspace selection {field} must be a sequence."
                    )
                try:
                    values = tuple(str(value) for value in values)
                except TypeError as error:
                    raise TypeError(
                        f"Workspace selection {field} must be a sequence."
                    ) from error
                if any(not value.strip() for value in values):
                    raise ValueError(
                        f"Workspace selection {field} cannot contain blanks."
                    )
                if len(set(values)) != len(values):
                    raise ValueError(
                        f"Workspace selection {field} cannot contain duplicates."
                    )
                saved[field] = values
            if kind == "map":
                for field, label in (
                    ("map_draw", "Wafer Map"),
                    ("radius_draw", "Radius Plot"),
                ):
                    if field not in state:
                        continue
                    draw_state = state[field]
                    if not isinstance(draw_state, dict):
                        raise TypeError(f"{label} draw state must be a mapping.")
                    enabled = draw_state.get("enabled", False)
                    if not isinstance(enabled, bool):
                        raise TypeError(
                            f"{label} draw state enabled must be boolean."
                        )
                    raw_cells = draw_state.get("cells", ())
                    if isinstance(raw_cells, (str, bytes)):
                        raise TypeError(
                            f"{label} draw cells must be a sequence."
                        )
                    cells = []
                    try:
                        for cell in raw_cells:
                            if isinstance(cell, (str, bytes)) or len(cell) != 2:
                                raise TypeError
                            wafer, metric = (str(value) for value in cell)
                            if not wafer.strip() or not metric.strip():
                                raise ValueError
                            cells.append((wafer, metric))
                    except (TypeError, ValueError) as error:
                        raise ValueError(
                            f"{label} draw cells must contain non-blank pairs."
                        ) from error
                    if len(set(cells)) != len(cells):
                        raise ValueError(
                            f"{label} draw cells cannot contain duplicates."
                        )
                    saved[field] = {
                        "enabled": enabled,
                        "cells": tuple(cells),
                    }
            normalized[kind][stage] = saved
    return normalized


def _normalized_correlation_selections(selections):
    """Return durable per-stage Correlation/Trend sidebar and draw state."""
    normalized = {stage: None for stage in _WORKSPACE_STAGES}
    if selections is None:
        return normalized
    if not isinstance(selections, dict):
        raise TypeError("Correlation selections must be a mapping.")
    if set(selections) - set(_WORKSPACE_STAGES):
        raise ValueError("Unknown correlation selection stage.")
    for stage, state in selections.items():
        if state is None:
            continue
        if not isinstance(state, dict):
            raise TypeError("Each correlation selection must be a mapping.")
        saved = {}
        for source in ("reference", "raw"):
            source_state = state.get(source, {})
            if not isinstance(source_state, dict):
                raise TypeError(
                    f"Correlation {source} selection must be a mapping."
                )
            selected = {}
            for field in ("wafers", "metrics"):
                values = source_state.get(field, ())
                if isinstance(values, (str, bytes)):
                    raise TypeError(
                        f"Correlation {source} {field} must be a sequence."
                    )
                try:
                    values = tuple(str(value) for value in values)
                except TypeError as error:
                    raise TypeError(
                        f"Correlation {source} {field} must be a sequence."
                    ) from error
                if any(not value.strip() for value in values):
                    raise ValueError(
                        f"Correlation {source} {field} cannot contain blanks."
                    )
                if len(set(values)) != len(values):
                    raise ValueError(
                        f"Correlation {source} {field} cannot contain duplicates."
                    )
                selected[field] = values
            saved[source] = selected
        for field, label in (
            ("correlation_draw", "Correlation"),
            ("trend_draw", "Trend"),
        ):
            draw_state = state.get(field, {})
            if not isinstance(draw_state, dict):
                raise TypeError(f"{label} draw state must be a mapping.")
            enabled = draw_state.get("enabled", False)
            if not isinstance(enabled, bool):
                raise TypeError(f"{label} draw state enabled must be boolean.")
            raw_cells = draw_state.get("cells", ())
            if isinstance(raw_cells, (str, bytes)):
                raise TypeError(f"{label} draw cells must be a sequence.")
            cells = []
            try:
                for cell in raw_cells:
                    if isinstance(cell, (str, bytes)) or len(cell) != 3:
                        raise TypeError
                    source, wafer, metric = (str(value) for value in cell)
                    if not source.strip() or not wafer.strip() or not metric.strip():
                        raise ValueError
                    cells.append((source, wafer, metric))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{label} draw cells must contain non-blank triples."
                ) from error
            if len(set(cells)) != len(cells):
                raise ValueError(f"{label} draw cells cannot contain duplicates.")
            saved[field] = {"enabled": enabled, "cells": tuple(cells)}
        ratio = state.get("trend_axis_ratio")
        if ratio is not None:
            try:
                ratio = float(ratio)
            except (TypeError, ValueError) as error:
                raise TypeError(
                    "Trend second-axis ratio must be a number."
                ) from error
            if not np.isfinite(ratio) or not 1 <= ratio <= 1_000_000:
                raise ValueError(
                    "Trend second-axis ratio must be between 1 and 1000000."
                )
            saved["trend_axis_ratio"] = ratio
        mode = state.get("trend_axis_mode")
        if mode is not None:
            if mode not in ("auto", "dual", "single"):
                raise ValueError("Trend Y-axis mode must be auto, dual, or single.")
            saved["trend_axis_mode"] = mode
        normalized[stage] = saved
    return normalized


def _normalized_trend_axis_settings(settings, selections, active_stage):
    """One workbook-wide policy; migrate an older stage policy as one pair."""
    if settings is None:
        other_stage = "final" if active_stage == "preview" else "preview"
        legacy = next((
            state for stage in (active_stage, other_stage)
            if (state := selections.get(stage)) is not None
            and any(key in state for key in ("trend_axis_ratio", "trend_axis_mode"))
        ), {})
        settings = {
            "ratio": legacy.get("trend_axis_ratio", 10.0),
            "mode": legacy.get("trend_axis_mode", "auto"),
        }
    if not isinstance(settings, dict):
        raise TypeError("Trend axis settings must be a mapping.")
    if set(settings) - {"ratio", "mode"}:
        raise ValueError("Unknown Trend axis setting.")
    try:
        ratio = float(settings.get("ratio", 10.0))
    except (TypeError, ValueError) as error:
        raise TypeError("Trend second-axis ratio must be a number.") from error
    if not np.isfinite(ratio) or not 1 <= ratio <= 1_000_000:
        raise ValueError("Trend second-axis ratio must be between 1 and 1000000.")
    mode = settings.get("mode", "auto")
    if mode not in ("auto", "dual", "single"):
        raise ValueError("Trend Y-axis mode must be auto, dual, or single.")
    return {"ratio": ratio, "mode": mode}


@dataclass(frozen=True, slots=True)
class ParameterMapping:
    """One named Reference column paired with one Raw Data column."""

    name: str
    reference_column: str
    raw_column: str
    bias_limit: float | None = None
    show_bias_limit: bool = False

    def __post_init__(self):
        if not all(str(value).strip() for value in (self.name, self.reference_column, self.raw_column)):
            raise ValueError("Parameter mapping names and columns cannot be blank.")
        if self.bias_limit is not None:
            object.__setattr__(self, "bias_limit", _validated_bias_limit(self.bias_limit))
        if not isinstance(self.show_bias_limit, bool):
            raise ValueError("Show Bias limit must be a checkbox value.")


@dataclass(frozen=True, slots=True)
class Card:
    """Linear calibration fitted as Reference = slope × Raw + intercept."""

    slope: float
    intercept: float
    r_squared: float
    valid_pairs: int


def _validated_bias_limit(value):
    try:
        limit = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Bias limit must be a finite, non-negative number.") from None
    if not np.isfinite(limit) or limit < 0:
        raise ValueError("Bias limit must be a finite, non-negative number.")
    return limit


class MatchAnalysisResult:
    """Compact result; materialize derived rows for only the selected parameter."""

    def __init__(self, reference, raw, mappings, cards, result_mode, bias_mode, match_type, bias_limit=.5):
        self._reference = reference
        self._raw = raw
        self._mappings = mappings
        self._cards = cards
        self.result_mode = result_mode
        self.bias_mode = bias_mode
        self.match_type = match_type
        self._mapping_by_name = {mapping.name: mapping for mapping in mappings}
        self.summary = pd.DataFrame([
            {
                "Parameter": mapping.name,
                "Reference column": mapping.reference_column,
                "Raw column": mapping.raw_column,
                "Slope": cards[mapping.name].slope,
                "Intercept": cards[mapping.name].intercept,
                "R²": cards[mapping.name].r_squared,
                "Valid pairs": cards[mapping.name].valid_pairs,
                "Match type": match_type,
                "Result mode": result_mode.title(),
            }
            for mapping in mappings
        ])
        self.bias_limits = {}
        self.set_bias_limit(bias_limit)

    def set_bias_limit(self, value, parameter=None):
        """Count strict absolute-Bias exceedances over all included finite rows."""
        limit = _validated_bias_limit(value)
        if parameter is not None:
            if parameter not in self._mapping_by_name:
                raise ValueError(f"Unknown parameter: {parameter}")
            self.bias_limits[parameter] = limit
        else:
            self.bias_limit = limit
            self.bias_limits.update({m.name: m.bias_limit if m.bias_limit is not None else limit for m in self._mappings})
        counts = []
        for index, mapping in enumerate(self._mappings):
            if parameter is not None and mapping.name != parameter:
                counts.append(self.summary.at[index, "Bias out of range"])
                continue
            bias = self.series(mapping.name)["Bias"].to_numpy(float)
            counts.append(int(np.count_nonzero(np.isfinite(bias) & (np.abs(bias) > self.bias_limits[mapping.name]))))
        self.summary["Bias limit"] = [self.bias_limits[m.name] for m in self._mappings]
        self.summary["Bias unit"] = [parse_unit(mapping.reference_column) for mapping in self._mappings]
        self.summary["Bias out of range"] = counts

    @property
    def parameter_names(self):
        return tuple(mapping.name for mapping in self._mappings)

    def card(self, parameter):
        try:
            return self._cards[parameter]
        except KeyError as error:
            raise ValueError(f"Unknown parameter: {parameter}") from error

    def raw_column(self, parameter):
        """The Raw Data column one parameter is fitted against."""
        try:
            return str(self._mapping_by_name[parameter].raw_column)
        except KeyError as error:
            raise ValueError(f"Unknown parameter: {parameter}") from error

    def series(self, parameter):
        """Return plot/export rows for one parameter without expanding all parameters."""
        try:
            mapping = self._mapping_by_name[parameter]
        except KeyError as error:
            raise ValueError(f"Unknown parameter: {parameter}") from error
        card = self._cards[parameter]
        reference = pd.to_numeric(self._reference[mapping.reference_column], errors="coerce").to_numpy(float)
        raw = pd.to_numeric(self._raw[mapping.raw_column], errors="coerce").to_numpy(float)
        card_value = card.slope * raw + card.intercept
        evaluated = card_value if self.result_mode == "preview" else raw.copy()
        bias = evaluated - reference
        bias_percent = np.full(len(reference), np.nan, dtype=float)
        np.divide(bias * 100.0, reference, out=bias_percent,
                  where=np.isfinite(reference) & (reference != 0))
        selected = bias_percent if self.bias_mode == "percent" else bias
        return pd.DataFrame({
            "Reference": reference,
            "Raw": raw,
            "Card Value": card_value,
            "Evaluated Value": evaluated,
            "Bias": bias,
            "Bias %": bias_percent,
            "Selected Bias": selected,
        }, index=self._reference.index.copy())

    def wafer_summary(self, parameter, wafer_column=None):
        """Fit each Raw Data measurement identity independently, in source order."""
        try:
            mapping = self._mapping_by_name[parameter]
        except KeyError as error:
            raise ValueError(f"Unknown parameter: {parameter}") from error
        source, measurements = self._measurement_groups(wafer_column)
        reference = pd.to_numeric(self._reference[mapping.reference_column], errors="coerce").to_numpy(float)
        raw = pd.to_numeric(self._raw[mapping.raw_column], errors="coerce").to_numpy(float)
        rows = []
        for measurement in measurements:
            mask = np.zeros(len(source), dtype=bool)
            mask[list(measurement.rows)] = True
            valid = mask & np.isfinite(raw) & np.isfinite(reference)
            if valid.sum() >= 2 and np.ptp(raw[valid]) > 0:
                card = _fit_card(
                    raw[valid], reference[valid],
                    f"{parameter} / {measurement.label}",
                )
                slope, intercept, r_squared = card.slope, card.intercept, card.r_squared
            else:
                slope = intercept = r_squared = np.nan
            group_label = "Not grouped"
            if self.group_plan.enabled:
                labels = list(dict.fromkeys(
                    self.group_plan.labels[self.source_rows[row]] for row in measurement.rows
                ))
                group_label = ("Mixed: " if len(labels) > 1 else "") + " / ".join(labels)
            rows.append({
                "Wafer": measurement.label,
                "Group": group_label,
                "Slope": slope,
                "Intercept": intercept,
                "R²": r_squared,
                "Valid pairs": int(valid.sum()),
            })
        return pd.DataFrame(rows, columns=["Wafer", "Group", "Slope", "Intercept", "R²", "Valid pairs"])

    def group_card(self, parameter, key):
        cache_key = (parameter, key)
        if cache_key not in self._group_cards:
            data = self.group_series(parameter, key)
            try:
                self._group_cards[cache_key] = _fit_card(data["Raw"].to_numpy(float),
                                                      data["Reference"].to_numpy(float), parameter)
            except ValueError:
                self._group_cards[cache_key] = None
        return self._group_cards[cache_key]

    def plot_scope(self, rows, *, local_card=False, label=""):
        """One source-aligned plot range, with explicit local/overall calibration."""
        allowed = set(rows)
        positions = [i for i, row in enumerate(self.source_rows) if row in allowed]
        reference, raw = self._reference.iloc[positions], self._raw.iloc[positions]
        fits = {}
        for mapping in self._mappings:
            x = pd.to_numeric(raw[mapping.raw_column], errors="coerce").to_numpy(float)
            y = pd.to_numeric(reference[mapping.reference_column], errors="coerce").to_numpy(float)
            try:
                fits[mapping.name] = _fit_card(x, y, mapping.name)
            except ValueError:
                fits[mapping.name] = Card(np.nan, np.nan, np.nan, int((np.isfinite(x) & np.isfinite(y)).sum()))
        result = MatchAnalysisResult(reference, raw, self._mappings,
                                     fits if local_card else self._cards,
                                     self.result_mode, self.bias_mode, self.match_type, self.bias_limit)
        result.source_rows = tuple(self.source_rows[i] for i in positions)
        result.group_plan = copy(self.group_plan)
        result.group_plan.included_rows = result.source_rows
        result.group_plan.display_rows = tuple(row for row in self.group_plan.display_rows if row in allowed)
        result.group_plan.scope_label = label
        result._group_cards = {}
        result.plot_fits = fits
        for name, limit in self.bias_limits.items():
            result.set_bias_limit(limit, name)
        return result

    def wafer_frames(self, row):
        """Paired sources for exactly the measurement identity in wafer_summary."""
        _, measurements = self._measurement_groups()
        if not 0 <= row < len(measurements):
            raise ValueError("Unknown single-wafer row.")
        indices = list(measurements[row].rows)
        return (self._reference.iloc[indices].reset_index(drop=True).copy(),
                self._raw.iloc[indices].reset_index(drop=True).copy())

    def group_series(self, parameter, key="all", *, trend=False, card_mode="raw"):
        data = self.series(parameter)
        lookup = {row: i for i, row in enumerate(self.source_rows)}
        rows = ([row for span in self.group_plan.trend_spans(key) for row in span["rows"]]
                if trend else self.group_plan.rows(key))
        output = data.iloc[[lookup[row] for row in rows]].copy()
        output["Source row"] = rows
        output["Group"] = [self.group_plan.row_groups[row] for row in rows]
        output["Trend value"] = output["Raw"].to_numpy(float)
        if card_mode == "global":
            output["Trend value"] = output["Card Value"].to_numpy(float)
        elif card_mode == "group":
            output["Trend value"] = np.nan
            for group in dict.fromkeys(output["Group"]):
                card = self.group_card(parameter, group)
                if card is not None:
                    mask = output["Group"] == group
                    output.loc[mask, "Trend value"] = card.slope * output.loc[mask, "Raw"] + card.intercept
        return output

    def group_summary(self, parameter):
        rows = []
        for key in self.group_plan.group_keys:
            data = self.group_series(parameter, key)
            card = self.group_card(parameter, key)
            valid = np.isfinite(data["Raw"]) & np.isfinite(data["Reference"])
            rows.append({"Group": self.group_plan.label(key), "Slope": card.slope if card else np.nan,
                         "Intercept": card.intercept if card else np.nan,
                         "R²": card.r_squared if card else np.nan, "Valid pairs": int(valid.sum()),
                         "Status": "" if card else "Card unavailable: need two distinct valid Raw values"})
        return pd.DataFrame(rows)

    def measurement_ticks(self, wafer_column=None):
        """Return one multi-line Raw Data identity label at each group centre."""
        _source, measurements = self._measurement_groups(wafer_column)
        return tuple(
            (float(np.mean(measurement.rows)) + 1.0, measurement.label)
            for measurement in measurements
            if measurement.rows
        )

    def measurement_spans(self, wafer_column=None):
        """Identity values and contiguous half-edge spans on the plotted row axis."""
        source, measurements = self._measurement_groups(wafer_column)
        spans = []
        for measurement in measurements:
            rows = np.asarray(measurement.rows, dtype=int)
            for run in np.split(rows, np.flatnonzero(np.diff(rows) != 1) + 1):
                if len(run):
                    spans.append((float(run[0]) + .5, float(run[-1]) + 1.5,
                                  wafer_identity_label(source.iloc[run], wafer_column)))
        return sorted(spans)

    def _measurement_groups(self, wafer_column=None):
        source, column = _wafer_groups(self._reference, self._raw, wafer_column)
        names = {_normalized(candidate): candidate for candidate in source.columns}
        lot_column = next(
            (names[name] for name in ("lotid", "lot", "lotno") if name in names),
            None,
        )
        pad_column = next(
            (names[name] for name in ("padname", "pad") if name in names),
            None,
        )
        identity = default_identity_columns(
            source, column, lot_column, pad_column
        )
        measurements = detect_measurements(
            source,
            column,
            identity,
            use_die_seq=False,
        )
        return source, measurements

class MatchWorkbook:
    """One Reference/Raw workbook with analysis and durable `.wkb` persistence."""

    def __init__(self, reference, raw, mappings, match_type="KLA",
                 result_mode="preview", bias_mode="absolute",
                 preview_raw=None, final_raw=None, final_match_raw=None,
                 bias_views=None,
                 setup_splitter_sizes=None, parameter_order=None,
                 preview_map=None, final_map=None,
                 preview_dynamic=None, final_dynamic=None,
                 workspace_selections=None, correlation_selections=None,
                 trend_axis_settings=None, workspace_states=None,
                 workspace_frames=None, test_flags=None, grouping_state=None, bias_limit=.5):
        self.reference = reference
        self.raw = raw
        from ..match_groups import group_state
        self.test_flags = test_flags
        self.grouping_state = group_state(grouping_state)
        self.bias_limit = _validated_bias_limit(bias_limit)
        self.workspace_states = dict(workspace_states or {})
        self.workspace_frames = dict(workspace_frames or {})
        self.preview_raw = preview_raw
        self.final_raw = final_raw
        self.final_match_raw = final_match_raw
        self.preview_map = preview_map
        self.final_map = final_map
        self.preview_dynamic = preview_dynamic
        self.final_dynamic = final_dynamic
        self.workspace_selections = _normalized_workspace_selections(
            workspace_selections
        )
        self.correlation_selections = _normalized_correlation_selections(
            correlation_selections
        )
        self.mappings = tuple(mappings)
        self.match_type = str(match_type).upper()
        self.result_mode = str(result_mode).lower()
        self.trend_axis_settings = _normalized_trend_axis_settings(
            trend_axis_settings, self.correlation_selections, self.result_mode
        )
        for state in self.correlation_selections.values():
            if state is not None:
                state.pop("trend_axis_ratio", None)
                state.pop("trend_axis_mode", None)
        self.bias_mode = str(bias_mode).lower()
        self.bias_views = tuple(
            str(view).lower() for view in (
                (self.bias_mode,) if bias_views is None else bias_views
            )
        )
        self.setup_splitter_sizes = (
            None
            if setup_splitter_sizes is None
            else tuple(int(size) for size in setup_splitter_sizes)
        )
        self.parameter_order = tuple(
            mapping.name for mapping in self.mappings
        ) if parameter_order is None else tuple(str(name) for name in parameter_order)
        self._validate()

    def _validate(self):
        if not isinstance(self.reference, pd.DataFrame) or not isinstance(self.raw, pd.DataFrame):
            raise TypeError("Reference and Raw Data must be pandas DataFrames.")
        if len(self.reference) != len(self.raw):
            raise ValueError("Reference and Raw Data must have the same number of rows for row-order matching.")
        if len(self.reference) > MAX_ROWS:
            raise ValueError(f"A workbook supports at most {MAX_ROWS:,} rows.")
        if not self.reference.columns.is_unique or not self.raw.columns.is_unique:
            raise ValueError("Reference and Raw Data column names must be unique.")
        if _ROW_COLUMN in self.reference.columns or _ROW_COLUMN in self.raw.columns:
            raise ValueError(f"{_ROW_COLUMN!r} is reserved for WKB storage.")
        self._validate_stage_source(self.preview_raw, "Preview FullMap")
        self._validate_stage_source(self.final_raw, "Final Raw Data")
        self._validate_stage_source(self.final_match_raw, "Final Match Raw Data")
        self._validate_workspace_snapshot(self.preview_map, "Preview Map")
        self._validate_workspace_snapshot(self.final_map, "Final Map")
        self._validate_workspace_snapshot(self.preview_dynamic, "Preview Dynamic")
        self._validate_workspace_snapshot(self.final_dynamic, "Final Dynamic")
        if (
            self.final_match_raw is not None
            and len(self.reference) != len(self.final_match_raw)
        ):
            raise ValueError(
                "Reference and Final Raw Data must have the same number of rows "
                "for row-order matching."
            )
        if not self.mappings:
            raise ValueError("Select at least one Reference/Raw parameter mapping.")
        if len(self.mappings) > MAX_PARAMETERS:
            raise ValueError(f"A workbook supports at most {MAX_PARAMETERS} parameters.")
        if len({mapping.name for mapping in self.mappings}) != len(self.mappings):
            raise ValueError("Mapped parameter names must be unique.")
        for mapping in self.mappings:
            if mapping.reference_column not in self.reference.columns:
                raise ValueError(f"Reference column not found: {mapping.reference_column}")
            if mapping.raw_column not in self.raw.columns:
                raise ValueError(f"Raw Data column not found: {mapping.raw_column}")
            for label, frame in (
                ("Preview FullMap", self.preview_raw),
                ("Final Raw Data", self.final_raw),
                ("Final Match Raw Data", self.final_match_raw),
            ):
                if frame is not None and mapping.raw_column not in frame.columns:
                    raise ValueError(
                        f"{label} column not found for {mapping.name}: {mapping.raw_column}"
                    )
        if self.match_type not in _ALLOWED_MATCH_TYPES:
            raise ValueError("Match type must be TEM, NOVA, or KLA.")
        if self.result_mode not in _ALLOWED_RESULT_MODES:
            raise ValueError("Result mode must be preview or final.")
        if self.bias_mode not in _ALLOWED_BIAS_MODES:
            raise ValueError("Bias mode must be absolute or percent.")
        if (
            not self.bias_views
            or len(set(self.bias_views)) != len(self.bias_views)
            or any(view not in _ALLOWED_BIAS_MODES for view in self.bias_views)
        ):
            raise ValueError("Bias views must contain absolute, percent, or both.")
        if self.bias_mode not in self.bias_views:
            raise ValueError("The primary Bias mode must be included in Bias views.")
        if (
            self.setup_splitter_sizes is not None
            and (
                len(self.setup_splitter_sizes) != 3
                or any(size < 0 for size in self.setup_splitter_sizes)
            )
        ):
            raise ValueError("Setup splitter layout must contain three non-negative sizes.")
        mapping_names = tuple(mapping.name for mapping in self.mappings)
        if (
            len(set(self.parameter_order)) != len(self.parameter_order)
            or set(self.parameter_order) != set(mapping_names)
        ):
            raise ValueError("Parameter order must contain every mapped parameter once.")

    @staticmethod
    def _validate_stage_source(frame, label):
        if frame is None:
            return
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{label} must be a pandas DataFrame.")
        if frame.empty:
            raise ValueError(f"{label} must contain at least one data row.")
        if len(frame) > MAX_ROWS:
            raise ValueError(f"{label} supports at most {MAX_ROWS:,} rows.")
        if not frame.columns.is_unique:
            raise ValueError(f"{label} column names must be unique.")
        if _ROW_COLUMN in frame.columns:
            raise ValueError(f"{_ROW_COLUMN!r} is reserved for WKB storage.")

    @staticmethod
    def _validate_workspace_snapshot(frame, label):
        if frame is None:
            return
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{label} must be a pandas DataFrame.")
        if len(frame) > MAX_ROWS:
            raise ValueError(f"{label} supports at most {MAX_ROWS:,} rows.")
        if not frame.columns.is_unique:
            raise ValueError(f"{label} column names must be unique.")
        if _ROW_COLUMN in frame.columns:
            raise ValueError(f"{_ROW_COLUMN!r} is reserved for WKB storage.")

    @staticmethod
    def suggest_mappings(reference, raw):
        """Match `<name> Reference` columns to Raw Data columns by normalized name."""
        raw_names = {}
        for column in raw.columns:
            raw_names.setdefault(_normalized(column), []).append(str(column))
        mappings = []
        for column in reference.columns:
            text = str(column).strip()
            if not text.lower().endswith(" reference"):
                continue
            name = text[:-len(" reference")].strip()
            candidates = raw_names.get(_normalized(name), [])
            if len(candidates) == 1:
                mappings.append(ParameterMapping(name, str(column), candidates[0]))
        return tuple(mappings)

    def analyze(self):
        analysis_raw = (
            self.final_match_raw
            if self.result_mode == "final" and self.final_match_raw is not None
            else self.raw
        )
        from ..match_groups import GroupPlan
        # TEM now shares the same optional Head/Mark grouping as KLA and NOVA.
        state = self.grouping_state
        flags = self.test_flags
        plan = GroupPlan(analysis_raw, flags, state, self.reference)
        if (plan.enabled or state.get("data_selection") is not None) and self.result_mode == "final" and self.final_match_raw is not None:
            from ..match_groups import row_ids
            if row_ids(self.raw) != row_ids(analysis_raw):
                raise ValueError("Preview/Final source identities differ; classifications cannot be shared by row count alone.")
        if not plan.included_rows and plan.state["data_selection"] is None:
            raise ValueError("No paired records pass the current filters.")
        reference_frame = self.reference.iloc[list(plan.included_rows)]
        analysis_raw = analysis_raw.iloc[list(plan.included_rows)]
        cards = {}
        for mapping in self.mappings:
            reference = pd.to_numeric(reference_frame[mapping.reference_column], errors="coerce").to_numpy(float)
            raw = pd.to_numeric(analysis_raw[mapping.raw_column], errors="coerce").to_numpy(float)
            try:
                cards[mapping.name] = _fit_card(raw, reference, mapping.name)
            except ValueError:
                if plan.state["data_selection"] is None:
                    raise
                cards[mapping.name] = Card(np.nan, np.nan, np.nan, int((np.isfinite(raw) & np.isfinite(reference)).sum()))
        result = MatchAnalysisResult(
            reference_frame, analysis_raw, self.mappings, cards,
            self.result_mode, self.bias_mode, self.match_type, self.bias_limit,
        )
        result.group_plan = plan
        result.source_rows = plan.included_rows
        result._group_cards = {}
        return result

    def participating_frame(self, frame, *, paired_source=False, apply_selection=True):
        """Project traceable Workbook rows; never position-match independent data."""
        from ..match_groups import applied_state, participation_rows, participation_source_keys
        selection = applied_state(self.grouping_state)["data_selection"]
        if selection is None or not apply_selection:
            return frame.reset_index(drop=True).copy()
        source = self.final_match_raw if self.result_mode == "final" and self.final_match_raw is not None else self.raw
        keys = participation_source_keys(source)
        allowed = set(participation_rows(source, selection))
        if paired_source:
            return frame.iloc[sorted(allowed)].reset_index(drop=True).copy()
        excluded = {key for i, key in enumerate(keys) if i not in allowed}
        # Identity columns, including duplicate occurrences, are preserved by
        # the derived KLA/NOVA data. Independent TEM tables are not this source.
        if self.match_type == "TEM":
            return frame.reset_index(drop=True).copy()
        if not any("".join(c.lower() for c in str(column) if c.isalnum()) in ("waferid", "cursmefilepath") for column in source) and not frame.equals(source):
            return frame.reset_index(drop=True).copy()
        return frame.iloc[[i for i, key in enumerate(participation_source_keys(frame)) if key not in excluded]].reset_index(drop=True).copy()

    def stage_frame(self, stage, *, apply_card=None, apply_selection=True):
        """Build map-ready Preview or Final rows while preserving wafer metadata.

        ``apply_card`` defaults to the stage's historical behaviour: Preview
        runs every mapped parameter through its Card, Final uses the table as
        it was pasted. Passing ``apply_card=False`` returns the untouched
        measurement values so a workspace can offer the Card as a choice.
        """
        stage = str(stage).lower()
        if stage not in _ALLOWED_RESULT_MODES:
            raise ValueError("Stage must be preview or final.")
        if apply_card is None:
            apply_card = stage == "preview"
        snapshot = self.preview_map if stage == "preview" else self.final_map
        if snapshot is not None:
            return self.participating_frame(snapshot, apply_selection=apply_selection)
        source = self.preview_raw if stage == "preview" else self.final_raw
        if source is None:
            if self.match_type == "TEM":
                return pd.DataFrame()
            source = (
                self.final_match_raw
                if stage == "final" and self.final_match_raw is not None
                else self.raw
            )
        frame = source.reset_index(drop=True).copy()
        result = self.analyze() if apply_card else None
        for mapping in self.mappings:
            if mapping.raw_column not in frame.columns:
                raise ValueError(
                    f"{stage.title()} data column not found for {mapping.name}: "
                    f"{mapping.raw_column}"
                )
            values = pd.to_numeric(frame[mapping.raw_column], errors="coerce").to_numpy(float)
            if apply_card:
                card = result.card(mapping.name)
                values = card.slope * values + card.intercept
            frame[mapping.name] = values
            if mapping.name != mapping.raw_column:
                frame.drop(columns=[mapping.raw_column], inplace=True)
        return self.participating_frame(
            frame,
            paired_source=source is self.raw or source is self.final_match_raw,
            apply_selection=apply_selection,
        )

    def parameter_cards(self):
        """Return the fitted Card of every mapping as {(name): (slope, intercept)}."""
        result = self.analyze()
        return {
            mapping.name: (
                result.card(mapping.name).slope,
                result.card(mapping.name).intercept,
            )
            for mapping in self.mappings
        }

    def dynamic_frame(self, stage, *, apply_card=None, apply_selection=True):
        """Return the stage's saved Dynamic table or its stage-data default."""
        stage = str(stage).lower()
        if stage not in _ALLOWED_RESULT_MODES:
            raise ValueError("Stage must be preview or final.")
        snapshot = (
            self.preview_dynamic if stage == "preview" else self.final_dynamic
        )
        if snapshot is not None:
            return self.participating_frame(snapshot, apply_selection=apply_selection)
        return self.stage_frame(stage, apply_card=apply_card, apply_selection=apply_selection)

    def to_snapshot(self):
        from ..workspace_store import WorkspaceSnapshot
        frames = {"reference": self.reference, "raw": self.raw}
        if self.test_flags is not None:
            frames["test_flags"] = self.test_flags
        for name in ("preview_raw", "final_raw", "final_match_raw", "preview_map",
                     "final_map", "preview_dynamic", "final_dynamic"):
            frame = getattr(self, name)
            if frame is not None:
                frames[name] = frame
        frames.update(self.workspace_frames)
        state = {name: getattr(self, name) for name in (
            "match_type", "result_mode", "bias_mode", "bias_views",
            "setup_splitter_sizes", "parameter_order", "workspace_selections",
            "correlation_selections", "trend_axis_settings", "grouping_state", "bias_limit")}
        state["mappings"] = [
            asdict(m)
            for m in self.mappings
        ]
        return WorkspaceSnapshot("match_workbook", frames, {"match": state, **self.workspace_states})

    def save(self, path):
        from ..workspace_store import save_workspace
        return save_workspace(path, self.to_snapshot())

    @classmethod
    def from_snapshot(cls, snapshot):
        if snapshot.workspace_type != "match_workbook":
            raise ValueError("This WKB is not a Match Workbook.")
        state = dict(snapshot.states["match"])
        state.pop("draft", None)
        state["mappings"] = tuple(ParameterMapping(**record) for record in state["mappings"])
        names = ("reference", "raw", "test_flags", "preview_raw", "final_raw", "final_match_raw",
                 "preview_map", "final_map", "preview_dynamic", "final_dynamic")
        frames = {name: snapshot.frames[name] for name in names if name in snapshot.frames}
        return cls(**frames, **state,
                   workspace_states={key: value for key, value in snapshot.states.items() if key != "match"},
                   workspace_frames={key: value for key, value in snapshot.frames.items() if key not in names})

    @classmethod
    def load(cls, path):
        from ..workspace_store import load_workspace
        return cls.from_snapshot(load_workspace(path, expected_type="match_workbook"))

    @classmethod
    def _load_legacy(cls, path):
        source = Path(path)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            try:
                metadata = pd.read_sql_query("SELECT * FROM metadata LIMIT 1", connection).iloc[0]
            except (sqlite3.DatabaseError, IndexError, pd.errors.DatabaseError) as error:
                raise ValueError("This file is not a valid Matching Workbook (WKB).") from error
            schema_version = int(metadata["schema_version"])
            if schema_version not in set(range(1, SCHEMA_VERSION + 1)):
                raise ValueError(
                    f"Unsupported WKB schema {metadata['schema_version']}; "
                    f"expected 1 through {SCHEMA_VERSION}."
                )
            mapping_rows = pd.read_sql_query(
                "SELECT name, reference_column, raw_column FROM parameter_mappings ORDER BY position",
                connection,
            )
            reference = _read_frame(connection, "reference_data")
            raw = _read_frame(connection, "raw_data")
            preview_raw = (
                _read_frame(connection, "preview_raw_data")
                if schema_version >= 2 and _table_exists(connection, "preview_raw_data")
                else None
            )
            final_raw = (
                _read_frame(connection, "final_raw_data")
                if schema_version >= 2 and _table_exists(connection, "final_raw_data")
                else None
            )
            final_match_raw = (
                _read_frame(connection, "final_match_raw_data")
                if schema_version >= 3
                and _table_exists(connection, "final_match_raw_data")
                else None
            )
            preview_map = (
                _read_frame(connection, "preview_map_data")
                if schema_version >= 4 and _table_exists(connection, "preview_map_data")
                else None
            )
            final_map = (
                _read_frame(connection, "final_map_data")
                if schema_version >= 4 and _table_exists(connection, "final_map_data")
                else None
            )
            preview_dynamic = (
                _read_frame(connection, "preview_dynamic_data")
                if schema_version >= 5
                and _table_exists(connection, "preview_dynamic_data")
                else None
            )
            final_dynamic = (
                _read_frame(connection, "final_dynamic_data")
                if schema_version >= 5
                and _table_exists(connection, "final_dynamic_data")
                else None
            )
        mappings = tuple(ParameterMapping(row.name, row.reference_column, row.raw_column)
                         for row in mapping_rows.itertuples(index=False))
        saved_bias_views = (
            str(metadata["bias_views"]).split(",")
            if "bias_views" in metadata.index
            and pd.notna(metadata["bias_views"])
            and str(metadata["bias_views"]).strip()
            else None
        )
        saved_splitter_sizes = None
        if (
            "setup_splitter_sizes" in metadata.index
            and pd.notna(metadata["setup_splitter_sizes"])
            and str(metadata["setup_splitter_sizes"]).strip()
        ):
            try:
                saved_splitter_sizes = tuple(
                    int(size)
                    for size in str(metadata["setup_splitter_sizes"]).split(",")
                )
            except ValueError as error:
                raise ValueError(
                    "This Matching Workbook has an invalid saved layout."
                ) from error
        saved_parameter_order = None
        if (
            "parameter_order" in metadata.index
            and pd.notna(metadata["parameter_order"])
            and str(metadata["parameter_order"]).strip()
        ):
            try:
                saved_parameter_order = tuple(
                    str(name) for name in json.loads(metadata["parameter_order"])
                )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    "This Matching Workbook has an invalid saved parameter order."
                ) from error
        saved_workspace_selections = None
        if (
            schema_version >= 6
            and "workspace_selections" in metadata.index
            and pd.notna(metadata["workspace_selections"])
            and str(metadata["workspace_selections"]).strip()
        ):
            try:
                saved_workspace_selections = json.loads(
                    metadata["workspace_selections"]
                )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    "This Matching Workbook has invalid workspace selections."
                ) from error
        saved_correlation_selections = None
        if (
            schema_version >= 9
            and "correlation_selections" in metadata.index
            and pd.notna(metadata["correlation_selections"])
            and str(metadata["correlation_selections"]).strip()
        ):
            try:
                saved_correlation_selections = json.loads(
                    metadata["correlation_selections"]
                )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    "This Matching Workbook has invalid Correlation/Trend selections."
                ) from error
        saved_trend_axis_settings = None
        if (
            "trend_axis_settings" in metadata.index
            and pd.notna(metadata["trend_axis_settings"])
            and str(metadata["trend_axis_settings"]).strip()
        ):
            try:
                saved_trend_axis_settings = json.loads(metadata["trend_axis_settings"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "This Matching Workbook has invalid Trend axis settings."
                ) from error
        return cls(
            reference=reference,
            raw=raw,
            mappings=mappings,
            match_type=metadata["match_type"],
            result_mode=metadata["result_mode"],
            bias_mode=metadata["bias_mode"],
            bias_views=saved_bias_views,
            preview_raw=preview_raw,
            final_raw=final_raw,
            final_match_raw=final_match_raw,
            preview_map=preview_map,
            final_map=final_map,
            preview_dynamic=preview_dynamic,
            final_dynamic=final_dynamic,
            setup_splitter_sizes=saved_splitter_sizes,
            parameter_order=saved_parameter_order,
            workspace_selections=saved_workspace_selections,
            correlation_selections=saved_correlation_selections,
            trend_axis_settings=saved_trend_axis_settings,
        )


def _wafer_groups(reference, raw, requested=None):
    if requested:
        if requested in raw.columns:
            return raw, requested
        if requested in reference.columns:
            return reference, requested
        raise ValueError(f"Wafer column not found: {requested}")
    preferred = {"waferid", "wafer"}
    for frame in (raw, reference):
        for column in frame.columns:
            if _normalized(column) in preferred:
                return frame, column
    raise ValueError("No Wafer ID column was found for single-wafer metrics.")

def _normalized(value):
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _fit_card(raw, reference, parameter):
    valid = np.isfinite(raw) & np.isfinite(reference)
    x, y = raw[valid], reference[valid]
    if len(x) < 2:
        raise ValueError(f"{parameter}: at least two numeric Reference/Raw pairs are required.")
    x_delta = x - x.mean()
    denominator = float(np.dot(x_delta, x_delta))
    if denominator == 0:
        raise ValueError(f"{parameter}: Raw Data values must not all be identical.")
    y_mean = float(y.mean())
    slope = float(np.dot(x_delta, y - y_mean) / denominator)
    intercept = float(y_mean - slope * x.mean())
    fitted = slope * x + intercept
    residual_sum = float(np.dot(y - fitted, y - fitted))
    total_sum = float(np.dot(y - y_mean, y - y_mean))
    r_squared = float(1.0 - residual_sum / total_sum) if total_sum else np.nan
    if np.isfinite(r_squared) and abs(r_squared - 1.0) < 1e-14:
        r_squared = 1.0
    return Card(slope, intercept, r_squared, int(valid.sum()))


def _write_frame(connection, table, frame):
    stored = frame.reset_index(drop=True).copy()
    stored.insert(0, _ROW_COLUMN, np.arange(len(stored), dtype=np.int64))
    stored.to_sql(table, connection, index=False, if_exists="replace", chunksize=2_000)


def _read_frame(connection, table):
    frame = pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY "{_ROW_COLUMN}"', connection)
    return frame.drop(columns=[_ROW_COLUMN])


def _table_exists(connection, table):
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


__all__ = [
    "Card", "MAX_PARAMETERS", "MAX_ROWS", "MatchAnalysisResult",
    "MatchWorkbook", "ParameterMapping", "SCHEMA_VERSION",
]

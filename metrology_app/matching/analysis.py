"""Deep module for row-aligned Reference/Raw card matching workflows."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import numpy as np
import pandas as pd

from ..measurements import default_identity_columns, detect_measurements


SCHEMA_VERSION = 8
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


@dataclass(frozen=True, slots=True)
class ParameterMapping:
    """One named Reference column paired with one Raw Data column."""

    name: str
    reference_column: str
    raw_column: str

    def __post_init__(self):
        if not all(str(value).strip() for value in (self.name, self.reference_column, self.raw_column)):
            raise ValueError("Parameter mapping names and columns cannot be blank.")


@dataclass(frozen=True, slots=True)
class Card:
    """Linear calibration fitted as Reference = slope × Raw + intercept."""

    slope: float
    intercept: float
    r_squared: float
    valid_pairs: int


class MatchAnalysisResult:
    """Compact result; materialize derived rows for only the selected parameter."""

    def __init__(self, reference, raw, mappings, cards, result_mode, bias_mode, match_type):
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

    @property
    def parameter_names(self):
        return tuple(mapping.name for mapping in self._mappings)

    def card(self, parameter):
        try:
            return self._cards[parameter]
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
            rows.append({
                "Wafer": measurement.label,
                "Slope": slope,
                "Intercept": intercept,
                "R²": r_squared,
                "Valid pairs": int(valid.sum()),
            })
        return pd.DataFrame(rows, columns=["Wafer", "Slope", "Intercept", "R²", "Valid pairs"])

    def measurement_ticks(self, wafer_column=None):
        """Return one multi-line Raw Data identity label at each group centre."""
        _source, measurements = self._measurement_groups(wafer_column)
        return tuple(
            (float(np.mean(measurement.rows)) + 1.0, measurement.label)
            for measurement in measurements
            if measurement.rows
        )

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
                 workspace_selections=None):
        self.reference = reference
        self.raw = raw
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
        self.mappings = tuple(mappings)
        self.match_type = str(match_type).upper()
        self.result_mode = str(result_mode).lower()
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
        cards = {}
        for mapping in self.mappings:
            reference = pd.to_numeric(self.reference[mapping.reference_column], errors="coerce").to_numpy(float)
            raw = pd.to_numeric(analysis_raw[mapping.raw_column], errors="coerce").to_numpy(float)
            cards[mapping.name] = _fit_card(raw, reference, mapping.name)
        return MatchAnalysisResult(
            self.reference, analysis_raw, self.mappings, cards,
            self.result_mode, self.bias_mode, self.match_type,
        )

    def stage_frame(self, stage):
        """Build map-ready Preview or Final rows while preserving wafer metadata."""
        stage = str(stage).lower()
        if stage not in _ALLOWED_RESULT_MODES:
            raise ValueError("Stage must be preview or final.")
        snapshot = self.preview_map if stage == "preview" else self.final_map
        if snapshot is not None:
            return snapshot.reset_index(drop=True).copy()
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
        result = self.analyze() if stage == "preview" else None
        for mapping in self.mappings:
            if mapping.raw_column not in frame.columns:
                raise ValueError(
                    f"{stage.title()} data column not found for {mapping.name}: "
                    f"{mapping.raw_column}"
                )
            values = pd.to_numeric(frame[mapping.raw_column], errors="coerce").to_numpy(float)
            if stage == "preview":
                card = result.card(mapping.name)
                values = card.slope * values + card.intercept
            frame[mapping.name] = values
            if mapping.name != mapping.raw_column:
                frame.drop(columns=[mapping.raw_column], inplace=True)
        return frame

    def dynamic_frame(self, stage):
        """Return the stage's saved Dynamic table or its stage-data default."""
        stage = str(stage).lower()
        if stage not in _ALLOWED_RESULT_MODES:
            raise ValueError("Stage must be preview or final.")
        snapshot = (
            self.preview_dynamic if stage == "preview" else self.final_dynamic
        )
        if snapshot is not None:
            return snapshot.reset_index(drop=True).copy()
        return self.stage_frame(stage)

    def save(self, path):
        """Atomically save source tables and settings in a SQLite-backed WKB file."""
        target = Path(path)
        if target.suffix.lower() != ".wkb":
            target = target.with_suffix(".wkb")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(prefix=f".{target.stem}-", suffix=".tmp",
                                             dir=target.parent, delete=False)
        temporary = Path(handle.name)
        handle.close()
        try:
            with closing(sqlite3.connect(temporary)) as connection, connection:
                connection.execute("PRAGMA journal_mode=OFF")
                connection.execute("PRAGMA synchronous=OFF")
                metadata = pd.DataFrame([{
                    "schema_version": SCHEMA_VERSION,
                    "match_type": self.match_type,
                    "result_mode": self.result_mode,
                    "bias_mode": self.bias_mode,
                    "bias_views": ",".join(self.bias_views),
                    "setup_splitter_sizes": (
                        None
                        if self.setup_splitter_sizes is None
                        else ",".join(str(size) for size in self.setup_splitter_sizes)
                    ),
                    "parameter_order": json.dumps(
                        self.parameter_order, ensure_ascii=False
                    ),
                    "workspace_selections": json.dumps(
                        self.workspace_selections, ensure_ascii=False
                    ),
                    "saved_utc": datetime.now(timezone.utc).isoformat(),
                }])
                metadata.to_sql("metadata", connection, index=False, if_exists="replace")
                pd.DataFrame([
                    {
                        "position": position,
                        "name": mapping.name,
                        "reference_column": mapping.reference_column,
                        "raw_column": mapping.raw_column,
                    }
                    for position, mapping in enumerate(self.mappings)
                ]).to_sql("parameter_mappings", connection, index=False, if_exists="replace")
                _write_frame(connection, "reference_data", self.reference)
                _write_frame(connection, "raw_data", self.raw)
                if self.preview_raw is not None:
                    _write_frame(connection, "preview_raw_data", self.preview_raw)
                if self.final_raw is not None:
                    _write_frame(connection, "final_raw_data", self.final_raw)
                if self.final_match_raw is not None:
                    _write_frame(
                        connection,
                        "final_match_raw_data",
                        self.final_match_raw,
                    )
                if self.preview_map is not None:
                    _write_frame(connection, "preview_map_data", self.preview_map)
                if self.final_map is not None:
                    _write_frame(connection, "final_map_data", self.final_map)
                if self.preview_dynamic is not None:
                    _write_frame(
                        connection, "preview_dynamic_data", self.preview_dynamic
                    )
                if self.final_dynamic is not None:
                    _write_frame(
                        connection, "final_dynamic_data", self.final_dynamic
                    )
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    @classmethod
    def load(cls, path):
        source = Path(path)
        with closing(sqlite3.connect(source)) as connection:
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

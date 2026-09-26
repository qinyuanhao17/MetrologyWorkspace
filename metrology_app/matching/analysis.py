"""Deep module for row-aligned Reference/Raw card matching workflows."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile

import numpy as np
import pandas as pd


SCHEMA_VERSION = 1
MAX_ROWS = 100_000
MAX_PARAMETERS = 50
_ALLOWED_MATCH_TYPES = {"TEM", "NOVA", "KLA"}
_ALLOWED_RESULT_MODES = {"preview", "final"}
_ALLOWED_BIAS_MODES = {"absolute", "percent"}
_ROW_COLUMN = "__wkb_row__"


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
        """Fit Reference against Raw independently for each wafer, in source order."""
        try:
            mapping = self._mapping_by_name[parameter]
        except KeyError as error:
            raise ValueError(f"Unknown parameter: {parameter}") from error
        source, column = _wafer_groups(self._reference, self._raw, wafer_column)
        groups = source[column].fillna("").astype(str).to_numpy()
        reference = pd.to_numeric(self._reference[mapping.reference_column], errors="coerce").to_numpy(float)
        raw = pd.to_numeric(self._raw[mapping.raw_column], errors="coerce").to_numpy(float)
        rows = []
        for wafer in pd.unique(groups):
            if not wafer.strip():
                continue
            mask = groups == wafer
            valid = mask & np.isfinite(raw) & np.isfinite(reference)
            if valid.sum() >= 2 and np.ptp(raw[valid]) > 0:
                card = _fit_card(raw[valid], reference[valid], f"{parameter} / {wafer}")
                slope, intercept, r_squared = card.slope, card.intercept, card.r_squared
            else:
                slope = intercept = r_squared = np.nan
            rows.append({
                "Wafer": wafer,
                "Slope": slope,
                "Intercept": intercept,
                "R²": r_squared,
                "Valid pairs": int(valid.sum()),
            })
        return pd.DataFrame(rows, columns=["Wafer", "Slope", "Intercept", "R²", "Valid pairs"])

class MatchWorkbook:
    """One Reference/Raw workbook with analysis and durable `.wkb` persistence."""

    def __init__(self, reference, raw, mappings, match_type="KLA",
                 result_mode="preview", bias_mode="absolute"):
        self.reference = reference
        self.raw = raw
        self.mappings = tuple(mappings)
        self.match_type = str(match_type).upper()
        self.result_mode = str(result_mode).lower()
        self.bias_mode = str(bias_mode).lower()
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
        if self.match_type not in _ALLOWED_MATCH_TYPES:
            raise ValueError("Match type must be TEM, NOVA, or KLA.")
        if self.result_mode not in _ALLOWED_RESULT_MODES:
            raise ValueError("Result mode must be preview or final.")
        if self.bias_mode not in _ALLOWED_BIAS_MODES:
            raise ValueError("Bias mode must be absolute or percent.")

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
        cards = {}
        for mapping in self.mappings:
            reference = pd.to_numeric(self.reference[mapping.reference_column], errors="coerce").to_numpy(float)
            raw = pd.to_numeric(self.raw[mapping.raw_column], errors="coerce").to_numpy(float)
            cards[mapping.name] = _fit_card(raw, reference, mapping.name)
        return MatchAnalysisResult(
            self.reference, self.raw, self.mappings, cards,
            self.result_mode, self.bias_mode, self.match_type,
        )

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
            if int(metadata["schema_version"]) != SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported WKB schema {metadata['schema_version']}; expected {SCHEMA_VERSION}."
                )
            mapping_rows = pd.read_sql_query(
                "SELECT name, reference_column, raw_column FROM parameter_mappings ORDER BY position",
                connection,
            )
            reference = _read_frame(connection, "reference_data")
            raw = _read_frame(connection, "raw_data")
        mappings = tuple(ParameterMapping(row.name, row.reference_column, row.raw_column)
                         for row in mapping_rows.itertuples(index=False))
        return cls(
            reference=reference,
            raw=raw,
            mappings=mappings,
            match_type=metadata["match_type"],
            result_mode=metadata["result_mode"],
            bias_mode=metadata["bias_mode"],
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


__all__ = [
    "Card", "MAX_PARAMETERS", "MAX_ROWS", "MatchAnalysisResult",
    "MatchWorkbook", "ParameterMapping", "SCHEMA_VERSION",
]
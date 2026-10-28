"""Immutable literal tables for normalized source records, without Qt state.

Columns contain source strings, never inferred numbers. Versions own immutable
tuples and may share unchanged columns. Mutable pandas objects are materialized
at the boundary, not retained in Undo history or shared between GUI owners.
"""
from dataclasses import dataclass, field
from itertools import chain, product
from math import isfinite
from operator import index

import numpy as np
import pandas as pd


def _freeze(value):
    if value is None or type(value) in (str, bool, int):
        return 'scalar', value
    if type(value) is float and isfinite(value):
        return 'scalar', value
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return 'dict', tuple((key, _freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return ('list' if isinstance(value, list) else 'tuple'), tuple(map(_freeze, value))
    raise TypeError('Table-version metadata must have an immutable literal representation')


def _thaw(value):
    kind, items = value
    if kind == 'scalar':
        return items
    if kind == 'dict':
        return {key: _thaw(item) for key, item in items}
    return (list if kind == 'list' else tuple)(map(_thaw, items))


def _strings(values):
    values = tuple(values)
    if not all(map(str.__instancecheck__, values)):
        raise TypeError('Normalize source values to literal strings before creating a version')
    return values


@dataclass(frozen=True, slots=True, eq=False)
class LiteralTableVersion:
    headers: tuple[str, ...]
    columns: tuple[tuple[str, ...], ...]
    _attributes: object = field(default_factory=dict, repr=False)
    _empty_range_columns: bool = field(default=False, repr=False)
    _dense: bool = field(init=False, repr=False)

    def __post_init__(self):
        headers = _strings(self.headers)
        columns = tuple(_strings(column) for column in self.columns)
        if len(headers) != len(columns) or len({len(column) for column in columns}) > 1:
            raise ValueError('Every literal column must have the same record extent')
        object.__setattr__(self, 'headers', headers)
        object.__setattr__(self, 'columns', columns)
        object.__setattr__(self, '_attributes', _freeze(self._attributes))
        object.__setattr__(self, '_dense', bool(headers) and all(headers)
                           and all(all(column) for column in columns))

    @classmethod
    def from_frame(cls, frame):
        if (not isinstance(frame.index, pd.RangeIndex) or frame.index.start != 0
                or frame.index.step != 1 or frame.index.name is not None
                or frame.columns.name is not None or (len(frame) and not len(frame.columns))):
            raise ValueError('Normalize source record positions explicitly before creating a version')
        return cls(tuple(frame.columns),
                   tuple(tuple(frame.iloc[:, column].to_numpy()) for column in range(len(frame.columns))),
                   dict(frame.attrs), isinstance(frame.columns, pd.RangeIndex))

    @property
    def row_count(self):
        return len(self.columns[0]) if self.columns else 0

    @property
    def dense(self):
        """Every rectangular cell, including headers, has a nonempty string."""
        return self._dense

    def cell(self, row, column):
        row, column = index(row), index(column)
        if not 0 <= row <= self.row_count or not 0 <= column < len(self.headers):
            raise KeyError((row, column))
        return self.headers[column] if row == 0 else self.columns[column][row - 1]

    def to_frame(self):
        values = np.empty((self.row_count, len(self.headers)), dtype=object)
        for column, data in enumerate(self.columns):
            values[:, column] = data
        columns = pd.RangeIndex(0) if not self.headers and self._empty_range_columns else self.headers
        frame = pd.DataFrame(values, columns=columns, copy=False)
        frame.attrs = _thaw(self._attributes)
        return frame

    def _matches_metadata(self, frame):
        if (frame.shape != (self.row_count, len(self.headers))
                or tuple(frame.columns) != self.headers
                or not isinstance(frame.index, pd.RangeIndex)
                or frame.index.start != 0 or frame.index.step != 1
                or frame.index.name is not None or frame.columns.name is not None):
            return False
        try:
            if _freeze(frame.attrs) != self._attributes:
                return False
        except (TypeError, ValueError):
            return False
        return True

    def matches_frame(self, frame):
        """Prove a mutable input still represents this exact source version."""
        if not self._matches_metadata(frame):
            return False
        return all(np.array_equal(frame.iloc[:, position].to_numpy(), np.asarray(column, dtype=object))
                   for position, column in enumerate(self.columns))

    def cell_items(self):
        keys = product(range(self.row_count + 1), range(len(self.headers)))
        values = chain(self.headers, chain.from_iterable(zip(*self.columns)))
        return zip(keys, values)

    def to_cells(self):
        cells = (dict(self.cell_items()) if self.dense
                 else {key: value for key, value in self.cell_items() if value})
        if self.row_count:
            cells.setdefault((self.row_count, 0), '')
        return cells

    def replace_columns(self, updates):
        columns = list(self.columns)
        changed = False
        for position, data in updates.items():
            position = index(position)
            if not 0 <= position < len(columns):
                raise KeyError(position)
            values = _strings(data)
            if len(values) != self.row_count:
                raise ValueError('A column replacement cannot change record extent')
            if values != columns[position]:
                columns[position] = values
                changed = True
        if not changed:
            return self
        # Both old and replacement columns have already been validated and
        # frozen. No full-table copy or revalidation is needed for this fork.
        result = object.__new__(type(self))
        object.__setattr__(result, 'headers', self.headers)
        object.__setattr__(result, 'columns', tuple(columns))
        object.__setattr__(result, '_attributes', self._attributes)
        object.__setattr__(result, '_empty_range_columns', self._empty_range_columns)
        object.__setattr__(result, '_dense', bool(self.headers) and all(self.headers)
                           and all(all(column) for column in columns))
        return result

    def replace_cells(self, changes):
        grouped = {}
        for (row, column), value in changes.items():
            row, column = index(row), index(column)
            if row == 0:
                raise ValueError('Header changes require the full table path')
            self.cell(row, column)  # Reject changes outside the existing source.
            if not isinstance(value, str):
                raise TypeError('Cell replacements must retain literal strings')
            values = grouped.get(column)
            if values is None:
                values = grouped[column] = list(self.columns[column])
            values[row - 1] = value
        return self.replace_columns(grouped)


@dataclass(frozen=True, slots=True, eq=False)
class LiteralFrameSource:
    """Short-lived proof from a model's current immutable document view.

    Only SheetModel creates this from its version-backed cache. It never lives
    in a table version or Undo command. Detached/mutated frames keep the full
    literal comparison; matching a region alone cannot prove another version.
    """
    version: LiteralTableVersion
    frame: pd.DataFrame = field(repr=False)
    _values: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        values = self.frame.to_numpy(copy=False)
        if values.flags.writeable or not self.version._matches_metadata(self.frame):
            raise ValueError('A source proof requires a readonly version-backed model view')
        object.__setattr__(self, '_values', values)

    def matches(self, frame, version):
        if version is not self.version or not version._matches_metadata(frame):
            return False
        values = frame.to_numpy(copy=False)
        return (not values.flags.writeable and values.shape == self._values.shape
                and values.dtype == self._values.dtype and values.strides == self._values.strides
                and values.__array_interface__['data'][0]
                == self._values.__array_interface__['data'][0])

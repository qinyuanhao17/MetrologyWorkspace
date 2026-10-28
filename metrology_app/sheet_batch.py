"""Owned column deltas for same-structure clipboard transactions.

Strings and row positions are immutable. The mapping views retain the existing
cell-coordinate contract without storing several large per-cell dictionaries.
This module neither owns a Qt model nor publishes document state.
"""
from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import chain, product
from operator import index
from types import MappingProxyType

import numpy as np

from .metadata_locks import is_metadata_column


@dataclass(frozen=True, slots=True)
class ColumnDelta:
    column: int
    rows: range | tuple[int, ...]
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True, eq=False)
class ColumnChanges(Mapping):
    parts: tuple[ColumnDelta, ...]
    side: str
    data_row_count: int
    _columns: Mapping = field(init=False, repr=False)
    _count: int = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, '_columns', MappingProxyType({p.column: p for p in self.parts}))
        object.__setattr__(self, '_count', sum(len(p.rows) for p in self.parts))

    def __len__(self):
        return self._count

    def __iter__(self):
        for part in self.parts:
            yield from product(part.rows, (part.column,))

    def __getitem__(self, key):
        try:
            row, column = key
            row, column = index(row), index(column)
        except (TypeError, ValueError):
            raise KeyError(key) from None
        part = self._columns[column]
        position = bisect_left(part.rows, row)
        if position == len(part.rows) or part.rows[position] != row:
            raise KeyError(key)
        if self.side == 'pairs':
            return part.before[position], part.after[position]
        return (part.before if self.side == 'before' else part.after)[position]

    @property
    def bounds(self):
        return (min(p.rows[0] for p in self.parts), min(p.column for p in self.parts),
                max(p.rows[-1] for p in self.parts), max(p.column for p in self.parts))

    def update_cells(self, cells):
        if self.parts and all(p.rows == self.parts[0].rows for p in self.parts):
            # Match the row-major cell dictionary's locality. Both the keys
            # and values are streamed by C iterators, not retained per cell.
            columns = tuple(p.column for p in self.parts)
            values = tuple(p.before if self.side == 'before' else p.after for p in self.parts)
            cells.update(zip(product(self.parts[0].rows, columns), chain.from_iterable(zip(*values))))
            return
        for part in self.parts:
            values = part.before if self.side == 'before' else part.after
            cells.update(zip(product(part.rows, (part.column,)), values))

    def frame_updates(self, document):
        """Prove the owned cache is at the expected side, or request fallback."""
        if document is None:
            return None
        updates = {}
        for part in self.parts:
            if part.column >= len(document.columns) or part.rows[-1] > len(document):
                return None
            rows = (np.arange(part.rows.start - 1, part.rows.stop - 1, dtype=np.intp)
                    if isinstance(part.rows, range) else np.asarray(part.rows, dtype=np.intp) - 1)
            current = document.iloc[:, part.column].to_numpy()[rows]
            expected = part.after if self.side == 'before' else part.before
            if not np.array_equal(current, np.asarray(expected, dtype=object)):
                return None
            updates[part.column] = (rows, part.before if self.side == 'before' else part.after)
        return updates


def prepare_column_paste(document, matrix, row, column):
    """Return immutable deltas, or None when general paste semantics are needed."""
    if document is None or not matrix or not document.columns.is_unique:
        return None
    width = len(matrix[0])
    if (not width or len(matrix) * width < 8192 or column < 0 or row < 0
            or column + width > len(document.columns)
            or any(len(line) != width for line in matrix)):
        return None
    if row == 0:
        if tuple(matrix[0]) != tuple(document.columns[column:column + width]):
            return None
        matrix, row = matrix[1:], 1
    if not matrix or row + len(matrix) - 1 > len(document):
        return None
    parts = []
    changed_rows = np.zeros(len(matrix), dtype=bool)
    for offset, values in enumerate(zip(*matrix)):
        target = column + offset
        previous = document.iloc[row - 1:row + len(matrix) - 1, target].to_numpy()
        incoming = np.asarray(values, dtype=object)
        positions = np.flatnonzero(previous != incoming)
        if not len(positions):
            continue
        if target == 0 or is_metadata_column(document.columns[target]):
            return None
        if len(positions) == len(values):
            source_rows = range(row, row + len(values))
            before, after = tuple(previous), values
        else:
            source_rows = tuple(row + int(position) for position in positions)
            before, after = tuple(previous[positions]), tuple(incoming[positions])
        literals = (*before, *after)
        if (not all(map(str.__instancecheck__, literals)) or not all(literals)
                or any(map(str.isspace, literals))):
            return None
        changed_rows[positions] = True
        parts.append(ColumnDelta(target, source_rows, before, after))
    return tuple(parts), int(np.count_nonzero(changed_rows))

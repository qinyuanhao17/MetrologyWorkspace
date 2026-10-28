"""Cell-coordinate compatibility for immutable dense source versions.

Unknown mutations materialize ordinary owned cells and invalidate cached reads.
Sparse tables and general structural edits keep the original dictionary path.
"""
from collections.abc import MutableMapping


class TrackedCells(dict):
    """A real dictionary; reads/serialization retain normal dict semantics."""

    def __init__(self, cells=(), *, changed):
        super().__init__(cells)
        self._changed = changed

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._changed()

    def update(self, *args, **kwargs):
        try:
            super().update(*args, **kwargs)
        finally:
            self._changed()

    def clear(self):
        super().clear()
        self._changed()

    def pop(self, *args):
        try:
            return super().pop(*args)
        finally:
            self._changed()

    def popitem(self):
        result = super().popitem()
        self._changed()
        return result

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default

    def __ior__(self, other):
        self.update(other)
        return self


class VersionCells(MutableMapping):
    """Dense immutable reads; the first direct write drops version ownership."""

    def __init__(self, version, *, changed):
        if not version.dense:
            raise ValueError('Only populated rectangular versions use this cell view')
        self.version = version
        self._changed = changed
        self._cells = None

    def __len__(self):
        return (len(self._cells) if self._cells is not None else
                (self.version.row_count + 1) * len(self.version.headers))

    def __iter__(self):
        return (iter(self._cells) if self._cells is not None else
                (key for key, _ in self.version.cell_items()))

    def __getitem__(self, key):
        if self._cells is not None:
            return self._cells[key]
        try:
            row, column = key
            return self.version.cell(row, column)
        except (TypeError, ValueError):
            raise KeyError(key) from None

    def _writable(self):
        if self._cells is None:
            self._cells = self.version.to_cells()
            self.version = None
        return self._cells

    def __setitem__(self, key, value):
        self._writable()[key] = value
        self._changed()

    def __delitem__(self, key):
        del self._writable()[key]
        self._changed()

    def copy(self):
        return self._cells.copy() if self._cells is not None else self.version.to_cells()

    def clear(self):
        self._cells, self.version = {}, None
        self._changed()

    def update(self, *args, **kwargs):
        try:
            self._writable().update(*args, **kwargs)
        finally:
            self._changed()

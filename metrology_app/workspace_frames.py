"""Immutable, disk-backed unopened spectra. No GUI objects cross this seam."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import weakref


class FrameSource:
    def __init__(self, source, revision, *, pin=True):
        # A private copy also survives external in-place edits, Save As and later
        # backup rotation. Only SQLite page copying, never Python sample strings.
        self.directory = tempfile.TemporaryDirectory(prefix='metrology-spectra-') if pin else None
        if self.directory is not None:
            self._cleanup = weakref.finalize(self,self.directory.cleanup)
        self.path = Path(self.directory.name)/'payload.sqlite' if pin else Path(source)
        if pin:
            shutil.copyfile(source,self.path)
        self.revision = revision


class StoredFrame:
    """Read-only frame reference; copies share immutable bytes, load returns owned cells."""
    def __init__(self, source, table, columns, types, count):
        self.source,self.table = source,table
        self.columns,self.types = tuple(columns),tuple(types)
        self.count = count
        self._loaded = None

    def __len__(self):
        return self.count

    def copy(self, deep=True):
        return self

    def __deepcopy__(self, memo):
        return self

    def load(self):
        if self._loaded is None:
            with closing(sqlite3.connect(self.source.path.as_uri()+'?mode=ro',uri=True)) as connection:
                self._loaded = read_frame(connection,self.table,self.columns,self.types,self.count)
        return self._loaded.copy(deep=True)

    def column_values(self, name):
        """Read one column without materializing unopened spectral sample strings."""
        if name not in self.columns:
            raise KeyError(name)
        if self._loaded is not None:
            return self._loaded[name].tolist()
        column = self.columns.index(name)
        with closing(sqlite3.connect(self.source.path.as_uri()+'?mode=ro',uri=True)) as connection:
            return [row[0] for row in connection.execute(
                f'SELECT "c{column}" FROM "{self.table}" ORDER BY row_order').fetchall()]

    def equals(self, other):
        return frames_equal(self,other)

    def write(self, connection, table):
        """Copy bounded native-fetch batches, retaining literal values and SQL column types."""
        with closing(sqlite3.connect(self.source.path.as_uri()+'?mode=ro',uri=True)) as source:
            schema = source.execute(f'PRAGMA table_info("{self.table}")').fetchall()
            types = [column[2].upper() for column in schema]
            if any(value not in ('TEXT','INTEGER','REAL','TIMESTAMP','BLOB','') for value in types):
                raise ValueError('Unsupported stored spectrum column type.')
            names = ['row_order',*[f'c{i}' for i in range(len(self.columns))]]
            connection.execute(f'CREATE TABLE "{table}" ('+
                               ','.join(f'"{name}" {dtype}' for name,dtype in zip(names,types))+')')
            rows = source.execute(f'SELECT * FROM "{self.table}"')
            statement = f'INSERT INTO "{table}" VALUES ('+','.join('?' for _ in names)+')'
            while batch := rows.fetchmany(32):
                connection.executemany(statement,batch)


def check_frame(connection, table, columns, types, count):
    names = [value[1] for value in connection.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if (type(count) is not int or count<0 or len(types)!=len(columns)
            or names != ['row_order',*[f'c{i}' for i in range(len(columns))]]):
        raise ValueError('Incomplete measurement table schema.')
    rows, distinct, low, high, invalid = connection.execute(
        f'SELECT COUNT(*),COUNT(DISTINCT row_order),MIN(row_order),MAX(row_order),'
        f'SUM(typeof(row_order)!=\'integer\') FROM "{table}"').fetchone()
    if (rows!=count or distinct!=count or (count and (low!=0 or high!=count-1 or invalid))):
        raise ValueError('Incomplete measurement table row order.')


def read_frame(connection, table, columns, types, count):
    import pandas as pd
    # Sorting SQLite rows with huge sample TEXT can spill hundreds of MB into
    # a sort buffer. Fetch payload once; sort only the row references if needed.
    cursor = connection.execute(f'SELECT * FROM "{table}"')
    names = [column[0] for column in cursor.description]
    frame = pd.DataFrame.from_records(cursor.fetchall(),columns=names)
    if (len(frame)!=count or len(types)!=len(columns)
            or names!=['row_order',*[f'c{i}' for i in range(len(columns))]]):
        raise ValueError('Incomplete measurement table.')
    if frame['row_order'].tolist()!=list(range(count)):
        frame = frame.sort_values('row_order',kind='stable').reset_index(drop=True)
        if frame['row_order'].tolist()!=list(range(count)):
            raise ValueError('Incomplete measurement table row order.')
    frame = frame.drop(columns='row_order')
    for index,dtype in enumerate(types):
        frame[frame.columns[index]] = frame.iloc[:,index].astype(dtype)
    frame.columns = columns
    return frame


def frames_equal(first, second):
    if first is second:
        return True
    if len(first)!=len(second) or list(first.columns)!=list(second.columns):
        return False
    if isinstance(first,StoredFrame) and isinstance(second,StoredFrame):
        if (first.source.revision==second.source.revision and first.table==second.table
                and first.columns==second.columns and first.types==second.types and first.count==second.count):
            return True
    if isinstance(first,StoredFrame):
        first = first.load()
    if isinstance(second,StoredFrame):
        second = second.load()
    return first.equals(second)

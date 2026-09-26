"""Read measurement tables and select layers. No GUI or plotting dependencies."""

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd


def number(series):
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def read_table(path=None, *, text=None, sheet=0, dtype=None):
    options = {"dtype": dtype, "keep_default_na": dtype is not str}
    if text is not None:
        if not text.strip():
            raise ValueError("请先复制包含表头的表格。")
        return pd.read_csv(StringIO(text), sep=None, engine="python", **options)
    if Path(path).suffix.lower() == ".xlsx":
        return pd.read_excel(path, sheet_name=sheet, engine="openpyxl", **options)
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding, sep=None, engine="python", **options)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 CSV。")


def inspect_table(frame, wafer_column=None):
    """Recognize headers without requiring a plot-ready table during editing."""
    names = {"".join(ch.lower() for ch in str(c) if ch.isalnum()): c for c in frame}
    wafer_column = wafer_column or next((names[n] for n in ("waferid", "wafer", "waferno") if n in names), None)
    excluded = {"fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey", "dieseq", "dieid",
                "diesequence", "diesequenceno", "lotid", "lot", "lotno", "toolsn", "toolid",
                "padname", "pad", "waferid", "wafer", "waferno"}
    metrics = [c for c in frame if c != wafer_column
               and "".join(ch.lower() for ch in c if ch.isalnum()) not in excluded
               and "path" not in c.lower() and number(frame[c]).notna().any()]
    counts = {}
    if wafer_column in frame:
        ids = frame[wafer_column].fillna("").astype(str).str.strip()
        counts = ids[ids != ""].value_counts(sort=False).to_dict()
    return wafer_column, counts, metrics


@dataclass
class Dataset:
    frame: pd.DataFrame
    source: str

    def __post_init__(self):
        self.frame = self.frame.dropna(how="all").copy()
        self.frame.columns = self.frame.columns.map(lambda s: str(s).strip().lstrip("\ufeff"))
        if self.frame.empty:
            raise ValueError("表格没有数据行。")
        if not self.frame.columns.is_unique:
            raise ValueError("表头存在重名列，请先修改列名。")
        names = {"".join(c for c in h.lower() if c.isalnum()): h for h in self.frame.columns}

        def find(*aliases):
            return next((names[a] for a in aliases if a in names), None)

        self.x = find("fieldx", "x", "diex", "coordx", "xcoordinate")
        self.y = find("fieldy", "y", "diey", "coordy", "ycoordinate")
        self.wafer = find("waferid", "wafer", "waferno")
        self.group = find("padname", "measurementgroup", "measurement", "timestamp", "recipe")
        if not self.x or not self.y:
            raise ValueError("需要坐标列 FIELD X / FIELD Y（或 X / Y）。")
        metadata = {self.x, self.y, find("xmm"), find("ymm"), self.wafer, self.group,
                    find("dieseq", "dieid"), find("lotid", "lot"), find("toolsn", "toolid")}
        self.metrics = [c for c in self.frame if c not in metadata
                        and "path" not in c.lower() and number(self.frame[c]).notna().any()]
        if not self.metrics:
            raise ValueError("找不到可绘制的数值指标。")
        for column in (self.wafer, self.group):
            if column:
                self.frame[column] = self.frame[column].fillna("(空白)").astype(str).str.strip()
                self.frame[column] = self.frame[column].replace("", "(空白)")

    def wafers(self):
        return sorted(self.frame[self.wafer].unique()) if self.wafer else ["全部"]

    def rows(self, wafer, group=None):
        rows = self.frame
        if self.wafer:
            rows = rows[rows[self.wafer] == wafer]
        if self.group and group is not None:
            rows = rows[rows[self.group] == group]
        return rows

    def groups(self, wafer):
        return sorted(self.rows(wafer)[self.group].unique()) if self.group else ["全部"]

    def geometry_points(self, wafer):
        rows = self.rows(wafer)
        return pd.DataFrame({"x": number(rows[self.x]), "y": number(rows[self.y])}).dropna().drop_duplicates()

    def samples(self, wafer, group, metric):
        rows = self.rows(wafer, group)
        points = pd.DataFrame({"x": number(rows[self.x]), "y": number(rows[self.y]),
                               "value": number(rows[metric])}).dropna(subset=["x", "y"])
        if points.duplicated(["x", "y"]).any():
            raise ValueError("当前测量组有重复坐标，请先拆分测量组；程序不会自动覆盖或平均。")
        return points.dropna(subset=["value"]).reset_index(drop=True)

    def layer(self, wafer, group_a, metric, group_b=None):
        a = self.samples(wafer, group_a, metric)
        if group_b is None:
            return a
        b = self.samples(wafer, group_b, metric)
        merged = a.merge(b, on=["x", "y"], suffixes=("_a", "_b"), validate="one_to_one")
        merged["value"] = merged["value_a"] - merged["value_b"]
        return merged

    def details(self, wafer, group, x, y):
        rows = self.rows(wafer, group)
        return rows[(number(rows[self.x]) == x) & (number(rows[self.y]) == y)]

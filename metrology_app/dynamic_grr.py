"""Evaluate Dynamic measurements with a local, formula-preserving Excel template."""

from base64 import b64encode
from dataclasses import dataclass
from functools import lru_cache
import json
from math import isfinite
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Lock

from . import settings


CYCLE_COUNT = 9
DIE_COUNT = 13
INPUT_ROWS = (12, 13, 14, 18, 19, 20, 24, 25, 26)
RESULT_RANGE = "M96:R98"
_EXCEL_LOCK = Lock()


def template_path():
    directory = settings.SETTINGS_PATH.parent
    if directory == settings.APP_DIRECTORY:
        directory = settings.APPLICATION_ROOT
    return directory / "grr_template.xlsx"


def cached_template_path():
    target = template_path()
    if target.is_file():
        return target
    legacy = settings.SETTINGS_PATH.with_name(target.name)
    return legacy if legacy.is_file() else target


def input_values(pivot, *, cycles=None, dies=None):
    """Read the leading Cycle 脳 Die measurements in the Dynamic table's order."""
    cycles = [label for label in pivot.index if label != "3 Sigma"] if cycles is None else cycles
    dies = pivot.columns if dies is None else dies
    selection = pivot.reindex(index=list(cycles)[:CYCLE_COUNT], columns=list(dies)[:DIE_COUNT])
    return _validated_values(selection.to_numpy())


def _validated_values(values):
    if len(values) != CYCLE_COUNT or any(len(row) != DIE_COUNT for row in values):
        raise ValueError("GRR requires at least 9 cycles and 13 dies.")
    matrix = tuple(tuple(float(value) for value in row) for row in values)
    if any(not isfinite(value) for row in matrix for value in row):
        raise ValueError("GRR requires a finite measurement in every cell of the first 9 cycles and 13 dies.")
    return matrix


@dataclass(frozen=True)
class GrrRequest:
    template: Path
    stamp: tuple[int, int]
    parameters: tuple[tuple[str, tuple[tuple[float, ...], ...]], ...]


@dataclass(frozen=True)
class GrrReport:
    results: tuple[tuple[str, str], ...]
    content: bytes


def _stamp(path):
    metadata = path.stat()
    return metadata.st_mtime_ns, metadata.st_size


def request(parameters, template=None):
    path = Path(template) if template is not None else cached_template_path()
    inputs = tuple((str(name), _validated_values(values)) for name, values in parameters)
    if not inputs:
        raise ValueError("No selected Dynamic parameters have complete GRR measurements.")
    return GrrRequest(path, _stamp(path), inputs)


def _grr_sheet(path):
    from openpyxl import load_workbook

    if Path(path).suffix.lower() != ".xlsx":
        raise ValueError("Select an Excel .xlsx GRR template.")
    book = load_workbook(path, keep_links=False)
    try:
        matches = [sheet.title for sheet in book.worksheets
                   if any(str(region) == RESULT_RANGE for region in sheet.merged_cells.ranges)]
        if len(matches) != 1:
            raise ValueError(f"The GRR template must have exactly one worksheet with merged {RESULT_RANGE}.")
        return matches[0], tuple(book.sheetnames)
    finally:
        book.close()


def install_template(source, destination=None):
    """Validate and atomically replace the cached master."""
    source = Path(source)
    _grr_sheet(source)
    destination = Path(destination) if destination is not None else template_path()
    if source.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_report(destination, source.read_bytes())


def write_report(target, content, *, before_replace=None):
    """Publish a complete Excel file, without generating a backup."""
    target = Path(target)
    temporary = NamedTemporaryFile(dir=target.parent, prefix=".grr-", suffix=".xlsx", delete=False)
    try:
        with temporary:
            temporary.write(content)
        if before_replace is not None:
            before_replace()
        os.replace(temporary.name, target)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def evaluate(job):
    # Serialize Excel instances and reuse the report when Save follows a preview.
    with _EXCEL_LOCK:
        return _evaluate(job)


def _parameter_sheets(parameters, reserved):
    used = {name.casefold() for name in reserved}
    for name, values in parameters:
        base = re.sub(r"[][\\/:*?]", "_", name).strip(" '") or "Parameter"
        number = 1
        while True:
            suffix = "_GRR" if number == 1 else f"_{number}_GRR"
            label = base.encode("utf-16-le")[:2 * (31 - len(suffix))].decode("utf-16-le", errors="ignore")
            sheet = label + suffix
            if sheet.casefold() not in used:
                used.add(sheet.casefold())
                yield sheet, values
                break
            number += 1


@lru_cache(maxsize=4)
def _evaluate(job):
    with TemporaryDirectory(prefix="metrology-grr-") as directory:
        copy = Path(directory) / "report.xlsx"
        shutil.copyfile(job.template, copy)
        if _stamp(job.template) != job.stamp:
            raise ValueError("The GRR template changed. Evaluate the current template again.")
        sheet_name, all_sheets = _grr_sheet(copy)
        source = None
        if len(job.parameters) > 1:
            source = Path(directory) / "master.xlsx"
            shutil.copyfile(copy, source)
        batches = [
            {
                "name": name,
                "cells": [
                    (row, column, value)
                    for row, measurements in zip(INPUT_ROWS, matrix)
                    for column, value in enumerate(measurements, start=4)
                ],
            }
            for name, matrix in _parameter_sheets(job.parameters, all_sheets)
        ]
        ratings = _excel_recalculate(copy, source, sheet_name, batches)
        return GrrReport(
            tuple((name, rating) for (name, _), rating in zip(job.parameters, ratings, strict=True)),
            copy.read_bytes(),
        )


_EXCEL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$excel = $null
$books = $null
$book = $null
$source = $null
$sheets = $null
$masterSheets = $null
$sheet = $null
$cell = $null
$after = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $books = $excel.Workbooks
    $book = $books.Open([string]$request.path, 0, $false)
    $sheets = $book.Sheets
    $sheet = $sheets.Item([string]$request.sheet)
    $sheetIndex = $sheet.Index
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
    $sheet = $null
    if ($request.source) {
        $source = $books.Open([string]$request.source, 0, $true)
        $masterSheets = $source.Sheets
    }
    $excel.Calculation = -4135
    $parameterNames = @()
    foreach ($batch in $request.batches) {
        if ($parameterNames.Count -eq 0) {
            $sheet = $sheets.Item([string]$request.sheet)
        } else {
            # Copy the whole group so cross-sheet formulas follow their own measurements.
            $after = $sheets.Item($parameterNames[-1])
            $insertAt = [int]$after.Index
            $masterSheets.Copy([System.Type]::Missing, $after)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($after)
            $after = $null
            $sheet = $sheets.Item($insertAt + $sheetIndex)
            for ($offset = 1; $offset -le $masterSheets.Count; $offset++) {
                if ($offset -ne $sheetIndex) {
                    $helper = $sheets.Item($insertAt + $offset)
                    $helper.Visible = 0
                    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($helper)
                }
            }
        }
        $sheet.Name = [string]$batch.name
        $sheet.Visible = -1
        $parameterNames += [string]$batch.name
        foreach ($entry in $batch.cells) {
            $column = [char](64 + [int]$entry[1])
            $address = '{0}{1}' -f $column, $entry[0]
            $cell = $sheet.Range($address)
            $cell.Value2 = [double]$entry[2]
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
            $cell = $null
        }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
        $sheet = $null
    }
    $excel.Calculation = -4105
    $excel.CalculateFull()
    $ratings = @()
    foreach ($name in $parameterNames) {
        $sheet = $sheets.Item($name)
        $cell = $sheet.Range('M96')
        $value = $cell.Value2
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) {
            throw "The GRR formula at $name!M96 did not return an evaluation label."
        }
        $ratings += $value
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
        $cell = $null
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
        $sheet = $null
    }
    $book.Save()
    [Console]::Out.Write((ConvertTo-Json -Compress -InputObject $ratings))
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($null -ne $source) { $source.Close($false) }
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) { $excel.Quit() }
    foreach ($comObject in @($cell, $sheet, $after, $masterSheets, $sheets, $source, $book, $books, $excel)) {
        if ($null -ne $comObject) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($comObject)
        }
    }
}
"""


def _excel_recalculate(path, source, sheet, batches):
    if os.name != "nt":
        raise OSError("GRR formula calculation requires Microsoft Excel on Windows.")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = b64encode(_EXCEL_SCRIPT.encode("utf-16-le")).decode("ascii")
    payload = json.dumps(
        {"path": str(path), "source": str(source) if source else None, "sheet": sheet, "batches": batches},
        allow_nan=False,
    )
    try:
        process = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
            input=payload, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as error:
        raise OSError("Excel did not finish calculating the GRR report within 60 seconds.") from error
    if process.returncode != 0:
        details = process.stderr.removeprefix('#< CLIXML').partition('<Objs')[0].strip()
        raise OSError(f"Excel could not calculate the GRR template. {details}")
    return json.loads(process.stdout)


def match_inputs(snapshot):
    """Select the most recently used Dynamic window's accepted GRR measurements."""
    scopes = snapshot.states
    preferred = scopes.get("match_ui", {}).get("grr_scope")
    dynamic = {}
    for scope, state in scopes.items():
        if state.get("workspace_type") == "dynamic":
            grr = state.get("analysis_states", {}).get("grr") or {}
            if grr.get("parameters"):
                dynamic[scope] = grr
    if preferred in dynamic:
        return preferred, dynamic[preferred]
    return next(iter(dynamic.items()), (None, None))


def match_report_path(path):
    path = Path(path)
    return path.with_name(f"GRR_{path.stem}.xlsx")


def existing_match_report(path):
    """Find the companion report published after the latest Workbook save."""
    path = Path(path)
    report = match_report_path(path)
    try:
        if report.is_file() and report.stat().st_mtime_ns >= path.stat().st_mtime_ns:
            return report
    except OSError:
        pass
    return None


class GrrReportWriteError(OSError):
    """The companion Excel file could not be replaced or written."""

    def __init__(self, path):
        super().__init__(str(path))
        self.path = path


def save_match_report(path, revision, inputs):
    from .workspace_store import file_revision

    target = match_report_path(path)
    parameters = inputs.get("parameters", ())
    if not parameters:
        return ""
    valid = [(name, values) for name, values in parameters if values is not None]
    if not valid:
        raise ValueError("No selected Dynamic parameter has 9 complete cycles and 13 dies.")
    report = evaluate(request(valid))

    def verify_revision():
        if file_revision(path) != revision:
            raise OSError("The Match Workbook changed before its GRR report was saved.")

    try:
        write_report(target, report.content, before_replace=verify_revision)
    except PermissionError as error:
        raise GrrReportWriteError(target) from error
    skipped = [name for name, values in parameters if values is None]
    return f"GRR omitted incomplete parameters: {', '.join(skipped)}" if skipped else ""

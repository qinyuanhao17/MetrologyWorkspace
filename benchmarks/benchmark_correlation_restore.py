"""Repeat the unchanged complete grouped-restore regression in fresh processes.

python -m benchmarks.benchmark_correlation_restore --count 30 --output .cache/restore.json
Use --profile separately: profiler overhead is not an acceptance measurement.
The fixture is the existing 6,000-row / 29-unmapped-column regression, including
its original two-second assertion and all fit/selection/source-data assertions.
"""
import argparse
import cProfile
import ctypes
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter, process_time
import unittest
from unittest.mock import patch


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@lru_cache(maxsize=1)
def _windows_memory_query():
    """One fixed counter type; ctypes caches pointer types by strong reference."""
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged",
                "pagefile", "peak_pagefile", "private")]

    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    return Counters, query


def memory_info():
    """Windows working set/private bytes without adding a runtime dependency."""
    if sys.platform != "win32":
        return {"rss": None, "private": None, "peak": None}
    from ctypes import wintypes
    Counters, query = _windows_memory_query()
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not query(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {name: getattr(counters, name) for name in ("rss", "private", "peak")}


def worker(output, profile):
    from run_tests import isolate_settings

    with tempfile.TemporaryDirectory(prefix="correlation-restore-") as directory:
        isolate_settings(directory)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtCore import QTimer, QT_VERSION_STR, PYQT_VERSION_STR
        from PyQt6.QtWidgets import QApplication
        from metrology_app.correlation_window import CorrelationWindow
        from tests.test_performance_regressions import WorkbookPerformanceTests

        app = QApplication.instance() or QApplication([])
        profiler = cProfile.Profile()
        sample = {"python": sys.version, "platform": platform.platform(),
                  "qt": QT_VERSION_STR, "pyqt": PYQT_VERSION_STR,
                  "logical_cpus": os.cpu_count(), "platform_plugin": app.platformName()}
        original = CorrelationWindow.restore_workspace

        def measured(window, snapshot):
            ticks = []
            timer = QTimer(interval=10)
            timer.timeout.connect(lambda: ticks.append(perf_counter()))
            memory = memory_info()
            timer.start()
            cpu, start = process_time(), perf_counter()
            ticks.append(start)
            if profile:
                profiler.enable()
            try:
                return original(window, snapshot)
            finally:
                if profile:
                    profiler.disable()
                end = perf_counter()
                ticks.append(end)
                timer.stop()
                after = memory_info()
                sample.update(restore_ms=(end - start) * 1000,
                              cpu_ms=(process_time() - cpu) * 1000,
                              max_gap_ms=max(b - a for a, b in zip(ticks, ticks[1:])) * 1000,
                              rss_before=memory["rss"], rss_after=after["rss"],
                              private_after=after["private"],
                              process_peak_rss=after["peak"])

        case = WorkbookPerformanceTests(
            "test_saved_correlation_restores_complete_grouped_plots_promptly")
        result = unittest.TestResult()
        with patch.object(CorrelationWindow, "restore_workspace", measured):
            case.run(result)
        sample.update(passed=result.wasSuccessful(),
                      failures=[message for _, message in result.failures + result.errors],
                      rss_after_close=memory_info()["rss"])
        if profile:
            profiler.dump_stats(str(output.with_suffix(".prof")))
            with output.with_suffix(".profile.txt").open("w", encoding="utf-8") as stream:
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(100)
        output.write_text(json.dumps(sample, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(output, args.profile)
        return
    settings = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
    before = digest(settings)
    samples = []
    for index in range(args.count):
        path = output.with_name(f"{output.stem}-{index + 1:02}.json")
        command = [sys.executable, "-X", "utf8", "-m", __spec__.name,
                   "--worker", "--output", str(path)]
        if args.profile:
            command.append("--profile")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        sample = json.loads(path.read_text(encoding="utf-8"))
        samples.append(sample)
        print(f"{index + 1}/{args.count}: {sample.get('restore_ms', 0):.1f} ms; "
              f"passed={sample['passed']}", flush=True)
    summary = {}
    for key in ("restore_ms", "cpu_ms", "max_gap_ms", "rss_after", "process_peak_rss"):
        values = sorted(sample[key] for sample in samples if sample.get(key) is not None)
        if values:
            summary[key] = {"p50": statistics.median(values),
                            "p95": values[math.ceil(.95 * len(values)) - 1], "max": max(values)}
    after = digest(settings)
    output.write_text(json.dumps({"profiled": args.profile, "samples": samples, "summary": summary,
                                  "settings_sha256_before": before, "settings_sha256_after": after,
                                  "scope": "fresh process, prepared child, synchronous complete restore; "
                                           "heartbeat includes interval edges; process peak includes fixture setup"},
                                 indent=2), encoding="utf-8")
    if before != after:
        raise RuntimeError("User settings changed during the benchmark")
    if not all(sample["passed"] for sample in samples):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

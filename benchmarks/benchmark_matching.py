"""Repeatable capacity benchmark for the Card Matching deep module."""

from argparse import ArgumentParser
from pathlib import Path
import tempfile
from time import perf_counter

import numpy as np
import pandas as pd

from metrology_app.matching import MatchWorkbook, ParameterMapping


def benchmark(rows=100_000, parameters=50, seed=20260926):
    rng = np.random.default_rng(seed)
    raw_values = rng.normal(50.0, 5.0, size=(rows, parameters))
    slopes = np.linspace(0.95, 1.05, parameters)
    intercepts = np.linspace(-0.5, 0.5, parameters)
    reference_values = raw_values * slopes + intercepts
    raw = pd.DataFrame(raw_values, columns=[f"P{i:02d}" for i in range(parameters)])
    reference = pd.DataFrame(
        reference_values,
        columns=[f"P{i:02d} Reference" for i in range(parameters)],
    )
    mappings = tuple(
        ParameterMapping(f"P{i:02d}", f"P{i:02d} Reference", f"P{i:02d}")
        for i in range(parameters)
    )

    start = perf_counter()
    workbook = MatchWorkbook(reference, raw, mappings, match_type="KLA")
    result = workbook.analyze()
    analysis_seconds = perf_counter() - start

    start = perf_counter()
    result.series(mappings[-1].name)
    series_seconds = perf_counter() - start

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "benchmark.wkb"
        start = perf_counter()
        workbook.save(path)
        save_seconds = perf_counter() - start
        size_mb = path.stat().st_size / 1024 / 1024
        start = perf_counter()
        restored = MatchWorkbook.load(path)
        load_seconds = perf_counter() - start
        restored.analyze()

    return {
        "rows": rows,
        "parameters": parameters,
        "seed": seed,
        "analysis_seconds": round(analysis_seconds, 3),
        "one_series_seconds": round(series_seconds, 3),
        "wkb_save_seconds": round(save_seconds, 3),
        "wkb_load_seconds": round(load_seconds, 3),
        "wkb_size_mb": round(size_mb, 1),
    }


def main():
    parser = ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--parameters", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args()
    print(benchmark(args.rows, args.parameters, args.seed))


if __name__ == "__main__":
    main()
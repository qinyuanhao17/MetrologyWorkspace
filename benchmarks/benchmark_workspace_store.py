"""Storage-only benchmark: python -m benchmarks.benchmark_workspace_store.

No GUI, global preferences or user documents are touched.
"""
import argparse
import json
from pathlib import Path
import tempfile
from time import perf_counter

import numpy as np
import pandas as pd

from metrology_app.workspace_store import WorkspaceSnapshot, load_workspace, save_workspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--parameters", type=int, default=50)
    args = parser.parse_args()
    generator = np.random.default_rng(20261003)
    frame = pd.DataFrame({f"CD_{i}": np.char.mod("%.4f", generator.uniform(1, 100, args.rows))
                          for i in range(args.parameters)})
    frame.insert(0, "Wafer ID", [f"{i // 1000:04d}" for i in range(args.rows)])
    frame.insert(1, "Die Seq", [str(i % 1000) for i in range(args.rows)])
    with tempfile.TemporaryDirectory(prefix="metrology-wkb-benchmark-") as directory:
        start = perf_counter()
        path = save_workspace(Path(directory) / "benchmark.wkb", WorkspaceSnapshot("wafer_map", {"input_data": frame}))
        save_seconds = perf_counter() - start
        start = perf_counter()
        restored = load_workspace(path)
        load_seconds = perf_counter() - start
        pd.testing.assert_frame_equal(restored.frames["input_data"], frame)
        print(json.dumps({"rows": args.rows, "parameters": args.parameters, "identity_columns": 2,
                          "save_seconds": round(save_seconds, 3), "load_seconds": round(load_seconds, 3),
                          "file_mib": round(path.stat().st_size / 1024**2, 2), "exact_round_trip": True}))


if __name__ == "__main__":
    main()

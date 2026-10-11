"""Actual Ctrl+A on a real WKB, optionally against frozen code in a new process."""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--code-root", required=True, type=Path)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.code_root.resolve()))
    os.environ["METROLOGY_SETTINGS_PATH"] = str(args.scratch / "settings.yaml")
    os.environ["METROLOGY_RECOVERY_DIR"] = str(args.scratch / "recovery")
    os.environ["MPLCONFIGDIR"] = str(args.scratch / "mpl")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np
    import pandas as pd
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    import metrology_app
    from metrology_app.match_group_ui import ProjectedSheetModel
    from metrology_app.sheet import SheetModel, SheetView
    from metrology_app.workspace_store import load_workspace
    from metrology_app.appearance import configure_fonts

    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()
    digest = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    raw = load_workspace(args.wkb).frames["raw"]
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    model = SheetModel()
    model.load(raw)
    projected = ProjectedSheetModel(model)
    projected.set_rows(range(len(raw) - 1, -1, -1))
    view = SheetView(projected)
    view.resize(850, 330)
    view.show()
    app.processEvents()
    samples = []
    profiler = cProfile.Profile()
    try:
        for _ in range(args.count):
            if args.profile:
                profiler.enable()
            start = perf_counter()
            QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            app.processEvents()
            samples.append((perf_counter() - start) * 1000)
            profiler.disable()
            selected = [(r.top(), r.left(), r.bottom(), r.right()) for r in view.selectionModel().selection()]
            assert selected == [(0, 0, len(raw), len(raw.columns) - 1)], selected
            # Deselect through the same native table between invocations.
            view.setCurrentIndex(projected.index(2, 2))
        pd.testing.assert_frame_equal(model.document_frame(), raw)
        assert model.undo.isClean()
        print(json.dumps({"file": args.wkb.name, "rows": len(raw), "columns": len(raw.columns),
                          "code_root": str(args.code_root), "count": len(samples),
                          "first_ms": samples[0], "median_ms": float(np.median(samples)),
                          "p95_ms": float(np.percentile(samples, 95)), "max_ms": max(samples),
                          "exact_source_and_selection": "pass", "sha256": digest}), flush=True)
        if args.profile:
            pstats.Stats(profiler).strip_dirs().sort_stats("cumtime").print_stats(18)
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()
        assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == digest


if __name__ == "__main__":
    main()

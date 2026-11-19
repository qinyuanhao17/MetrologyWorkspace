"""Measure the Spectra Viewer import pipeline with temporary app settings."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_tests import isolate_settings


def benchmark(folder, modes):
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
    from unittest.mock import patch
    from metrology_app import spectra_workbook
    from metrology_app.settings import load_settings
    from metrology_app.sme_spectra import scan_sme_files
    from metrology_app.spectra_viewer import SpectraViewerWindow

    load_settings()
    app = QApplication.instance() or QApplication([])
    files = scan_sme_files(folder)
    cpu_count = os.cpu_count()
    encode = spectra_workbook.encode_sources
    runs = []
    for mode in modes:
        timing = {"mode": mode}

        def measured(sources, *args, **kwargs):
            if kwargs.get("cancelled") is None:
                return encode(sources, *args, **kwargs)
            if mode == "serial" and "workers" in kwargs:
                kwargs["workers"] = 1
            timing["workers"] = kwargs.get("workers", 1)
            start = perf_counter()
            result = encode(sources, *args, **kwargs)
            timing["prepare_seconds"] = perf_counter() - start
            return result

        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        viewer.show()
        app.processEvents()
        loop = QEventLoop()
        ready = QTimer(interval=10)
        start = perf_counter()

        def check_ready():
            if viewer._loader is None and not viewer._plot_paint_timer.isActive():
                timing["viewer_seconds"] = perf_counter() - start
                loop.quit()

        ready.timeout.connect(check_ready)
        with patch.object(spectra_workbook, "encode_sources", measured):
            viewer.start_loading(folder, replace=True)
            ready.start()
            loop.exec()
            ready.stop()
        if "prepare_seconds" not in timing or not viewer.catalog.spectra:
            raise RuntimeError(viewer.status.text())
        digest = hashlib.sha256()
        for record in viewer._workbook_samples.values():
            for value in record:
                digest.update(value.encode("utf-8"))
                digest.update(b"\0")
        timing.update(spectra=len(viewer.catalog.spectra), issues=len(viewer.catalog.issues),
                      issue_statuses=dict(Counter(issue.status for issue in viewer.catalog.issues)),
                      embedded_records=len(viewer._workbook_samples), record_sha256=digest.hexdigest())
        runs.append(timing)
        print(json.dumps(timing), flush=True)
        viewer.close()
        viewer.deleteLater()
        from PyQt6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    return {"folder": str(folder), "logical_cpus": cpu_count, "sme_files": len(files),
            "sme_bytes": sum(path.stat().st_size for path in files), "runs": runs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--modes", nargs="+", choices=("serial", "auto"), default=("serial", "auto"))
    args = parser.parse_args()
    with TemporaryDirectory(prefix="spectra-import-benchmark-") as scratch:
        isolate_settings(scratch)
        args.output.write_text(json.dumps(benchmark(args.folder.resolve(), args.modes), indent=2) + "\n",
                               encoding="utf-8")

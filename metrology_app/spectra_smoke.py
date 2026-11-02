"""Opt-in source/frozen Spectra release validation, without AutoWeighting."""
import json
from pathlib import Path
import sqlite3
import sys
import time


def run_spectra_smoke(shell, app, folder, report_path):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest
    from .sme_spectra import load_folder
    state = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
             "sqlite_version": sqlite3.sqlite_version}
    try:
        sources = load_folder(Path(folder))
        if not sources.spectra or sources.issues:
            raise ValueError("Release smoke test requires readable SME sources.")
        viewer = shell.open_component("spectra_viewer")
        viewer.apply_load_result(sources, replace=True)
        mapping = viewer.open_wafer_map()
        deadline = time.monotonic() + 15
        while mapping._pending_page_wafers and time.monotonic() < deadline:
            app.processEvents()
        if mapping._pending_page_wafers or not mapping.wafer_plots:
            raise ValueError("Die Map page did not finish loading.")
        QTest.qWait(100)
        mapping.grab()
        QTest.qWait(50)
        plot = next(iter(mapping.wafer_plots.values()))
        view = plot.plot.getViewBox()
        xr, yr = view.viewRange()
        a = plot.plot.mapFromScene(view.mapViewToScene(QPointF(xr[0]+1, yr[0]+1)))
        b = plot.plot.mapFromScene(view.mapViewToScene(QPointF(xr[1]-1, yr[1]-1)))
        QTest.mousePress(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(plot.plot.viewport(), ((QPointF(a)+QPointF(b))/2).toPoint(), delay=25)
        QTest.qWait(30)
        QTest.mouseMove(plot.plot.viewport(), b, delay=25)
        QTest.qWait(30)
        QTest.mouseRelease(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=b)
        QTest.qWait(30)
        expected = {key for keys in plot._spot_keys for key in keys}
        if not expected or mapping._selected_keys != expected:
            raise ValueError("Native rectangle selection failed.")
        point = plot._plot_positions[0]
        position = plot.plot.mapFromScene(view.mapViewToScene(QPointF(*point)))
        QTest.mouseDClick(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseRelease(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
        app.processEvents()
        checked = {source.key for source in viewer.checked_spectra()}
        if not set(plot._spot_keys[0]) <= checked:
            raise ValueError("Native double-click checkbox update failed.")
        state.update(title=mapping.windowTitle(), spectra=len(sources.spectra),
                     rectangle_selection=True, double_click_check=True,
                     auto_weighting_loaded=any(name.startswith("metrology_app.auto_weighting") for name in sys.modules))
        state["ok"] = state["title"] == "Spectrum Die Map" and not state["auto_weighting_loaded"]
    except Exception as error:
        state["error"] = str(error)
    finally:
        for windows in tuple(shell.loaded_components.values()):
            for window in tuple(windows):
                window.document.force_close = True
                window.close()
        QTest.qWait(10)
        shell.close()
        app.processEvents()
        Path(report_path).write_text(json.dumps(state, indent=2), encoding="utf-8")
    return 0 if state["ok"] else 2

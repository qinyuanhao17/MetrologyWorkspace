"""Capture real NOVA Correlation UI before/after a single-plot axis swap."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["METROLOGY_SETTINGS_PATH"] = str(args.scratch / "settings.yaml")
    os.environ["METROLOGY_RECOVERY_DIR"] = str(args.scratch / "recovery")
    os.environ["MPLCONFIGDIR"] = str(args.scratch / "mpl")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import numpy as np
    import pandas as pd
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QAbstractButton
    from metrology_app.appearance import configure_fonts
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.settings import apply_theme, save_settings

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    save_settings({"theme": "light"})
    original_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    workbook = MatchingWindow()
    workbook.document.timer.stop()
    workbook.load_workbook(args.wkb)
    workbook.result_mode.setCurrentText("Preview")
    workbook.run_analysis()
    window = workbook.open_correlation_workspace()
    window.document.timer.stop()
    window.resize(1740, 1040)
    apply_theme(window, "light")
    page = window.correlation_page
    page.min_rsq.setValue(0)
    page.columns.setCurrentText("3")
    page.selector.selectAll()
    page.start_draw()
    window.tabs.setCurrentWidget(page)
    QTest.qWait(250)
    app.processEvents()
    assert page.ready, page.status.text()
    target = 0
    fit = page.page_fits()[target]
    widgets = list(page.plot_widgets)
    views = [widget.getViewBox().viewRange() for widget in widgets]
    source = page.frame.copy(deep=True)
    window.grab().save(str(args.scratch / "correlation-before.png"))
    page.panel_hosts[target].grab().save(str(args.scratch / "panel-before.png"))
    button = next(control for control in page.panel_hosts[target].findChildren(QAbstractButton)
                  if control.text() == "Swap X/Y")
    samples = []
    first = None
    for repeat in range(21):
        start = perf_counter()
        button.click()
        callback = perf_counter()
        widgets[target].viewport().repaint()
        app.processEvents()
        samples.append({"callback_ms": (callback - start) * 1000,
                        "paint_ms": (perf_counter() - start) * 1000})
        if repeat == 0:
            first = samples[-1]
        QTest.qWait(10)
    assert page.plot_widgets == widgets
    for index, widget in enumerate(widgets):
        if index != target:
            np.testing.assert_allclose(widget.getViewBox().viewRange(), views[index])
    pd.testing.assert_frame_equal(page.frame, source)
    page.ensure_export_figure()
    assert page.figure.axes[target].get_xlabel() == fit.y_name
    assert page.figure.axes[target].get_ylabel() == fit.x_name
    window.grab().save(str(args.scratch / "correlation-after.png"))
    page.panel_hosts[target].grab().save(str(args.scratch / "panel-after.png"))
    print(json.dumps({"file": args.wkb.name, "rows": len(workbook.raw_model.document_frame()),
                      "plots": len(widgets), "target": target, "old_x": fit.x_name, "old_y": fit.y_name,
                      "new_x": fit.y_name, "new_y": fit.x_name, "first_swap": first,
                      "warm_swap_p50_ms": float(np.median([sample["callback_ms"] for sample in samples[1:]])),
                      "warm_paint_p50_ms": float(np.median([sample["paint_ms"] for sample in samples[1:]]))},
                     ensure_ascii=False))
    for target_window in (window, workbook):
        target_window.document.force_close = True
        target_window.document.timer.stop()
        target_window.document.identity_timer.stop()
        target_window.close()
    app.processEvents()
    assert hashlib.sha256(args.wkb.read_bytes()).hexdigest() == original_hash
    print("source unchanged; unaffected widgets/views and export direction verified")


if __name__ == "__main__":
    main()

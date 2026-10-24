"""Synthetic sheet keyboard baseline with exact text and one-step Undo checks.

python -m benchmarks.benchmark_sheet_workflows --output .cache/sheets.json
Separate from full-workbook analysis latency; offscreen timings are not FPS.
"""
import argparse
import cProfile
import csv
import json
import math
import os
import platform
from io import StringIO
from pathlib import Path
import statistics
import sys
import pstats
from time import perf_counter, process_time

from .benchmark_correlation_restore import digest, memory_info


def selection_workflows(dialog, frame, measure, app):
    """Exercise the same public model, search, show-mode and mouse paths as the dialog."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    model, table = dialog.model, dialog.table
    rows = len(frame)
    column = list(frame.columns).index("Die Seq") if "Die Seq" in frame else 0
    values = frame.iloc[:, column].fillna("").astype(str).tolist()
    try:
        numeric = [float(value) if value.strip() else None for value in values]
        expected = sorted(range(rows), key=lambda row: (numeric[row] is None,
                          -numeric[row] if numeric[row] is not None else 0))
    except ValueError:
        expected = sorted(range(rows), key=lambda row: values[row], reverse=True)
    measure("sort_descending", table, action=lambda: model.sort(column + 2, Qt.SortOrder.DescendingOrder))
    assert model.rows == expected, "Sort lost stable source positions"
    measure("sort_source_order", table, action=lambda: model.sort(1, Qt.SortOrder.AscendingOrder))
    assert model.rows == list(range(rows))
    query = str(frame.iat[0, 0])
    expected = [row for row, record in enumerate(frame.itertuples(index=False, name=None))
                if any(query.casefold() in str(value).casefold() for value in record)]
    measure("filter_search", table, action=lambda: dialog.search.setText(query))
    assert model.rows == expected
    measure("filter_clear", table, action=dialog.search.clear)
    model.checked = set(model.ids[::2])  # Deterministic participation fixture for each cycle.
    measure("hide_unchecked", table, action=lambda: dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("checked")))
    assert model.rows == list(range(0, rows, 2))
    measure("show_all", table, action=lambda: dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("all")))
    assert model.rows == list(range(rows))
    measure("bulk_uncheck_visible", table, action=lambda: dialog.check_visible(False))
    assert not model.checked
    measure("bulk_check_visible", table, action=lambda: dialog.check_visible(True))
    assert model.checked == set(model.ids)
    for name, expected in (("shift_uncheck_range", set()), ("shift_check_range", set(model.ids))):
        first, last = model.index(0, 1), model.index(rows - 1, 1)
        table.scrollTo(first)
        app.processEvents()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(first).center())
        table.scrollTo(last)
        app.processEvents()
        point = table.visualRect(last).center()
        assert table.viewport().rect().contains(point)
        measure(name, table, action=lambda: QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=point))
        assert model.checked == expected, "Shift range changed the wrong source identities"


def projected_edits(frame, model, projected, view, visible_rows, measure, app):
    """Clipboard edits must preserve hidden rows and retain one-command Undo."""
    import pandas as pd
    from PyQt6.QtCore import QItemSelection, QItemSelectionModel, Qt
    from PyQt6.QtTest import QTest
    column = len(frame.columns) - 1
    value = "9.876543210123456"
    expected = frame.copy(deep=True)
    expected.iloc[visible_rows, column] = value
    app.clipboard().setText("\n".join([value] * len(visible_rows)))
    view.setCurrentIndex(projected.index(1, column))
    measure("projected_paste", view, Qt.Key.Key_V)
    pd.testing.assert_frame_equal(model.document_frame(), expected)
    assert model.undo.count() == 1
    measure("projected_undo", view, Qt.Key.Key_Z)
    pd.testing.assert_frame_equal(model.document_frame(), frame)
    measure("projected_redo", view, Qt.Key.Key_Y)
    pd.testing.assert_frame_equal(model.document_frame(), expected)
    model.undo.undo()
    view.selectionModel().select(QItemSelection(projected.index(1, column),
        projected.index(len(visible_rows), column)), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    measure("projected_delete", view, Qt.Key.Key_Delete, control=False)
    expected.iloc[visible_rows, column] = ""
    pd.testing.assert_frame_equal(model.document_frame(), expected)
    measure("projected_undo_delete", view, Qt.Key.Key_Z)
    pd.testing.assert_frame_equal(model.document_frame(), frame)
    model.undo.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[1000, 10000, 100000])
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--platform", choices=("offscreen", "windows"), default="offscreen")
    parser.add_argument("--wkb", type=Path, help="Repeat/slice the read-only Raw table to the requested sizes")
    parser.add_argument("--reuse-views", action="store_true", help="Repeat on the same views, resetting only destination data/history")
    parser.add_argument("--interactions", action="store_true", help="Also measure sort/filter/hidden-row/bulk selection workflows")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--projected-edits", action="store_true")
    parser.add_argument("--profile-actions", nargs="*", default=[],
                        help="Profile selected operations separately from acceptance timings")
    args = parser.parse_args()
    if args.count < 1 or any(rows < 1 for rows in args.rows):
        parser.error("Row counts and repetition count must be positive")
    os.environ["QT_QPA_PLATFORM"] = args.platform
    sys.path.insert(0, str(args.code_root.resolve()))
    import pandas as pd
    from PyQt6.QtCore import QCoreApplication, QEvent, QMimeData, Qt, QTimer, QT_VERSION_STR
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from metrology_app.match_group_ui import ProjectedSheetModel
    from metrology_app.sheet import SheetModel, SheetView
    from metrology_app.appearance import configure_fonts
    from metrology_app.settings import apply_theme
    import metrology_app
    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    assert app.platformName() == args.platform
    settings = Path(__file__).resolve().parents[1] / "config/settings.yaml"
    before = digest(settings)
    source_hash = digest(args.wkb) if args.wkb else None
    source = None
    if args.wkb:
        from metrology_app.workspace_store import load_workspace
        source = load_workspace(args.wkb).frames["raw"]
        assert len(source), "The workbook Raw table is empty"
    original_clipboard = QMimeData()
    incoming = app.clipboard().mimeData()
    if incoming is not None:
        for kind in incoming.formats():
            original_clipboard.setData(kind, incoming.data(kind))
    import atexit
    atexit.register(lambda: app.clipboard().setMimeData(original_clipboard))
    screen = app.primaryScreen()
    environment = {"python": platform.python_version(), "os": platform.platform(),
                   "qt": QT_VERSION_STR, "platform": app.platformName(), "cpu_count": os.cpu_count(),
                   "screen": {"width": screen.size().width(), "height": screen.size().height(),
                              "dpi": screen.logicalDotsPerInch(), "pixel_ratio": screen.devicePixelRatio(),
                              "refresh_hz": screen.refreshRate()}}
    samples = []
    for rows in args.rows:
        frame = pd.DataFrame({"Wafer ID": [f"W{i // 20:06}" for i in range(rows)],
                              "Die Seq": [f"{i % 20 + 1:02}" for i in range(rows)],
                              "CD": ["1.123456789000000"] * rows,
                              "Depth": ["" if i % 7 == 0 else "2.000000000000001" for i in range(rows)]})
        if source is not None:
            frame = pd.concat([source] * math.ceil(rows / len(source)), ignore_index=True).iloc[:rows].copy()
        selection_dialog = None
        for iteration in range(args.count):
            if iteration == 0 or not args.reuse_views:
                model, target = SheetModel(), SheetModel()
                model.load(frame)
                view, destination = SheetView(model), SheetView(target)
                projected = ProjectedSheetModel(model)
                visible_rows = list(range(rows - 1, -1, -2))
                projected.set_rows(visible_rows)
                projection = SheetView(projected)
                views = (view, destination, projection)
                if args.interactions:
                    from metrology_app.data_selection import SelectionDialog
                    ids = [str(row) for row in range(rows)]
                    selection_dialog = SelectionDialog(frame, ids, ids[::2], [])
                    views = (*views, selection_dialog)
                for widget in views:
                    apply_theme(widget)
                    widget.resize(850, 330)
                    widget.show()
            else:
                target.load_matrix([])
            app.processEvents()
            if args.platform == "windows":
                assert all(widget.windowHandle().isExposed() for widget in views)
            if args.screenshot and iteration == 0:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                view.grab().save(str(args.screenshot.with_name(f"{args.screenshot.stem}-{rows}.png")))

            def measure(name, widget, key=None, control=True, *, action=None):
                ticks = []
                timer = QTimer(interval=10)
                timer.timeout.connect(lambda: ticks.append(perf_counter()))
                timer.start()
                profiler = cProfile.Profile() if name in args.profile_actions else None
                if profiler is not None:
                    profiler.enable()
                cpu, start = process_time(), perf_counter()
                ticks.append(start)
                if action is not None:
                    action()
                else:
                    QTest.keyClick(widget, key, Qt.KeyboardModifier.ControlModifier
                                   if control else Qt.KeyboardModifier.NoModifier)
                app.processEvents()
                viewport = widget.viewport() if hasattr(widget, "viewport") else widget
                viewport.repaint()
                end = perf_counter()
                ticks.append(end)
                timer.stop()
                if profiler is not None:
                    profiler.disable()
                samples.append({"rows": rows, "iteration": iteration, "operation": name,
                                "wall_ms": (end - start) * 1000,
                                "cpu_ms": (process_time() - cpu) * 1000,
                                "max_gap_ms": max(b - a for a, b in zip(ticks, ticks[1:])) * 1000,
                                **memory_info()})
                if profiler is not None:
                    report = args.output.with_name(f"{args.output.stem}-{rows}-{iteration}-{name}.profile.txt")
                    with report.open("w", encoding="utf-8") as stream:
                        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)

            try:
                measure("select_all", view, Qt.Key.Key_A)
                measure("copy", view, Qt.Key.Key_C)
                copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
                assert copied == [list(frame.columns), *frame.values.tolist()]
                destination.setCurrentIndex(target.index(0, 0))
                measure("paste", destination, Qt.Key.Key_V)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                assert target.undo.count() == 1
                measure("undo", destination, Qt.Key.Key_Z)
                assert target.document_frame().empty and target.undo.index() == 0
                measure("redo", destination, Qt.Key.Key_Y)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                destination.selectAll()
                measure("delete", destination, Qt.Key.Key_Delete, control=False)
                assert target.document_frame().empty
                measure("undo_delete", destination, Qt.Key.Key_Z)
                pd.testing.assert_frame_equal(target.document_frame(), frame)
                measure("projected_select_all", projection, Qt.Key.Key_A)
                measure("projected_copy", projection, Qt.Key.Key_C)
                copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
                assert copied == [list(frame.columns), *frame.iloc[visible_rows].values.tolist()]
                pd.testing.assert_frame_equal(model.document_frame(), frame)
                assert model.undo.isClean()
                if args.projected_edits:
                    projected_edits(frame, model, projected, projection, visible_rows, measure, app)
                measure("scroll_bottom", view, action=lambda: view.scrollTo(model.index(rows, 0)))
                measure("scroll_top", view, action=lambda: view.scrollTo(model.index(0, 0)))
                if selection_dialog is not None:
                    selection_workflows(selection_dialog, frame, measure, app)
                print(json.dumps({"rows": rows, "iteration": iteration, "exact_text_and_undo": "pass"}), flush=True)
            finally:
                if not args.reuse_views or iteration == args.count - 1 or sys.exc_info()[0] is not None:
                    for widget in views:
                        widget.close()
                        widget.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    app.processEvents()
    assert digest(settings) == before, "Real settings changed during the benchmark"
    assert args.wkb is None or digest(args.wkb) == source_hash, "Source workbook changed"
    summary = []
    for rows, name in dict.fromkeys((row["rows"], row["operation"]) for row in samples):
        group = [row for row in samples if row["rows"] == rows and row["operation"] == name]
        result = {"rows": rows, "operation": name, "count": len(group)}
        for key in ("wall_ms", "cpu_ms", "max_gap_ms", "rss", "private", "peak"):
            values = sorted(row[key] for row in group if row[key] is not None)
            result[key] = ({"p50": statistics.median(values),
                            "p95": values[math.ceil(len(values) * .95) - 1], "max": max(values)}
                           if values else None)
        summary.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"count": args.count, "columns": len(frame.columns),
                                      "environment": environment, "reuse_views": args.reuse_views,
                                      "projected_edits": args.projected_edits,
                                      "source_path": str(args.wkb) if args.wkb else None,
                                      "source_sha256": source_hash,
                                      "code_root": str(args.code_root.resolve()),
                                      "profile_actions": args.profile_actions,
                                      "fixture": "Exact text; repeated wafers/dies; high precision; empty values",
                                      "measurement": "Synchronous Qt event + viewport paint, not compositor FPS; process peak includes setup",
                                      "settings_sha256": before, "samples": samples, "summary": summary}, indent=2),
                           encoding="utf-8")


if __name__ == "__main__":
    main()

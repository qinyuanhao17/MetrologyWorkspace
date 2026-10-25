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


def sheet_probe_host(view):
    """Match production's embedded tables; a bare top-level table is a UIA root."""
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    host = QWidget()
    QVBoxLayout(host).addWidget(view)
    return host


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
        # Force a new selection delta for BOTH directions. The custom release
        # handler can otherwise retain the old range and hide cold Qt cost.
        table.clearSelection()
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


def workbook_keys(frame, path, measure, app, *, stage="preview"):
    """First keys on actual subscribed Workbook grids, not a naked SheetModel."""
    import pandas as pd
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from metrology_app.matching import MatchWorkbook
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.workspace_store import load_workspace

    window = MatchingWindow()
    try:
        snapshot = load_workspace(path)
        book = MatchWorkbook.from_snapshot(snapshot)
        # Fresh analysis with the real source/mappings. Restoring the WKB's
        # hundreds of saved individual plot widgets is a different benchmark.
        window.match_type.setCurrentText(book.match_type)
        window.document.timer.stop()
        window._auto_run_enabled = False
        window.result_mode.setCurrentText("Preview")
        source = snapshot.frames["reference"]
        reference = pd.concat([source]*math.ceil(len(frame)/len(source)), ignore_index=True).iloc[:len(frame)].copy()
        window.set_reference_frame(reference)
        window.set_raw_frame(frame)
        window._populate_mappings(book.mappings)
        window.group_controls.restore({"enabled": False, "mark_enabled": False, "trend_order": "original"},
                                      pd.DataFrame({"TestFlag": [""]*len(frame)}))
        window.run_analysis()
        if stage == "final":
            window.result_mode.setCurrentText("Final")
            window.set_raw_frame(frame.copy())
            window.run_analysis()
        window.resize(1500, 950)
        window.show()
        app.processEvents()

        def ready():
            return not window._auto_run_pending and not window._raw_keyboard_timer.isActive()

        def drain():
            deadline = perf_counter()+60
            while not ready():
                assert perf_counter() < deadline, "Workbook analysis timed out"
                QTest.qWait(5)
            app.processEvents()

        def exercise(name, view, model, parameter, *, analysis=True):
            window.setup_scroll.ensureWidgetVisible(view)
            view.setFocus()
            app.processEvents()
            measure(name+"_first_select_all", view, Qt.Key.Key_A)
            bounds = model.selection_bounds()
            actual = [(r.top(), r.left(), r.bottom(), r.right()) for r in view.selectionModel().selection()]
            assert actual == ([bounds] if bounds else [])
            view.clearSelection()
            before = model.document_frame()
            before_summary = window.result.summary.copy(deep=True) if analysis else None
            column = model.source_headers().index(parameter)
            value = str(float(before.iat[0, column])+.001) if str(before.iat[0, column]).strip() else "1"
            model.edit({(1, column): value})
            drain()
            edited = model.document_frame()
            edited_summary = window.result.summary.copy(deep=True) if analysis else None
            view.setCurrentIndex(view.model().index(1, column))
            measure(name+"_first_undo", view, Qt.Key.Key_Z, until=ready if analysis else None)
            pd.testing.assert_frame_equal(model.document_frame(), before)
            if analysis:
                assert window._analysis_current
                pd.testing.assert_frame_equal(window.result.summary, before_summary)
            measure(name+"_first_redo", view, Qt.Key.Key_Y, until=ready if analysis else None)
            pd.testing.assert_frame_equal(model.document_frame(), edited)
            if analysis:
                assert window._analysis_current
                pd.testing.assert_frame_equal(window.result.summary, edited_summary)
            model.undo.undo()
            drain()

        mapping = window.selected_mappings()[0]
        if stage == "preview":
            exercise("workbook_raw", window.raw_view, window.raw_model, mapping.raw_column)
            exercise("workbook_reference", window.reference_view, window.reference_model, mapping.reference_column)
            exercise("workbook_order", window.order_view, window.group_controls.order_model, "TestFlag", analysis=False)
        else:
            preview = window.raw_model.document_frame()
            exercise("workbook_final", window.raw_view, window.final_raw_model, mapping.raw_column)
            pd.testing.assert_frame_equal(window.raw_model.document_frame(), preview)
            assert window.result.result_mode == "final"
    finally:
        window.document.force_close = True
        window.document.timer.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


def auxiliary_keys(rows, measure, app):
    """Other QTableView implementations, using their own real history paths."""
    import pandas as pd
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractItemView
    from metrology_app.auto_weighting import Cell, step_columns
    from metrology_app.auto_weighting_window import AutoWeightingWindow
    from metrology_app.dynamic_page import DynamicPivotModel, DynamicPivotView

    pivot = DynamicPivotModel()
    pivot.set_frame(pd.DataFrame(1.123456789, index=[*range(rows-1), '3 Sigma'],
                                columns=range(33)))
    view = DynamicPivotView(pivot)
    view.resize(850, 330)
    view.show()
    app.processEvents()
    measure('dynamic_first_select_all', view, Qt.Key.Key_A)
    span = view.selectionModel().selection()[0]
    assert (span.bottom(), span.right()) == (rows-1, 32)
    view.close()
    view.deleteLater()

    window = AutoWeightingWindow()
    writer_rows = min(rows, 10000)  # WriterDocument's validated row limit.
    window.writer.columns['steps'] = step_columns(20)
    window.writer.tables['parameters'] = [[Cell(text=v, reviewed=True) for v in
        (f'P{i:06}', '1.123456789000', '0', '2')] for i in range(writer_rows)]
    window.writer.tables['steps'] = [[Cell(text=v, reviewed=True) for v in
        [f'P{i:06}', *(['Fix', '1.123456789000']*20)]] for i in range(writer_rows)]
    window._refresh()
    window.resize(1000, 600)
    window.show()
    window.document.timer.stop()
    window.document.mark_clean()
    try:
        for kind in ('parameters', 'steps'):
            window.tabs.setCurrentIndex(0 if kind == 'parameters' else 1)
            table = window.views[kind]
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            app.processEvents()
            measure(f'writer_{kind}_first_select_all', table, Qt.Key.Key_A)
            span = table.selectionModel().selection()[0]
            assert (span.bottom(), span.right()) == (writer_rows-1, len(window.writer.columns[kind])-1)
        baseline = window.writer.to_dict()
        table = window.views['steps']
        model = table.model()
        measure('writer_steps_single_edit', table,
                action=lambda: model.setData(model.index(0, 2), '1.987654321000'))
        assert window.writer.tables['steps'][0][2].text == '1.987654321000'
        measure('writer_steps_first_undo', table, action=window.undo,
                until=lambda: not window.document.identity_timer.isActive())
        assert window.writer.to_dict() == baseline
        measure('writer_steps_first_redo', table, action=window.redo,
                until=lambda: not window.document.identity_timer.isActive())
        assert window.writer.tables['steps'][0][2].text == '1.987654321000'
    finally:
        window.document.closed()
        window.hide()
        window.deleteLater()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[1000, 10000, 100000])
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--platform", choices=("offscreen", "windows"), default="offscreen")
    parser.add_argument("--wkb", type=Path, help="Repeat/slice the read-only Raw table to the requested sizes")
    parser.add_argument("--omit-raw-columns", nargs="*", default=[],
                        help="Explicitly omit unused Raw columns from the benchmark copy only")
    parser.add_argument("--reuse-views", action="store_true", help="Repeat on the same views, resetting only destination data/history")
    parser.add_argument("--interactions", action="store_true", help="Also measure sort/filter/hidden-row/bulk selection workflows")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--projected-edits", action="store_true")
    parser.add_argument("--accessibility", action="store_true",
                        help="Activate native Qt accessibility with a UI Automation WM_GETOBJECT request")
    parser.add_argument("--workbook-keys", action="store_true", help="Also probe first keys in subscribed Workbook grids (requires --wkb)")
    parser.add_argument("--workbook-only", action="store_true", help="Probe Workbook keys in a fresh process without earlier Sheet interactions")
    parser.add_argument("--workbook-stage", choices=("preview", "final"), default="preview")
    parser.add_argument("--auxiliary-only", action="store_true", help="Probe Dynamic pivot and AutoWeighting Writer tables")
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
        if args.omit_raw_columns:
            from metrology_app.matching import MatchWorkbook
            book = MatchWorkbook.from_snapshot(load_workspace(args.wkb))
            missing = set(args.omit_raw_columns) - set(source.columns)
            mapped = {mapping.raw_column for mapping in book.mappings} & set(args.omit_raw_columns)
            if missing or mapped:
                parser.error(f"Cannot omit missing or mapped Raw columns: {sorted(missing | mapped)}")
            source = source.drop(columns=args.omit_raw_columns)
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
            if args.workbook_only or args.auxiliary_only:
                views = ()
            elif iteration == 0 or not args.reuse_views:
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
                    host = sheet_probe_host(widget) if isinstance(widget, SheetView) else widget
                    if host is not widget:
                        widget._benchmark_host = host
                    apply_theme(host)
                    host.resize(850, 330)
                    host.show()
            else:
                target.load_matrix([])
            app.processEvents()
            if args.platform == "windows":
                assert all(widget.window().windowHandle().isExposed() for widget in views)
            if args.screenshot and iteration == 0 and views:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                view.grab().save(str(args.screenshot.with_name(f"{args.screenshot.stem}-{rows}.png")))

            def measure(name, widget, key=None, control=True, *, action=None, until=None):
                if args.accessibility:
                    if args.platform != "windows":
                        parser.error("--accessibility requires --platform windows")
                    import ctypes
                    from ctypes import wintypes
                    send = ctypes.WinDLL("user32", use_last_error=True).SendMessageW
                    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                    send.restype = ctypes.c_ssize_t
                    send(int(widget.window().winId()), 0x003D, 0, -25)
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
                dispatch = (perf_counter() - start)*1000
                if until is not None:
                    deadline = perf_counter()+60
                    while not until():
                        assert perf_counter() < deadline, f"{name} did not complete"
                        QTest.qWait(5)
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
                                "dispatch_ms": dispatch,
                                "cpu_ms": (process_time() - cpu) * 1000,
                                "max_gap_ms": max(b - a for a, b in zip(ticks, ticks[1:])) * 1000,
                                **memory_info()})
                if name.startswith("workbook_"):
                    print(json.dumps({"operation": name, "wall_ms": (end-start)*1000,
                                      "dispatch_ms": dispatch}), flush=True)
                if profiler is not None:
                    report = args.output.with_name(f"{args.output.stem}-{rows}-{iteration}-{name}.profile.txt")
                    with report.open("w", encoding="utf-8") as stream:
                        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)

            try:
                if args.auxiliary_only:
                    auxiliary_keys(rows, measure, app)
                    continue
                if args.workbook_only:
                    if args.wkb is None:
                        parser.error("--workbook-only requires --wkb")
                    workbook_keys(frame, args.wkb, measure, app, stage=args.workbook_stage)
                    continue
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
                if args.workbook_keys and iteration == 0:
                    if args.wkb is None:
                        parser.error("--workbook-keys requires --wkb")
                    workbook_keys(frame, args.wkb, measure, app, stage=args.workbook_stage)
                print(json.dumps({"rows": rows, "iteration": iteration, "exact_text_and_undo": "pass"}), flush=True)
            finally:
                if not args.reuse_views or iteration == args.count - 1 or sys.exc_info()[0] is not None:
                    for widget in views:
                        widget.window().close()
                        widget.window().deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    app.processEvents()
    assert digest(settings) == before, "Real settings changed during the benchmark"
    assert args.wkb is None or digest(args.wkb) == source_hash, "Source workbook changed"
    summary = []
    for rows, name in dict.fromkeys((row["rows"], row["operation"]) for row in samples):
        group = [row for row in samples if row["rows"] == rows and row["operation"] == name]
        result = {"rows": rows, "operation": name, "count": len(group)}
        for key in ("wall_ms", "dispatch_ms", "cpu_ms", "max_gap_ms", "rss", "private", "peak"):
            values = sorted(row[key] for row in group if row[key] is not None)
            result[key] = ({"p50": statistics.median(values),
                            "p95": values[math.ceil(len(values) * .95) - 1], "max": max(values)}
                           if values else None)
        summary.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"count": args.count, "columns": len(frame.columns),
                                      "environment": environment, "reuse_views": args.reuse_views,
                                      "projected_edits": args.projected_edits,
                                      "workbook_stage": args.workbook_stage if args.workbook_only or args.workbook_keys else None,
                                      "auxiliary_only": args.auxiliary_only,
                                      "auxiliary_dimensions": ({"dynamic_columns": 33, "writer_rows": min(args.rows[-1], 10000),
                                                                 "writer_parameter_columns": 4, "writer_step_columns": 41}
                                                                if args.auxiliary_only else None),
                                      "accessibility_requested": args.accessibility,
                                      "generic_sheet_host": "QWidget",
                                      "source_path": str(args.wkb) if args.wkb else None,
                                      "source_sha256": source_hash,
                                      "omitted_raw_columns": args.omit_raw_columns,
                                      "code_root": str(args.code_root.resolve()),
                                      "profile_actions": args.profile_actions,
                                      "fixture": "Exact text; repeated wafers/dies; high precision; empty values",
                                      "measurement": "Synchronous Qt event + viewport paint, not compositor FPS; process peak includes setup",
                                      "settings_sha256": before, "samples": samples, "summary": summary}, indent=2),
                           encoding="utf-8")


if __name__ == "__main__":
    main()

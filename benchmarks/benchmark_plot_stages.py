"""Bounded plot-stage probe, reusing the existing map and Dynamic fixtures.

Run with -m so benchmarks/__init__.py isolates every persistence path. Stage
spans are inclusive and can overlap; they must not be added together. Native
Qt paint completion is measured, not compositor frame rate. Profile separately.
"""
import argparse
from contextlib import ExitStack
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter, process_time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wkb", required=True, type=Path)
    parser.add_argument("--code-root", type=Path, default=Path.cwd())
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--only", nargs="*", help="Time these actions; still initialize all fixtures")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", choices=("dynamic_font", "map_caption", "radius_caption"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.code_root.resolve()))
    import numpy as np
    import pandas as pd
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
    import metrology_app
    from metrology_app import correlation_page, dynamic_page, dynamic_trend, radius_page
    from metrology_app.array_plot import ArrayOptions, prepare_array
    from metrology_app.dynamic_page import DynamicPage
    from metrology_app.dynamic_trend import DynamicTrendPage
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.plot_page import PlotPage
    from metrology_app.plotting.grid import PanelGrid
    from metrology_app.radius_page import RadiusPage
    from metrology_app.wafer_graphics import WaferMapGrid as WaferGrid
    from metrology_app.radius_graphics import RadiusGrid
    from benchmarks.benchmark_correlation_restore import memory_info
    from tests.test_wafer_static import map_fixture
    assert Path(metrology_app.__file__).resolve().parent.parent == args.code_root.resolve()
    app = QApplication.instance() or QApplication([])
    source_hash = hashlib.sha256(args.wkb.read_bytes()).hexdigest()
    windows, records, spans, gaps = [], {}, {}, []
    last_tick = perf_counter()

    def tick():
        nonlocal last_tick
        now = perf_counter()
        gaps.append((now - last_tick) * 1000)
        last_tick = now

    heartbeat = QTimer(interval=10)
    heartbeat.timeout.connect(tick)
    heartbeat.start()

    def settle():
        app.processEvents()
        for window in windows:
            if window.isVisible():
                window.repaint()
        app.processEvents()

    def hook(owner, name, category):
        original = getattr(owner, name)

        def timed(*a, **kw):
            start = perf_counter()
            try:
                return original(*a, **kw)
            finally:
                spans[category] = spans.get(category, 0) + (perf_counter() - start) * 1000
        return patch.object(owner, name, timed)

    def measure(name, action):
        nonlocal last_tick
        if args.only and name not in args.only:
            action(0)
            settle()
            return
        samples = []
        for index in range(args.count + 1):
            settle()
            spans.clear()
            gaps.clear()
            last_tick = perf_counter()
            profiler = cProfile.Profile()
            if args.profile == name:
                profiler.enable()
            start, cpu = perf_counter(), process_time()
            action(index)
            direct = (perf_counter() - start) * 1000
            settle()
            painted = (perf_counter() - start) * 1000
            loop = QEventLoop()
            QTimer.singleShot(25, loop.quit)
            loop.exec()
            profiler.disable()
            sample = dict(direct_ms=direct, paint_complete_ms=painted,
                          cpu_ms=(process_time() - cpu) * 1000,
                          max_gap_ms=max(gaps, default=0), spans_ms=dict(spans),
                          memory=memory_info())
            if index:
                samples.append(sample)
            if args.profile == name and index == 1:
                with args.output.with_suffix(".profile.txt").open("w", encoding="utf-8") as stream:
                    pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(45)
        records[name] = samples
        print(json.dumps({name: {k: round(float(np.median([s[k] for s in samples])), 2)
                                  for k in ("direct_ms", "paint_complete_ms", "max_gap_ms")}}), flush=True)

    def show(page):
        for window in windows:
            window.hide()
        if page not in windows:
            windows.append(page)
        page.resize(1500, 950)
        page.show()
        settle()

    def digest_arrays(arrays):
        digest = hashlib.sha256()
        for array in arrays:
            a = np.asarray(array, dtype="<f8")
            digest.update(str(a.shape).encode())
            # Canonicalize NaN payload bits while retaining each exact gap.
            a = a.copy()
            a[np.isnan(a)] = np.nan
            digest.update(a.tobytes())
        return digest.hexdigest()

    def curves(page):
        return [array for widget in page.plot_widgets
                for curve in (widget.listDataItems() + [item for view in widget.secondary_views
                              for item in view.addedItems if hasattr(item, "getData")])
                for array in curve.getData() if array is not None]

    try:
        parent = MatchingWindow()
        windows.append(parent)
        parent.load_workbook(args.wkb)
        parent.document.timer.stop()
        child = parent.open_correlation_workspace()
        child.document.timer.stop()
        windows.append(child)
        trend, correlation = child.sequence_page, child.correlation_page
        for page in (trend, correlation):
            metrics = page.selection["metrics"][:2]
            page.selector.set_selected_cells({(w, m) for w in page.selection["wafers"] for m in metrics})
        semantics = {"raw_shape": list(parent.raw_model.document_frame().shape)}
        with ExitStack() as stack:
            for page, method, category in ((trend, "_sequence_groups", "prepare"),
                                           (trend, "_metric_values", "prepare"),
                                           (trend, "render_interactive", "render"),
                                           (correlation, "render_interactive", "render")):
                stack.enter_context(hook(page, method, category))
            for name in ("pairwise_linear_fits", "source_pairwise_linear_fits"):
                stack.enter_context(hook(correlation_page, name, "prepare"))
            stack.enter_context(hook(PanelGrid, "add_panel", "layout"))
            child.tabs.setCurrentWidget(trend)
            show(child)
            measure("trend_draw", lambda _: trend.draw_plot())
            semantics["trend"] = digest_arrays(curves(trend))
            child.tabs.setCurrentWidget(correlation)
            measure("correlation_draw", lambda _: correlation.draw_plot())
            semantics["correlation"] = digest_arrays([
                a for pair in correlation.all_fits for source in pair.sources
                for a in (source.fit.x, source.fit.y, source.fit.predicted,
                          [source.fit.slope, source.fit.intercept, source.fit.rsquared])])

        parameters = ["DP", "EW", "TG", "UC", "WTH"] + [f"Model_{i}" for i in range(21)]
        frame = pd.DataFrame([
            {"Cur SME File Path": rf"C:\data\DYNAMIC\run-{cycle}\die-{die}.csv",
             "Wafer ID": "W1", "Die Seq": die,
             **{p: str(30 + i + die * .1 + cycle * .003) for i, p in enumerate(parameters)}}
            for cycle in range(1, 11) for die in range(1, 14)])
        frame.loc[26, "DP"] = ""  # A real missing-cycle gap, never interpolated.
        selection = {"wafer_column": "Wafer ID", "wafers": ["W1"], "metrics": parameters,
                     "groups": {"W1": list(range(len(frame)))}}
        dynamic, cycle = DynamicPage(), DynamicTrendPage()
        for page, module, render_methods in (
                (dynamic, dynamic_page, ("_add_comparison_plot", "_add_parameter_section", "_add_parameter_plot")),
                (cycle, dynamic_trend, ("render_interactive",))):
            page.set_input(frame, selection)
            assert page.parameter_models if page is dynamic else page.ready
            show(page)
            with ExitStack() as stack:
                for name in ("prepare_dynamic_frame", "dynamic_pivot" if page is dynamic else "cycle_trend"):
                    stack.enter_context(hook(module, name, "prepare"))
                for name in render_methods:
                    stack.enter_context(hook(page, name, "render"))
                stack.enter_context(hook(PanelGrid, "add_panel", "layout"))
                measure("dynamic_draw" if page is dynamic else "dynamic_trend_draw", lambda _: page.refresh())
        cycle.add_compare("DP")
        show(cycle)
        semantics["dynamic"] = digest_arrays([t.to_numpy(float) for t in cycle.panel_tables.values()])
        with hook(cycle, "render_interactive", "render"):
            measure("dynamic_font", lambda i: cycle.font_size.setCurrentText("16" if i % 2 else "12"))

        frame, selection = map_fixture(12, 10)
        selection["labels"] = {w: f"{w}\nPAD: ARRAY\nLOT: L001" for w in selection["wafers"]}
        frame["Die Seq"] = [str(i) for i in range(len(frame))]
        page, radius = PlotPage(), RadiusPage()
        result = None

        def prepare(_):
            nonlocal result
            result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        measure("map_prepare", prepare)
        show(page)
        with hook(WaferGrid, "relayout", "layout"):
            measure("map_render", lambda _: page.render_result(result))
        with hook(WaferGrid, "relayout", "layout"):
            measure("map_caption", lambda i: page.set_identity_labels({"pad": bool(i % 2), "lot": bool(i % 2)}))
        semantics["map"] = digest_arrays([a for scene in result["scenes"]
                                          for a in (scene["layer"][["x", "y", "value"]].to_numpy(),
                                                    scene["surface"][3].filled(np.nan))])
        radius.set_input(frame, selection)
        radius.selector.selectAll()
        show(radius)
        with ExitStack() as stack:
            for name in ("number", "signed_radius", "infer_wafer_geometry"):
                stack.enter_context(hook(radius_page, name, "prepare"))
            stack.enter_context(hook(RadiusGrid, "set_result", "render"))
            stack.enter_context(hook(RadiusGrid, "relayout", "layout"))
            measure("radius_draw", lambda _: radius.draw_plot())
        with hook(RadiusGrid, "relayout", "layout"):
            measure("radius_caption", lambda i: radius.set_identity_labels({"pad": bool(i % 2), "lot": bool(i % 2)}))
        semantics["radius"] = digest_arrays([a for source in radius.plot_sources
                                             for a in (source["radius"], source["value"])])
        assert source_hash == hashlib.sha256(args.wkb.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"code_root": str(args.code_root.resolve()),
            "qt_platform": app.platformName(), "count": args.count,
            "stage_note": "inclusive spans overlap; paint excludes compositor; first run discarded",
            "semantics": semantics, "samples": records}, indent=2), encoding="utf-8")
    finally:
        heartbeat.stop()
        for window in reversed(windows):
            if hasattr(window, "document"):
                window.document.force_close = True
                window.document.timer.stop()
            if hasattr(window, "stop"):
                window.stop()
            window.close()
            window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()

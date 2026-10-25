"""Diagnose new-window construction with existing large tables.

Run with -m so benchmarks/__init__.py isolates every persistence path.
Default holders are real workbooks. --kind sheets deliberately reproduces the
old bare-table root; --wrap-sheets uses the production-like benchmark host.
--profile is diagnostic only, never a before/after acceptance timing.
"""
import argparse
import cProfile
import ctypes
import faulthandler
import gc
import json
import os
import pstats
from pathlib import Path
from time import perf_counter, process_time

from .benchmark_correlation_restore import digest, memory_info


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kind', choices=('none', 'sheets', 'workbooks', 'projected_workbooks', 'sorted_workbooks', 'saved_workbooks', 'dict'), default='workbooks')
    p.add_argument('--rows', type=int, default=10000)
    p.add_argument('--columns', type=int, default=30)
    p.add_argument('--holders', type=int, default=1)
    p.add_argument('--count', type=int, default=1)
    p.add_argument('--profile', action='store_true')
    p.add_argument('--collect-before', action='store_true')
    p.add_argument('--sheet-view', choices=('both','source','projection'), default='both')
    p.add_argument('--wrap-sheets', action='store_true')
    p.add_argument('--uia', action='store_true')
    p.add_argument('--shell', action='store_true')
    p.add_argument('--memory-mib', type=int, default=0, help='Diagnostic resident-memory control, outside timing')
    p.add_argument('--platform', choices=('windows', 'offscreen'), default='windows')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if min(a.rows, a.columns, a.count) < 1 or min(a.holders, a.memory_mib) < 0:
        p.error('rows, columns and count must be positive; holders must be nonnegative')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ['QT_QPA_PLATFORM'] = a.platform
    from PyQt6.QtCore import QEvent, QCoreApplication, QTimer, QT_VERSION_STR
    from PyQt6.QtWidgets import QApplication
    import pandas as pd
    from metrology_app.appearance import configure_fonts
    from metrology_app.settings import apply_theme
    from metrology_app.sheet import SheetModel, SheetView
    from metrology_app.match_group_ui import ProjectedSheetModel
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.module_registry import create_default_registry
    from metrology_app.workspace_store import load_workspace
    from .benchmark_sheet_workflows import sheet_probe_host

    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    configure_fonts(app)
    paths = [Path(x) for x in ('config/settings.yaml', '.cache/p0-audit/input/nova.wkb', 'asdf.xlsx', 'matching-matplotlib.xlsx')]
    before = {str(x): digest(x) for x in paths}
    phase = 'setup'
    starts, collections, phases, ticks = {}, [], [], []
    def gc_event(event, info):
        generation = info['generation']
        if event == 'start':
            starts[generation] = perf_counter()
        else:
            collections.append(dict(phase=phase, generation=generation,
                ms=(perf_counter()-starts.pop(generation))*1000,
                collected=info['collected'], uncollectable=info['uncollectable']))
    gc.callbacks.append(gc_event)
    heartbeat = QTimer(interval=10)
    heartbeat.timeout.connect(lambda: ticks.append(perf_counter()))
    heartbeat.start()
    faulthandler.dump_traceback_later(20, repeat=True)

    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [(name,ctypes.c_ulonglong) for name in ('total','available','total_page','available_page','total_virtual','available_virtual','extended')]
    system_memory = MemoryStatus()
    system_memory.length = ctypes.sizeof(system_memory)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(system_memory))
    if a.memory_mib * 1024**2 > system_memory.available // 4:
        p.error('Diagnostic memory control exceeds one quarter of currently available memory')
    pressure = bytearray(a.memory_mib * 1024**2)
    for offset in range(0, len(pressure), 4096):
        pressure[offset] = 1
    uia_listening = bool(ctypes.windll.UIAutomationCore.UiaClientsAreListening())

    def measure(name, action):
        nonlocal phase
        phase = name
        ticks[:] = [perf_counter()]
        ci, cpu, start = len(collections), process_time(), perf_counter()
        value = action()
        end = perf_counter()
        ticks.append(end)
        report = dict(phase=name, wall_ms=(end-start)*1000,
            cpu_ms=(process_time()-cpu)*1000,
            gc_ms=sum(r['ms'] for r in collections[ci:]),
            gc_count=len(collections)-ci,
            max_gap_ms=max(y-x for x,y in zip(ticks,ticks[1:]))*1000,
            gc_counts=gc.get_count(), memory=memory_info())
        phases.append(report)
        print(json.dumps(report), flush=True)
        return value

    windows, owned = [], []
    registry = create_default_registry()
    shell = None
    if a.shell:
        from metrology_app.shell import MainWindow as Shell
        shell = Shell()
        shell.show()
        app.processEvents()
    def create_window():
        return shell.open_component('card_matching') if shell is not None else registry.create('card_matching')
    try:
        source = load_workspace(paths[1]).frames['raw']
        frame = pd.concat([source]*((a.rows+len(source)-1)//len(source)), ignore_index=True).iloc[:a.rows,:a.columns].copy()
        assert frame.shape == (a.rows, a.columns)
        expected = frame.copy(deep=True)
        for index in range(a.holders if a.kind != 'none' else 0):
            if a.kind == 'sheets':
                def hold_sheets():
                    model, target = SheetModel(), SheetModel()
                    model.load(frame)
                    projected = ProjectedSheetModel(model)
                    projected.set_rows(list(range(a.rows-1,-1,-2)))
                    views = ([SheetView(model), SheetView(target), SheetView(projected)]
                             if a.sheet_view == 'both' else [SheetView(model if a.sheet_view == 'source' else projected)])
                    owned.extend((model, target, projected))
                    for view in views:
                        if a.wrap_sheets:
                            root = sheet_probe_host(view)
                        else:
                            root = view
                        apply_theme(root)
                        root.resize(850,330)
                        root.show()
                        windows.append(root)
                    app.processEvents()
                measure(f'holders_{index}_sheets', hold_sheets)
            elif a.kind in ('workbooks', 'projected_workbooks', 'sorted_workbooks', 'saved_workbooks'):
                holder = measure(f'holders_{index}_construct', create_window)
                windows.append(holder)
                holder.document.timer.stop()
                holder._auto_run_enabled = False
                if a.kind == 'saved_workbooks':
                    assert source.shape == frame.shape, 'Saved WKB scenario uses its original dimensions'
                    measure(f'holders_{index}_load', lambda: holder.load_workbook(paths[1]))
                else:
                    measure(f'holders_{index}_load', lambda: holder.set_raw_frame(frame))
                if a.kind == 'projected_workbooks':
                    proxy = holder._group_proxies['preview']
                    proxy.set_rows(list(range(a.rows-1,-1,-2)))
                    holder.raw_view.setModel(proxy)
                elif a.kind == 'sorted_workbooks':
                    measure(f'holders_{index}_sort', lambda: holder.group_controls.change(
                        'sort',[{'table':'raw','column':'Die Seq','descending':True}]))
                    assert holder.raw_view.model() is holder._group_proxies['preview']
                    proxy = holder.raw_view.model()
                    assert sorted(proxy.rows) == list(range(1, a.rows + 1))
                    for row in (1, max(1, a.rows // 2), a.rows):
                        index = proxy.index(row, a.columns - 1)
                        source_index = proxy.mapToSource(index)
                        assert source_index.row() == proxy.rows[row - 1]
                        assert proxy.data(index) == frame.iat[source_index.row() - 1, a.columns - 1]
                holder.document.identity_timer.stop()
                holder.show()
                app.processEvents()
            else:
                measure(f'holders_{index}_dict', lambda: owned.append(
                    {(r,c):v for r,row in enumerate(frame.itertuples(index=False,name=None),1)
                     for c,v in enumerate(row) if v}))
        if a.collect_before:
            measure('explicit_gc_before', gc.collect)
        if a.uia and a.platform == 'windows':
            from ctypes import wintypes
            send = ctypes.windll.user32.SendMessageW
            send.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            send.restype = ctypes.c_ssize_t
            for window in windows:
                send(int(window.winId()),0x003D,0,-25)
        for index in range(a.count):
            profiler = cProfile.Profile()
            if a.profile:
                profiler.enable()
            new = measure(f'new_{index}_construct', create_window)
            windows.append(new)
            measure(f'new_{index}_show', lambda: (new.show(), app.processEvents(), new.repaint(), app.processEvents()))
            if a.platform == 'windows':
                assert new.windowHandle().isExposed()
            profiler.disable()
            new.document.timer.stop()
            new.document.identity_timer.stop()
            if a.profile:
                profile_path = a.output.with_name(a.output.stem + f'-{index}.profile.txt')
                with profile_path.open('w',encoding='utf-8') as stream:
                    pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(75)
            new.document.force_close = True
            new.close()
            new.deleteLater()
            windows.remove(new)
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        pd.testing.assert_frame_equal(frame, expected)
        for obj in owned:
            if type(obj) is SheetModel and obj._document_rows:
                pd.testing.assert_frame_equal(obj.document_frame(), expected)
        for window in windows:
            if isinstance(window,MatchingWindow):
                pd.testing.assert_frame_equal(window.raw_model.document_frame(),expected)
        assert before == {str(x):digest(x) for x in paths}
        result = dict(kind=a.kind,shell=a.shell,sheet_view=a.sheet_view,wrap_sheets=a.wrap_sheets,uia_requested=a.uia,memory_mib=a.memory_mib,
            uia_clients_listening=uia_listening,system_memory={name:getattr(system_memory,name) for name in ('load','total','available')},rows=a.rows,columns=a.columns,holders=a.holders,count=a.count,
            profile=a.profile,collect_before=a.collect_before,platform=app.platformName(),qt=QT_VERSION_STR,
            phases=phases,collections=collections,protected=before,exact_source_unchanged=True)
        a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    finally:
        faulthandler.cancel_dump_traceback_later()
        heartbeat.stop()
        gc.callbacks.remove(gc_event)
        for window in reversed(windows):
            if hasattr(window,'document'):
                window.document.force_close=True
                window.document.timer.stop()
                window.document.identity_timer.stop()
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
        if shell is not None:
            shell.close()
            shell.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    main()

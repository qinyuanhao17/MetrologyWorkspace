"""Repeatable Dynamic edit/undo timing; scratch settings, no user-data writes."""
from pathlib import Path
import cProfile
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings

isolate_settings()
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from metrology_app.dynamic_window import DynamicWindow


def main():
    app = QApplication.instance() or QApplication([])
    parameters = ["DP", "EW", "TG", "UC", "WTH"] + [f"Model_{i}" for i in range(21)]
    frame = pd.DataFrame([
        {"Cur SME File Path": rf"C:\data\DYNAMIC\run-{cycle}\die-{die}.csv",
         "Wafer ID": "W1", "Lot ID": "L1", "PAD Name": "P1", "Die Seq": die,
         **{name: 30 + i + die * .1 + cycle * .003 for i, name in enumerate(parameters)}}
        for cycle in range(1, 11) for die in range(1, 14)
    ])
    window = DynamicWindow()
    window.set_table(frame, "Benchmark: 10 cycles × 13 dies × 26 parameters")
    window.parameter_list.blockSignals(True)
    for index in range(window.parameter_list.topLevelItemCount()):
        item = window.parameter_list.topLevelItem(index)
        if item.text(0) in parameters:
            item.setCheckState(0, Qt.CheckState.Checked)
    window.parameter_list.blockSignals(False)
    window.update_plan()
    window.tabs.setCurrentIndex(1)
    window.resize(1500, 900)
    window.show()
    app.processEvents()
    edit_times, undo_times = [], []
    profiler = cProfile.Profile()
    if "--profile" in sys.argv:
        profiler.enable()
    for iteration in range(9):
        start = perf_counter()
        window.dynamic_page.parameter_models["DP"].edit({(0, 0): str(31 + iteration * .01)})
        window.recognize()  # Drain the normal debounce for comparable timings.
        app.processEvents()
        edit_times.append((perf_counter() - start) * 1000)
        start = perf_counter()
        window.model.undo.undo()
        window.recognize()
        app.processEvents()
        undo_times.append((perf_counter() - start) * 1000)
    profiler.disable()
    print(f"26 parameters, 130 rows; edit median {statistics.median(edit_times[1:]):.1f} ms; "
          f"undo median {statistics.median(undo_times[1:]):.1f} ms (excludes debounce delay)")
    if "--profile" in sys.argv:
        import pstats
        pstats.Stats(profiler).strip_dirs().sort_stats("cumtime").print_stats(18)
    window.model.undo.setClean()
    window.close()


if __name__ == "__main__":
    main()

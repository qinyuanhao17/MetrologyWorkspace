"""Reference Summarizer session data in the shared SQLite workspace format."""

from dataclasses import asdict
from pathlib import Path
from zipfile import BadZipFile

from PyQt6.QtCore import QSignalBlocker, Qt

from .reference_alignment import AlignmentColumns, coordinate_bias, load_alignment_output
from .trend import MAGNITUDE_RATIO_LIMIT
from .workspace_store import WorkspaceSnapshot


def cache_available_outputs(page):
    """Embed readable outputs that haven't been selected in Tab 2 yet."""
    for path in page._output_vendors:
        if path in page._datasets or path in page._saved_output_frames:
            continue
        try:
            page._saved_output_frames[path] = load_alignment_output(path)
        except (OSError, ValueError, StopIteration, BadZipFile):
            # Preserve the path so a missing output can still be loaded later.
            continue


def snapshot(window):
    page = window.alignment
    analysis = window._analysis
    if analysis is None:
        axis_mode, axis_ratio, die_column = "auto", MAGNITUDE_RATIO_LIMIT, None
        options = {"enabled": True, "follow_groups": True, "labels_enabled": True, "follow_labels": True,
                   "labels": {"pad": True, "lot": True}, "workbook_labels": {"pad": True, "lot": True},
                   "local_applied": False, "local_identities": None, "grouping": None, "flags": []}
        saved = window._saved_analysis_ui or {}
        axis_mode = saved.get("trend_axis_mode", axis_mode)
        axis_ratio = saved.get("trend_axis_ratio", axis_ratio)
        die_column = saved.get("die_columns", {}).get("raw", die_column)
        options = saved.get("analysis_options") or options
    else:
        trend = analysis.sequence_page
        axis_mode, axis_ratio = trend.axis_mode_value(), trend.axis_ratio_limit()
        die_column = analysis.die_picker.currentData()
        options = analysis.display_options.snapshot(readonly=True)
    paths = [Path(page.output_picker.itemData(index)) for index in range(page.output_picker.count())]
    active = page._dataset.path
    if active is None:
        paths.insert(0, None)
    frames, entries = {}, []
    for index, path in enumerate(paths):
        entry = {"path": str(path) if path is not None else None,
                 "vendor": page._output_vendors.get(path, "Ref")}
        entries.append(entry)
        dataset = page._datasets.get(path) if path is not None else page._dataset
        if dataset is None:
            if path in page._saved_output_frames:
                frames[f"ref.{index}"] = page._saved_output_frames[path]
            continue
        orders = ((page.ref_wafers.keys(), page.raw_wafers.keys()) if dataset is page._dataset else dataset.orders)
        entry.update(links=[[list(ref), list(raw)] for ref, raw in dataset.links.items()],
                     orders=[[None if key is None else list(key) for key in order] for order in orders],
                     plotted=bool(dataset.results), data_selection=dataset.data_selection)
        for name, sheet in (("ref", dataset.ref), ("raw", dataset.raw)):
            frames[f"{name}.{index}"] = sheet.frame()
            entry[name] = {"vendor": sheet.vendor, "rows": list(sheet.source_rows),
                           "columns": asdict(sheet.columns()),
                           "coordinate_pair": sheet.coordinate_pair.currentData()}
    report = None
    if window.report is not None:
        value = window.report
        result = asdict(value.result)
        result["output_dir"] = str(result["output_dir"])
        report = {"vendor": value.request.vendor, "files": list(map(str, value.request.files)),
                  "parent": str(value.request.output_parent), "result": result,
                  "outputs": list(map(str, value.output_files)), "issues": list(value.issue_lines)}
    return WorkspaceSnapshot(window.workspace_type, frames, {"ui": {
        "version": 2, "vendor": window.vendor_name, "files": list(map(str, window.files)),
        "checked": list(map(str, window.selected_source_files())),
        "output_parent": str(window.output_parent) if window.output_parent else None,
        "report": report, "outputs": entries, "active": str(active) if active is not None else None,
        "source_metadata": window._source_metadata,
        "fixed": page.raw_fixed.isChecked(), "basis": page.sort_basis.currentData(),
        "primary": page.primary.currentData(), "x_order": page.x_order.currentData(),
        "y_order": page.y_order.currentData(), "plot_columns": window.trend_page.columns.currentText(),
        "plot_order": window.trend_page._order, "tab": window.tabs.currentIndex(),
        "trend_axis_mode": axis_mode, "trend_axis_ratio": axis_ratio,
        "analysis_options": options, "die_columns": {"raw": die_column},
    }})


def _keys(values):
    if any(key is not None and (len(key) != 3 or not all(isinstance(part, str) for part in key))
           for key in values):
        raise ValueError("Invalid wafer identity in Reference workspace.")
    return tuple(None if key is None else tuple(key) for key in values)


def _read_sheet(snapshot, entry, name, index):
    frame = snapshot.frames[f"{name}.{index}"]
    state = entry[name]
    columns = AlignmentColumns(**state["columns"])
    if any(column is not None and column not in frame.columns
           for key, column in state["columns"].items() if key != "unit"):
        raise ValueError("A saved column mapping is missing from its measurement table.")
    rows = state["rows"]
    if (len(rows) != len(frame) or any(type(row) is not int or row < 2 for row in rows)
            or len(set(rows)) != len(rows)):
        raise ValueError("Invalid source row order in Reference workspace.")
    if columns.unit not in ("", "mm", "µm", "nm"):
        raise ValueError("Invalid coordinate unit in Reference workspace.")
    return frame, state, columns


def _validate_analysis_options(options):
    from .match_groups import group_state

    if options is None:
        return
    if not isinstance(options, dict):
        raise ValueError("Invalid Reference analysis options.")
    for key in ("enabled", "follow_groups", "labels_enabled", "follow_labels", "local_applied"):
        if key in options and type(options[key]) is not bool:
            raise ValueError(f"Invalid Reference analysis option: {key}.")
    for key in ("labels", "workbook_labels"):
        labels = options.get(key, {})
        if not isinstance(labels, dict) or any(type(value) is not bool for value in labels.values()):
            raise ValueError(f"Invalid Reference analysis labels: {key}.")
    identities = options.get("local_identities")
    if identities is not None and (
        not isinstance(identities, list) or any(not isinstance(key, str) for key in identities)
    ):
        raise ValueError("Invalid Reference analysis row identities.")

    def validate_flags(flags):
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            raise ValueError("Invalid Reference analysis TestFlags.")

    validate_flags(options.get("flags", []))
    grouping = options.get("grouping")
    if grouping is not None:
        if not isinstance(grouping, dict):
            raise ValueError("Invalid Reference analysis Group settings.")
        for config in (grouping, grouping.get("applied", {})):
            if not isinstance(config, dict) or any(
                key in config and type(config[key]) is not bool
                for key in ("enabled", "use_group_card")
            ):
                raise ValueError("Invalid Reference analysis Group settings.")
            validate_flags(config.get("flags", []))
        try:
            group_state(grouping)
        except (AttributeError, KeyError, TypeError) as error:
            raise ValueError("Invalid Reference analysis Group settings.") from error


def prepare(snapshot):
    """Validate the snapshot and recover Bias data before replacing UI state."""
    from .cdsem1 import CDSEM1Result
    from .match_groups import group_state
    from .reference_merge import MergeResult
    from .reference_summary_window import ReferenceSummaryReport, ReferenceSummaryRequest, VENDOR_DETAILS

    ui = snapshot.states.get("ui", {})
    version = ui.get("version")
    if (snapshot.workspace_type != "reference_summary" or version not in (1, 2)
            or ui.get("vendor") not in VENDOR_DETAILS):
        raise ValueError("Invalid Reference Summarizer workspace.")
    if (ui["plot_columns"] not in ("1", "2", "3") or ui["plot_order"] not in ("raw", "ref", "sorted")
            or ui["basis"] not in ("field", "xy") or ui["primary"] not in ("x", "y")
            or type(ui["tab"]) is not int or not 0 <= ui["tab"] <= (7 if version == 1 else 8)
            or any(type(ui[key]) is not bool for key in ("fixed", "x_order", "y_order"))):
        raise ValueError("Invalid Reference workspace controls.")
    if version == 1 and ui["tab"] >= 4:
        ui = {**ui, "tab": ui["tab"] + 1}
    _validate_analysis_options(ui.get("analysis_options"))
    die_columns = ui.get("die_columns", {})
    if not isinstance(die_columns, dict) or any(
        value is not None and not isinstance(value, str) for value in die_columns.values()
    ):
        raise ValueError("Invalid Reference Die columns.")
    metadata = ui.get("source_metadata", {})
    if not isinstance(metadata, dict) or any(
            vendor not in VENDOR_DETAILS or not isinstance(paths, dict)
            or any(not isinstance(fields, dict)
                   or any(not isinstance(values, list) or not all(isinstance(value, str) for value in values)
                          for values in fields.values()) for fields in paths.values())
            for vendor, paths in metadata.items()):
        raise ValueError("Invalid Reference source metadata.")
    sources = tuple(map(Path, ui["files"]))
    checked = set(map(Path, ui["checked"]))
    parent = Path(ui["output_parent"]) if ui["output_parent"] else None
    report = None
    if ui["report"] is not None:
        saved = ui["report"]
        vendor = saved["vendor"]
        if vendor not in VENDOR_DETAILS:
            raise ValueError("Invalid Reference report vendor.")
        request = ReferenceSummaryRequest(vendor, tuple(map(Path, saved["files"])), Path(saved["parent"]))
        result_type = CDSEM1Result if vendor == "CDSEM1" else MergeResult
        result = result_type(**{**saved["result"], "output_dir": Path(saved["result"]["output_dir"])})
        report = ReferenceSummaryReport(request, result, tuple(map(Path, saved["outputs"])), tuple(saved["issues"]))
    entries, active = {}, Path(ui["active"]) if ui["active"] else None
    for index, entry in enumerate(ui["outputs"]):
        path = Path(entry["path"]) if entry["path"] is not None else None
        if path in entries:
            raise ValueError("Duplicate Ref output in Reference workspace.")
        if "raw" not in entry:
            entries[path] = (entry["vendor"], snapshot.frames.get(f"ref.{index}"), None)
            continue
        ref, ref_state, ref_columns = _read_sheet(snapshot, entry, "ref", index)
        raw, raw_state, raw_columns = _read_sheet(snapshot, entry, "raw", index)
        links = dict(zip(_keys([link[0] for link in entry["links"]]),
                         _keys([link[1] for link in entry["links"]])))
        if (None in links or None in links.values() or len(links) != len(entry["links"])
                or len(set(links.values())) != len(links)):
            raise ValueError("The saved wafer links must be one-to-one.")
        orders = tuple(_keys(order) for order in entry["orders"])
        results = []
        if entry["plotted"]:
            results = coordinate_bias(ref, raw, ref_columns, raw_columns, links,
                                      ref_source_rows=ref_state["rows"], raw_source_rows=raw_state["rows"], notes=[])
            if not results:
                raise ValueError("Saved XY Bias results could not be recovered.")
        data_selection = group_state({'data_selection': entry.get('data_selection')})['data_selection']
        entries[path] = (entry["vendor"], ref, (ref_state, raw, raw_state, links, orders, results, data_selection))
    if active not in entries or entries[active][2] is None:
        raise ValueError("Reference workspace has no active data sheet.")
    return ui, sources, checked, parent, report, entries, active


def _restore_sheet(sheet, frame, state):
    with QSignalBlocker(sheet):
        sheet.set_frame(frame, state["vendor"])
        sheet.source_rows = state["rows"].copy()
        with QSignalBlocker(sheet.coordinate_pair):
            sheet.coordinate_pair.setCurrentIndex(sheet.coordinate_pair.findData(state["coordinate_pair"]))
        for name, value in state["columns"].items():
            combo = sheet.pickers[name]
            combo.setCurrentIndex(combo.findData(value))


def install(window, prepared):
    ui, sources, checked, parent, report, entries, active = prepared
    with QSignalBlocker(window.vendor):
        window.vendor.setCurrentText(ui["vendor"])
    window._vendor_changed()
    window.output_parent = parent
    window._source_metadata = ui.get("source_metadata", {})
    window.set_source_files(sources)
    with QSignalBlocker(window.source_list):
        for index, path in enumerate(window.files):
            window.source_list.item(index).setCheckState(
                Qt.CheckState.Checked if path in checked else Qt.CheckState.Unchecked)
    window._update_source_selection()
    if report is not None:
        window._show_report(report)

    page, trend = window.alignment, window.trend_page
    with QSignalBlocker(page.output_picker), QSignalBlocker(trend.output_picker):
        page.output_picker.clear()
    page._datasets.clear()
    page._output_vendors.clear()
    page._saved_output_frames.clear()
    while page.sheet_stack.count():
        widget = page.sheet_stack.widget(0)
        page.sheet_stack.removeWidget(widget)
        widget.deleteLater()
    page._add_outputs(((path, saved[0]) for path, saved in entries.items() if path is not None), select=False)
    for path, (_, ref, state) in entries.items():
        if state is None:
            if ref is not None:
                page._saved_output_frames[path] = ref
            continue
        ref_state, raw, raw_state, links, orders, results, data_selection = state
        dataset = page._new_dataset()
        dataset.path, dataset.links, dataset.orders, dataset.results = path, links, orders, results
        dataset.data_selection = data_selection
        _restore_sheet(dataset.ref, ref, ref_state)
        _restore_sheet(dataset.raw, raw, raw_state)
        if path is not None:
            page._datasets[path] = dataset
        if path == active:
            page._dataset = dataset

    page.raw_fixed.setChecked(ui["fixed"])
    for picker, key in ((page.sort_basis, "basis"), (page.primary, "primary"),
                        (page.x_order, "x_order"), (page.y_order, "y_order")):
        picker.setCurrentIndex(picker.findData(ui[key]))
    with QSignalBlocker(trend.columns):
        trend.columns.setCurrentText(ui["plot_columns"])
    trend._order = ui["plot_order"]
    page.sheet_stack.setCurrentWidget(page._dataset.sheets)
    page._set_output_indexes(page.output_picker.findData(str(active)) if active is not None else -1)
    page._rebuild_wafer_lists(page._dataset.orders)
    trend.source_output = active
    trend.show_results(page.results, defer=ui["tab"] != 2)
    page.active_output_changed.emit(active)
    window._saved_analysis_ui = ui
    page.alignment_changed.emit()
    window._restore_analysis_controls()
    window.tabs.setCurrentIndex(ui["tab"])
    window._analysis_tab_opened(ui["tab"])

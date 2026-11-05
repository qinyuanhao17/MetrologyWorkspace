"""Portable Spectra child drafts inside an existing Match Workbook container."""
from dataclasses import asdict
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import base64
import json
import zlib

import numpy as np
import pandas as pd

from .sme_spectra import ChannelKey, LoadIssue, LoadResult, SpectrumChannel, SpectrumFile, SpectrumIdentity
from .spectra_plots import WaferChannelKey
from .workspace_store import WorkspaceSnapshot, json_text


def _key(value):
    value = dict(value)
    value["channel"] = ChannelKey(**value["channel"])
    return WaferChannelKey(**value)


def encode_sources(sources, cache=None, cancelled=None):
    cache = cache or {}
    retained = {}
    for source in sources:
        if cancelled and cancelled():
            break
        version = source.key, id(source)
        record = cache.get(version)
        if record is None:
            metadata = {name: getattr(source, name) for name in
                        ("key", "size_bytes", "mtime_ns", "embedded_filename", "x_mm", "y_mm", "coordinate_source")}
            metadata.update(path=str(source.path), identity=asdict(source.identity),
                            channels=[{"metadata": c.metadata, "spectrum_type": c.spectrum_type} for c in source.channels])
            arrays = {f"{i}_{field}": getattr(channel, field)
                      for i, channel in enumerate(source.channels) for field in ("numeric", "wavelength")}
            stream = BytesIO()
            np.savez(stream, **arrays)
            record = (source.key, json_text(metadata), base64.b64encode(zlib.compress(stream.getvalue(), 1)).decode("ascii"))
        retained[version] = record
    return retained


def snapshot(viewer):
    if viewer.spec_save_type == "paths":
        records = [(source.key, json_text({"path": str(source.path)}), "") for source in viewer.catalog.spectra]
        records.extend(viewer._unavailable_paths.values())
    else:
        if viewer._unavailable_paths:
            raise ValueError("Cannot embed unavailable spectra. Restore the missing SME files or save Paths Only.")
        retained = encode_sources(viewer.catalog.spectra, getattr(viewer, "_workbook_samples", {}))
        viewer._workbook_samples = retained
        records = list(retained.values())
    panels = {**viewer.plot_panels, **viewer.mueller_panel.mij_plots}
    ui = {"version": 1, "save_type": viewer.spec_save_type,
          "checked": sorted(viewer._checked_keys | viewer._unavailable_checked), "selected": sorted(viewer._selected_keys),
          "baseline": viewer._baseline_key, "analysis": viewer.analysis_mode,
          "group_by": viewer.group_by_combo.currentData(), "color_by": viewer._color_mode,
          "data_selection": deepcopy(viewer._data_selection_view),
          "test_flags": dict(viewer.test_flags), "verify_spectra_time": viewer.verify_spectra_time_action.isChecked(),
          "test_flag_values": list(viewer.test_flag_values), "test_flag_grouping": list(viewer.test_flag_grouping),
          "views": {name: action.isChecked() for name, action in viewer.view_actions.items()},
          "colors": [[asdict(key), color.rgba()] for key, color in viewer._channel_colors.items()],
          "hidden": [asdict(key) for key in viewer._hidden_channel_keys],
          "expanded": [list(path) for path in viewer._expanded_paths],
          "ranges": {name: {**_view_state(panel.plot.getViewBox()),
                             "secondary": _view_state(panel.secondary) if panel.secondary is not None else None}
                     for name, panel in panels.items()},
          "splitters": [splitter.sizes() for splitter in _splitters(viewer)],
          "issues": [{"path": str(issue.path), "status": issue.status, "message": issue.message} for issue in viewer.catalog.issues]}
    return WorkspaceSnapshot("spectra_viewer", {"spectra": pd.DataFrame(records, columns=["source", "metadata", "samples"])}, {"ui": ui})


def _view_state(view):
    automatic = [float(value) for value in view.autoRangeEnabled()]
    return {"range": [None if auto else [float(value) for value in limits]
                      for auto, limits in zip(automatic, view.viewRange())], "auto": automatic}


def _splitters(viewer):
    return (viewer.main_splitter, viewer.legend_splitter, viewer.plot_splitter, viewer.left_plot_splitter,
            viewer.mueller_panel.plot_splitter, *viewer.mueller_panel.row_splitters)


def _restore_range(view, saved):
    limits = {axis: value for axis, value in zip(("xRange", "yRange"), saved["range"]) if value is not None}
    if limits:
        view.setRange(**limits, padding=0)
    view.enableAutoRange(x=saved["auto"][0], y=saved["auto"][1])


def _validate_ui(viewer, draft):
    """Reject unsupported controls before replacing any live source data."""
    ui = draft.states.get("ui", {})
    if ui.get("save_type", "embedded") not in ("embedded", "paths"):
        raise ValueError("Invalid Spectra save type.")
    flags = ui.get("test_flags", {})
    values = ui.get("test_flag_values", [0, 1, -1])
    grouping = ui.get("test_flag_grouping", ["wafer", "lot", "pad"])
    if (not isinstance(flags, dict) or any(not isinstance(key, str) or type(value) is not int
                                         for key, value in flags.items())
            or type(ui.get("verify_spectra_time", True)) is not bool
            or not isinstance(values, list) or not values or values[0] != 0
            or any(type(value) is not int for value in values) or len(set(values)) != len(values)
            or not isinstance(grouping, list) or any(field not in ("wafer", "lot", "tool_sn", "pad") for field in grouping)
            or len(set(grouping)) != len(grouping)):
        raise ValueError("Invalid Spectra Info or Test Flag settings.")
    if (ui.get("version") != 1 or ui.get("analysis") not in {"original", "residual", "3sigma"}
            or ui.get("color_by") not in {"wafer", "sme"}
            or ui.get("group_by") not in {"wafer", "lot", "pad", "die"}
            or list(draft.frames["spectra"].columns) != ["source", "metadata", "samples"]):
        raise ValueError("Invalid or unsupported Spectra file settings.")
    for name in ("checked", "selected"):
        if not isinstance(ui.get(name), list) or not all(isinstance(key, str) for key in ui[name]):
            raise ValueError("Invalid spectrum selection.")
    views = ui.get("views", {})
    if set(views) != set(viewer.view_actions) or any(type(value) is not bool for value in views.values()):
        raise ValueError("Invalid Spectra views.")
    panels = {**viewer.plot_panels, **viewer.mueller_panel.mij_plots}
    for name, saved in ui.get("ranges", {}).items():
        if name not in panels:
            raise ValueError("Unknown Spectra plot.")
        for settings in (saved, saved.get("secondary")):
            if settings is None:
                continue
            if len(settings.get("range", ())) != 2 or len(settings.get("auto", ())) != 2:
                raise ValueError("Invalid Spectra axis settings.")
            if any(not isinstance(value, (bool, int, float)) or not 0 <= value <= 1 for value in settings["auto"]):
                raise ValueError("Invalid automatic axis setting.")
            for limits in settings["range"]:
                if limits is not None and (len(limits) != 2 or not np.isfinite(limits).all()):
                    raise ValueError("Invalid Spectra axis limits.")
    for sizes in ui.get("splitters", ()):
        if not all(type(size) is int and size >= 0 for size in sizes):
            raise ValueError("Invalid Spectra splitter sizes.")
    try:
        for path in ui.get("expanded", ()):
            hash(tuple(path))
        for key, rgba in ui.get("colors", ()):
            hash(_key(key))
            if type(rgba) is not int or not 0 <= rgba <= 0xffffffff:
                raise ValueError("Invalid Spectra color.")
        for key in ui.get("hidden", ()):
            hash(_key(key))
    except (TypeError, KeyError) as error:
        raise ValueError("Invalid Spectra grouping or color settings.") from error


def decode_sources(draft):
    """Decode detached arrays/references without touching Qt objects."""
    ui = draft.states["ui"]
    spectra = []
    encoded = {}
    unavailable = {}
    path_issues = []
    seen = set()
    for _source, metadata, payload in draft.frames["spectra"].itertuples(index=False, name=None):
        values = json.loads(metadata)
        if ui.get("save_type", "embedded") == "paths":
            from .sme_spectra import parse_sme_file
            if payload != "" or set(values) != {"path"} or not isinstance(values["path"], str) or _source in seen:
                raise ValueError("Invalid spectrum path reference.")
            seen.add(_source)
            try:
                source = parse_sme_file(Path(values["path"]))
                if source.key != _source:
                    raise ValueError("Spectrum path identity changed.")
            except Exception as error:
                unavailable[_source] = (_source, metadata, "")
                path_issues.append(LoadIssue(Path(values["path"]), "unavailable", f"Referenced SME unavailable: {error}"))
            else:
                spectra.append(source)
            continue
        with np.load(BytesIO(zlib.decompress(base64.b64decode(payload, validate=True))), allow_pickle=False) as arrays:
            channels = tuple(SpectrumChannel(c["metadata"], arrays[f"{i}_wavelength"].copy(),
                                             arrays[f"{i}_numeric"].copy(), c["spectrum_type"])
                             for i, c in enumerate(values.pop("channels")))
        values["path"] = Path(values["path"])
        values["identity"] = SpectrumIdentity(**values["identity"])
        source = SpectrumFile(**values, channels=channels)
        if source.key != _source or source.key in seen:
            raise ValueError("Invalid or duplicate embedded spectrum identity.")
        seen.add(source.key)
        spectra.append(source)
        encoded[source.key, id(source)] = (_source, metadata, payload)
    return spectra, encoded, unavailable, path_issues


def restore(viewer, draft):
    from PyQt6.QtGui import QColor
    _validate_ui(viewer, draft)
    ui = draft.states["ui"]
    if ui.get("version") != 1:
        raise ValueError("Unsupported Spectra Workbook draft version.")
    from .workspace_document import document_io
    decoded = (document_io(viewer, lambda: decode_sources(draft), "Opening spectra…")
               if len(draft.frames["spectra"]) > 64 else decode_sources(draft))
    spectra, encoded, unavailable, path_issues = decoded
    issues = tuple(LoadIssue(Path(i["path"]), i["status"], i["message"]) for i in ui.get("issues", ()))
    issues += tuple(path_issues)
    from .selection_script import validate_view
    from .sme_spectra import file_metadata_dataframe
    selection_frame = file_metadata_dataframe(spectra).rename(columns=lambda c: f"Raw Data / {c}")
    view = validate_view(selection_frame, ui.get("data_selection", {}))
    # Restore on an invisible window, avoiding a separate redraw for each choice.
    viewer.apply_load_result(LoadResult(tuple(spectra), issues), replace=True, allow_empty_replace=True)
    viewer.spec_save_type = ui.get("save_type", "embedded")
    viewer.spec_save_actions[viewer.spec_save_type].setChecked(True)
    viewer._unavailable_paths = unavailable
    viewer._unavailable_checked = set(ui["checked"]) & unavailable.keys()
    viewer.spec_save_actions["embedded"].setEnabled(not unavailable)
    viewer._workbook_samples = encoded
    keys = {s.key for s in spectra}
    viewer._checked_keys = set(ui["checked"]) & keys
    viewer._data_selection_view = view
    viewer.test_flags = {key: value for key, value in ui.get("test_flags", {}).items() if key in keys | unavailable.keys() and value}
    viewer.test_flag_values = list(dict.fromkeys((*ui.get("test_flag_values", [0, 1, -1]), *viewer.test_flags.values())))
    viewer.test_flag_grouping = list(ui.get("test_flag_grouping", ["wafer", "lot", "pad"]))
    viewer.verify_spectra_time_action.setChecked(ui.get("verify_spectra_time", True))
    viewer._selected_keys = set(ui["selected"]) & keys
    viewer._baseline_key = ui.get("baseline") if ui.get("baseline") in keys else None
    viewer._analysis_mode = ui.get("analysis", "original")
    if viewer._analysis_mode == "residual" and viewer._baseline_key is None:
        viewer._analysis_mode = "original"
    viewer._color_mode = ui.get("color_by", "wafer")
    for combo, value in ((viewer.group_by_combo, ui.get("group_by", "wafer")), (viewer.color_by_combo, viewer.color_mode)):
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findData(value))
        combo.blockSignals(False)
    for name, checked in ui["views"].items():
        action = viewer.view_actions[name]
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)
    viewer._channel_colors = {_key(key): QColor.fromRgba(rgba) for key, rgba in ui.get("colors", ())}
    viewer._hidden_channel_keys = {_key(key) for key in ui.get("hidden", ())}
    viewer._expanded_paths = {tuple(path) for path in ui.get("expanded", ())}
    viewer._rebuild_tree(remember_expansion=False)
    viewer._update_baseline_marker()
    viewer.analysis_actions[viewer._analysis_mode].setChecked(True)
    viewer._refresh_plots()
    viewer.select_spectrum_keys(viewer._selected_keys)
    panels = {**viewer.plot_panels, **viewer.mueller_panel.mij_plots}
    for name, saved in ui.get("ranges", {}).items():
        view = panels[name].plot.getViewBox()
        _restore_range(view, saved)
        if saved.get("secondary") is not None and panels[name].secondary is not None:
            _restore_range(panels[name].secondary, saved["secondary"])
    for splitter, sizes in zip(_splitters(viewer), ui.get("splitters", ())):
        splitter._initial_sizes_applied = True
        splitter.setSizes(sizes)


def capture(owner, scope, viewer):
    from .analysis_windows import window_metadata
    draft = snapshot(viewer)
    prior = owner._workspace_states.get(scope, {})
    owner._workspace_states[scope] = {"window": dict(window_metadata(scope, prior)), "ui": draft.states["ui"],
                                     "workspace_type": "spectra_viewer", "data_override": True}
    owner._workspace_frames[f"{scope}.spectra"] = draft.frames["spectra"]


def open_child(owner, scope):
    from PyQt6.QtCore import Qt
    from .analysis_windows import window_metadata
    from .spectra_viewer import SpectraViewerWindow
    if scope in owner._spectra_windows:
        child = owner._spectra_windows[scope]
        child.showNormal()
        child.raise_()
        return child
    child = SpectraViewerWindow()
    child.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    saved = owner._workspace_states.get(scope, {})
    try:
        if "ui" in saved:
            restore(child, WorkspaceSnapshot("spectra_viewer", {"spectra": owner._workspace_frames[f"{scope}.spectra"]}, {"ui": saved["ui"]}))
    except Exception:
        child.deleteLater()
        raise
    child._managed_scope = scope
    child._workbook_child = True
    child._spectra_workbook_owner = owner
    child.set_workbook_selection_source(owner.selection_script)
    child.set_spectra_info_source(lambda: (
        owner._effective_raw_frame(),
        owner._matching_reference(strict=True) if getattr(owner, "workbook_type", "type1") == "type2"
        else owner.reference_frame,
    ))
    child._analysis_window_name = window_metadata(scope, saved)["name"]
    child.document.refresh_identity()
    def closed(viewer):
        capture(owner, scope, viewer)
        owner._spectra_windows.pop(scope, None)
        owner.document.refresh_identity()
    child._workbook_on_close = closed
    child._workbook_embedded = True
    child.stateChanged.connect(owner.document.identity_timer.start)
    for panel in (*child.plot_panels.values(), *child.mueller_panel.mij_plots.values()):
        panel.plot.getViewBox().sigRangeChanged.connect(lambda *_: owner.document.identity_timer.start())
        if panel.secondary is not None:
            panel.secondary.sigRangeChanged.connect(lambda *_: owner.document.identity_timer.start())
    child.tree.itemSelectionChanged.connect(owner.document.identity_timer.start)
    child.group_by_combo.currentIndexChanged.connect(lambda *_: owner.document.identity_timer.start())
    for splitter in _splitters(child):
        splitter.splitterMoved.connect(lambda *_: owner.document.identity_timer.start())
    child.save_spec_action.setShortcut("")
    child.save_spec_as_action.setShortcut("")
    child.file_menu.addSeparator()
    action = child.file_menu.addAction("Save Match Workbook")
    action.setShortcut("Ctrl+S")
    action.triggered.connect(lambda: owner.save_wkb())
    save_as = child.file_menu.addAction("Save Match Workbook As…")
    save_as.setShortcut("Ctrl+Shift+S")
    save_as.triggered.connect(lambda: owner.save_wkb_dialog())
    owner._spectra_windows[scope] = child
    child.show()
    return child


def close_children(owner):
    for child in tuple(owner._spectra_windows.values()):
        child._workbook_on_close = None
        child.close()
        child.deleteLater()
    owner._spectra_windows.clear()

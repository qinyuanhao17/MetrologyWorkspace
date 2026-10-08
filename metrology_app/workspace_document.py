"""Document choices and close/recovery workflow, shared by real windows."""
from copy import deepcopy
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import os
import stat
import uuid
import weakref

import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox,
                            QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox, QSpinBox)

from .workspace_store import (EXTENSIONS, REQUIRED_FRAMES, WORKSPACE_LABELS, WorkspaceSnapshot, file_revision,
                              json_text, load_workspace, same_file, save_workspace, workspace_path)

DOCUMENTS = weakref.WeakSet()


def recovery_decision(method):
    """Keep nested Save/Open/close dialogs outside automatic recovery."""
    @wraps(method)
    def guarded(target, *args, **kwargs):
        document = getattr(target, "document", target)
        with document.pause_recovery():
            return method(target, *args, **kwargs)
    return guarded


def writable_path(path):
    return not Path(path).exists() or (bool(Path(path).stat().st_mode & stat.S_IWRITE) and os.access(path, os.W_OK))


def commit_editors(window):
    """Flush active input without processing timers or forcing an analysis draw."""
    focus = QApplication.focusWidget()
    if focus is not None and window.isAncestorOf(focus):
        for view in window.findChildren(QAbstractItemView):
            if view.viewport().isAncestorOf(focus):
                view.commitData(focus)
                break
        if focus is getattr(window, "formula", None):
            window.edit_formula()
        focus.clearFocus()
    for control in window.findChildren(QAbstractSpinBox):
        control.interpretText()
    for child in tuple(getattr(window, "_stage_windows", ())):
        if hasattr(child, "document"):
            commit_editors(child)


def local_ui(ui):
    ui = deepcopy(ui)
    for key in ("trend_axis_ratio", "trend_axis_mode"):
        ui.get("selection", {}).pop(key, None)
    for key in ("axis_ratio", "axis_mode"):
        ui.get("pages", {}).get("sequence_page", {}).get("controls", {}).pop(key, None)
    return ui


def local_snapshot(window, snapshot=None):
    snapshot = deepcopy(snapshot or window.workspace_snapshot())
    if getattr(window, "_managed_owner", None) is not None and snapshot.workspace_type == "correlation_trend":
        snapshot.states["ui"] = local_ui(snapshot.states.get("ui", {}))
    return snapshot


def pack_snapshot(container, name, snapshot):
    """Recovery references ordinary frame tables, never embeds DataFrames in JSON."""
    references = {}
    for key, frame in snapshot.frames.items():
        stored = f"__recovery__.{name}.{key}"
        container.frames[stored] = frame.copy(deep=True)
        references[key] = stored
    return {"workspace_type": snapshot.workspace_type, "frames": references,
            "states": deepcopy(snapshot.states)}


def unpack_snapshot(container, description, *, copy=True):
    kind = description["workspace_type"]
    frames = {key: container.frames[value] for key, value in description["frames"].items()}
    states = description["states"]
    if kind not in REQUIRED_FRAMES or not REQUIRED_FRAMES[kind].issubset(frames) or not isinstance(states, dict):
        raise ValueError("Invalid recovery snapshot.")
    if copy:
        frames = {key: frame.copy(deep=True) for key, frame in frames.items()}
        states = deepcopy(states)
    return WorkspaceSnapshot(kind, frames, states)


def legacy_match_recovery(live, baseline):
    """Split old flat child snapshots only when the original saved scope proves its baseline."""
    from .matching import MatchWorkbook
    accepted = deepcopy(live)
    accepted.states.pop("recovery", None)
    children = {}
    for scope, state in live.states.items():
        kind = {"map": "wafer_map", "dynamic": "dynamic", "correlation": "correlation_trend"}.get(scope.split(".")[0])
        if kind is None or scope.split(".")[-1] not in ("preview", "final"):
            continue
        draft_frames = {name.split(scope + ".", 1)[1]: frame.copy() for name, frame in live.frames.items()
                        if name.startswith(scope + ".")}
        if not draft_frames:
            continue
        saved = baseline.states.get(scope)
        if saved is None:
            raise ValueError("The original file has no saved baseline for a recovered analysis.")
        saved_frames = {name.split(scope + ".", 1)[1]: frame.copy() for name, frame in baseline.frames.items()
                        if name.startswith(scope + ".")}
        if not saved_frames:
            workbook = MatchWorkbook.from_snapshot(baseline)
            stage = scope.split(".")[-1]
            if kind == "wafer_map":
                saved_frames = {"input_data": workbook.stage_frame(stage, apply_card=False)}
            elif kind == "dynamic":
                saved_frames = {"input_data": workbook.dynamic_frame(stage, apply_card=False)}
            else:
                # Correlation needs both exact source tables, not a guessed alias map.
                raise ValueError("This correlation recovery has no exact saved source baseline.")
        children[scope] = {"baseline": WorkspaceSnapshot(kind, saved_frames, {"ui": saved["ui"]}),
                           "draft": WorkspaceSnapshot(kind, draft_frames, {"ui": state["ui"]})}
        accepted.states[scope] = deepcopy(saved)
        for name in tuple(accepted.frames):
            if name.startswith(scope + "."):
                del accepted.frames[name]
        for name, frame in saved_frames.items():
            accepted.frames[f"{scope}.{name}"] = frame
    for name in ("preview_map", "final_map", "preview_dynamic", "final_dynamic"):
        if name in baseline.frames:
            accepted.frames[name] = baseline.frames[name].copy()
        else:
            accepted.frames.pop(name, None)
    for field in ("workspace_selections", "correlation_selections"):
        if field in baseline.states["match"]:
            accepted.states["match"][field] = deepcopy(baseline.states["match"][field])
    return accepted, children


PAGE_NAMES = ("plot_page", "radius_page", "correlation_page", "sequence_page", "dynamic_page", "dynamic_trend")
CONTROL_NAMES = ("x_column", "y_column", "diameter", "color_map", "opacity", "labels", "points",
                 "contour", "point_outline", "fill_edge", "shared", "scale_bar", "font_size",
                 "resolution", "columns", "min_rsq", "page_size", "axis_ratio", "axis_mode", "zoom")


def _key(value):
    return tuple(_key(item) for item in value) if isinstance(value, list) else value


def analysis_state(window):
    """Capture only editable document controls, never graphics objects or caches."""
    state = {"selection": window.selection_state(), "grouping": window.group_columns(),
             "card": window.card_check.isChecked(), "tab": window.tabs.currentIndex(), "pages": {}}
    state["metadata_locks"] = {name: sorted(model.clipboard_locks)
                               for name in ("model", "reference_model")
                               if (model := getattr(window, name, None)) is not None
                               and hasattr(model, "clipboard_locks")}
    if hasattr(window, "reference_model"):
        state["reference_grouping"] = window._reference_group_columns()
    for name in PAGE_NAMES:
        page = getattr(window, name, None)
        if page is None or window.tabs.indexOf(page) < 0:
            continue
        controls = {}
        for field in CONTROL_NAMES:
            control = getattr(page, field, None)
            if isinstance(control, QCheckBox):
                controls[field] = control.isChecked()
            elif isinstance(control, QComboBox):
                controls[field] = control.currentText()
            elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
                controls[field] = control.value()
        saved = {"controls": controls}
        if hasattr(page, "parameter_filter"):
            saved["parameter_filter"] = page.parameter_filter.parameter
        if hasattr(page, "selector"):
            saved["boxes"] = [[wafer, metric] for wafer, metric in sorted(
                page.selector.selected_cells(), key=str)]
            saved["pending_draw"] = page.selector.pending_draw
        if hasattr(page, "color_range"):
            saved["color_range"] = list(page.color_range.range())
        if name == "correlation_page":
            saved["page_index"] = page.page_index
        if name == "sequence_page":
            saved["overlay"] = deepcopy(page.overlay)
            saved["source_overlay"] = [
                {"source": source, "metric": metric,
                 "comparisons": [{"source": s, "metric": m} for s, m in comparisons]}
                for (source, metric), comparisons in page.source_overlay.items()]
        if name == "dynamic_trend":
            saved["selected_dies"] = dict(page.selected_dies)
        state["pages"][name] = saved
    # Cards are plain coefficients, not pickled calibration objects.
    state["cards"] = {
        name: {"slope": card[0], "intercept": card[1]}
        for name, card in window.parameter_cards.items()}
    return state


def restore_analysis_state(window, state):
    if not isinstance(state, dict):
        raise ValueError("Invalid analysis workspace state.")
    locks = state.get("metadata_locks", {})
    for name in ("model", "reference_model"):
        model = getattr(window, name, None)
        if model is not None and hasattr(model, "set_clipboard_locks"):
            model.set_clipboard_locks(locks.get(name, []))
    for checks, field in ((window.group_checks, "grouping"),
                          (getattr(window, "reference_group_checks", {}), "reference_grouping")):
        if field not in state:
            continue
        for column, action in checks.items():
            action.blockSignals(True)
            action.setChecked(column in state[field])
            action.blockSignals(False)
    window._reset_selection = False
    if hasattr(window, "reference_model"):
        window._reset_reference_selection = False
    window.recognize()
    if hasattr(window, "reference_model"):
        # Source-aware Correlation recognizes Reference together with Raw and
        # publishes their combined plan. The ordinary single-source path still
        # needs its separate Reference choice refresh.
        if not getattr(window, "_workbook_sources", ()):
            window._populate_reference_choices()
    window.set_parameter_cards({name: (value["slope"], value["intercept"])
                                for name, value in state.get("cards", {}).items()})
    window.card_check.blockSignals(True)
    window.card_check.setChecked(bool(state.get("card", False)) and bool(window.parameter_cards))
    window.card_check.blockSignals(False)
    for name, saved in state.get("pages", {}).items():
        page = getattr(window, name, None)
        if page is None:
            continue
        for field, value in saved.get("controls", {}).items():
            control = getattr(page, field, None)
            if control is None:
                continue
            control.blockSignals(True)
            if isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QComboBox):
                control.setCurrentText(str(value))
            elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
                control.setValue(value)
            control.blockSignals(False)
        if "color_range" in saved:
            from matplotlib import colormaps
            page.color_range.blockSignals(True)
            page.color_range.set_colormap(colormaps[page.color_map.currentData()])
            page.color_range.set_range(*saved["color_range"])
            page.color_range.blockSignals(False)
        if name == "sequence_page":
            page.overlay = page._normalise_overlay(saved.get("overlay", {}))
            page.source_overlay = page._normalise_source_overlay(saved.get("source_overlay", []))
            page._source_overlay_initialised = True
        if name == "dynamic_trend":
            page.selected_dies = dict(saved.get("selected_dies", {}))
    selection = deepcopy(state.get("selection", {}))
    for name, field in (("plot_page", "map_draw"), ("radius_page", "radius_draw"),
                        ("correlation_page", "correlation_draw"), ("sequence_page", "trend_draw")):
        if state.get("pages", {}).get(name, {}).get("pending_draw") and field in selection:
            selection[field]["enabled"] = False
    window.restore_selection(selection)
    for name, saved in state.get("pages", {}).items():
        page = getattr(window, name, None)
        if page is None:
            continue
        if hasattr(page, "selector"):
            page.selector.set_selected_cells({(_key(w), m) for w, m in saved.get("boxes", [])}, notify=False)
            page.selector.pending_draw = bool(saved.get("pending_draw"))
        if hasattr(page, "parameter_filter"):
            parameter = saved.get("parameter_filter")
            if parameter in page.parameter_filter.buttons:
                page.parameter_filter.buttons[parameter].click()
        if name == "correlation_page":
            page.set_page(int(saved.get("page_index", 0)))
    window.tabs.setCurrentIndex(min(max(0, int(state.get("tab", 0))), window.tabs.count() - 1))


def same_snapshot(first, second):
    return (first.workspace_type == second.workspace_type
            and first.frames.keys() == second.frames.keys()
            and all(frame.equals(second.frames[name]) for name, frame in first.frames.items())
            and json_text(first.states) == json_text(second.states))


def recovery_directory():
    override = os.environ.get("METROLOGY_RECOVERY_DIR")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MetrologyWorkspace" / "recovery"


def apply_recovery_settings():
    """Update every open document, keeping managed-child timers stopped."""
    from .settings import get_settings
    interval = get_settings().get("recovery_interval_seconds", 120) * 1000
    for document in tuple(DOCUMENTS):
        if document.timer.interval() != interval:
            document.timer.setInterval(interval)


class WkbDocument:
    """Own the accepted snapshot, file revision and Save/Discard/Cancel decision."""

    def __init__(self, window):
        self.window = window
        self.path = None
        self.revision = None
        self.baseline = None
        self.force_close = False
        self.forced_dirty = False
        self.untrusted_recovery = False
        self.last_warning = ""
        self._last_recovery = None
        self._last_recovery_path = None
        self._recovery_future = None
        self._recovery_again = False
        self._recovery_target = None
        self._recovery_pause_depth = 0
        self.recovery_path = recovery_directory() / f"{uuid.uuid4().hex}{EXTENSIONS[window.workspace_type]}"
        DOCUMENTS.add(self)
        from .settings import get_settings
        self.timer = QTimer(window, interval=get_settings().get("recovery_interval_seconds", 120) * 1000)
        self.timer.timeout.connect(self.request_recovery)
        self.timer.start()
        self.recovery_poll = QTimer(window, interval=25)
        self.recovery_poll.timeout.connect(self._finish_recovery)
        self.identity_timer = QTimer(window, interval=300, singleShot=True)
        self.identity_timer.timeout.connect(self.refresh_identity)
        for control in window.findChildren(QComboBox):
            control.currentIndexChanged.connect(lambda *_: self.identity_timer.start())
        for control in window.findChildren(QCheckBox):
            control.toggled.connect(lambda *_: self.identity_timer.start())
        for control in window.findChildren(QAbstractSpinBox):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(lambda *_: self.identity_timer.start())
        for name in ("model", "reference_model", "raw_model", "final_raw_model"):
            model = getattr(window, name, None)
            if model is not None and hasattr(model, "changed"):
                model.changed.connect(lambda *_: self.identity_timer.start())
                if hasattr(model, "metadata_locks_changed"):
                    model.metadata_locks_changed.connect(lambda *_: self.identity_timer.start())
        for name in PAGE_NAMES:
            page = getattr(window, name, None)
            if page is not None and hasattr(page, "parameter_filter"):
                page.parameter_filter.changed.connect(lambda *_: self.identity_timer.start())
        if hasattr(window, "selection_changed"):
            window.selection_changed.connect(lambda *_: self.identity_timer.start())

    def mark_clean(self, snapshot=None):
        self._cancel_recovery()
        if snapshot is None:
            snapshot = (self.window.workspace_snapshot(readonly=True)
                        if self.window.workspace_type in ("match_workbook", "correlation_trend")
                        else self.window.workspace_snapshot())
        # Detach once, here on the GUI thread. Save/recovery still receive
        # independent snapshots; none of these read-only views escape to workers.
        self.baseline = deepcopy(snapshot)
        self.forced_dirty = False
        try:
            self.refresh_identity()
        except Exception as error:
            # Baseline is committed even when a display update fails.
            from .diagnostics import get_logger
            get_logger().warning("Saved baseline; title update failed: %s", error)
            self.last_warning = str(error)

    def is_dirty(self, snapshot=None):
        if self.forced_dirty or self.baseline is None:
            return True
        # Comparison is read-only. Normalize only the managed Correlation UI,
        # without copying its source tables and classification context twice.
        if snapshot is None:
            if self.window.workspace_type == "match_workbook":
                # Equality needs current values, not a second reconstruction of
                # a validated MatchWorkbook. Formal Save/recovery captures keep
                # their full validation; no candidate is accepted on this path.
                snapshot = self.window.workspace_snapshot(readonly=True, validate=False)
            elif self.window.workspace_type == "correlation_trend":
                snapshot = self.window.workspace_snapshot(readonly=True)
            else:
                snapshot = self.window.workspace_snapshot()
        current, baseline = snapshot, self.baseline
        if (getattr(self.window, "_managed_owner", None) is not None
                and self.window.workspace_type == "correlation_trend"):
            current = WorkspaceSnapshot(current.workspace_type, current.frames,
                {**current.states, "ui": local_ui(current.states.get("ui", {}))})
            baseline = WorkspaceSnapshot(baseline.workspace_type, baseline.frames,
                {**baseline.states, "ui": local_ui(baseline.states.get("ui", {}))})
        return not same_snapshot(current, baseline)

    def has_changes(self):
        return (self.is_dirty() or bool(getattr(self.window, "_recovered_children", {}))
                or any(child.document.is_dirty() for child in getattr(self.window, "_stage_windows", ())
                       if hasattr(child, "document")))

    def refresh_identity(self):
        owner = getattr(self.window, "_managed_owner", None)
        path = owner.document.path if owner is not None else self.path
        name = path.name if path else ("Unsaved Match Workbook" if owner is not None else "Untitled")
        stage = getattr(self.window, "_managed_scope", "").split(".")[-1].title() if owner else ""
        label = WORKSPACE_LABELS[self.window.workspace_type]
        title = f"{stage + ' ' if stage else ''}{label} — {name}"
        self.window.setWindowTitle(title + " [*]")
        self.window.setWindowModified(self.has_changes())
        info = getattr(self.window, "ownership_label", None)
        if info is not None:
            detached = " · Independent data" if getattr(self.window, "_independent_data", False) else ""
            info.setText(f"Save to: {name} · {stage + ' / ' if stage else ''}{label}{detached}")
            info.setToolTip(str(path or "No formal file has been saved yet.") +
                            ("\nIndependently edited data; Workbook source updates will not overwrite it." if detached else ""))
        if owner is not None:
            self.window.save_workspace_action.setToolTip(
                f"Save this analysis to {name}, including current Workbook data and shared settings. "
                "Other analysis drafts are not included.")
            owner.document.identity_timer.start()

    def choose_target(self, path=None):
        kind = self.window.workspace_type
        if path is None:
            default = workspace_path(self.path or f"workspace{EXTENSIONS[kind]}", kind)
            chosen, _ = QFileDialog.getSaveFileName(self.window, f"Save {WORKSPACE_LABELS[kind]}",
                                                   str(default), f"{WORKSPACE_LABELS[kind]} (*{EXTENSIONS[kind]})")
            if not chosen:
                return None
            path = chosen
        target = workspace_path(path, kind)
        if target.exists() and not same_file(target, self.path):
            load_workspace(target, expected_type=kind)
            if QMessageBox.question(self.window, "Replace workspace", f"Replace {target}?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return None
        self.protect_target(target)
        self.selected_target_revision = file_revision(target)
        return target

    def protect_target(self, target, *, copy=False):
        for document in tuple(DOCUMENTS):
            candidates = [document.path, document.recovery_path]
            if not copy and same_file(target, self.path) and same_file(document.path, self.path):
                candidates.remove(document.path)  # Ordinary saves use revision conflict protection.
            if document.path:
                candidates.append(Path(str(document.path) + ".bak"))
            if any(same_file(target, path) for path in candidates):
                raise ValueError("This target belongs to an open document, its backup or recovery draft. Choose another file.")

    @recovery_decision
    def save(self, path=None, *, save_as=False):
        commit_editors(self.window)
        owner = getattr(self.window, "_managed_close_handler", None)
        if callable(owner) and path is None:
            if getattr(self.window, "_managed_owner", None) and self.window._managed_owner.document.untrusted_recovery:
                raise ValueError("This old recovery has no reliable baseline. Save the entire Workbook As first.")
            result = owner(self.window.model.document_frame())
            if result is False:
                return None
            return result or True
        if callable(owner):
            raise ValueError("Use Export Standalone Copy, or Save Workbook As in the Match window.")
        if self.window.workspace_type == "match_workbook":
            if save_as or (path is None and self.path is None):
                return self.window.save_wkb_dialog()
            return self.window.save_workbook(path or self.path)
        target = Path(path or self.path) if path or self.path else None
        if save_as or target is None or (path is None and (target.suffix.lower() != EXTENSIONS[self.window.workspace_type]
                                               or self.untrusted_recovery
                                               or not writable_path(target))):
            target = self.choose_target()
        else:
            target = self.choose_target(target)
        if target is None:
            return None
        snapshot = self.window.workspace_snapshot()
        self.last_warning = ""
        expected = self.revision if target == self.path else self.selected_target_revision
        saved = save_workspace(target, snapshot, expected_revision=expected)
        self.last_warning = "; ".join(snapshot.warnings)
        self.path = saved.resolve()
        self.revision = snapshot.revision
        self.untrusted_recovery = False
        self.mark_clean(snapshot)
        self.remove_recovery()
        self.remember_recent()
        return saved

    def remember_recent(self):
        try:
            from .settings import remember_recent_wkb
            remember_recent_wkb(self.path)
        except Exception as error:
            from .diagnostics import get_logger
            get_logger().warning("Workspace saved/opened; recent files update failed: %s", error)

    def export_copy(self, path=None):
        commit_editors(self.window)
        if path is None:
            kind = self.window.workspace_type
            chosen, _ = QFileDialog.getSaveFileName(self.window, "Export Standalone Copy", f"analysis{EXTENSIONS[kind]}",
                                                   f"{WORKSPACE_LABELS[kind]} (*{EXTENSIONS[kind]})")
            if not chosen:
                return None
            path = chosen
        target = workspace_path(path, self.window.workspace_type)
        self.protect_target(target, copy=True)
        if target.exists():
            load_workspace(target, expected_type=self.window.workspace_type)
            if QMessageBox.question(self.window, "Replace standalone copy", f"Replace {target}?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return None
        expected = file_revision(target)
        snapshot = self.window.workspace_snapshot()
        saved = save_workspace(target, snapshot, expected_revision=expected)
        self.refresh_identity()
        self.window.statusBar().showMessage(f"Exported standalone copy: {saved}. Original document remains unchanged.", 8000)
        return saved

    def close_choice(self):
        commit_editors(self.window)
        if not self.has_changes():
            return QMessageBox.StandardButton.Discard
        owner = getattr(self.window, "_managed_owner", None)
        text = "Save changes before continuing?"
        if owner:
            text = (f"Save this analysis to {owner.document.path or 'the unsaved Match Workbook'}?\n"
                    "Save includes current Workbook data and shared settings, but not other analysis drafts.\n"
                    "Discard affects only this analysis.")
        elif self.window.workspace_type == "match_workbook":
            text = "Save this Workbook, including all open analysis drafts, before continuing?"
        return QMessageBox.question(self.window, "Unsaved workspace", text,
                                   QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                   QMessageBox.StandardButton.Cancel)

    def discard(self):
        owner = getattr(self.window, "_managed_owner", None)
        if owner is not None:
            if owner.document.untrusted_recovery:
                raise ValueError("Save the entire recovered Workbook As before discarding one analysis.")
            owner.document.write_recovery(exclude=self.window)
        else:
            self.remove_recovery()

    @recovery_decision
    def confirm_close(self):
        if self.force_close:
            return True
        commit_editors(self.window)
        if not self.has_changes():
            if getattr(self.window, "_managed_owner", None) is None:
                self.remove_recovery()
            return True
        choice = self.close_choice()
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            if not self.window.save_wkb():
                return False
        elif choice == QMessageBox.StandardButton.Discard:
            try:
                self.discard()
            except ValueError as error:
                QMessageBox.warning(self.window, "Cannot discard analysis", str(error))
                return False
        else:
            return False
        return True

    def _recovery_matches(self, current, baseline, children):
        saved = self._last_recovery
        if saved is None or self.recovery_path != self._last_recovery_path:
            return False
        info = saved.states["recovery"]
        if (info["original_path"] != str(self.path or "") or info["revision"] != self.revision
                or children.keys() != info["children"].keys()):
            return False
        live = WorkspaceSnapshot(saved.workspace_type,
            {key: frame for key, frame in saved.frames.items() if not key.startswith("__recovery__.")},
            {key: state for key, state in saved.states.items() if key != "recovery"})
        # These are read-only views of the last frozen successful write, never
        # inputs to a restore. Compare before copying/packing another payload.
        if (not same_snapshot(current, live)
                or not same_snapshot(baseline, unpack_snapshot(saved, info["baseline"], copy=False))):
            return False
        for scope, child in children.items():
            old = info["children"][scope]
            if (bool(child.get("follow_source")) != old.get("follow_source", False)
                    or any(not same_snapshot(child[role], unpack_snapshot(saved, old[role], copy=False))
                           for role in ("baseline", "draft"))):
                return False
        # Missing, replaced or externally changed recovery files must not be
        # treated as durable just because our in-memory draft is unchanged.
        return file_revision(self.recovery_path) == saved.revision

    @property
    def recovery_pending(self):
        return self._recovery_future is not None or self._recovery_again

    @contextmanager
    def pause_recovery(self):
        pending = self.recovery_pending
        self._recovery_pause_depth += 1
        self._cancel_recovery()
        try:
            yield
        finally:
            self._recovery_pause_depth -= 1
            pending = pending or self._recovery_again
            if pending and self._recovery_pause_depth:
                self._recovery_again = True
            elif pending and self.timer.isActive():
                self._recovery_again = False
                self.request_recovery()

    def _cancel_recovery(self):
        future, self._recovery_future = self._recovery_future, None
        self._recovery_again = False
        self.recovery_poll.stop()
        if future is not None:
            from .recovery import discard_result
            future.cancel()
            future.add_done_callback(discard_result)

    def request_recovery(self):
        """Automatic recovery: capture once, then prepare a candidate off-thread."""
        if getattr(self.window, "_managed_owner", None) is not None:
            return
        if self._recovery_pause_depth:
            self._recovery_again = True
            return
        if self._recovery_future is not None:
            self._recovery_again = True  # Never queue another full payload.
            return
        from .recovery import freeze_snapshot, submit_recovery
        try:
            source = (self.window.workspace_snapshot(readonly=True, validate=False)
                      if self.window.workspace_type == "match_workbook" else self.window.workspace_snapshot())
            current = freeze_snapshot(source)
            baseline = freeze_snapshot(self.baseline) if self.baseline is not None else None
            children = {scope: {"baseline": freeze_snapshot(saved["baseline"]),
                                "draft": freeze_snapshot(saved["draft"]),
                                "follow_source": bool(saved.get("follow_source"))}
                        for scope, saved in getattr(self.window, "_recovered_children", {}).items()}
            for child in getattr(self.window, "_stage_windows", ()):
                if not hasattr(child, "document"):
                    continue
                children[child._managed_scope] = {
                    "baseline": freeze_snapshot(child.document.baseline) if child.document.baseline is not None else None,
                    "draft": freeze_snapshot(child.workspace_snapshot()), "open": True,
                    "forced_dirty": child.document.forced_dirty,
                    "follow_source": bool(getattr(child, "_use_workbook_data", False))}
            target = Path(self.recovery_path).resolve()
            previous = self._last_recovery if target == self._last_recovery_path else None
            self._recovery_target = target
            self._recovery_future = submit_recovery(target, current, baseline, children,
                self.forced_dirty or baseline is None, str(self.path or ""), self.revision, previous)
            self.recovery_poll.start()
        except Exception as error:
            self.last_warning = f"Recovery draft could not be saved: {error}"
            self.window.statusBar().showMessage(self.last_warning, 8000)

    def _finish_recovery(self):
        future = self._recovery_future
        if future is None or not future.done():
            return
        self._recovery_future = None
        self.recovery_poll.stop()
        again, self._recovery_again = self._recovery_again, False
        prepared = None
        try:
            prepared = future.result()  # Already done: never wait on the GUI thread.
            if Path(self.recovery_path).resolve() != self._recovery_target:
                again = True
            elif prepared.action == "write":
                prepared.publish()
                self.recovery_path = prepared.target
                self._last_recovery = prepared.snapshot
                self._last_recovery_path = prepared.target
                self.last_warning = "; ".join(prepared.snapshot.warnings)
            elif prepared.action == "remove":
                # Don't delete a valid draft if an edit followed the capture.
                if self._last_recovery is not None or self.recovery_path.exists():
                    if self.has_changes():
                        again = True
                    else:
                        self.remove_recovery()
        except Exception as error:
            self.last_warning = f"Recovery draft could not be saved: {error}"
            self.window.statusBar().showMessage(self.last_warning, 8000)
        finally:
            if prepared is not None:
                prepared.discard()
        if again:
            self.request_recovery()

    def write_recovery(self, *, exclude=None):
        self._cancel_recovery()
        if getattr(self.window, "_managed_owner", None) is not None:
            return  # Only the owner writes one aggregate recovery.
        try:
            current = self.window.workspace_snapshot()
            children = dict(getattr(self.window, "_recovered_children", {}))
            for child in getattr(self.window, "_stage_windows", ()):
                if child is exclude or not hasattr(child, "document"):
                    continue
                draft = child.workspace_snapshot()
                if child.document.is_dirty(draft):
                    children[child._managed_scope] = {"baseline": child.document.baseline, "draft": draft,
                        "follow_source": bool(getattr(child, "_use_workbook_data", False))}
            remaining = self.is_dirty(current) or bool(children)
            if not remaining:
                self.remove_recovery()
                return
            baseline = self.baseline or current
            if self._recovery_matches(current, baseline, children):
                return
            snapshot = deepcopy(current)
            info = {"payload_version": 2, "original_path": str(self.path or ""), "revision": self.revision,
                    "baseline": pack_snapshot(snapshot, "baseline", baseline),
                    "children": {}}
            for scope, saved in children.items():
                info["children"][scope] = {role: pack_snapshot(snapshot, f"{scope}.{role}", saved[role])
                                           for role in ("baseline", "draft")}
                info["children"][scope]["follow_source"] = bool(saved.get("follow_source"))
            snapshot.states["recovery"] = info
            self.recovery_path = save_workspace(self.recovery_path, snapshot, backup=False)
            self._last_recovery = snapshot
            self._last_recovery_path = self.recovery_path
        except Exception as error:
            self.last_warning = f"Recovery draft could not be saved: {error}"
            self.window.statusBar().showMessage(self.last_warning, 8000)

    def remove_recovery(self):
        self._cancel_recovery()
        self._last_recovery = None
        self._last_recovery_path = None
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError as error:
            # Cleanup failure must not turn a successful save into a failed
            # close or escape a Qt event handler. Keep the draft recoverable.
            self.last_warning = f"Saved draft could not be cleaned up: {error}"
            self.window.statusBar().showMessage(self.last_warning, 8000)

    def closed(self):
        self._cancel_recovery()
        self.timer.stop()
        self.identity_timer.stop()
        DOCUMENTS.discard(self)

    @recovery_decision
    def recover(self, path, snapshot=None):
        self._cancel_recovery()
        snapshot = snapshot or load_workspace(path, expected_type=self.window.workspace_type)
        if "recovery" not in snapshot.states:
            raise ValueError("Select a recovery draft, or use Open to load a saved WKB.")
        info = snapshot.states.get("recovery", {})
        if info.get("payload_version") == 2:
            baseline = unpack_snapshot(snapshot, info["baseline"])
            children = {scope: {role: unpack_snapshot(snapshot, saved[role]) for role in ("baseline", "draft")}
                        for scope, saved in info.get("children", {}).items()}
            live = deepcopy(snapshot)
            live.states.pop("recovery")
            live.frames = {key: frame for key, frame in live.frames.items() if not key.startswith("__recovery__.")}
            if baseline.workspace_type != self.window.workspace_type:
                raise ValueError("Recovery baseline belongs to a different document type.")
            for scope, saved in children.items():
                parts = scope.split(".")
                expected = {"map": "wafer_map", "dynamic": "dynamic", "correlation": "correlation_trend"}.get(parts[0])
                if len(parts) != 2 or parts[1] not in ("preview", "final") or any(value.workspace_type != expected for value in saved.values()):
                    raise ValueError("Invalid recovery analysis scope.")
                if set(saved) != {"baseline", "draft"}:
                    raise ValueError("Recovery requires both accepted and draft analysis snapshots.")
                saved["follow_source"] = bool(info["children"][scope].get("follow_source"))
            if self.window.workspace_type != "match_workbook" and children:
                raise ValueError("Independent tool recovery cannot contain Workbook children.")
        else:
            live, children = snapshot, {}
            source = info.get("original_path")
            baseline = load_workspace(source, self.window.workspace_type) if source and Path(source).is_file() and file_revision(source) == info.get("revision") else None
            if self.window.workspace_type == "match_workbook" and baseline is not None:
                try:
                    live, children = legacy_match_recovery(live, baseline)
                except ValueError:
                    baseline = None
        self.window.restore_workspace(live)
        if self.window.workspace_type == "match_workbook":
            self.window._recovered_children = children
        self.path = Path(info["original_path"]).resolve() if info.get("original_path") else None
        self.revision = info.get("revision")
        if self.window.workspace_type == "match_workbook":
            self.window.workbook_path = self.path
            self.window.reveal_wkb_action.setEnabled(self.path is not None)
        self.recovery_path = Path(path).resolve()
        self.baseline = baseline
        self.untrusted_recovery = baseline is None
        self.forced_dirty = True
        self.refresh_identity()
        if self.untrusted_recovery:
            self.window.statusBar().showMessage("Old recovery has no reliable saved baseline. Save the entire document As before local Save/Discard.", 15000)

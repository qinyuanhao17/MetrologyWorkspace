"""Owned recovery inputs and one bounded background SQLite writer.

Workers prepare private, complete candidates. Only the GUI owner can publish
one, so Save/Discard/close can invalidate a result without waiting for disk IO.
No window, widget or Qt model crosses this seam.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import uuid

from .workspace_store import WorkspaceSnapshot, file_revision, load_workspace, save_workspace


# ponytail: one disk writer for all documents; rotate latest requests at the
# document seam rather than running several large copies/writes concurrently.
_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="metrology-recovery")
_SCALARS = frozenset((str, int, float, bool, type(None)))


def copy_state(value):
    """Detach JSON containers without deepcopy's memo work on every row ID."""
    kind = type(value)
    if kind in _SCALARS:
        return value
    if kind is dict:
        result = value.copy()
        for key, item in value.items():
            if type(item) not in _SCALARS:
                result[key] = copy_state(item)
        return result
    if kind is list:
        result = value.copy()
        for index, item in enumerate(value):
            if type(item) not in _SCALARS:
                result[index] = copy_state(item)
        return result
    if kind is tuple:
        if all(type(item) in _SCALARS for item in value):
            return value  # An immutable tuple of immutable values is safe to share.
        return tuple(copy_state(item) for item in value)
    return deepcopy(value)


def freeze_snapshot(snapshot):
    return WorkspaceSnapshot(snapshot.workspace_type,
        {name: frame.copy(deep=True) for name, frame in snapshot.frames.items()},
        copy_state(snapshot.states), snapshot.revision)


def _matches(current, baseline, children, saved, original_path, revision):
    from .workspace_document import same_snapshot, unpack_snapshot
    if saved is None:
        return False
    info = saved.states["recovery"]
    if (info["original_path"] != original_path or info["revision"] != revision
            or children.keys() != info["children"].keys()):
        return False
    live = WorkspaceSnapshot(saved.workspace_type,
        {key: frame for key, frame in saved.frames.items() if not key.startswith("__recovery__.")},
        {key: state for key, state in saved.states.items() if key != "recovery"})
    if (not same_snapshot(current, live)
            or not same_snapshot(baseline, unpack_snapshot(saved, info["baseline"], copy=False))):
        return False
    for scope, child in children.items():
        old = info["children"][scope]
        if (bool(child.get("follow_source")) != old.get("follow_source", False)
                or any(not same_snapshot(child[role], unpack_snapshot(saved, old[role], copy=False))
                       for role in ("baseline", "draft"))):
            return False
    return True


@dataclass
class PreparedRecovery:
    target: Path
    action: str
    expected_revision: str | None = None
    candidate: Path | None = None
    snapshot: WorkspaceSnapshot | None = None

    def discard(self):
        if self.candidate is not None:
            try:
                self.candidate.unlink(missing_ok=True)
            except OSError as error:
                logging.getLogger(__name__).warning("Private recovery candidate cleanup failed: %s", error)

    def publish(self):
        """Short owner-thread commit, retaining locks and full revision checks."""
        lock = self.target.with_name(self.target.name + ".lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
        committed = False
        try:
            if file_revision(self.target) != self.expected_revision:
                raise ValueError("Recovery changed while preparing a draft; the existing file was not overwritten.")
            os.replace(self.candidate, self.target)
            committed = True
            self.candidate = None
        finally:
            try:
                lock.unlink(missing_ok=True)
            except OSError as error:
                if not committed:
                    raise
                self.snapshot.warnings.append(f"Recovery saved, but write lock could not be removed: {error}")


def _prepare(target, current, baseline, children, forced_dirty, original_path, revision, previous):
    from .workspace_document import local_ui, pack_snapshot, same_snapshot
    if current.workspace_type == "match_workbook" and not current.states["match"]["draft"]:
        from .matching import MatchWorkbook
        try:
            MatchWorkbook.from_snapshot(current)
        except (ValueError, TypeError):
            current.states["match"]["draft"] = True
    dirty_children = {}
    for scope, child in children.items():
        if child.get("open"):
            draft, accepted = child["draft"], child["baseline"]
            if draft.workspace_type == "correlation_trend" and accepted is not None:
                draft = WorkspaceSnapshot(draft.workspace_type, draft.frames,
                    {**draft.states, "ui": local_ui(draft.states.get("ui", {}))})
                accepted = WorkspaceSnapshot(accepted.workspace_type, accepted.frames,
                    {**accepted.states, "ui": local_ui(accepted.states.get("ui", {}))})
            if not child["forced_dirty"] and accepted is not None and same_snapshot(draft, accepted):
                continue
        dirty_children[scope] = child
    baseline = baseline or current
    if not forced_dirty and not dirty_children and same_snapshot(current, baseline):
        return PreparedRecovery(target, "remove")
    old_revision = file_revision(target)
    if (_matches(current, baseline, dirty_children, previous, original_path, revision)
            and old_revision == previous.revision):
        return PreparedRecovery(target, "unchanged")
    if old_revision is not None:
        load_workspace(target, expected_type=current.workspace_type)
    snapshot = WorkspaceSnapshot(current.workspace_type, dict(current.frames), dict(current.states))
    info = {"payload_version": 2, "original_path": original_path, "revision": revision,
            "baseline": pack_snapshot(snapshot, "baseline", baseline), "children": {}}
    for scope, child in dirty_children.items():
        info["children"][scope] = {role: pack_snapshot(snapshot, f"{scope}.{role}", child[role])
                                   for role in ("baseline", "draft")}
        info["children"][scope]["follow_source"] = bool(child.get("follow_source"))
    snapshot.states["recovery"] = info
    candidate = target.with_name(f".{target.stem}-pending-{uuid.uuid4().hex}{target.suffix}")
    prepared = PreparedRecovery(target, "write", old_revision, candidate, snapshot)
    try:
        save_workspace(candidate, snapshot, backup=False)
        # Keep ready candidates out of Recover's workspace-file filter and
        # out of valid Save As targets until their owner publishes them.
        temporary = candidate.with_suffix(".tmp")
        os.replace(candidate, temporary)
        prepared.candidate = temporary
        return prepared
    except Exception:
        prepared.discard()
        raise


def submit_recovery(*args):
    # Cancelled executor work items may remain queued behind slow disk IO.
    # Hold inputs in a releasable box so cancelling a queued request also
    # releases its large frames immediately, not when that queue is drained.
    inputs = [args]
    future = _WRITER.submit(lambda: _prepare(*inputs.pop()))
    future.add_done_callback(lambda _future: inputs.clear())
    return future


def discard_result(future):
    """May run off-thread after a window closes; never touches the GUI."""
    if not future.cancelled():
        try:
            future.result().discard()
        except Exception:
            pass  # Preparation already cleaned its candidate on failure.

"""Copy checked SME originals into their source folders without overwriting."""
import os
from pathlib import Path
import shutil
from .file_paths import filesystem_path


def export_spectra(paths, destination, *, cancelled=None, progress=None, on_error=None):
    """Copy originals. An optional on_error(path, OSError) chooses retry/skip/cancel."""
    paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
    if not paths:
        raise ValueError("Check at least one spectrum to export.")
    missing = [str(path) for path in paths if not filesystem_path(path).is_file()]
    if missing and on_error is None:
        raise ValueError(f"{len(missing)} original SME files are unavailable. Restore their source files before exporting.\n" + "\n".join(missing[:10]))
    destination = Path(destination).resolve()
    try:
        common = Path(os.path.commonpath([path.parent for path in paths]))
        anchor = common.parent if common.name else common
        names = [path.relative_to(anchor) for path in paths]
    except ValueError:  # Different Windows drives retain their drive and folder names.
        names = [Path(path.drive.replace(":", "")) / path.relative_to(path.anchor) for path in paths]
    targets = [(destination / name).resolve() for name in names]
    if any(not target.is_relative_to(destination) for target in targets):
        raise ValueError("Export paths must stay inside the selected folder.")
    if len(set(targets)) != len(targets):
        raise ValueError("Checked spectra have conflicting export paths.")
    collisions = [str(target) for target in targets if filesystem_path(target).exists()]
    if collisions:
        raise ValueError("Export would overwrite existing files; choose another folder.\n" + "\n".join(collisions[:10]))
    created = []
    exported = []
    try:
        for index, (source, target) in enumerate(zip(paths, targets), 1):
            source_io, target_io = filesystem_path(source), filesystem_path(target)
            while True:
                if cancelled and cancelled():
                    raise InterruptedError("Spectrum export cancelled.")
                current_created = False
                try:
                    with source_io.open("rb") as original:
                        target_io.parent.mkdir(parents=True, exist_ok=True)
                        with target_io.open("xb") as output:
                            created.append(target)
                            current_created = True
                            shutil.copyfileobj(original, output)
                    shutil.copystat(source_io, target_io)
                except OSError as error:
                    if current_created:
                        target_io.unlink(missing_ok=True)
                        created.remove(target)
                    if on_error is None:
                        raise
                    decision = on_error(source, error)
                    if decision == "retry":
                        continue
                    if decision == "skip":
                        break
                    if decision == "cancel":
                        raise InterruptedError("Spectrum export cancelled.") from error
                    raise ValueError("Export recovery must choose retry, skip or cancel.") from error
                exported.append(target)
                break
            if progress:
                progress(index, len(paths), source.name)
    except Exception:
        for target in created:
            filesystem_path(target).unlink(missing_ok=True)
        raise
    return tuple(exported)

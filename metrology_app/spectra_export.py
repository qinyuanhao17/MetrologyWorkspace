"""Copy checked SME originals into their source folders without overwriting."""
import os
from pathlib import Path
import shutil


def export_spectra(paths, destination, *, cancelled=None, progress=None):
    paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
    if not paths:
        raise ValueError("Check at least one spectrum to export.")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
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
    collisions = [str(target) for target in targets if target.exists()]
    if collisions:
        raise ValueError("Export would overwrite existing files; choose another folder.\n" + "\n".join(collisions[:10]))
    created = []
    try:
        for index, (source, target) in enumerate(zip(paths, targets), 1):
            if cancelled and cancelled():
                raise InterruptedError("Spectrum export cancelled.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                created.append(target)
                with source.open("rb") as original:
                    shutil.copyfileobj(original, output)
            shutil.copystat(source, target)
            if progress:
                progress(index, len(paths), source.name)
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    return tuple(targets)

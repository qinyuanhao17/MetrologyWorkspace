"""Native filesystem paths, separate from user-facing source identities."""
import os
from pathlib import Path


def filesystem_path(path):
    """Accept an absolute path and support long Windows/UNC paths for I/O."""
    path = Path(path)
    text = str(path)
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)

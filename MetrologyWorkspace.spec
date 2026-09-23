# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys


root = Path(SPECPATH)
datas = [
    (str(root / "wafermap" / "theme.qss"), "wafermap"),
    (str(root / "wafermap" / "theme_light.qss"), "wafermap"),
    (str(root / "wafermap" / "assets"), "wafermap/assets"),
]
ffi = Path(sys.base_prefix) / "Library" / "bin" / "ffi.dll"
binaries = [(str(ffi), ".")] if ffi.exists() else []

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qtagg", "lmfit.models", "openpyxl", "pyqtgraph"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
    optimize=1,
)

# Qt 6 uses the Windows system ICU shim.  In the Conda-based build
# environment PyInstaller can discover a second, versioned ICU runtime from
# another environment on PATH.  Bundling that copy shadows the system DLL and
# prevents PyQt6.QtWidgets from loading on a clean machine.
conflicting_icu = {"icuuc.dll", "icudt78.dll"}
analysis.binaries = [
    entry for entry in analysis.binaries
    if Path(entry[0]).name.lower() not in conflicting_icu
]
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MetrologyWorkspace",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MetrologyWorkspace",
)

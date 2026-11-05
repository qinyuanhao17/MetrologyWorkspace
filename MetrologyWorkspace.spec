# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, copy_metadata


root = Path(SPECPATH)
datas = [
    (str(root / "metrology_app" / "theme.qss"), "metrology_app"),
    (str(root / "metrology_app" / "theme_light.qss"), "metrology_app"),
    (str(root / "metrology_app" / "assets"), "metrology_app/assets"),
    (str(root / "help"), "help"),
]
# Recognition only: bundle its pinned local model/config/attribution, not the
# unused detection/direction models or any online font download.
datas += collect_data_files("rapidocr", includes=["*.yaml", "models/PP-OCRv6_rec_small.onnx"])
datas += copy_metadata("rapidocr", recursive=True)
datas += copy_metadata("onnxruntime", recursive=True)
datas += collect_data_files("onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt", "Privacy.md"])
ffi = Path(sys.base_prefix) / "Library" / "bin" / "ffi.dll"
binaries = [(str(ffi), ".")] if ffi.exists() else []
sqlite_dll = Path(sys.base_prefix) / "Library" / "bin" / "sqlite3.dll"
if sqlite_dll.exists():
    binaries.append((str(sqlite_dll), "."))

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qtagg", "lmfit.models", "openpyxl", "lxml.etree", "pyqtgraph",
                   "rapidocr", "rapidocr.inference_engine.onnxruntime", "onnxruntime", "cv2"],
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

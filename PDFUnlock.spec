# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
if sys.platform == "win32":
    # Do not collect DLLs from unrelated software on the build machine's PATH.
    # In particular, Conda/Poppler ICU DLLs use different exports from Windows ICU.
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
    )))
license_data = [(str(root / "LICENSE"), "licenses/PDFUnlock")]
license_data.append((str(root / "THIRD_PARTY_NOTICES.txt"), "licenses"))
license_data.append((str(root / "licenses"), "licenses"))
for package in ("PySide6-Essentials", "shiboken6", "pikepdf", "pillow", "lxml", "packaging"):
    license_data += copy_metadata(package)

a = Analysis(
    [str(root / "desktop.py")],
    pathex=[str(root)],
    binaries=[],
    datas=license_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PDFUnlock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.environ.get("PDFUNLOCK_DEBUG_CONSOLE") == "1",
    icon=str(root / "assets" / "pdfunlock.ico"),
)

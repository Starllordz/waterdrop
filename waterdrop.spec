# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for the standalone Waterdrop app.

Produces a self-contained one-dir build (interpreter + dependencies + the
bundled czkawka_cli/ffmpeg/ffprobe binaries) so the end user installs nothing.
Run `python scripts/fetch_tools.py` first to populate `bin/`, then:

    pyinstaller waterdrop.spec

Output: dist/Waterdrop/ — distribute the whole folder (zip it).
"""

import glob
import os

# Bundled binaries from bin/ → placed at the bundle root, where tools.resolve()
# looks (sys._MEIPASS). Built by scripts/fetch_tools.py.
bin_files = [(f, ".") for f in glob.glob(os.path.join(SPECPATH, "bin", "*"))
             if os.path.isfile(f)]

datas = [(os.path.join(SPECPATH, "static"), "static")]

a = Analysis(
    ["launch.py"],
    pathex=[SPECPATH],
    binaries=bin_files,
    datas=datas,
    # These are imported lazily / dynamically, so name them explicitly.
    hiddenimports=["server", "scanner", "platform_tools", "tools", "version", "send2trash"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Waterdrop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Waterdrop",
)

# ─── imports ─────────────────────────────────────────────────────────
from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_dynamic_libs,
)
from PyInstaller.building.build_main import Analysis, PYZ, EXE, Splash
import os

from pathlib import Path
import os
import importlib.util
import glob

block_cipher = None

# ─── Gather everything ──────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []

hiddenimports += collect_submodules("aubio")
hiddenimports += collect_submodules("sounddevice")
hiddenimports += ["pynput"]

# 3) PySide6 core modules
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

pk_datas, pk_bins, pk_hidden = collect_all("q_materialise")
datas += pk_datas
binaries += pk_bins
hiddenimports += pk_hidden


asset_dir = Path("audiokeys") / "assets"
datas += [
    (str(p), "assets")  # ← was "audiokeys/assets"
    for p in asset_dir.glob("*")
    if p.is_file() and p.suffix.lower() != ".xcf"
]

hiddenimports += ["PySide6.QtSvg"]

binaries += collect_dynamic_libs("sounddevice")
# aubio may or may not ship shared libs; harmless if none:
binaries += collect_dynamic_libs("aubio")



# ─── Analysis ───────────────────────────────────────────────────────
block_cipher = None
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ─── PYZ ────────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── Splash (use PNG if .xcf causes issues) ────────────────────────
splash = Splash(
    os.path.join("audiokeys", "assets", "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,       # add (x, y) to show progress text during unpacking
    text_size=12,
    minify_script=True,
    always_on_top=False,
)

# ─── EXE (one-file build; include splash + splash.binaries) ─────────
exe = EXE(
    pyz,
    a.scripts,
    splash,              # include the splash target
    splash.binaries,     # and its binaries for one-file
    a.binaries,
    a.zipfiles,
    a.datas,
    name="audiokeys",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # set False if you don't want a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("audiokeys", "assets", "icon.ico"),
)
# linux.spec

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_dynamic_libs,
    collect_data_files
)
from pathlib import Path
import os
import importlib.util
import glob

block_cipher = None

# ─── Gather everything ──────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []

# 2) aubio, sounddevice, uinput, pynput
hiddenimports += collect_submodules("aubio")
hiddenimports += collect_submodules("sounddevice")
hiddenimports += ["uinput", "pynput"]

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
binaries += collect_dynamic_libs("uinput")
spec_u = importlib.util.find_spec("uinput")

if spec_u and spec_u.origin:
    _u_pkg_dir = Path(spec_u.origin).parent
    _u_libs = sorted(_u_pkg_dir.glob("_libsuinput*.so"))
    if _u_libs:
        # Put the .so at MEIPASS root (".") so pyimod03_ctypes can find it.
        binaries.append((str(_u_libs[0]), "."))
    else:
        print("WARNING: uinput native lib not found next to uinput package")
else:
    print("WARNING: uinput package not importable during spec collection")

# ─── Analysis ───────────────────────────────────────────────────
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

# ─── PYZ ────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── EXE (no splash) ───────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="audiokeys",
    debug=False,
    strip=False,
    upx=True,
    console=True,     # show the terminal on Linux
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=os.path.join("audiokeys", "assets", "icon.png"),
)

# linux.spec

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_dynamic_libs,
)
import os

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

# 4) Bundle your asset files (including splash.png so it's in dist/)
asset_dir = os.path.join("audiokeys", "assets")
for fn in ("icon.png", "splash.png"):
    src = os.path.join(asset_dir, fn)
    if os.path.exists(src):
        datas.append((src, os.path.join("audiokeys", "assets")))

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

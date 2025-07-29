# pyinstaller.spec

# ─── imports ─────────────────────────────────────────────────────────
from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_dynamic_libs,
)
import os

# ─── collect datas, bins, hiddenimports ────────────────────────────
datas, binaries, hiddenimports = [], [], []

# 2) aubio, sounddevice, uinput & pynput backends
hiddenimports += collect_submodules("aubio")
hiddenimports += collect_submodules("sounddevice")
# uinput isn’t a package, just the module name
hiddenimports += ["uinput", "pynput"]

# 3) PySide6 GUI modules
# PyInstaller’s built‑in hook for PySide6 will pick up most things,
# but we can be explicit:
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

# 4) Application assets (icon, splash, etc.)
asset_dir = os.path.join("audiokeys", "assets")
for fn in ("icon.ico", "icon.png", "splash.xcf"):
    src = os.path.join(asset_dir, fn)
    if os.path.exists(src):
        datas.append((src, os.path.join("audiokeys", "assets")))

# ─── build Analysis ─────────────────────────────────────────────────
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

# ─── create the PYZ ─────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── splash screen ─────────────────────────────────────────────────
splash = Splash(
    os.path.join("audiokeys", "assets", "splash.xcf"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=False,
)

# ─── build the EXE ──────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    splash,
    name="audiokeys",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("audiokeys", "assets", "icon.ico"),
)

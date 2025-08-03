# linux.spec — tidy, one-file build that correctly bundles python-uinput's C ext

from pathlib import Path
import os
import importlib.util
import sysconfig

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_dynamic_libs,
)

block_cipher = None

# ── Helpers ────────────────────────────────────────────────────────────────────
def add_binary(path: str | None, dest: str = "."):
    if path and os.path.exists(path):
        binaries.append((path, dest))

# ── Gather everything ──────────────────────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []

# App assets (flat files only; adjust to rglob if you add nested dirs)
asset_dir = Path("audiokeys") / "assets"
for p in sorted(asset_dir.glob("*")):
    if p.is_file() and p.suffix.lower() != ".xcf":
        datas.append((str(p), "assets"))

# Project lib that ships data/binaries
pk_datas, pk_bins, pk_hidden = collect_all("q_materialise")
datas += pk_datas
binaries += pk_bins
hiddenimports += pk_hidden

# Runtime libs / hidden imports
hiddenimports += collect_submodules("aubio")
hiddenimports += collect_submodules("sounddevice")
hiddenimports += [
    "uinput",
    "pynput",
    # Qt modules explicitly referenced
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
]

# Dynamic libraries pulled by Python modules at runtime
binaries += collect_dynamic_libs("sounddevice")  # portaudio
binaries += collect_dynamic_libs("aubio")        # aubio (if present)

# ── Ensure python-uinput's C extension is present at MEIPASS root ─────────────
# python-uinput loads a top-level module named _libsuinput via ctypes.
# It lives at site-packages/_libsuinput<EXT>.so (NOT inside the uinput/ pkg).
# PyInstaller's ctypes support will look in the MEIPASS root for this filename.
ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"

# 1) Try to locate as a top-level module
spec_su = importlib.util.find_spec("_libsuinput")
if spec_su and spec_su.origin:
    add_binary(spec_su.origin, ".")
    hiddenimports.append("_libsuinput")
else:
    # 2) Fallback: find the uinput package and look one dir up
    spec_u = importlib.util.find_spec("uinput")
    if spec_u and spec_u.origin:
        u_pkg_dir = Path(spec_u.origin).parent
        candidate = u_pkg_dir.parent / f"_libsuinput{ext_suffix}"
        if candidate.exists():
            add_binary(str(candidate), ".")
            hiddenimports.append("_libsuinput")
        else:
            print("WARNING: _libsuinput not found next to site-packages; is python-uinput installed?")
    else:
        print("WARNING: uinput package not importable during spec collection")

# ── PyInstaller build graph ───────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],                # add custom hooks here if you create any
    runtime_hooks=[],            # add runtime hooks here if needed
    excludes=[],                 # e.g. ["tkinter"] if unused
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="audiokeys",
    debug=False,
    strip=False,
    upx=False,                   # clearer on Linux; set True only if you know UPX is safe
    console=True,                # show terminal on Linux
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=os.path.join("audiokeys", "assets", "icon.png"),
)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import types

_dummy_mod = types.ModuleType("dummy")
_dummy_mod.QToolButton = type("QToolButton", (), {})
_dummy_mod.QIcon = lambda *args, **kwargs: None
_dummy_mod.QSize = lambda *args, **kwargs: None
pkg = types.ModuleType("PySide6")
pkg.QtCore = _dummy_mod
pkg.QtWidgets = _dummy_mod
pkg.QtGui = _dummy_mod
sys.modules["PySide6"] = pkg
sys.modules["PySide6.QtCore"] = _dummy_mod
sys.modules["PySide6.QtWidgets"] = _dummy_mod
sys.modules["PySide6.QtGui"] = _dummy_mod

from audiokeys.utils import generate_sample_id  # noqa: E402


def test_generate_sample_id_unique_increment():
    existing = {"tap_1", "tap_2"}
    assert generate_sample_id("tap", existing) == "tap_3"


def test_generate_sample_id_spaces_normalised():
    existing = set()
    assert generate_sample_id("my tap", existing).startswith("my_tap_1")

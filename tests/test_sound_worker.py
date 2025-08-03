"""Tests for :class:`audiokeys.sound_worker.SoundWorker`."""

from __future__ import annotations

import numpy as np

import pytest
import sys
import types

sys.modules.setdefault("sounddevice", types.SimpleNamespace())
sys.modules.setdefault(
    "utils", types.SimpleNamespace(elevate_and_setup_uinput=lambda: None)
)


class _DummySignal:
    def __init__(self, *_, **__):
        self._subs: list[object] = []

    def connect(self, func):
        self._subs.append(func)

    def emit(self, *args, **kwargs):
        for func in self._subs:
            func(*args, **kwargs)


class _DummyQThread:
    def __init__(self, *_, **__):
        pass

    def start(self) -> None:  # pragma: no cover - unused
        pass

    def wait(self, *_: object) -> None:  # pragma: no cover - unused
        pass


qt_core = types.SimpleNamespace(QThread=_DummyQThread, Signal=_DummySignal)
qt_widgets = types.SimpleNamespace(QMessageBox=object)
sys.modules.setdefault(
    "PySide6", types.SimpleNamespace(QtWidgets=qt_widgets, QtCore=qt_core)
)
sys.modules.setdefault("PySide6.QtWidgets", qt_widgets)
sys.modules.setdefault("PySide6.QtCore", qt_core)

from audiokeys import sound_worker  # noqa: E402


class DummySender:
    """Minimal ``KeySender`` replacement for testing."""

    def __init__(self, *_: object, **__: object) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def release(self, _key: str) -> None:  # pragma: no cover - behaviour trivial
        return None

    def set_send_enabled(self, _enabled: bool) -> None:  # pragma: no cover
        return None


def test_match_threshold_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """SoundWorker should honour ``match_threshold`` when processing segments."""

    monkeypatch.setattr(sound_worker, "KeySender", DummySender)

    sample = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    worker = sound_worker.SoundWorker(
        0,
        {"x": [sample]},
        {"x": "a"},
        match_threshold=0.5,
        min_press_interval=0.0,
    )
    worker._process_segment(sample)
    assert worker.sender.pressed == ["x"]

    worker.match_threshold = 1.1
    worker._process_segment(sample)
    assert worker.sender.pressed == ["x"]

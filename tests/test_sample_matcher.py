import sys
from pathlib import Path

import numpy as np
import pytest
import threading
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audiokeys.sample_matcher import (
    cosine_similarity,
    match_sample,
    record_until_silence,
)


def test_cosine_similarity_identical() -> None:
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_match_sample_returns_best_key() -> None:
    ref_a = np.array([0.1, 0.2, 0.3])
    ref_b = np.array([1.0, 0.0, -1.0])
    segment = ref_b + np.random.normal(0, 0.01, size=3)
    key, score = match_sample(segment, {"a": ref_a, "b": ref_b}, threshold=0.5)
    assert key == "b"
    assert 0.0 <= score <= 1.0


def test_match_sample_threshold_none() -> None:
    ref = np.array([1.0, 0.0, -1.0])
    segment = np.array([0.1, 0.1, 0.1])
    key, score = match_sample(segment, {"r": ref}, threshold=0.9)
    assert key is None
    assert score >= 0.0


def test_match_sample_handles_multiple_refs() -> None:
    """``match_sample`` should consider all reference samples for a key."""
    ref1 = np.array([1.0, 0.0, 0.0])
    ref2 = np.array([0.0, 1.0, 0.0])
    segment = ref2 + np.random.normal(0, 0.01, size=3)
    key, _ = match_sample(segment, {"x": [ref1, ref2]}, threshold=0.5)
    assert key == "x"


def _sine(freq: float, sr: int = 8000, dur: float = 0.1) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def test_match_sample_mfcc() -> None:
    sr = 8000
    ref_a = _sine(440, sr)
    ref_b = _sine(660, sr)
    segment = _sine(660, sr)
    key, _ = match_sample(
        segment,
        {"a": [ref_a], "b": [ref_b]},
        threshold=0.5,
        method="mfcc",
        sample_rate=sr,
    )
    assert key == "b"


def test_match_sample_dtw() -> None:
    sr = 8000
    ref_a = _sine(440, sr)
    ref_b = _sine(660, sr)
    segment = _sine(440, sr)
    key, _ = match_sample(
        segment,
        {"a": [ref_a], "b": [ref_b]},
        threshold=0.5,
        method="dtw",
        sample_rate=sr,
    )
    assert key == "a"


def test_dtw_segment_mfcc_computed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """DTW should compute the segment MFCC only once per call."""

    sr = 8000
    segment = _sine(440, sr)
    ref_a = _sine(440, sr)
    ref_b = _sine(660, sr)

    calls = 0

    original = audiokeys.librosa.feature.mfcc

    def counting_mfcc(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(audiokeys.librosa.feature, "mfcc", counting_mfcc)

    match_sample(
        segment,
        {"a": [ref_a], "b": [ref_b]},
        threshold=0.1,
        method="dtw",
        sample_rate=sr,
    )

    # Expect three calls: one for the segment and one for each reference
    assert calls == 3


def test_default_match_threshold() -> None:
    from audiokeys.constants import MATCH_THRESHOLD

    assert MATCH_THRESHOLD == pytest.approx(0.2)


def test_record_until_silence_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyStream:
        def __enter__(self) -> "DummyStream":
            return self

        def __exit__(self, *_) -> None:
            return None

        def read(self, hop: int):
            return np.zeros((hop, 1), dtype=np.float32), None

    dummy_sd = types.SimpleNamespace(InputStream=lambda **_: DummyStream())
    monkeypatch.setitem(sys.modules, "sounddevice", dummy_sd)

    stop = threading.Event()
    stop.set()
    data = record_until_silence(0, stop_event=stop)
    assert data.size == 0

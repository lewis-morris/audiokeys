"""Utility functions for sound-sample matching."""

from __future__ import annotations

from typing import Iterable, Literal, Mapping, Optional, Sequence

import sys
import threading
import types

import numpy as np

try:  # pragma: no cover - exercised indirectly
    import numba  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - runtime fallback when numba is absent
    numba = types.ModuleType("numba")

    def _decorator(*args, **kwargs):
        def wrap(func):
            return func

        if args and callable(args[0]):
            return args[0]
        return wrap

    numba.jit = _decorator  # type: ignore[attr-defined]
    numba.stencil = _decorator  # type: ignore[attr-defined]
    numba.guvectorize = _decorator  # type: ignore[attr-defined]
    sys.modules["numba"] = numba

# Supported matching techniques
DetectionMethod = Literal["waveform", "mfcc", "dtw"]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return the cosine similarity between ``a`` and ``b``."""
    if a.size == 0 or b.size == 0:
        return 0.0
    n = min(len(a), len(b))
    a = a[:n]
    b = b[:n]
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def _mfcc_mean(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Return the mean MFCC vector for ``samples``."""

    mfcc = audiokeys.librosa.feature.mfcc(y=samples, sr=sample_rate, n_mfcc=13)
    return mfcc.mean(axis=1)


def _dtw_mfcc_similarity(mfcc_a: np.ndarray, mfcc_b: np.ndarray) -> float:
    """Return similarity between two MFCC matrices using DTW.

    Args:
        mfcc_a: MFCC matrix of the segment being compared.
        mfcc_b: MFCC matrix of the reference sample.

    Returns:
        Cosine-based similarity score in the range ``0``‑``1``.
    """

    # ``librosa.sequence.dtw`` returns both the cost matrix and the alignment
    # path by default.  ``backtrack=False`` avoids computing the path which we
    # don't use, significantly reducing CPU and memory usage for long signals.
    dist = audiokeys.librosa.sequence.dtw(mfcc_a, mfcc_b, metric="cosine", backtrack=False)
    final = float(dist[-1, -1])
    return 1.0 / (1.0 + final)


def match_sample(
    segment: np.ndarray,
    samples: Mapping[str, Sequence[np.ndarray] | np.ndarray],
    *,
    threshold: float = 0.8,
    method: DetectionMethod = "waveform",
    sample_rate: int = 44_100,
) -> tuple[Optional[str], float]:
    """Return the best-matching key and its similarity score.

    Args:
        segment: Captured audio segment.
        samples: Mapping from sample identifier to one or more reference
            samples.
        threshold: Minimum similarity score required to return a match.
        method: Technique used for comparison. ``"waveform"`` performs raw
            cosine similarity, ``"mfcc"`` compares averaged MFCC vectors and
            ``"dtw"`` uses Dynamic Time Warping over MFCC sequences.
        sample_rate: Sample rate of ``segment`` and references.

    Returns:
        Tuple of ``(key, score)`` where ``key`` is the identifier of the
        best-matching sample or ``None`` if no match exceeds ``threshold`` and
        ``score`` is the similarity score of that best match.
    """

    best_key: Optional[str] = None
    best_score: float = 0.0
    # Pre-compute segment features depending on the method
    if method == "mfcc":
        segment_feat = _mfcc_mean(segment, sample_rate)
    elif method == "dtw":
        # Pre-compute MFCCs for the segment once.  Previously these were
        # calculated for every reference sample which caused significant
        # slowdown in the GUI when using DTW.
        segment_feat = audiokeys.librosa.feature.mfcc(y=segment, sr=sample_rate, n_mfcc=13)
    else:
        segment_feat = segment
    for key, refs in samples.items():
        if isinstance(refs, np.ndarray):
            iterable: Iterable[np.ndarray] = (refs,)
        else:
            iterable = refs
        for ref in iterable:
            if method == "waveform":
                score = cosine_similarity(segment_feat, ref)
            elif method == "mfcc":
                ref_feat = _mfcc_mean(ref, sample_rate)
                score = cosine_similarity(segment_feat, ref_feat)
            elif method == "dtw":
                ref_feat = audiokeys.librosa.feature.mfcc(y=ref, sr=sample_rate, n_mfcc=13)
                score = _dtw_mfcc_similarity(segment_feat, ref_feat)
            else:  # pragma: no cover - validated by type
                raise ValueError(f"Unknown method: {method}")
            if score > best_score:
                best_score = score
                best_key = key
    if best_key is not None and best_score >= threshold:
        return best_key, best_score
    return None, best_score


def record_until_silence(
    device_index: int,
    *,
    sample_rate: int = 44_100,
    hop_size: int = 1024,
    threshold: float = 0.01,
    silence_duration: float = 0.5,
    max_duration: float = 5.0,
    channels: int = 1,
    stop_event: Optional["threading.Event"] = None,
) -> np.ndarray:
    """Record audio until a period of silence is detected.

    Args:
        device_index: Index of the audio input device.
        sample_rate: Sampling rate of the device in Hertz.
        hop_size: Number of samples processed per iteration.
        threshold: RMS amplitude below which audio is considered silent.
        silence_duration: Consecutive seconds of silence required to stop.
        max_duration: Maximum length of the recording in seconds.
        channels: Number of input channels to record.
        stop_event: Optional event that, when set, aborts recording early.

    Returns:
        Recorded audio samples. An empty array is returned if no audio was
        captured.
    """
    import sounddevice as sd

    frames: list[np.ndarray] = []
    silent = 0
    required = int(silence_duration * sample_rate)
    limit = int(max_duration * sample_rate)
    with sd.InputStream(
        device=device_index,
        channels=channels,
        samplerate=sample_rate,
        blocksize=hop_size,
        dtype="float32",
    ) as stream:
        while sum(len(x) for x in frames) < limit:
            if stop_event and stop_event.is_set():
                break
            data, _ = stream.read(hop_size)
            if data.ndim == 2 and data.shape[1] > 1:
                block = data.mean(axis=1)
            else:
                block = data.reshape(-1)
            frames.append(block)
            rms = float(np.sqrt(np.mean(block**2)))
            if rms < threshold:
                silent += hop_size
                if silent >= required and sum(len(x) for x in frames) > hop_size:
                    break
            else:
                silent = 0
    if frames:
        return np.concatenate(frames)
    return np.array([], dtype=np.float32)


__all__ = ["cosine_similarity", "match_sample", "record_until_silence"]

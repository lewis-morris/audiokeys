"""Utility functions for sound-sample matching."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import threading


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


def match_sample(
    segment: np.ndarray,
    samples: Mapping[str, Sequence[np.ndarray] | np.ndarray],
    *,
    threshold: float = 0.8,
) -> Optional[str]:
    """Return the mapping key with the highest similarity to ``segment``.

    Args:
        segment: Captured audio segment.
        samples: Mapping from sample identifier to one or more reference
            samples.
        threshold: Minimum similarity score required to return a match.

    Returns:
        The identifier of the best-matching sample or ``None`` if no match
        exceeds ``threshold``.
    """
    best_key: Optional[str] = None
    best_score: float = 0.0
    for key, refs in samples.items():
        # Normalise refs to an iterable of arrays
        if isinstance(refs, np.ndarray):
            iterable: Iterable[np.ndarray] = (refs,)
        else:
            iterable = refs
        for ref in iterable:
            score = cosine_similarity(segment, ref)
            if score > best_score:
                best_score = score
                best_key = key
    if best_key is not None and best_score >= threshold:
        return best_key
    return None


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
    """Record audio until ``silence_duration`` of silence is detected.

    Recording stops early if ``stop_event`` is set.
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

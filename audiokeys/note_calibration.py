"""Utilities for calibrating note detection stability."""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np

from .constants import A4_FREQ, A4_MIDI


def _freq_to_midi(freq: float) -> float:
    """Convert frequency to MIDI number using A4 reference."""
    return 12.0 * np.log2(freq / A4_FREQ) + A4_MIDI


def calculate_midi_tolerance(pitches: Mapping[str, Iterable[float]]) -> float:
    """Return a recommended MIDI tolerance for measured pitches."""
    diffs: list[float] = []
    for freq_list in pitches.values():
        for f in freq_list:
            midi = _freq_to_midi(float(f))
            diffs.append(abs(midi - round(midi)))
    if not diffs:
        return 0.5
    return float(max(0.1, min(1.0, np.percentile(diffs, 95))))


def detect_pitch_fft(samples: np.ndarray, sample_rate: int) -> float:
    """Estimate dominant frequency of ``samples`` using FFT."""
    if samples.size == 0:
        return 0.0
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    mask = (freqs >= 50.0) & (freqs <= 2000.0)
    if not np.any(mask):
        return 0.0
    idx = int(np.argmax(spectrum[mask]))
    return float(freqs[mask][idx])


__all__ = [
    "calculate_midi_tolerance",
    "detect_pitch_fft",
]

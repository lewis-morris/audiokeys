"""Utilities for calibrating note detection stability."""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Optional

import numpy as np

from .constants import A4_FREQ, A4_MIDI, NOTE_NAMES


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


def midi_to_freq(midi: float) -> float:
    """Convert MIDI number to frequency using A4 reference."""
    return A4_FREQ * 2 ** ((midi - A4_MIDI) / 12.0)


def note_to_midi(note: str, octave: int = 4) -> int:
    """Return MIDI number for ``note`` in the given octave."""
    idx = NOTE_NAMES.index(note)
    return idx + (octave + 1) * 12


def calibrate_pitches(
    notes: Iterable[str] = NOTE_NAMES,
    *,
    duration: float = 2.0,
    sample_rate: int = 44_100,
    hop_size: int = 512,
    channels: int = 1,
    octave: int = 4,
    device: Optional[int] = None,
    record_func: Optional[
        Callable[[str, float, int, int, Optional[int]], np.ndarray]
    ] = None,
    interactive: bool = True,
) -> Mapping[str, list[float]]:
    """Interactively measure pitches for a sequence of notes.

    Parameters
    ----------
    notes:
        Iterable of note names (e.g. ``"C#"``) to record.
    duration:
        Recording time in seconds for each note.
    sample_rate:
        Sampling rate used when recording.
    hop_size:
        Frame size for pitch extraction.
    channels:
        Number of input channels to record.
    octave:
        Octave of notes being played. ``4`` corresponds to middle C.
    device:
        Optional sounddevice input device index.
    record_func:
        Custom audio capture callable used instead of ``sounddevice``.
        The callable is invoked as ``record_func(note, duration, sample_rate, channels, device)``
        and must return a ``numpy.ndarray`` of samples.
    interactive:
        When ``True`` the user is prompted before each recording.

    Returns
    -------
    Mapping[str, list[float]]
        Recorded pitch frequencies for each note.
    """
    if record_func is None:
        from sounddevice import rec, wait  # type: ignore

        def record_func(
            note: str,
            dur: float,
            rate: int,
            ch: int,
            dev: Optional[int],
        ) -> np.ndarray:
            data = rec(
                int(dur * rate),
                samplerate=rate,
                channels=ch,
                device=dev,
                dtype="float32",
            )
            wait()
            if data.ndim > 1:
                data = data.mean(axis=1)
            return data.reshape(-1)

    results: dict[str, list[float]] = {}
    for note in notes:
        attempts = 0
        while attempts < 3:
            attempts += 1
            if interactive:
                input(f"Play note {note} and press Enter to start recording…")
            samples = record_func(note, duration, sample_rate, channels, device)
            freqs: list[float] = []
            for start in range(0, len(samples), hop_size):
                block = samples[start : start + hop_size]
                freq = detect_pitch_fft(block, sample_rate)
                if freq > 0:
                    freqs.append(freq)
            if not freqs:
                if interactive:
                    print("No pitch detected, retrying…")
                continue
            median = float(np.median(freqs))
            expected = midi_to_freq(note_to_midi(note, octave))
            spread = np.percentile(freqs, 75) - np.percentile(freqs, 25)
            if spread / median < 0.05 and abs(median - expected) / expected < 0.03:
                results[note] = freqs
                break
            if interactive:
                print("Pitch unstable, try again…")
        else:
            results[note] = freqs

    return results


__all__ = [
    "calculate_midi_tolerance",
    "detect_pitch_fft",
    "midi_to_freq",
    "note_to_midi",
    "calibrate_pitches",
]

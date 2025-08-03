"""Adaptive noise gating utilities for audio capture.

This module provides the :class:`AdaptiveNoiseGate` used by
:class:`~audiokeys.sound_worker.SoundWorker` to differentiate between
silence and significant audio.  The gate measures the ambient noise
level during an initial calibration period and exposes methods to update
and query the current noise floor.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .constants import (
    HOP_SIZE,
    NOISE_GATE_CALIBRATION_TIME,
    NOISE_GATE_MARGIN,
    SAMPLE_RATE,
)


class AdaptiveNoiseGate:
    """Adaptive noise gating based on a measured background noise floor.

    The gate samples incoming audio for a brief calibration period to
    estimate the ambient noise level.  Once the median RMS value has been
    established it is multiplied by ``margin`` to determine the silence
    threshold.  Blocks whose RMS falls below this threshold are treated as
    silence.

    Parameters
    ----------
    duration:
        Seconds of audio used to estimate the noise floor.
    margin:
        Multiplier applied to the measured noise floor when checking for
        silence.
    sample_rate:
        Sampling frequency in hertz.
    hop_size:
        Number of samples per processing block.
    preset_noise_floor:
        Optional pre‑computed noise floor. When provided the gate skips
        calibration and uses this value directly.
    """

    def __init__(
        self,
        duration: float = NOISE_GATE_CALIBRATION_TIME,
        margin: float = NOISE_GATE_MARGIN,
        sample_rate: int = SAMPLE_RATE,
        hop_size: int = HOP_SIZE,
        preset_noise_floor: Optional[float] = None,
    ) -> None:
        frames = int((duration * sample_rate) / hop_size)
        self.calibration_frames: int = max(frames, 1)
        self.margin: float = margin
        self.rms_values: list[float] = []
        self.noise_floor: Optional[float] = None
        if preset_noise_floor is not None:
            self.noise_floor = max(float(preset_noise_floor), 1e-12)

    def update(self, samples: np.ndarray) -> float:
        """Record the RMS of ``samples`` and update the noise floor.

        Parameters
        ----------
        samples:
            One‑dimensional array of audio samples.

        Returns
        -------
        float
            The RMS level of ``samples``.
        """

        rms = float(np.sqrt(np.mean(samples**2)))
        if self.noise_floor is None:
            self.rms_values.append(rms)
            if len(self.rms_values) >= self.calibration_frames:
                median_rms = float(np.median(self.rms_values))
                self.noise_floor = max(median_rms, 1e-12)
        return rms

    def is_silent(self, samples: np.ndarray) -> bool:
        """Return ``True`` if ``samples`` are below the silence threshold."""
        if self.noise_floor is None:
            return False
        rms = float(np.sqrt(np.mean(samples**2)))
        return rms < (self.noise_floor * self.margin)


def calculate_noise_floor(samples: np.ndarray, hop_size: int = HOP_SIZE) -> float:
    """Estimate the ambient noise floor for ``samples``.

    The input is split into consecutive blocks of ``hop_size`` samples and the
    root‑mean‑square (RMS) is computed for each block.  The median RMS is
    returned as a robust estimate of the background level.

    Parameters
    ----------
    samples:
        One‑dimensional array of audio samples.
    hop_size:
        Number of samples per analysis block.

    Returns
    -------
    float
        Estimated noise floor or ``0.0`` if ``samples`` is empty.
    """

    if samples.ndim != 1:
        samples = samples.reshape(-1)
    if samples.size == 0:
        return 0.0

    blocks = np.array_split(samples, max(1, samples.size // hop_size))
    rms_vals = [float(np.sqrt(np.mean(b**2))) for b in blocks if b.size]
    return float(np.median(rms_vals)) if rms_vals else 0.0


def trim_silence(
    samples: np.ndarray,
    *,
    hop_size: int = HOP_SIZE,
    margin: float = NOISE_GATE_MARGIN,
) -> np.ndarray:
    """Remove leading and trailing silence from ``samples``.

    The ambient noise floor is estimated using :func:`calculate_noise_floor`.
    Blocks at the beginning and end of ``samples`` whose RMS level falls below
    ``noise_floor * margin`` are discarded.  If the trimmed region would be
    empty the original ``samples`` are returned unchanged.

    Parameters
    ----------
    samples:
        One-dimensional array of audio samples.
    hop_size:
        Number of samples per analysis block.
    margin:
        Multiplier applied to the noise floor when determining the silence
        threshold.

    Returns
    -------
    np.ndarray
        Trimmed audio samples.
    """

    if samples.ndim != 1:
        samples = samples.reshape(-1)
    if samples.size == 0:
        return samples

    floor = calculate_noise_floor(samples, hop_size=hop_size)
    threshold = floor * margin
    if threshold <= 0.0:
        return samples

    blocks = np.array_split(samples, max(1, samples.size // hop_size))
    rms_vals = [float(np.sqrt(np.mean(b**2))) for b in blocks]
    active = [i for i, rms in enumerate(rms_vals) if rms >= threshold]
    if not active:
        return np.array([], dtype=samples.dtype)

    start_block = active[0]
    end_block = active[-1] + 1
    start_idx = start_block * hop_size
    end_idx = min(end_block * hop_size, samples.size)
    return samples[start_idx:end_idx]


__all__ = ["AdaptiveNoiseGate", "calculate_noise_floor", "trim_silence"]

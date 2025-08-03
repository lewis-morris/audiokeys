"""Subset of spectral features required for tests."""

from __future__ import annotations

import numpy as np
from scipy.fftpack import dct


def mfcc(y: np.ndarray, sr: int, n_mfcc: int = 13) -> np.ndarray:
    """Compute simplified MFCC coefficients.

    This implementation performs a very small subset of the real librosa
    functionality: it converts the input signal to a log power spectrum and
    applies a DCT to obtain ``n_mfcc`` coefficients.

    Args:
        y: Input samples.
        sr: Sampling rate of ``y`` in Hertz (unused, kept for API
            compatibility).
        n_mfcc: Number of coefficients to return.

    Returns:
        Array of shape ``(n_mfcc, 1)`` containing the coefficients.
    """

    spectrum = np.abs(np.fft.rfft(y)) ** 2
    log_spectrum = np.log(spectrum + 1e-10)
    coeffs = dct(log_spectrum, type=2, norm="ortho")[:n_mfcc]
    return coeffs.reshape(n_mfcc, 1)


__all__ = ["mfcc"]

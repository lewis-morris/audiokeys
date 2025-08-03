"""Application-wide constants used for audio capture.

The values in this module configure aspects of the audio pipeline such
as sample rate, buffer sizes and noise-gating behaviour.  Centralising
the configuration avoids magic numbers spread throughout the code base
and makes it easy to tune performance characteristics in one place.
"""

from __future__ import annotations

# ─── Audio configuration ────────────────────────────────────────────────────

# Sampling frequency used throughout the application.  Standard CD quality
# (44.1 kHz) offers a good trade‑off between fidelity and CPU usage.
SAMPLE_RATE: int = 44_100

# Number of samples processed per block.  Larger buffers increase
# latency but can improve stability.
BUFFER_SIZE: int = 2048
HOP_SIZE: int = BUFFER_SIZE // 4

# ─── Noise gating defaults ────────────────────────────────────────────────

# When capturing live audio there is always some ambient noise.  The
# ``AdaptiveNoiseGate`` uses these values to determine how many frames
# to use for calibration and how far above
# the noise floor the system should trigger notes.  You can adjust
# these constants to better suit your environment.

# Duration (in seconds) over which to sample the ambient noise when
# starting a listening session.  The worker collects audio for this
# duration and computes a median RMS to establish the noise floor.
NOISE_GATE_CALIBRATION_TIME: float = 1.0  # seconds

# Safety margin applied to the estimated noise floor.  Multiplying the
# baseline RMS by this factor sets the threshold above which the
# system will treat incoming sound as a potential note.  Larger values
# make the noise gate more conservative (harder to trigger notes) while
# smaller values make it more sensitive.
NOISE_GATE_MARGIN: float = 1.5

# Cutoff frequency for the high‑pass filter used to remove low‑frequency
# rumble and hum (e.g. mains hum at 50/60 Hz).  Values between 50 and
# 80 Hz are appropriate for most scenarios.
HP_FILTER_CUTOFF: float = 60.0

# ─── Sample matching defaults ────────────────────────────────────────────

# Minimum similarity score required for a segment to be considered a
# match to a reference sample.  A lower default of ``0.2`` works better
# with MFCC and DTW based matching while still being suitable for
# waveform comparison.
MATCH_THRESHOLD: float = 0.2

# Default technique used when comparing an audio segment to stored
# reference samples. ``"waveform"`` performs raw cosine similarity on the
# waveform, ``"mfcc"`` compares mean MFCC vectors and ``"dtw"`` applies
# Dynamic Time Warping over MFCC sequences.
MATCH_METHOD: str = "waveform"

__all__ = [
    "SAMPLE_RATE",
    "BUFFER_SIZE",
    "HOP_SIZE",
    "NOISE_GATE_CALIBRATION_TIME",
    "NOISE_GATE_MARGIN",
    "HP_FILTER_CUTOFF",
    "MATCH_THRESHOLD",
    "MATCH_METHOD",
]

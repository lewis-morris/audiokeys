"""
Application-wide constants used for audio capture and pitch detection.

This module centralises configuration values such as the sample rate,
buffer sizes and musical reference values (A4 frequency and midi number).
Separating these values into a standalone module makes it easy to
adjust them in one place and promotes reuse across different parts of
the application.  Developers can tune these values to balance latency
against stability; for example increasing ``BUFFER_SIZE`` can improve
pitch estimation at the cost of higher latency, while reducing it
makes the system more responsive but less accurate.
"""

from __future__ import annotations

# ─── Audio configuration ────────────────────────────────────────────────────

# Sampling frequency used throughout the application.  Standard CD quality
# (44.1 kHz) offers a good trade‑off between fidelity and CPU usage.
SAMPLE_RATE: int = 44_100

# Number of samples processed per aubio buffer.  A larger buffer yields
# smoother pitch estimates but increases latency.  We default to 2048
# samples to match the original implementation.  ``HOP_SIZE`` is derived
# from this value to provide a 4× overlap.
BUFFER_SIZE: int = 2048
HOP_SIZE: int = BUFFER_SIZE // 4

# ─── Musical reference values ──────────────────────────────────────────────

# Frequency of concert A (A4) in hertz.  This value is used to convert
# detected frequencies into MIDI note numbers and names.  Changing it
# allows users to retune the system to alternate standards such as
# 432 Hz.
A4_FREQ: float = 440.0

# MIDI note number corresponding to A4.  MIDI numbers are used by the
# internal note mapping logic.
A4_MIDI: int = 69

# Names of the twelve chromatic semitones.  The index into this list is
# obtained by rounding the detected MIDI value and taking modulo 12.
NOTE_NAMES: list[str] = [
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
]

# Default key bindings for each note.  Users can override these via
# the GUI; the values are persisted using ``QSettings``.  Keeping the
# defaults here avoids repeating the mapping literals in multiple files.
DEFAULT_NOTE_MAP: dict[str, str] = {
    "C": "a",
    "C#": "b",
    "D": "c",
    "D#": "d",
    "E": "e",
    "F": "f",
    "F#": "g",
    "G": "h",
    "G#": "i",
    "A": "j",
    "A#": "k",
    "B": "l",
}

# ─── Noise gating defaults ────────────────────────────────────────────────

# When capturing live audio there is always some ambient noise.  The
# ``AdaptiveNoiseGate`` in ``audio_worker.py`` uses these values to
# determine how many frames to use for calibration and how far above
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
# 80 Hz are appropriate for most pitched instruments.  See
# ``audio_worker.py`` for details.
HP_FILTER_CUTOFF: float = 60.0

# Tolerance for pitch changes, in semitones.  See ``AudioWorker`` for
# explanation.  Smaller values result in more sensitive note changes.
MIDI_SEMITONE_TOLERANCE: float = 0.5

# Minimum confidence reported by aubio before a detected pitch is
# considered reliable.  Values range from 0–1.  Increasing this value
# makes the detector more selective and helps reject spurious notes
# caused by background noise.
AUBIO_CONFIDENCE_THRESHOLD: float = 0.8

__all__ = [
    "SAMPLE_RATE",
    "BUFFER_SIZE",
    "HOP_SIZE",
    "A4_FREQ",
    "A4_MIDI",
    "NOTE_NAMES",
    "DEFAULT_NOTE_MAP",
    "NOISE_GATE_CALIBRATION_TIME",
    "NOISE_GATE_MARGIN",
    "HP_FILTER_CUTOFF",
    "MIDI_SEMITONE_TOLERANCE",
    "AUBIO_CONFIDENCE_THRESHOLD",
]

import numpy as np

from audiokeys.note_calibration import calculate_midi_tolerance, detect_pitch_fft


def test_detect_pitch_fft_sine():
    sr = 44100
    t = np.linspace(0, 1.0, sr, endpoint=False)
    freq = 440.0
    samples = np.sin(2 * np.pi * freq * t)
    detected = detect_pitch_fft(samples.astype(np.float32), sr)
    assert abs(detected - freq) < 1.0


def test_calculate_midi_tolerance():
    data = {
        "C": [261.63, 261.5],
        "D": [293.66, 293.7],
    }
    tol = calculate_midi_tolerance(data)
    assert 0.1 <= tol <= 1.0

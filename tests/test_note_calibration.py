import numpy as np

from audiokeys.note_calibration import (
    calculate_midi_tolerance,
    detect_pitch_fft,
    calibrate_pitches,
)


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


def test_calibrate_pitches_stub():
    sr = 44100
    freq_map = {"C": 261.63, "C#": 277.18}

    def fake_rec(note: str, duration: float, rate: int, ch: int, dev):
        t = np.linspace(0, duration, int(rate * duration), endpoint=False)
        f = freq_map[note]
        return np.sin(2 * np.pi * f * t).astype(np.float32)

    data = calibrate_pitches(
        ["C", "C#"],
        duration=0.2,
        sample_rate=sr,
        hop_size=2048,
        record_func=fake_rec,
        interactive=False,
    )
    assert set(data.keys()) == {"C", "C#"}
    assert len(data["C"]) > 0
    assert abs(np.median(data["C"]) - freq_map["C"]) < 5.0

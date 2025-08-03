import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audiokeys.noise_gate import calculate_noise_floor, trim_silence


def test_calculate_noise_floor_estimates_median_rms():
    rng = np.random.default_rng(123)
    noise = rng.normal(scale=0.01, size=2048)
    floor = calculate_noise_floor(noise)
    expected = float(np.sqrt(np.mean(noise**2)))
    assert np.isclose(floor, expected, rtol=0.1)


def test_trim_silence_removes_leading_and_trailing_noise() -> None:
    rng = np.random.default_rng(0)
    lead = rng.normal(scale=0.001, size=200)
    tail = rng.normal(scale=0.001, size=200)
    tone = np.sin(np.linspace(0, 2 * np.pi, 400))
    samples = np.concatenate([lead, tone, tail])
    trimmed = trim_silence(samples, hop_size=50, margin=1.2)
    assert trimmed.size < samples.size
    assert trimmed.size == pytest.approx(tone.size, rel=0.2)

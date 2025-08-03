import numpy as np

from audiokeys.noise_gate import calculate_noise_floor


def test_calculate_noise_floor_estimates_median_rms():
    rng = np.random.default_rng(123)
    noise = rng.normal(scale=0.01, size=2048)
    floor = calculate_noise_floor(noise)
    expected = float(np.sqrt(np.mean(noise**2)))
    assert np.isclose(floor, expected, rtol=0.1)

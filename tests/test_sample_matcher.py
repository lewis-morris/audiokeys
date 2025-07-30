import numpy as np

from audiokeys.sample_matcher import cosine_similarity, match_sample


def test_cosine_similarity_basic():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert cosine_similarity(a, b) == 1.0


def test_match_sample():
    t = np.linspace(0, 1.0, 44100, endpoint=False)
    ref_a = np.sin(2 * np.pi * 440.0 * t)
    ref_b = np.sin(2 * np.pi * 880.0 * t)
    samples = {"a": ref_a, "b": ref_b}
    segment = np.sin(2 * np.pi * 440.0 * t)
    assert match_sample(segment, samples, threshold=0.5) == "a"

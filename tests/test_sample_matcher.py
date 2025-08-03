import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audiokeys.sample_matcher import cosine_similarity, match_sample


def test_cosine_similarity_identical() -> None:
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_match_sample_returns_best_key() -> None:
    ref_a = np.array([0.1, 0.2, 0.3])
    ref_b = np.array([1.0, 0.0, -1.0])
    segment = ref_b + np.random.normal(0, 0.01, size=3)
    key = match_sample(segment, {"a": ref_a, "b": ref_b}, threshold=0.5)
    assert key == "b"


def test_match_sample_threshold_none() -> None:
    ref = np.array([1.0, 0.0, -1.0])
    segment = np.array([0.1, 0.1, 0.1])
    key = match_sample(segment, {"r": ref}, threshold=0.9)
    assert key is None

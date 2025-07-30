"""Audiokeys package."""

from .sample_matcher import cosine_similarity, match_sample, record_until_silence

try:  # sounddevice may be missing in test environments
    from .sound_worker import SoundWorker
except Exception:  # pragma: no cover - optional dependency
    SoundWorker = None  # type: ignore

__all__ = [
    "cosine_similarity",
    "match_sample",
    "record_until_silence",
    "SoundWorker",
]

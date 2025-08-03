"""Lightweight stub of the :mod:`librosa` package for testing.

This minimal implementation provides only the features required by the test
suite: ``feature.mfcc`` and ``sequence.dtw``. It is **not** a drop-in
replacement for the real library but allows the project to run in environments
where the heavy dependency cannot be installed.
"""

from . import feature, sequence

__all__ = ["feature", "sequence"]

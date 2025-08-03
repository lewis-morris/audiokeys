"""Minimal sequence utilities used for Dynamic Time Warping."""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist


def dtw(
    X: np.ndarray,
    Y: np.ndarray,
    *,
    metric: str = "euclidean",
    backtrack: bool = True,
) -> np.ndarray | tuple[np.ndarray, list[tuple[int, int]]]:
    """Compute the Dynamic Time Warping cost matrix.

    Args:
        X: Feature matrix shaped ``(n_features, n_frames)``.
        Y: Feature matrix shaped ``(n_features, m_frames)``.
        metric: Distance metric passed to :func:`scipy.spatial.distance.cdist`.
        backtrack: If ``True``, also return the optimal path.

    Returns:
        The cumulative cost matrix. When ``backtrack`` is ``True`` a tuple of
        ``(cost, path)`` is returned.
    """

    cost = cdist(X.T, Y.T, metric=metric)
    acc = np.zeros_like(cost)
    acc[0, 0] = cost[0, 0]
    for i in range(1, cost.shape[0]):
        acc[i, 0] = cost[i, 0] + acc[i - 1, 0]
    for j in range(1, cost.shape[1]):
        acc[0, j] = cost[0, j] + acc[0, j - 1]
    for i in range(1, cost.shape[0]):
        for j in range(1, cost.shape[1]):
            acc[i, j] = cost[i, j] + min(
                acc[i - 1, j], acc[i, j - 1], acc[i - 1, j - 1]
            )
    if not backtrack:
        return acc

    path: list[tuple[int, int]] = []
    i, j = cost.shape[0] - 1, cost.shape[1] - 1
    path.append((i, j))
    while i > 0 or j > 0:
        options = []
        if i > 0 and j > 0:
            options.append((acc[i - 1, j - 1], i - 1, j - 1))
        if i > 0:
            options.append((acc[i - 1, j], i - 1, j))
        if j > 0:
            options.append((acc[i, j - 1], i, j - 1))
        _, i, j = min(options)
        path.append((i, j))
    path.reverse()
    return acc, path


__all__ = ["dtw"]

"""A fixed-size ring buffer of samples.

The monitor holds only the display window in memory, so a long session cannot grow
the process. Pre-allocating the array (rather than a ``deque`` of rows) keeps the
per-tick cost a ``memcpy`` instead of thousands of small allocations.
"""

from __future__ import annotations

import numpy as np

from eeg_api.domain.models import FloatArray


class RingBuffer:
    """The newest ``capacity`` rows, oldest first, with O(1) append."""

    def __init__(self, capacity: int, width: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self.width = int(width)
        self._data = np.zeros((self.capacity, self.width), dtype=np.float64)
        self._total = 0

    def __len__(self) -> int:
        return min(self._total, self.capacity)

    @property
    def total(self) -> int:
        """Rows ever written, including those already overwritten."""
        return self._total

    def extend(self, rows: FloatArray) -> None:
        n = int(rows.shape[0])
        if n == 0:
            return
        if n >= self.capacity:
            self._data[:] = rows[-self.capacity :]
            self._total += n
            return
        start = self._total % self.capacity
        end = start + n
        if end <= self.capacity:
            self._data[start:end] = rows
        else:
            split = self.capacity - start
            self._data[start:] = rows[:split]
            self._data[: end - self.capacity] = rows[split:]
        self._total += n

    def latest(self, count: int) -> FloatArray:
        """The newest ``count`` rows, oldest first. Fewer if not yet available."""
        available = len(self)
        n = int(min(max(count, 0), available))
        if n == 0:
            return np.zeros((0, self.width), dtype=np.float64)
        end = self._total % self.capacity
        if end == 0:
            end = self.capacity
        start = end - n
        if start >= 0:
            return self._data[start:end].copy()
        return np.vstack([self._data[start:], self._data[:end]])

    def clear(self) -> None:
        self._data[:] = 0.0
        self._total = 0

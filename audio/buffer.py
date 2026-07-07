"""
audio/buffer.py

高性能 Sliding Ring Buffer（配置驱动版）

适用于：

    InputStream
        ↓
    append()
        ↓
    AudioProcessor

特点：

    • 连续内存
    • 零 concatenate
    • O(1) append
    • O(1) overlap
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import AUDIO_BUFFER_CONFIG


@dataclass(slots=True)
class BufferStats:
    samples: int
    duration: float
    ready: bool


class RingAudioBuffer:

    def __init__(
        self,
        sample_rate: int = 16000,
        target_duration: float | None = None,
        overlap_duration: float | None = None,
    ):
        self.sample_rate = sample_rate

        # 从配置文件读取默认值，允许显式覆盖
        self.target_duration = (
            target_duration
            if target_duration is not None
            else AUDIO_BUFFER_CONFIG["target_duration"]
        )
        self.overlap_duration = (
            overlap_duration
            if overlap_duration is not None
            else AUDIO_BUFFER_CONFIG["overlap_duration"]
        )

        self.target_samples = int(self.target_duration * sample_rate)
        self.overlap_samples = int(self.overlap_duration * sample_rate)

        # 预分配一块连续内存
        self._buffer = np.empty(self.target_samples * 2, dtype=np.int16)
        self._size = 0

    # -------------------------------------------------
    @property
    def ready(self):
        return self._size >= self.target_samples

    @property
    def duration(self):
        return self._size / self.sample_rate

    @property
    def sample_count(self):
        return self._size

    # -------------------------------------------------
    def append(self, pcm: np.ndarray):
        if pcm is None:
            return
        if len(pcm) == 0:
            return

        n = len(pcm)

        # 容量不足时保留最后 overlap
        if self._size + n > len(self._buffer):
            keep = min(self.overlap_samples, self._size)
            if keep > 0:
                self._buffer[:keep] = self._buffer[self._size - keep : self._size]
            self._size = keep

        self._buffer[self._size : self._size + n] = pcm
        self._size += n

    # -------------------------------------------------
    def read(self):
        if self._size == 0:
            return None
        return self._buffer[:self._size]

    # -------------------------------------------------
    def pop(self):
        """返回一段 PCM，同时保留 overlap 部分"""
        if self._size == 0:
            return None

        audio = self._buffer[:self._size].copy()
        keep = min(self.overlap_samples, self._size)

        if keep > 0:
            self._buffer[:keep] = self._buffer[self._size - keep : self._size]
        self._size = keep
        return audio

    # -------------------------------------------------
    def clear(self):
        self._size = 0

    # -------------------------------------------------
    def flush(self):
        """返回所有数据并清空缓冲"""
        if self._size == 0:
            return None
        audio = self._buffer[:self._size].copy()
        self._size = 0
        return audio

    # -------------------------------------------------
    def stats(self):
        return BufferStats(
            samples=self._size,
            duration=self.duration,
            ready=self.ready,
        )
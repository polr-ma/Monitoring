"""
audio/capture.py

实时音频采集模块（配置驱动版）

职责：
    - 管理 sounddevice.InputStream
    - 接收 PCM 数据
    - 提供线程安全 Queue
    - 不做任何 ASR / VAD / NoiseReduction

Author:
    ChatGPT Refactor / Config Integration
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from config import AUDIO_CAPTURE_CONFIG

logger = logging.getLogger(__name__)


class AudioCapture:
    """
    实时麦克风采集器

    所有默认值来自 config.AUDIO_CAPTURE_CONFIG，
    允许在构造时覆盖。
    """

    def __init__(
        self,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        block_size: Optional[int] = None,
        device: Optional[int] = None,
        queue_size: Optional[int] = None,
        dtype: Optional[str] = None,
    ):
        # 参数优先使用传入值，否则从配置读取
        self.sample_rate = sample_rate if sample_rate is not None else AUDIO_CAPTURE_CONFIG["sample_rate"]
        self.channels = channels if channels is not None else AUDIO_CAPTURE_CONFIG["channels"]
        self.block_size = block_size if block_size is not None else AUDIO_CAPTURE_CONFIG["chunk_size"]
        # device_index 可以为 None（系统默认），需严格按 is not None 判断
        self.device = device if device is not None else AUDIO_CAPTURE_CONFIG["device_index"]
        self._queue_size = queue_size if queue_size is not None else AUDIO_CAPTURE_CONFIG["queue_size"]
        self._dtype = dtype if dtype is not None else AUDIO_CAPTURE_CONFIG["dtype"]

        self._queue: queue.Queue = queue.Queue(maxsize=self._queue_size)

        self._stream: Optional[sd.InputStream] = None
        self._running = False
        self._lock = threading.Lock()

    # ==========================================================
    # callback
    # ==========================================================
    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(status)

        if not self._running:
            return

        pcm = indata[:, 0].copy().astype(np.int16)

        try:
            self._queue.put_nowait(pcm)
        except queue.Full:
            # 丢弃最旧的数据
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(pcm)
            except queue.Full:
                pass

    # ==========================================================
    # start
    # ==========================================================
    def start(self):
        with self._lock:
            if self._running:
                return

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",      # sounddevice 的 dtype 参数，与内部存储无关
                blocksize=self.block_size,
                callback=self._callback,
                device=self.device,
            )
            self._running = True
            self._stream.start()
            logger.info("AudioCapture started (sr=%d, channels=%d, blocksize=%d)",
                        self.sample_rate, self.channels, self.block_size)

    # ==========================================================
    # stop
    # ==========================================================
    def stop(self):
        with self._lock:
            self._running = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None
            logger.info("AudioCapture stopped")

    # ==========================================================
    # read
    # ==========================================================
    def read(self, timeout: Optional[float] = 0.2) -> Optional[np.ndarray]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ==========================================================
    # clear
    # ==========================================================
    def clear(self):
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    # ==========================================================
    # properties
    # ==========================================================
    @property
    def running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    # ==========================================================
    # context manager
    # ==========================================================
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
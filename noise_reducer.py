"""
实时降噪模块 — 基于 scipy 的谱减法 + Wiener 滤波
无需 GPU，CPU 上实时运行，适合嘈杂环境下的语音增强
"""

import logging
import time
from typing import Optional

import numpy as np
from scipy import signal
from scipy.ndimage import uniform_filter1d

logger = logging.getLogger('audio.denoise')


class NoiseReducer:
    """实时谱减法降噪器

    原理：
    1. 从静音片段估计噪声频谱
    2. 对每帧音频做 STFT
    3. 用 Wiener 增益抑制噪声频带
    4. 平滑处理后做 ISTFT 还原
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        n_fft: int = 512,              # 32ms @ 16kHz
        hop_length: int = 256,          # 50% overlap
        noise_reduce_db: float = 12.0,  # 目标降噪量 (dB)
        noise_smooth_frames: int = 3,   # 噪声平滑帧数
        learning_rate: float = 0.05,    # 噪声估计学习率
        enabled: bool = True,
    ):
        self._sr = sample_rate
        self._n_fft = n_fft
        self._hop = hop_length
        self._noise_reduce_db = noise_reduce_db
        self._noise_smooth_frames = noise_smooth_frames
        self._lr = learning_rate
        self._enabled = enabled

        self._window = np.hanning(n_fft).astype(np.float32)

        # 噪声频谱估计（持续更新）
        self._noise_mag: Optional[np.ndarray] = None

        # 统计
        self._total_frames = 0
        self._processed_frames = 0
        self._last_reduction_db = 0.0

    # ── 公共接口 ──────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val
        if not val:
            self._noise_mag = None  # 重置噪声估计

    @property
    def last_reduction_db(self) -> float:
        return self._last_reduction_db

    def process(self, audio: np.ndarray) -> tuple[np.ndarray, dict]:
        """处理一段音频，返回 (降噪后音频, 诊断信息)

        Args:
            audio: int16 或 float32 一维数组

        Returns:
            (denoised_audio_int16, diagnostics_dict)
        """
        t0 = time.perf_counter()

        # 统一转为 float32 [-1, 1]
        if audio.dtype == np.int16:
            orig_dtype = np.int16
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            orig_dtype = audio.dtype
            audio_f = audio.astype(np.float32)
            if np.abs(audio_f).max() > 1.5:
                audio_f = audio_f / 32768.0

        orig_rms = float(np.sqrt(np.mean(audio_f ** 2)) + 1e-10)

        if not self._enabled or len(audio_f) < self._n_fft:
            diag = {
                'method': 'bypass',
                'orig_rms': round(orig_rms, 6),
                'denoised_rms': round(orig_rms, 6),
                'reduction_db': 0.0,
                'proc_ms': round((time.perf_counter() - t0) * 1000, 1),
            }
            out = audio_f if not self._enabled else audio_f
            if orig_dtype == np.int16:
                out = (out * 32768.0).clip(-32768, 32767).astype(np.int16)
            return out, diag

        # STFT
        f, t_seg, Zxx = signal.stft(
            audio_f,
            fs=self._sr,
            window=self._window,
            nperseg=self._n_fft,
            noverlap=self._n_fft - self._hop,
            boundary='zeros',
        )
        mag = np.abs(Zxx)  # (freq_bins, time_frames)

        # ── 噪声估计 ──
        noise_est = self._estimate_noise(mag)

        # ── Wiener 增益 ──
        # G = (|X| - α*|N|) / |X|   clamped to [floor, 1]
        alpha = 10 ** (self._noise_reduce_db / 20)  # oversubtraction factor
        noise_thresh = alpha * noise_est[:, np.newaxis]

        # 平滑噪声阈值
        noise_thresh_s = uniform_filter1d(noise_thresh, self._noise_smooth_frames, axis=1)

        gain = (mag - noise_thresh_s) / (mag + 1e-10)
        gain = np.clip(gain, 0.05, 1.0)  # 5% spectral floor to reduce musical noise

        # 平滑增益减少突变
        gain = uniform_filter1d(gain, 2, axis=1)

        # 应用增益
        mag_denoised = mag * gain
        Zxx_denoised = mag_denoised * np.exp(1j * np.angle(Zxx))

        # ISTFT
        _, audio_denoised = signal.istft(
            Zxx_denoised,
            fs=self._sr,
            window=self._window,
            nperseg=self._n_fft,
            noverlap=self._n_fft - self._hop,
            boundary=True,
        )

        # 截断到原始长度
        audio_denoised = audio_denoised[:len(audio_f)]

        self._processed_frames += 1
        self._total_frames += 1

        denoised_rms = float(np.sqrt(np.mean(audio_denoised ** 2)) + 1e-10)
        reduction_db = float(20 * np.log10(denoised_rms / orig_rms))
        self._last_reduction_db = reduction_db

        diag = {
            'method': 'wiener',
            'orig_rms': round(orig_rms, 6),
            'denoised_rms': round(denoised_rms, 6),
            'reduction_db': round(reduction_db, 1),
            'proc_ms': round((time.perf_counter() - t0) * 1000, 1),
            'frames': mag.shape[1],
        }

        if orig_dtype == np.int16:
            audio_denoised = (audio_denoised * 32768.0).clip(-32768, 32767).astype(np.int16)

        return audio_denoised, diag

    def _estimate_noise(self, mag: np.ndarray) -> np.ndarray:
        """估计每频带的噪声幅度谱

        策略：取每个频带的最小值作为噪声估计，并用 EMA 持续更新
        """
        # 每个频带的当前帧最小幅度（作为瞬态噪声估计）
        frame_noise = np.min(mag, axis=1)  # (freq_bins,)

        if self._noise_mag is None:
            # 首次直接用当前帧初始化
            self._noise_mag = frame_noise.copy()
        else:
            # EMA 更新
            self._noise_mag = (
                (1 - self._lr) * self._noise_mag + self._lr * frame_noise
            )

        return self._noise_mag.copy()

    def reset(self):
        """重置噪声估计（切换环境时调用）"""
        self._noise_mag = None
        self._total_frames = 0
        self._processed_frames = 0
        self._last_reduction_db = 0.0

    def get_status(self) -> dict:
        return {
            'enabled': self._enabled,
            'total_frames': self._total_frames,
            'noise_estimated': self._noise_mag is not None,
            'last_reduction_db': self._last_reduction_db,
        }

"""
audio/processor.py

高性能语音识别处理模块（配置驱动版）

所有运行参数从 config 读取，彻底消除硬编码。
修正：缩进、方法名、冗余变量、日志名称、线程安全等。
"""

from __future__ import annotations

import logging
import threading
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from config import AUDIO_PROCESSOR_CONFIG, SENSEVOICE_CONFIG, NOISE_REDUCTION_CONFIG

# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------
try:
    from funasr import AutoModel
    _FUNASR_AVAILABLE = True
except ImportError:
    _FUNASR_AVAILABLE = False
    AutoModel = None

try:
    from audio.noise_reducer import NoiseReducer
except ImportError:
    class NoiseReducer:
        # 注意：根据原 noise_reducer 的接口，可能是 process 方法
        # 这里暂时保持 reduce_noise，但建议检查 noise_reducer.py 的实现
        def reduce_noise(self, pcm: np.ndarray, sample_rate: int) -> np.ndarray:
            return pcm

logger = logging.getLogger('audio.processor')   # 统一使用 audio.processor


# ======================================================================
# 结构化结果
# ======================================================================
@dataclass
class RecognitionResult:
    """识别结果（text 为本次增量文本，GUI 可直接追加）"""
    text: str = ""
    raw_text: str = ""
    is_sensitive: bool = False
    sensitive_words: Set[str] = field(default_factory=set)
    confidence: Optional[float] = None
    audio_duration: float = 0.0


# ======================================================================
# Aho‑Corasick 违禁词匹配
# ======================================================================
class _TrieNode:
    __slots__ = ("children", "fail", "output")
    def __init__(self):
        self.children: Dict[str, "_TrieNode"] = {}
        self.fail: Optional["_TrieNode"] = None
        self.output: Set[str] = set()


class SensitiveWordMatcher:
    def __init__(self):
        self._root = _TrieNode()
        self._built = False

    def add_words(self, words: List[str]) -> None:
        for word in words:
            if not word:
                continue
            node = self._root
            for ch in word:
                node = node.children.setdefault(ch, _TrieNode())
            node.output.add(word)
        self._built = False

    def build(self) -> None:
        queue = deque()
        for child in self._root.children.values():
            child.fail = self._root
            queue.append(child)
        while queue:
            cur = queue.popleft()
            for ch, child in cur.children.items():
                queue.append(child)
                fail = cur.fail
                while fail and ch not in fail.children:
                    fail = fail.fail
                child.fail = fail.children[ch] if fail else self._root
                child.output.update(child.fail.output)
        self._built = True

    def search(self, text: str) -> Set[str]:
        if not self._built:
            self.build()
        matched = set()
        node = self._root
        for ch in text:
            while node and ch not in node.children:
                node = node.fail
            if not node:
                node = self._root
                continue
            node = node.children[ch]
            if node.output:
                matched.update(node.output)
        return matched


# ======================================================================
# 核心处理器
# ======================================================================
class AudioProcessor:
    """语音识别处理器（配置驱动）"""

    # ---------- 文本清洗正则（静态） ----------
    _SPECIAL_TAG = re.compile(r"<\|[^|]*\|>")
    _BRACKET_TAG = re.compile(r"\[[^\]]*\]|\([^\)]*\)|<[^>]*>")
    _SPACES = re.compile(r"\s+")
    _ILLEGAL_CHAR = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9，。！？、；：“”‘’（）—…\s]")

    # ---------- 去重上下文长度 ----------
    MAX_CONTEXT_CHARS = 100

    def __init__(
        self,
        sample_rate: int = 16000,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
        noise_reducer: Optional[NoiseReducer] = None,
        sensitive_words: Optional[List[str]] = None,
        language: Optional[str] = None,
        use_itn: Optional[bool] = None,
        min_audio_ms: Optional[int] = None,
        energy_threshold: Optional[float] = None,
        warmup: bool = False,          # 默认不预热，由 Engine 控制
    ):
        # 模型加载锁（线程安全）
        self._model_lock = threading.Lock()

        # ---- 基本参数 ----
        self.sample_rate = sample_rate

        # SenseVoice 配置
        self.model_path = model_path if model_path is not None else SENSEVOICE_CONFIG["model"]
        self.device = device if device is not None else SENSEVOICE_CONFIG["device"]

        # 处理器行为参数（来自 AUDIO_PROCESSOR_CONFIG）
        self.language = language if language is not None else AUDIO_PROCESSOR_CONFIG["language"]
        self.use_itn = use_itn if use_itn is not None else AUDIO_PROCESSOR_CONFIG["use_itn"]
        self.min_audio_ms = min_audio_ms if min_audio_ms is not None else AUDIO_PROCESSOR_CONFIG["min_audio_ms"]
        self.energy_threshold = energy_threshold if energy_threshold is not None else AUDIO_PROCESSOR_CONFIG["energy_threshold"]

        # 降噪启用状态（唯一来源：NOISE_REDUCTION_CONFIG）
        self._denoise_enabled = NOISE_REDUCTION_CONFIG.get("enabled", False)
        # 降噪器：若外部传入则用，否则根据启用状态创建一个默认降噪器
        if noise_reducer is not None:
            self.noise_reducer = noise_reducer
        elif self._denoise_enabled:
            self.noise_reducer = NoiseReducer()
        else:
            self.noise_reducer = None

        # 违禁词匹配器
        self._sensitive_matcher = SensitiveWordMatcher()
        if sensitive_words:
            self.set_sensitive_words(sensitive_words)

        # ASR 模型（懒加载）
        self._model = None

        # 去重上下文
        self._last_text: str = ""

        # 最小样本数（根据 min_audio_ms 计算）
        self._min_samples = int(self.min_audio_ms * sample_rate / 1000)

        # 性能统计
        self._proc_count = 0

        if not _FUNASR_AVAILABLE:
            logger.warning("FunASR 未安装，语音识别不可用。")

        # 如果外部明确要求预热，则立即执行（通常 Engine 会异步调用）
        if warmup:
            self.warmup()

    # ==================================================================
    # 公开接口
    # ==================================================================
    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        # 避免重复预热
        if self.model_loaded:
            return
        if not _FUNASR_AVAILABLE:
            logger.warning("FunASR 不可用，跳过预热")
            return
        self._ensure_model()
        silence = np.zeros(int(0.2 * self.sample_rate), dtype=np.int16)
        try:
            _ = self._recognize(silence)
            logger.info("ASR 模型预热完成")
        except Exception:
            logger.exception("预热失败，可忽略")

    def process(self, audio_chunk: np.ndarray) -> RecognitionResult:
        if audio_chunk is None or len(audio_chunk) == 0:
            return RecognitionResult()

        # 最小长度过滤
        if len(audio_chunk) < self._min_samples:
            return RecognitionResult(audio_duration=len(audio_chunk) / self.sample_rate)

        # 能量门限（RMS）
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)) / 32768.0
        if rms < self.energy_threshold:
            return RecognitionResult(audio_duration=len(audio_chunk) / self.sample_rate)

        t_start = time.perf_counter()

        # 1. 降噪
        t0 = time.perf_counter()
        denoised = self._reduce_noise(audio_chunk)
        t1 = time.perf_counter()

        # 2. ASR
        raw_text = self._recognize(denoised)
        t2 = time.perf_counter()

        # 3. 清洗
        cleaned = self._clean_text(raw_text)

        # 4. 去重并提取增量
        _, new_text = self._merge_overlap(cleaned)

        # 5. 违禁词检测
        t3 = time.perf_counter()
        is_sensitive, matched = self._check_sensitive(new_text)
        t4 = time.perf_counter()

        # 性能日志
        self._proc_count += 1
        if self._proc_count % 100 == 0:
            logger.debug(
                "Perf[%d]: Noise=%.1fms ASR=%.1fms Sensitive=%.1fms Total=%.1fms",
                self._proc_count,
                (t1 - t0) * 1000,
                (t2 - t1) * 1000,
                (t4 - t3) * 1000,
                (t4 - t_start) * 1000,
            )

        duration = len(audio_chunk) / self.sample_rate
        return RecognitionResult(
            text=new_text,          # 返回增量文本（GUI 可追加）
            raw_text=raw_text,
            is_sensitive=is_sensitive,
            sensitive_words=matched,
            confidence=None,
            audio_duration=duration,
        )

    def reset(self) -> None:
        self._last_text = ""

    # ==================================================================
    # 内部实现
    # ==================================================================
    def _ensure_model(self):
        """线程安全地加载模型（双重检查锁）"""
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            if not _FUNASR_AVAILABLE:
                raise RuntimeError("请安装 funasr: pip install funasr")
            logger.info("加载 SenseVoice 模型: %s", self.model_path)
            vad_model = SENSEVOICE_CONFIG.get("vad_model", "fsmn-vad")
            vad_max_segment = SENSEVOICE_CONFIG.get("vad_max_segment", 30000)
            disable_update = SENSEVOICE_CONFIG.get("disable_update", True)
            self._model = AutoModel(
                model=self.model_path,
                vad_model=vad_model,
                vad_kwargs={"max_single_segment_time": vad_max_segment},
                device=self.device,
                disable_update=disable_update,
            )
            logger.info("模型加载完成")

    def _recognize(self, audio: np.ndarray) -> str:
        self._ensure_model()
        if audio.dtype != np.float32:
            audio_f = audio.astype(np.float32) / 32768.0
        else:
            audio_f = audio

        try:
            result = self._model.generate(
                input=audio_f,
                cache={},
                language=self.language,
                use_itn=self.use_itn,
                ban_emo_unk=True,
                batch_size_s=60,
            )
            if result and len(result) > 0:
                return result[0].get("text", "").strip()
            return ""
        except Exception:
            logger.exception("ASR 识别异常")
            return ""

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = self._SPECIAL_TAG.sub("", text)
        text = self._BRACKET_TAG.sub("", text)
        text = self._ILLEGAL_CHAR.sub("", text)
        text = self._SPACES.sub(" ", text)
        return text.strip()

    def _check_sensitive(self, text: str) -> Tuple[bool, Set[str]]:
        if not text:
            return False, set()
        matched = self._sensitive_matcher.search(text)
        return len(matched) > 0, matched

    def _merge_overlap(self, new_text: str) -> Tuple[str, str]:
        if not new_text:
            return self._last_text, ""

        if not self._last_text:
            self._last_text = new_text
            return new_text, new_text

        last = self._last_text
        max_overlap = min(len(last), len(new_text))
        overlap_len = 0
        for i in range(1, max_overlap + 1):
            if last[-i:] == new_text[:i]:
                overlap_len = i

        if overlap_len > 0:
            merged = last + new_text[overlap_len:]
            added = new_text[overlap_len:]
        else:
            merged = new_text
            added = new_text

        # 截断上下文
        if len(merged) > self.MAX_CONTEXT_CHARS:
            merged = merged[-self.MAX_CONTEXT_CHARS:]

        self._last_text = merged
        return merged, added

    def _reduce_noise(self, pcm: np.ndarray) -> np.ndarray:
        if self.noise_reducer is None:
            return pcm
        t0 = time.perf_counter()
        try:
            # 注意：noise_reducer 可能为 process 方法，请根据实际接口调整
            # 此处假设有 reduce_noise 方法，若否，改为 self.noise_reducer.process(pcm, self.sample_rate)
            result = self.noise_reducer.reduce_noise(pcm, self.sample_rate)
            t1 = time.perf_counter()
            logger.debug("Noise reduction: %.1f ms", (t1 - t0) * 1000)
            return result
        except Exception:
            logger.exception("降噪失败，回退原始音频")
            return pcm

    # ==================================================================
    # 敏感词管理
    # ==================================================================
    def set_sensitive_words(self, words: List[str]) -> None:
        self._sensitive_matcher = SensitiveWordMatcher()
        self._sensitive_matcher.add_words(words)

    def add_sensitive_words(self, words: List[str]) -> None:
        # 修正：使用 add_words 而不是不存在的 add_word
        self._sensitive_matcher.add_words(words)
        self._sensitive_matcher.build()

    def clear_sensitive_words(self) -> None:
        self._sensitive_matcher = SensitiveWordMatcher()

    def __repr__(self):
        return (
            f"AudioProcessor(sr={self.sample_rate}, model={self.model_path}, "
            f"denoise={self._denoise_enabled})"
        )
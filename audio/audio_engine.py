"""
audio_engine.py

极度精简的音频引擎（调度器）

所有子模块自行从 config.py 读取配置。
引擎只负责串联调用，不传递任何配置参数。
"""

import logging
import queue
import threading
from datetime import datetime
from typing import Callable, Optional

from audio.capture import AudioCapture
from audio.buffer import RingAudioBuffer
from audio.processor import AudioProcessor
from models import ViolationEvent
from config import FORBIDDEN_WORDS
from audit_logger import ASRAuditEntry

logger = logging.getLogger('audio')


class AudioEngine(threading.Thread):
    """音频采集 → 缓冲 → 识别 调度器"""

    def __init__(self, event_queue, stop_event, output_dir='.'):
        super().__init__(daemon=True)
        self._event_queue = event_queue
        self._stop_event = stop_event
        self._output_dir = output_dir
        self._audit_callback: Optional[Callable] = None
        self._running = False

        # 三大组件（全部无参构造，读取配置）
        self._capture: Optional[AudioCapture] = None
        self._buffer: Optional[RingAudioBuffer] = None
        self._processor: Optional[AudioProcessor] = None

        # 懒加载保护
        self._processor_lock = threading.Lock()
        self._warmup_thread: Optional[threading.Thread] = None

    # ==================================================================
    # 公开接口
    # ==================================================================
    def set_audit_callback(self, cb):
        self._audit_callback = cb

    def run(self):
        if not self._setup():
            return
        self._running = True
        logger.info("AudioEngine 启动")
        try:
            self._capture.start()
            self._listen_loop()
        finally:
            self._cleanup()
            self._running = False
            logger.info("AudioEngine 已停止")

    def stop(self):
        self._stop_event.set()
        if self._capture:
            self._capture.stop()

    def get_status(self) -> dict:
        status = {
            'running': self._running,
            'capture_running': self._capture.running if self._capture else False,
            'capture_queue': self._capture.queue_size if self._capture else 0,
        }
        if self._buffer:
            s = self._buffer.stats()
            status['buffer_samples'] = s.samples
            status['buffer_duration'] = s.duration
            status['buffer_ready'] = s.ready
        status['model_loaded'] = getattr(self._processor, 'model_loaded', False)
        return status

    # ==================================================================
    # 内部实现
    # ==================================================================
    def _setup(self) -> bool:
        """创建采集与缓冲组件（无参数，完全从配置读取）"""
        try:
            self._capture = AudioCapture()
        except Exception:
            logger.exception("AudioCapture 初始化失败")
            return False

        self._buffer = RingAudioBuffer()
        return True

    def _ensure_processor(self):
        if self._processor is not None:
            return
        with self._processor_lock:
            if self._processor is not None:
                return
            self._processor = AudioProcessor(
                sensitive_words=FORBIDDEN_WORDS,
                warmup=False,  # ← 关键修改，避免重复预热
            )
            # 后台预热线程只执行一次
            self._warmup_thread = threading.Thread(
                target=self._safe_warmup,
                daemon=True,
                name="asr-warmup"
            )
            self._warmup_thread.start()

    def _safe_warmup(self):
        try:
            self._processor.warmup()
            logger.info("ASR 模型预热完成")
        except Exception:
            logger.exception("模型预热失败")

    def _listen_loop(self):
        """主循环：读取 → 缓冲 → 触发识别 → 分发结果"""
        while not self._stop_event.is_set():
            # capture.read() 使用默认 timeout（配置驱动）
            pcm = self._capture.read()
            if pcm is not None:
                self._buffer.append(pcm)

            if self._buffer.ready:
                audio = self._buffer.pop()
                if audio is not None:
                    self._ensure_processor()
                    result = self._processor.process(audio)
                    self._handle_result(result)

        # 处理残留数据
        if self._buffer.sample_count > 0:
            audio = self._buffer.flush()
            if audio is not None:
                self._ensure_processor()
                result = self._processor.process(audio)
                self._handle_result(result)

    def _handle_result(self, result):
        """结果分发：日志 → 审计 → 违禁词事件"""
        if not result or not result.text:
            return

        logger.info("识别: %s", result.text)

        # 审计
        if self._audit_callback:
            entry = ASRAuditEntry(
                timestamp=datetime.now(),
                text=result.text,
                audio_duration_sec=round(result.audio_duration, 2),
                audio_peak=0,
                buffer_chunks=0,
                matched_words=', '.join(result.sensitive_words) if result.sensitive_words else '',
                anomaly_flags='',
            )
            try:
                self._audit_callback(entry)
            except Exception:
                logger.exception("审计回调异常")

        # 违禁词事件（防阻塞）
        if result.is_sensitive:
            for word in result.sensitive_words:
                event = ViolationEvent(
                    timestamp=datetime.now(),
                    violation_type='forbidden_word',
                    description=f'违禁词: {word}',
                    context=result.text,
                )
                try:
                    self._event_queue.put_nowait(event)
                except queue.Full:
                    logger.warning("事件队列已满，丢弃违禁词事件: %s", word)

    def _cleanup(self):
        if self._capture:
            self._capture.stop()
        if self._buffer:
            self._buffer.clear()
        if self._processor:
            self._processor.reset()
        logger.debug("AudioEngine 资源已清理")
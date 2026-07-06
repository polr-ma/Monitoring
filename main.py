"""直播间人员工作状态监控系统 — 主入口"""

import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime

# 尽早抑制 tqdm/funasr 进度条
os.environ.setdefault('TQDM_DISABLE', '1')

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBS_DIR = os.path.join(_PROJECT_DIR, 'libs')
if _LIBS_DIR not in sys.path:
    sys.path.insert(0, _LIBS_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

os.environ.setdefault('MPLCONFIGDIR', os.path.join(_PROJECT_DIR, 'tmp'))
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

from camera_engine import CameraEngine
from audio_engine import AudioEngine
from violation_recorder import ViolationRecorder
from alert_player import AlertPlayer
from audit_logger import ASRAuditLogger
from noise_reducer import NoiseReducer
from obs_helper import OBSAudioHelper
from config import ALERT_COOLDOWN, AUDIO_CONFIG, NOISE_REDUCTION_CONFIG


def setup_logging(log_dir: str = '.'):
    """配置日志：控制台 + 文件双输出"""
    log_file = os.path.join(log_dir,
                            f'debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 文件 handler — 全量 DEBUG
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(name)-8s] %(levelname)-7s %(message)s',
        datefmt='%H:%M:%S'
    ))
    root.addHandler(fh)

    # 控制台 handler — WARNING 以上 + 音频 INFO
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter('[%(name)-8s] %(levelname)-7s %(message)s'))
    root.addHandler(ch)

    # audio logger 单独设低级别，方便看到语音诊断
    logging.getLogger('audio').setLevel(logging.DEBUG)
    logging.getLogger('audio.denoise').setLevel(logging.DEBUG)
    logging.getLogger('camera').setLevel(logging.DEBUG)

    return log_file


TYPE_ICONS = {
    'leave_post': '🚪',
    'return_post': '✅',
    'look_around': '👀',
    'head_down': '📱',
    'sleeping': '😴',
    'forbidden_word': '🚫',
}


def print_banner(recorder, log_file):
    bar = '─' * 60
    print(f'\n{bar}')
    print(f'  🎥 直播监控系统    文档: {os.path.basename(recorder.filepath)}')
    print(f'  📋 调试日志: {os.path.basename(log_file)}')
    print(f'{bar}')


def main():
    log_file = setup_logging('.')
    logger = logging.getLogger('main')
    logger.info('系统启动')

    event_queue = queue.Queue(maxsize=500)
    stop_event = threading.Event()

    recorder = ViolationRecorder(output_dir='.')
    alert_player = AlertPlayer(ALERT_COOLDOWN)

    camera_engine = CameraEngine(event_queue, stop_event, show_preview=True)
    audio_engine = AudioEngine(event_queue, stop_event, output_dir='.')

    # ── 降噪器 ─────────────────────────────
    noise_reducer = NoiseReducer(
        sample_rate=AUDIO_CONFIG['sample_rate'],
        n_fft=NOISE_REDUCTION_CONFIG['n_fft'],
        hop_length=NOISE_REDUCTION_CONFIG['hop_length'],
        noise_reduce_db=NOISE_REDUCTION_CONFIG['noise_reduce_db'],
        noise_smooth_frames=NOISE_REDUCTION_CONFIG['noise_smooth_frames'],
        learning_rate=NOISE_REDUCTION_CONFIG['learning_rate'],
        enabled=NOISE_REDUCTION_CONFIG['enabled'],
    )
    audio_engine.set_noise_reducer(noise_reducer)

    # ── ASR 审计日志 ─────────────────────────
    asr_audit_logger = ASRAuditLogger(output_dir='.')
    audio_engine.set_audit_callback(asr_audit_logger.add_entry)

    recent_violations = []

    camera_engine.start()
    audio_engine.start()

    print_banner(recorder, log_file)
    print(f'  📝 ASR审计: {os.path.basename(asr_audit_logger.filepath)}')
    nr_label = f'降噪: {"开" if noise_reducer.enabled else "关"} ({NOISE_REDUCTION_CONFIG["noise_reduce_db"]}dB)'
    print(f'  🔇 {nr_label}')
    print(f'{"─" * 60}')
    print('  按 Ctrl+C 停止   预览窗口按 Q 可关闭')
    print('')

    def signal_handler(sig, frame):
        print('\n⚠ 正在停止...')
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)

    # 上次打印状态行的时间
    last_status_print = 0

    try:
        while not stop_event.is_set():
            # 消费事件
            try:
                while True:
                    event = event_queue.get_nowait()
                    recent_violations.append(event)
                    if len(recent_violations) > 200:
                        recent_violations.pop(0)
                    recorder.add_violation(event)
                    played = alert_player.play(event.violation_type)

                    icon = TYPE_ICONS.get(event.violation_type, '❓')
                    ts = event.timestamp.strftime('%H:%M:%S')
                    alert_mark = ' 🔔' if played else ''
                    msg = f'  [{ts}] {icon} {event.description}{alert_mark}'
                    print(msg)
                    logger.info(f'违规事件: {event.violation_type} — {event.description}')
            except queue.Empty:
                pass

            # 摄像头状态
            cam = camera_engine.get_status()
            audio = audio_engine.get_status()

            # 状态行（1秒刷新一次）
            now = time.time()
            if now - last_status_print >= 1.0:
                status_line = f'\r  FPS:{cam["fps"]:.1f}  '
                if cam['is_absent']:
                    status_line += '| ⚠离开 '
                if cam['is_looking_around']:
                    status_line += '| 👀张望 '
                if cam['is_head_down']:
                    status_line += '| 📱低头 '
                if cam['is_sleeping']:
                    status_line += '| 😴闭眼 '
                if not any([cam['is_absent'], cam['is_looking_around'],
                            cam['is_head_down'], cam['is_sleeping']]):
                    status_line += '| ✅正常 '
                status_line += (f'| Y:{cam["yaw"]:.0f} '
                                f'P:{cam["pitch"]:.0f} E:{cam["ear"]:.2f}')

                if audio.get('sensevoice_available'):
                    buf = audio.get('buffer_chunks', 0)
                    results = audio.get('last_result_count', 0)
                    peak = audio.get('audio_peak', 0)
                    nr_db = audio.get('denoise_reduction_db', 0)
                    status_line += f' | 🎤缓冲:{buf} 结果:{results} 电平:{peak:.0f} NR:{nr_db:.0f}dB'
                else:
                    status_line += ' | 🎤不可用'

                print(status_line, end='', flush=True)
                last_status_print = now

            time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        print('\n💾 正在保存...')
        camera_engine.join(timeout=3)
        audio_engine.join(timeout=3)
        recorder.close()
        asr_audit_logger.close()
        logger.info(f'系统停止，违规记录: {recorder.filepath}')
        print(f'✅ 违规记录已保存至: {recorder.filepath}')
        print(f'📋 调试日志: {log_file}')
        print(f'📝 ASR审计日志: {asr_audit_logger.filepath}')
        print('   系统已停止。')


if __name__ == '__main__':
    main()

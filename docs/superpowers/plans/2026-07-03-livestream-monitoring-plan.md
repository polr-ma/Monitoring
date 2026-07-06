# 直播间人员工作状态监控系统 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个实时监控系统，通过摄像头检测主播行为违规，通过麦克风检测违禁词，违规时声音告警并写入 Word 文档。

**Architecture:** 多线程管道：CameraEngine 线程 + AudioEngine 线程 → 线程安全队列 → 主线程消费（Word 写入 + 告警播放）。

**Tech Stack:** Python 3.10+, OpenCV, MediaPipe, Vosk, pyahocorasick, python-docx, PyAudio, winsound

---

### Task 1: 项目骨架 — requirements.txt, models.py, config.py

**Files:**
- Create: `D:\study\Monitoring\requirements.txt`
- Create: `D:\study\Monitoring\models.py`
- Create: `D:\study\Monitoring\config.py`

- [ ] **Step 1: 创建 requirements.txt**

```text
opencv-python-headless>=4.8.0
mediapipe>=0.10.0
vosk>=0.3.45
pyahocorasick>=2.0.0
python-docx>=0.8.11
PyAudio>=0.2.13
numpy>=1.24.0
```

- [ ] **Step 2: 安装依赖**

```powershell
C:\Python314\python.exe -m pip install opencv-python-headless mediapipe vosk pyahocorasick python-docx PyAudio numpy --break-system-packages 2>&1
```

验证：无报错即成功。

- [ ] **Step 3: 创建 models.py — ViolationEvent 数据类**

```python
"""共享数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ViolationEvent:
    """违规事件"""
    timestamp: datetime = field(default_factory=datetime.now)
    violation_type: str = ""   # 'leave_post' | 'return_post' | 'look_around' |
                                # 'head_down' | 'sleeping' | 'forbidden_word'
    description: str = ""
    context: Optional[str] = None  # 违禁词上下文，仅 forbidden_word 类型使用
```

验证：`& "C:\Python314\python.exe" -c "from models import ViolationEvent; e = ViolationEvent(violation_type='test', description='test'); print(e)"`

- [ ] **Step 4: 创建 config.py — 集中配置**

```python
"""集中配置文件"""

# ── 违禁词列表 ──────────────────────────────────────────
FORBIDDEN_WORDS = [
    # 业务相关类（会被平台直接处罚）
    '办号', '办卡', '选号', '入网', '激活', '办理号卡', '办理手机卡', '选手机号',
    '开通', '办理合约机', '购机送卡', '办卡送手机', '大流量卡',
    '融合宽带', '新入网宽带', '宽带合约',
    # 营销承诺类（会被判定为虚假宣传）
    '最便宜', '最划算', '全网最低', '性价比最高', '最快', '最强', '第一', '顶级', '独家',
    '免费', '0元', '零元', '白送', '送卡', '送话费', '送流量', '限时', '限量', '抢', '秒杀',
    '内部价', '员工价', '内部福利',
    '终身使用', '无限流量', '不限速', '全国通用', '官方授权', '唯一指定',
    # 违规导流类（会被判定为私下导流）
    '加微信', '加QQ', '打电话', '私信我办', '私聊办理', '发手机号', '发你地址', '加群领福利',
    '线上办理', '远程办理', '扫码办理', 'APP办理', '线上核销',
    # 资质违规类（最隐蔽、最容易踩坑）
    '宽带+号卡', '办宽带送号卡', '办卡送宽带', '手机+宽带套餐', '家庭套餐',
    '私信发你资费', '私信了解详情', '到店办更划算', '找我办有优惠', '专属福利', '内部渠道',
]

# ── 行为检测阈值 ──────────────────────────────────────────
POSE_THRESHOLDS = {
    'absent_frames': 30,       # 连续多少帧无人 → 离开工位
    'yaw_threshold': 30.0,     # yaw 绝对值 > 此值 → 东张西望
    'look_around_seconds': 2.0, # 东张西望持续时间
    'pitch_threshold': 25.0,   # pitch > 此值 → 低头
    'head_down_seconds': 5.0,  # 低头持续时间
    'ear_threshold': 0.2,      # EAR < 此值 → 闭眼
    'sleeping_seconds': 3.0,   # 闭眼持续时间
}

# ── 摄像头配置 ──────────────────────────────────────────
CAMERA_CONFIG = {
    'index': 0,
    'width': 640,
    'height': 480,
    'fps': 30,
}

# ── 音频配置 ──────────────────────────────────────────
AUDIO_CONFIG = {
    'sample_rate': 16000,
    'chunk_size': 3200,        # 每次读取的帧数 (200ms @ 16kHz)
    'device_index': None,      # None = 系统默认麦克风
}

# ── 告警配置 ──────────────────────────────────────────
ALERT_COOLDOWN = {
    'leave_post': 10.0,
    'return_post': 5.0,
    'look_around': 10.0,
    'head_down': 15.0,
    'sleeping': 10.0,
    'forbidden_word': 5.0,
}

# ── Vosk 模型路径 ──────────────────────────────────────────
# 下载地址: https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
# 解压后放到项目目录下的 models/ 文件夹
VOSK_MODEL_PATH = 'models/vosk-model-small-cn-0.22'
```

验证：`& "C:\Python314\python.exe" -c "import config; print(len(config.FORBIDDEN_WORDS), config.POSE_THRESHOLDS)"`

- [ ] **Step 5: 提交**

```bash
git add requirements.txt models.py config.py
git commit -m "feat: add project skeleton with config and models"
```

---

### Task 2: alert_player.py — 声音告警 + 防抖

**Files:**
- Create: `D:\study\Monitoring\alert_player.py`

- [ ] **Step 1: 创建 alert_player.py**

```python
"""声音告警模块 — 使用 Windows 系统音，带防抖机制"""

import time
import winsound
from typing import Dict


class AlertPlayer:
    """声音告警播放器，同一类型告警在冷却时间内不重复播放"""

    def __init__(self, cooldowns: Dict[str, float]):
        self._cooldowns = cooldowns        # {violation_type: cooldown_seconds}
        self._last_alert_time: Dict[str, float] = {}

    def play(self, violation_type: str) -> bool:
        """播放告警音。返回 True 表示实际播放了，False 表示被冷却跳过。"""
        now = time.time()
        cooldown = self._cooldowns.get(violation_type, 5.0)
        last = self._last_alert_time.get(violation_type, 0.0)

        if now - last < cooldown:
            return False

        self._last_alert_time[violation_type] = now
        try:
            # 使用系统惊叹声，类似 QQ/微信消息提示
            winsound.PlaySound('SystemExclamation', winsound.SND_ALIAS)
        except Exception:
            # 备用：MessageBeep
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True
```

验证：`& "C:\Python314\python.exe" -c "from alert_player import AlertPlayer; ap = AlertPlayer({'test': 1.0}); assert ap.play('test') is True; assert ap.play('test') is False; print('OK')"`

- [ ] **Step 2: 提交**

```bash
git add alert_player.py
git commit -m "feat: add alert player with cooldown debounce"
```

---

### Task 3: violation_recorder.py — Word 文档违规记录

**Files:**
- Create: `D:\study\Monitoring\violation_recorder.py`

- [ ] **Step 1: 创建 violation_recorder.py**

```python
"""违规记录模块 — 自动写入 Word 文档"""

import os
import time
from datetime import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn


class ViolationRecorder:
    """违规事件 Word 文档记录器"""

    def __init__(self, output_dir: str = '.'):
        self._output_dir = output_dir
        self._doc: Document = None
        self._table = None
        self._counter = 0
        self._save_interval = 5       # 每写入 N 条自动保存
        self._pending_count = 0
        self._filepath = ''
        self._init_document()

    def _init_document(self):
        """创建 Word 文档和表格"""
        self._doc = Document()

        # 页面设置
        section = self._doc.sections[0]
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)

        # 标题
        title = self._doc.add_heading('直播间违规记录', level=1)
        title.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 生成时间
        now = datetime.now()
        self._doc.add_paragraph(f'生成时间：{now.strftime("%Y-%m-%d %H:%M:%S")}')
        self._doc.add_paragraph('')

        # 创建表格
        self._table = self._doc.add_table(rows=1, cols=4, style='Table Grid')
        self._table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 表头
        header_cells = self._table.rows[0].cells
        headers = ['序号', '时间', '违规类型', '具体描述']
        for i, text in enumerate(headers):
            header_cells[i].text = text
            for paragraph in header_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.bold = True
                    run.font.size = Pt(10)
                paragraph.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 设置列宽
        widths = [Cm(1.5), Cm(3.5), Cm(3.0), Cm(8.0)]
        for i, width in enumerate(widths):
            for cell in self._table.columns[i].cells:
                cell.width = width

        # 文件路径
        filename = f'违规记录_{now.strftime("%Y-%m-%d_%H-%M-%S")}.docx'
        self._filepath = os.path.join(self._output_dir, filename)
        self._save()

    def add_violation(self, event) -> str:
        """添加一条违规记录，返回文件路径"""
        self._counter += 1
        self._pending_count += 1

        row = self._table.add_row()
        cells = row.cells

        # 序号
        cells[0].text = str(self._counter)
        cells[0].paragraphs[0].alignment = WD_TABLE_ALIGNMENT.CENTER

        # 时间
        cells[1].text = event.timestamp.strftime('%H:%M:%S')

        # 违规类型
        type_labels = {
            'leave_post': '离开工位',
            'return_post': '回到工位',
            'look_around': '东张西望',
            'head_down': '低头(瞌睡/玩手机)',
            'sleeping': '睡觉/闭眼',
            'forbidden_word': '语音违禁词',
        }
        cells[2].text = type_labels.get(event.violation_type, event.violation_type)

        # 具体描述
        cells[3].text = event.description

        # 设置字体大小
        for cell in cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)

        # 定期保存
        if self._pending_count >= self._save_interval:
            self._save()
            self._pending_count = 0

        return self._filepath

    def _save(self):
        """保存文档到磁盘"""
        if self._doc and self._filepath:
            self._doc.save(self._filepath)

    def close(self):
        """关闭时强制保存"""
        self._save()

    @property
    def filepath(self) -> str:
        return self._filepath
```

验证：`& "C:\Python314\python.exe" -c "from violation_recorder import ViolationRecorder; from models import ViolationEvent; r = ViolationRecorder('.'); r.add_violation(ViolationEvent(violation_type='leave_post', description='测试离开工位')); r.close(); print('File:', r.filepath)"`

- [ ] **Step 2: 提交**

```bash
git add violation_recorder.py
git commit -m "feat: add Word document violation recorder"
```

---

### Task 4: camera_engine.py — 摄像头采集 + 行为状态机

**Files:**
- Create: `D:\study\Monitoring\camera_engine.py`

- [ ] **Step 1: 创建 camera_engine.py**

```python
"""摄像头引擎 — 采集 + MediaPipe 推理 + 行为状态机"""

import time
import threading
import queue
from datetime import datetime

import cv2
import numpy as np
import mediapipe as mp

from models import ViolationEvent
from config import POSE_THRESHOLDS, CAMERA_CONFIG


class CameraEngine(threading.Thread):
    """摄像头行为检测线程"""

    def __init__(self, event_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._event_queue = event_queue
        self._stop_event = stop_event

        # 状态机状态
        self._absent_frames = 0          # 无人帧计数
        self._is_absent = False          # 当前是否处于离开状态

        self._look_around_start = None   # 东张西望开始时间
        self._is_looking_around = False

        self._head_down_start = None     # 低头开始时间
        self._is_head_down = False

        self._eye_closed_start = None    # 闭眼开始时间
        self._is_sleeping = False

        # FPS 统计
        self._frame_count = 0
        self._fps_start = time.time()
        self.current_fps = 0.0

    def run(self):
        self._setup()
        try:
            while not self._stop_event.is_set():
                self._process_frame()
        finally:
            self._cleanup()

    def _setup(self):
        """初始化 MediaPipe 和摄像头"""
        self.mp_pose = mp.solutions.pose
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils

        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        idx = CAMERA_CONFIG['index']
        self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_CONFIG['width'])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_CONFIG['height'])
        self.cap.set(cv2.CAP_PROP_FPS, CAMERA_CONFIG['fps'])

        if not self.cap.isOpened():
            print(f'[CameraEngine] 警告：无法打开摄像头 (index={idx})')

    def _process_frame(self):
        if not self.cap or not self.cap.isOpened():
            time.sleep(0.1)
            return

        ret, frame = self.cap.read()
        if not ret:
            time.sleep(0.01)
            return

        # FPS
        self._frame_count += 1
        elapsed = time.time() - self._fps_start
        if elapsed >= 1.0:
            self.current_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_start = time.time()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False

        pose_results = self.pose.process(rgb)
        face_results = self.face_mesh.process(rgb)

        now = time.time()

        # ── 1. 人体检测：判断是否有人 ──
        has_person = pose_results.pose_landmarks is not None

        # ── 2. 头部姿态（基于 Face Mesh） ──
        yaw, pitch, ear = None, None, None
        if face_results.multi_face_landmarks:
            face_landmarks = face_results.multi_face_landmarks[0]
            h, w = frame.shape[:2]
            landmarks_2d = np.array([
                (lm.x * w, lm.y * h) for lm in face_landmarks.landmark
            ])
            landmarks_3d = np.array([
                (lm.x, lm.y, lm.z) for lm in face_landmarks.landmark
            ])
            yaw, pitch = self._estimate_head_pose(landmarks_2d, landmarks_3d, w, h)
            ear = self._calc_ear(landmarks_2d)

        # ── 3. 行为状态机 ──
        self._update_state(has_person, yaw, pitch, ear, now)

    def _estimate_head_pose(self, landmarks_2d, landmarks_3d, width, height):
        """估算头部 yaw 和 pitch（简化几何法）"""
        # 使用鼻尖(1)、左眼外角(33)、右眼外角(263) 三个点
        nose_tip = landmarks_3d[1]
        left_eye = landmarks_3d[33]
        right_eye = landmarks_3d[263]

        # 两眼中心
        eye_center = (left_eye + right_eye) / 2
        # 鼻尖到两眼中心的向量
        nose_to_eye = eye_center - nose_tip

        # yaw: 鼻尖偏离中线的水平角度
        # 简化：用两眼在画面中的不对称性估算
        left_2d = landmarks_2d[33]
        right_2d = landmarks_2d[263]
        nose_2d = landmarks_2d[1]
        mid = (left_2d + right_2d) / 2
        yaw = (nose_2d[0] - mid[0]) / (np.linalg.norm(right_2d - left_2d) + 1e-6) * 60

        # pitch: 鼻尖到眼中心的垂直分量
        pitch = np.arctan2(-nose_to_eye[1], np.linalg.norm([nose_to_eye[0], nose_to_eye[2]]) + 1e-6)
        pitch = np.degrees(pitch)

        return yaw, pitch

    def _calc_ear(self, landmarks_2d):
        """计算眼睛纵横比 (Eye Aspect Ratio)，左右眼平均"""
        # 右眼索引 (根据 MediaPipe Face Mesh)
        right_indices = [33, 160, 158, 133, 153, 144]
        # 左眼索引
        left_indices = [362, 385, 387, 263, 373, 380]

        def ear(indices):
            pts = [landmarks_2d[i] for i in indices]
            # 垂直距离
            v1 = np.linalg.norm(pts[1] - pts[5])
            v2 = np.linalg.norm(pts[2] - pts[4])
            # 水平距离
            h = np.linalg.norm(pts[0] - pts[3])
            if h < 1e-6:
                return 1.0
            return (v1 + v2) / (2.0 * h)

        return (ear(right_indices) + ear(left_indices)) / 2.0

    def _update_state(self, has_person, yaw, pitch, ear, now):
        """行为状态机，检测状态变化并推送事件"""
        th = POSE_THRESHOLDS

        # ── 离开 / 回到工位 ──
        if not has_person:
            self._absent_frames += 1
            if not self._is_absent and self._absent_frames >= th['absent_frames']:
                self._is_absent = True
                self._push_event('leave_post', '主播离开工位')
                # 重置所有正在进行的状态
                self._look_around_start = None
                self._is_looking_around = False
                self._head_down_start = None
                self._is_head_down = False
                self._eye_closed_start = None
                self._is_sleeping = False
        else:
            if self._is_absent:
                self._is_absent = False
                self._push_event('return_post', '主播回到工位')
            self._absent_frames = 0

            # ── 离开状态时不检测以下行为 ──
            # ── 东张西望 ──
            if yaw is not None and abs(yaw) > th['yaw_threshold']:
                if self._look_around_start is None:
                    self._look_around_start = now
                elif not self._is_looking_around and (now - self._look_around_start) >= th['look_around_seconds']:
                    self._is_looking_around = True
                    direction = '左' if yaw > 0 else '右'
                    self._push_event('look_around', f'主播东张西望（偏向{direction}）')
            else:
                self._look_around_start = None
                self._is_looking_around = False

            # ── 低头 ──
            if pitch is not None and pitch > th['pitch_threshold']:
                if self._head_down_start is None:
                    self._head_down_start = now
                elif not self._is_head_down and (now - self._head_down_start) >= th['head_down_seconds']:
                    self._is_head_down = True
                    self._push_event('head_down', '主播持续低头（可能瞌睡或玩手机）')
            else:
                self._head_down_start = None
                self._is_head_down = False

            # ── 闭眼 / 睡觉 ──
            if ear is not None and ear < th['ear_threshold']:
                if self._eye_closed_start is None:
                    self._eye_closed_start = now
                elif not self._is_sleeping and (now - self._eye_closed_start) >= th['sleeping_seconds']:
                    self._is_sleeping = True
                    self._push_event('sleeping', '主播疑似睡觉（长时间闭眼）')
            else:
                self._eye_closed_start = None
                self._is_sleeping = False

    def _push_event(self, vtype, desc):
        event = ViolationEvent(
            timestamp=datetime.now(),
            violation_type=vtype,
            description=desc,
        )
        self._event_queue.put(event)

    def _cleanup(self):
        if hasattr(self, 'cap') and self.cap:
            self.cap.release()
        if hasattr(self, 'pose') and self.pose:
            self.pose.close()
        if hasattr(self, 'face_mesh') and self.face_mesh:
            self.face_mesh.close()

    def get_status(self) -> dict:
        """返回当前状态摘要"""
        return {
            'fps': round(self.current_fps, 1),
            'is_absent': self._is_absent,
            'is_looking_around': self._is_looking_around,
            'is_head_down': self._is_head_down,
            'is_sleeping': self._is_sleeping,
        }
```

验证：语法检查

```powershell
& "C:\Python314\python.exe" -c "import ast; ast.parse(open('camera_engine.py').read()); print('Syntax OK')"
```

- [ ] **Step 2: 提交**

```bash
git add camera_engine.py
git commit -m "feat: add camera engine with behavior state machine"
```

---

### Task 5: audio_engine.py — 麦克风采集 + 违禁词检测

**Files:**
- Create: `D:\study\Monitoring\audio_engine.py`

- [ ] **Step 1: 创建 audio_engine.py**

```python
"""音频引擎 — 麦克风采集 + Vosk 语音识别 + AC 自动机违禁词匹配"""

import json
import queue
import threading
import time
from datetime import datetime

import ahocorasick
import pyaudio

from models import ViolationEvent
from config import FORBIDDEN_WORDS, AUDIO_CONFIG, VOSK_MODEL_PATH


class AudioEngine(threading.Thread):
    """音频检测线程"""

    def __init__(self, event_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._event_queue = event_queue
        self._stop_event = stop_event

        # AC 自动机
        self._automaton = None
        self._build_automaton()

        # Vosk 模型
        self._recognizer = None
        self._vosk_available = False

        # 状态
        self._matched_in_current = set()  # 防重复（同一句同一词只报一次）
        self._current_sentence = ''       # 当前积累的句子片段

    def _build_automaton(self):
        """构建 AC 自动机"""
        self._automaton = ahocorasick.Automaton()
        for word in FORBIDDEN_WORDS:
            self._automaton.add_word(word, word)
        self._automaton.make_automaton()

    def run(self):
        self._setup()
        if not self._vosk_available:
            return

        try:
            self._listen_loop()
        finally:
            self._cleanup()

    def _setup(self):
        """初始化 PyAudio 和 Vosk"""
        try:
            import vosk
            self.vosk = vosk
        except ImportError:
            print('[AudioEngine] 错误：vosk 未安装')
            return

        # 检查模型
        import os
        if not os.path.exists(VOSK_MODEL_PATH):
            print(f'[AudioEngine] 错误：Vosk 模型未找到: {VOSK_MODEL_PATH}')
            print('[AudioEngine] 下载地址: https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip')
            print('[AudioEngine] 解压后放到 models/ 目录下')
            return

        model = self.vosk.Model(VOSK_MODEL_PATH)
        self._recognizer = self.vosk.KaldiRecognizer(model, AUDIO_CONFIG['sample_rate'])
        self._recognizer.SetWords(True)

        self._audio = pyaudio.PyAudio()
        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=AUDIO_CONFIG['sample_rate'],
            input=True,
            frames_per_buffer=AUDIO_CONFIG['chunk_size'],
            input_device_index=AUDIO_CONFIG['device_index'],
        )
        self._stream.start_stream()
        self._vosk_available = True
        print('[AudioEngine] 音频引擎已启动')

    def _listen_loop(self):
        while not self._stop_event.is_set():
            try:
                data = self._stream.read(
                    AUDIO_CONFIG['chunk_size'],
                    exception_on_overflow=False,
                )
            except Exception:
                time.sleep(0.01)
                continue

            if self._recognizer.AcceptWaveform(data):
                result = json.loads(self._recognizer.Result())
                text = result.get('text', '').strip()
                if text:
                    self._current_sentence = text
                    self._check_text(text)
                    self._matched_in_current.clear()
            else:
                partial = json.loads(self._recognizer.PartialResult())
                partial_text = partial.get('partial', '').strip()
                if partial_text and partial_text != self._current_sentence:
                    self._check_text(partial_text)

    def _check_text(self, text: str):
        """用 AC 自动机扫描文本，匹配违禁词"""
        matches = []
        for end_idx, word in self._automaton.iter(text):
            if word not in self._matched_in_current:
                matches.append((end_idx, word))
                self._matched_in_current.add(word)

        for end_idx, word in matches:
            # 提取上下文（前后各 10 字）
            start = max(0, end_idx - len(word) - 10)
            end = min(len(text), end_idx + 10)
            ctx = text[start:end]

            event = ViolationEvent(
                timestamp=datetime.now(),
                violation_type='forbidden_word',
                description=f'检测到违禁词：「{word}」',
                context=ctx,
            )
            self._event_queue.put(event)

    def _cleanup(self):
        if hasattr(self, '_stream') and self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if hasattr(self, '_audio') and self._audio:
            self._audio.terminate()

    def get_status(self) -> dict:
        return {
            'vosk_available': self._vosk_available,
            'current_text': self._current_sentence if hasattr(self, '_current_sentence') else '',
        }
```

验证：语法检查

```powershell
& "C:\Python314\python.exe" -c "import ast; ast.parse(open('audio_engine.py').read()); print('Syntax OK')"
```

- [ ] **Step 2: 提交**

```bash
git add audio_engine.py
git commit -m "feat: add audio engine with forbidden word detection"
```

---

### Task 6: main.py — 入口 + 线程编排 + 状态面板

**Files:**
- Create: `D:\study\Monitoring\main.py`

- [ ] **Step 1: 创建 main.py**

```python
"""直播间人员工作状态监控系统 — 主入口"""

import os
import queue
import signal
import sys
import threading
import time

from camera_engine import CameraEngine
from audio_engine import AudioEngine
from violation_recorder import ViolationRecorder
from alert_player import AlertPlayer
from config import ALERT_COOLDOWN


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_status(camera_status, audio_status, recent_violations, recorder):
    """打印运行状态面板"""
    clear_screen()
    print('=' * 55)
    print('  直播间人员工作状态监控系统')
    print('=' * 55)
    print(f'  运行时间: {time.strftime("%H:%M:%S")}')
    print(f'  Word 文件: {os.path.basename(recorder.filepath) if recorder.filepath else "N/A"}')
    print('-' * 55)
    print('  【摄像头状态】')
    print(f'    FPS: {camera_status.get("fps", 0):.1f}')
    print(f'    在工位: {"否" if camera_status.get("is_absent") else "是"}')
    print(f'    东张西望: {"⚠ 是" if camera_status.get("is_looking_around") else "否"}')
    print(f'    低头: {"⚠ 是" if camera_status.get("is_head_down") else "否"}')
    print(f'    闭眼: {"⚠ 是" if camera_status.get("is_sleeping") else "否"}')
    print('-' * 55)
    print('  【音频状态】')
    print(f'    Vosk: {"运行中" if audio_status.get("vosk_available") else "未就绪"}')
    text = audio_status.get('current_text', '')
    if text:
        display = text[:50] + ('...' if len(text) > 50 else '')
        print(f'    最近识别: {display}')
    print('-' * 55)
    print('  【最近违规记录】')
    if recent_violations:
        for v in recent_violations[-5:]:
            ts = v.timestamp.strftime('%H:%M:%S')
            print(f'    [{ts}] {v.description}')
    else:
        print('    (暂无)')
    print('-' * 55)
    print('  按 Ctrl+C 停止监控')
    print('=' * 55)


def main():
    # 事件队列
    event_queue = queue.Queue(maxsize=500)
    stop_event = threading.Event()

    # 初始化各模块
    recorder = ViolationRecorder(output_dir='.')
    alert_player = AlertPlayer(ALERT_COOLDOWN)

    camera_engine = CameraEngine(event_queue, stop_event)
    audio_engine = AudioEngine(event_queue, stop_event)

    recent_violations = []

    # 启动线程
    camera_engine.start()
    audio_engine.start()

    print(f'系统已启动，Word 文件: {recorder.filepath}')
    print('按 Ctrl+C 停止...')

    def signal_handler(sig, frame):
        print('\n正在停止...')
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while not stop_event.is_set():
            # 消费事件队列
            try:
                while True:
                    event = event_queue.get_nowait()
                    recent_violations.append(event)
                    # 只保留最近 100 条在内存中显示
                    if len(recent_violations) > 100:
                        recent_violations.pop(0)
                    # 写入 Word
                    recorder.add_violation(event)
                    # 播放告警
                    alert_player.play(event.violation_type)
            except queue.Empty:
                pass

            # 刷新状态面板
            camera_status = camera_engine.get_status()
            audio_status = audio_engine.get_status()
            print_status(camera_status, audio_status, recent_violations, recorder)

            time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        print('正在保存并退出...')
        camera_engine.join(timeout=3)
        audio_engine.join(timeout=3)
        recorder.close()
        print(f'违规记录已保存至: {recorder.filepath}')
        print('系统已停止。')


if __name__ == '__main__':
    main()
```

验证：语法检查

```powershell
& "C:\Python314\python.exe" -c "import ast; ast.parse(open('main.py').read()); print('Syntax OK')"
```

- [ ] **Step 2: 提交**

```bash
git add main.py
git commit -m "feat: add main entry with thread orchestration and status panel"
```

---

### Task 7: 集成验证 — 检查所有模块可导入

- [ ] **Step 1: 创建 models/ 目录和 Vosk 模型占位说明**

```powershell
New-Item -ItemType Directory -Path "D:\study\Monitoring\models" -Force | Out-Null
```

创建 `models/README.txt`:

```text
Vosk 中文模型
==============

下载地址: https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip

1. 下载 vosk-model-small-cn-0.22.zip（约 42MB）
2. 解压到本目录，确保路径为: models/vosk-model-small-cn-0.22/
3. 解压后结构:
   models/vosk-model-small-cn-0.22/
   ├── am/
   ├── conf/
   ├── graph/
   ├── ivector/
   └── ...
```

- [ ] **Step 2: 全部模块导入测试**

```powershell
& "C:\Python314\python.exe" -c "
import importlib
modules = ['models', 'config', 'alert_player', 'violation_recorder', 'camera_engine', 'audio_engine', 'main']
for m in modules:
    importlib.import_module(m)
    print(f'  {m}: OK')
print('All modules import successfully!')
"
```

预期：全部模块导入成功（audio_engine 可能因 Vosk 模型不存在而在导入时报 warning 但不会崩溃）

- [ ] **Step 3: 单元测试 — AC 自动机匹配**

```powershell
& "C:\Python314\python.exe" -c "
import ahocorasick
from config import FORBIDDEN_WORDS

auto = ahocorasick.Automaton()
for w in FORBIDDEN_WORDS:
    auto.add_word(w, w)
auto.make_automaton()

test_cases = [
    ('大家好今天给大家介绍最便宜的套餐', ['最便宜']),
    ('加我微信私聊办理', ['加微信', '私聊办理']),
    ('这个卡是免费的', ['免费']),
    ('正常说话没有违禁词', []),
]

for text, expected in test_cases:
    found = set()
    for end, word in auto.iter(text):
        found.add(word)
    status = 'PASS' if found == set(expected) else f'FAIL (got {found}, expected {expected})'
    print(f'{status}: \"{text}\" -> {found}')
print('AC automaton tests done.')
"
```

- [ ] **Step 4: 提交**

```bash
git add models/README.txt
git commit -m "chore: add Vosk model download instructions and integration tests"
```

---

## 部署运行说明

部署完成后，在项目目录运行：

```powershell
& "C:\Python314\python.exe" main.py
```

**前置条件：**
1. 安装所有依赖（Task 1 Step 2）
2. 下载 Vosk 中文模型并放到 `models/vosk-model-small-cn-0.22/`
3. 确保摄像头和麦克风可用

**输出：**
- 终端实时状态面板
- `违规记录_YYYY-MM-DD_HH-MM-SS.docx` 违规记录文件

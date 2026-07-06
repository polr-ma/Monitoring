# 直播间人员工作状态监控系统 — 设计文档

> 创建时间：2026-07-03
> 状态：已确认

## 概述

一个运行在直播电脑上的实时监控系统，通过摄像头检测主播行为违规（离开工位、东张西望、低头/瞌睡、闭眼睡觉），通过麦克风检测违禁词，违规事件即时声音告警并自动记录到 Word 文档。

**监控对象：** 单人（主播本人）
**运行环境：** 普通 Windows 电脑 / 直播用机器，CPU 推理

---

## 技术选型

| 模块 | 技术 | 版本/备注 |
|------|------|-----------|
| 摄像头采集 | OpenCV (`opencv-python-headless`) | 无 GUI 依赖版本 |
| 人体姿态检测 | MediaPipe Pose | 33 个关键点 |
| 头部姿态/人脸 | MediaPipe Face Mesh | 468 个人脸关键点 |
| 语音识别 | Vosk (`vosk`) | 中文小模型 `vosk-model-small-cn-0.22`，约 42MB |
| 违禁词匹配 | AC 自动机 (`pyahocorasick`) | 单次扫描 O(n) |
| Word 文档 | `python-docx` | 外部进程可随时打开 |
| 声音告警 | `winsound` (Windows 内置) | 零依赖 |
| 音频采集 | `PyAudio` | 跨平台麦克风采集 |

**全部免费、开源、离线运行。**

---

## 架构

多线程管道架构，三个核心线程：

```
摄像头线程 → 行为检测 → ┐
                        ├→ 违规事件队列 (queue.Queue) → 主线程 → Word 记录 + 声音告警
音频线程   → 违禁词检测 → ┘
```

### 文件结构

```
D:\study\Monitoring\
├── main.py                  # 入口，线程管理，状态面板
├── config.py                # 配置：违禁词、阈值、摄像头参数
├── camera_engine.py         # 摄像头采集 + MediaPipe 推理 + 行为状态机
├── audio_engine.py          # 麦克风采集 + Vosk 识别 + 违禁词匹配
├── violation_recorder.py    # Word 文档写入
├── alert_player.py          # 声音告警（防抖）
├── requirements.txt
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-07-03-livestream-monitoring-design.md
```

---

## 模块设计

### 1. `config.py` — 集中配置

- `FORBIDDEN_WORDS`: 违禁词列表（四类：业务相关、营销承诺、违规导流、资质违规）
- `POSE_THRESHOLDS`: 行为检测阈值（离开帧数、yaw/pitch 角度、EAR 阈值、持续时间）
- `CAMERA_CONFIG`: 摄像头索引、分辨率、帧率
- `AUDIO_CONFIG`: 采样率、设备索引
- `ALERT_COOLDOWN`: 告警冷却时间（同类型违规不重复响）

### 2. `camera_engine.py` — 摄像头 + 行为检测

**MediaPipe 初始化：**
- Pose (static_image_mode=False, model_complexity=1, min_detection_confidence=0.5)
- Face Mesh (static_image_mode=False, max_num_faces=1, min_detection_confidence=0.5)

**行为状态机（4 个状态各带计时器）：**

| 行为 | 判定条件 | 触发阈值 |
|------|----------|----------|
| 离开工位 | 连续 N 帧未检测到人体 | 30 帧（约 1 秒） |
| 回到工位 | 离开状态后重新检测到人体 | 立即 |
| 东张西望 | \|yaw\| > 30° | 持续 2 秒 |
| 低头 | pitch > 25°（头前倾） | 持续 5 秒 |
| 闭眼 | EAR < 0.2 | 持续 3 秒 |

**实现细节：**
- 每帧通过 `mp.solutions.face_mesh` 获取鼻尖 (1)、左眼内角 (133, 362) 等关键点
- 使用 solvePnP 或简化的几何方法计算头部 yaw/pitch
- EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)，对左右眼分别计算取平均
- 状态机维护 `state_start_time`，同一状态计时，超阈值后生成 `ViolationEvent`

### 3. `audio_engine.py` — 音频 + 违禁词

**流程：**
1. PyAudio 以 16000Hz、mono、int16 采集音频流
2. 每 0.2 秒将缓冲区数据送入 Vosk 识别器
3. Vosk 返回 `PartialResult`（实时）和 `Result`（句子结束）
4. 对每个识别结果，用 AC 自动机扫描匹配违禁词
5. 匹配命中时，提取前后各 10 字的上下文，脱敏后生成 `ViolationEvent`

**AC 自动机构建：**
- 启动时将 `FORBIDDEN_WORDS` 全部插入 `ahocorasick.Automaton`
- 设置为最长匹配模式
- 每次匹配: O(n)，不受词表大小影响

### 4. `violation_recorder.py` — Word 文档记录

**输出格式：**
- 文件命名：`违规记录_2026-07-03_14-30-00.docx`（按启动时间）
- 表格结构：序号 | 时间 | 违规类型 | 具体描述

**写入策略：**
- `python-docx` 操作 Word 文档
- 每次收到事件立即追加一行到表格
- 每写入 5 条自动执行 `document.save()`，防止崩溃丢失数据
- 程序退出时最终保存

### 5. `alert_player.py` — 声音告警

- 使用 `winsound.MessageBeep(winsound.MB_ICONASTERISK)` 播放系统提示音
- 或使用 `winsound.PlaySound('SystemExclamation', winsound.SND_ALIAS)` 播放系统惊叹声
- 防抖机制：同类型告警在冷却时间内（默认 10 秒）不重复播放

### 6. `main.py` — 入口

- 解析命令行参数（可选 `--camera`, `--no-audio` 等）
- 初始化 Event 队列、Recorder、AlertPlayer
- 启动 CameraEngine 线程和 AudioEngine 线程（均为 daemon）
- 主循环消费队列：调 recorder 写入，调 alert_player 发声
- 终端实时打印状态摘要（帧率、当前行为状态、最近违规）
- Ctrl+C 优雅退出：保存 Word 文档，释放摄像头和麦克风

---

## 数据流

```
ViolationEvent (dataclass):
    timestamp: datetime
    violation_type: str          # 'leave_post' | 'return_post' | 'look_around' |
                                 # 'head_down' | 'sleeping' | 'forbidden_word'
    description: str             # 人类可读描述
    context: Optional[str]       # 违禁词上下文（仅 forbidden_word 类型）
```

---

## 错误处理

- 摄像头不可用 → 日志警告，跳过视频检测，程序继续运行
- 麦克风不可用 → 日志警告，跳过音频检测，程序继续运行
- MediaPipe 推理异常 → 捕获单帧异常，丢弃该帧，不中断流
- Vosk 模型未找到 → 启动时明确提示下载链接，优雅退出
- Word 文件被占用 → 重试 3 次后跳过该条记录，日志警告

---

## 性能预算

- MediaPipe Pose: ~5ms/帧 (CPU)
- MediaPipe Face Mesh: ~3ms/帧 (CPU)
- Vosk 推理: ~50ms/次 (CPU)，但异步采集不阻塞
- 总 CPU 占用目标: < 30%（在 i5 级别 CPU 上）
- 内存占用目标: < 500MB

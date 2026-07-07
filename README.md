# 直播间人员工作状态监控系统

基于 AI 视觉 + 语音识别的直播间工作人员状态实时监控系统。支持行为检测（离岗、低头、闭眼、东张西望）和语音违禁词检测，违规事件自动截图并生成审计报告。

## 功能概览

**视觉检测（CameraEngine + MediaPipe）**

| 检测项     | 说明                               |
| ---------- | ---------------------------------- |
| 离开工位   | 摄像头未检测到人体超过阈值（30 帧） |
| 东张西望   | 头部偏转角 (yaw) 超过 30°，持续 2s |
| 低头       | 头部俯仰角 (pitch) 超过 50°，持续 5s |
| 闭眼/睡觉  | 眼睛纵横比 (EAR) 低于 0.2，持续 3s  |

**语音检测（AudioEngine + FunASR SenseVoiceSmall）**

| 检测项     | 说明                                               |
| ---------- | -------------------------------------------------- |
| 违禁词匹配 | Aho-Corasick 多模式匹配，支持 8000+ 词 O(n) 扫描   |
| 实时降噪   | 谱减法 + Wiener 滤波，CPU 实时运行                 |
| ASR 识别   | SenseVoiceSmall 模型，中英文混合识别，自带 VAD     |

**输出产物**

- `违规记录_日期时间.docx` — 违规事件表格，含截图
- `ASR审计_日期时间.docx` — 每次语音识别结果明细
- `debug_日期时间.log` — 全量运行日志

## 系统架构

```
main.py  (事件循环 + 组件编排)
├── CameraEngine           视频行为检测线程
│   ├── MediaPipe Pose     人体姿态估计
│   ├── MediaPipe Face     人脸关键点 + 头部姿态
│   └── 行为状态机         离岗/张望/低头/闭眼 判断
│
├── AudioEngine            音频采集→缓冲→识别 调度线程
│   ├── AudioCapture       sounddevice 麦克风采集
│   ├── RingAudioBuffer    滑动窗口环形缓冲 (4s + 0.5s 重叠)
│   └── AudioProcessor     ASR + 降噪 + 违禁词匹配
│       ├── NoiseReducer   谱减法 + Wiener 滤波降噪
│       ├── FunASR         SenseVoiceSmall 语音识别
│       └── SensitiveWordMatcher  Aho-Corasick 自动机
│
├── ViolationRecorder      违规记录 → Word 文档 (含截图)
├── ASRAuditLogger         ASR 识别审计 → Word 文档
├── AlertPlayer            Windows 系统音告警 (带冷却)
└── OBSAudioHelper         OBS WebSocket 音频路由 (可选)
```

所有模块通过 `config.py` 集中配置，构造参数优先使用显式传入值，未传入则回退到配置文件默认值。

## 环境要求

| 项目         | 要求                              |
| ------------ | --------------------------------- |
| 操作系统     | Windows 10/11                     |
| Python       | 3.10+（推荐 3.11~3.12）           |
| 摄像头       | USB 或内置摄像头                   |
| 麦克风       | 用于语音违禁词检测                 |
| 磁盘空间     | 约 5GB（含 Python 依赖和模型）     |
| 网络         | 首次运行需下载 SenseVoice 模型 (~400MB) |

## 快速开始

### 1. 安装 Python

从 [python.org](https://www.python.org/downloads/) 下载安装 Python 3.10+，安装时勾选 **Add Python to PATH**。

### 2. 配置环境

双击运行 `setup.bat`，脚本会自动创建虚拟环境并安装所有依赖（首次约 5~10 分钟）。

```bash
# 或手动执行
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 启动监控

双击运行 `start.bat`，或：

```bash
.venv\Scripts\activate
python main.py
```

首次运行会自动从 ModelScope 下载 SenseVoiceSmall 模型，请保持网络畅通。

### 4. 停止

按 `Ctrl+C` 或关闭预览窗口，违规记录和审计日志会自动保存。

## 配置说明

编辑 [config.py](D:\study\Monitoring\config.py) 调整以下参数：

**违禁词**
- `FORBIDDEN_WORDS` — 违禁词列表，分类包括业务相关、营销承诺、违规导流、资质违规

**行为检测阈值** (`POSE_THRESHOLDS`)
- `absent_frames` — 离岗判定帧数（默认 30）
- `yaw_threshold` — 张望角度阈值（默认 30°）
- `look_around_seconds` — 张望持续时间（默认 2s）
- `head_down_seconds` — 低头持续时间（默认 5s）
- `sleeping_seconds` — 闭眼持续时间（默认 3s）

**音频处理**
- `AUDIO_CAPTURE_CONFIG` — 采样率、声道、缓冲大小、设备索引
- `AUDIO_BUFFER_CONFIG` — 识别窗口 4s + 重叠 0.5s
- `AUDIO_PROCESSOR_CONFIG` — 最小音频长度 300ms、能量门限 0.002
- `SENSEVOICE_CONFIG` — 模型路径、VAD 参数、推理设备（CPU/GPU）
- `NOISE_REDUCTION_CONFIG` — 降噪开关、降噪量、STFT 参数

**其他**
- `ALERT_COOLDOWN` — 各类型告警冷却时间（秒）
- `CAMERA_CONFIG` — 摄像头索引、分辨率、帧率

## 项目结构

```
D:\study\Monitoring\
├── main.py                 主入口，事件循环 + 组件编排
├── config.py               集中配置文件
├── models.py               共享数据模型 (ViolationEvent)
│
├── camera_engine.py        摄像头行为检测引擎 (MediaPipe)
├── alert_player.py         Windows 系统音告警 (带冷却)
├── violation_recorder.py   违规记录 → Word 文档
├── audit_logger.py         ASR 审计日志 → Word 文档
├── noise_reducer.py        谱减法降噪模块
├── obs_helper.py           OBS WebSocket 音频路由
│
├── audio/                  音频子系统
│   ├── audio_engine.py     调度引擎（线程）
│   ├── capture.py          麦克风采集 (sounddevice)
│   ├── buffer.py           环形缓冲区
│   └── processor.py        ASR + 降噪 + 违禁词匹配
│
├── models/mediapipe/       MediaPipe 模型文件
├── models/vosk-model-*/    Vosk 模型 (已弃用，保留兼容)
│
├── requirements.txt        Python 依赖
├── setup.bat               一键环境配置
├── start.bat               一键启动
├── build.bat               打包分发
│
├── find_mic.py             列出可用麦克风设备
└── test_mic_detailed.py    详细麦克风测试
```

## 音频子系统设计要点

- **采集**：`AudioCapture` 通过 sounddevice 回调采集 PCM 数据，存入线程安全 Queue。队列满时自动丢弃最旧帧。
- **缓冲**：`RingAudioBuffer` 使用预分配连续内存实现滑动窗口，4 秒目标窗口 + 0.5 秒重叠，避免语音截断。
- **处理**：`AudioProcessor` 包含能量门限过滤 → 降噪（可选）→ ASR 识别 → 文本清洗 → 连续文本去重 → Aho-Corasick 违禁词检测。每次识别使用全新 `cache={}` 防止状态污染。
- **调度**：`AudioEngine` 仅负责串联调用，不包含任何处理逻辑。支持懒加载 + 后台预热，避免启动阻塞。
- **降噪**：`NoiseReducer` 基于 scipy 实现谱减法 + Wiener 滤波，纯 CPU 实时运行，不依赖 GPU。

## OBS 集成（可选）

`obs_helper.py` 提供 OBS WebSocket 连接能力，用于将 OBS 处理后的音频（含降噪滤镜）路由到虚拟声卡供系统采集。

```python
from obs_helper import OBSAudioHelper
obs = OBSAudioHelper(host='192.168.80.1', port=4455, password='')
obs.connect()
obs.print_audio_summary()
```

## 打包分发

双击运行 `build.bat`，会在项目上级目录生成 `分发包.zip`。接收方解压后运行 `setup.bat` 即可。

## 常见问题

**依赖安装失败**：部分包（torch 等）较大，网络不稳定时可换国内镜像：
```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

**摄像头无法打开**：检查是否被其他应用占用，或修改 `config.py` 中 `CAMERA_CONFIG['index']`。

**麦克风无声音**：运行 `python find_mic.py` 查看可用设备列表，然后在 `AUDIO_CAPTURE_CONFIG['device_index']` 中指定正确的设备索引。也可运行 `python test_mic_detailed.py` 逐个测试。

**GPU 加速**：将 `SENSEVOICE_CONFIG['device']` 改为 `'cuda:0'` 可利用 GPU 加速 ASR 推理。

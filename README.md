# 直播监控系统

基于 AI 视觉 + 语音识别的直播间工作人员状态实时监控系统。

## 功能

| 检测项 | 说明 |
|--------|------|
| 🚪 离开工位 | 摄像头未检测到人体超过阈值 |
| 👀 东张西望 | 头部偏转角度超过阈值 |
| 📱 低头 | 头部俯仰角超过阈值（瞌睡/玩手机） |
| 😴 睡觉 | 眼睛纵横比低于阈值（长时间闭眼） |
| 🚫 语音违禁词 | 实时语音识别，匹配违禁词库 |

- 违规事件自动截图并生成 Word 文档报告
- 实时预览窗口（含骨架/人脸标注）
- Windows 系统音告警

## 系统要求

- **操作系统**：Windows 10/11
- **Python**：3.10 或更高版本（推荐 3.11~3.12）
- **摄像头**：USB 摄像头或笔记本内置摄像头
- **麦克风**：用于语音违禁词检测
- **网络**：首次运行需下载 SenseVoice 语音模型（约 400MB）
- **磁盘空间**：约 5GB（含 Python 依赖）

## 快速开始

### 1. 安装 Python

如果还没有 Python，从官网下载安装：
https://www.python.org/downloads/

**安装时务必勾选「Add Python to PATH」**

### 2. 一键配置环境

双击运行 `setup.bat`，脚本会自动：
- 创建 Python 虚拟环境
- 安装所有依赖（torch、mediapipe、funasr 等）

首次安装约需 5~10 分钟，请耐心等待。

### 3. 启动监控

双击运行 `启动监控.bat`。

⚠ **首次运行**会从 ModelScope 自动下载 SenseVoice 语音模型（约 400MB），
请保持网络畅通，等待模型下载完成后即可正常使用。

### 4. 停止监控

- 在控制台窗口按 `Ctrl+C`
- 或关闭预览窗口

违规记录会自动保存为 Word 文档（`违规记录_日期时间.docx`）。

## 配置修改

编辑 `config.py` 可调整：

- `FORBIDDEN_WORDS`：违禁词列表
- `POSE_THRESHOLDS`：行为检测阈值（灵敏度）
- `CAMERA_CONFIG`：摄像头参数
- `AUDIO_CONFIG`：麦克风参数
- `ALERT_COOLDOWN`：告警冷却时间
- `SENSEVOICE_CONFIG`：语音模型参数

## 文件说明

```
├── main.py                 # 主程序入口
├── camera_engine.py        # 摄像头行为检测引擎
├── audio_engine.py         # 语音识别引擎
├── violation_recorder.py   # 违规 Word 文档记录
├── alert_player.py         # 声音告警
├── models.py               # 数据模型
├── config.py               # 配置文件
├── models/                 # 模型文件目录
│   └── mediapipe/          # MediaPipe 姿态/人脸模型
├── requirements.txt        # Python 依赖
├── setup.bat              # 一键环境配置（首次运行）
└── 启动监控.bat            # 一键启动
```

## 常见问题

**Q: 提示「未找到 Python」**
A: 请从 python.org 下载安装 Python，安装时勾选「Add Python to PATH」

**Q: 依赖安装失败**
A: 检查网络连接，部分包（如 torch）较大，可能需要使用国内镜像：
执行 `pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` 后再运行 setup.bat

**Q: 摄像头无法打开**
A: 检查摄像头是否被其他程序占用，或修改 config.py 中 CAMERA_CONFIG 的 index 值

**Q: 麦克风没有声音**
A: 检查 Windows 隐私设置中是否允许应用访问麦克风，或修改 AUDIO_CONFIG 的 device_index

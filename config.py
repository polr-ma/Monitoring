"""集中配置文件 - 最终版（向后兼容）"""

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
    'absent_frames': 30,
    'yaw_threshold': 30.0,
    'look_around_seconds': 2.0,
    'pitch_threshold': 50.0,
    'head_down_seconds': 5.0,
    'ear_threshold': 0.2,
    'sleeping_seconds': 3.0,
}

# ── 摄像头配置 ──────────────────────────────────────────
CAMERA_CONFIG = {
    'index': 0,
    'width': 640,
    'height': 480,
    'fps': 30,
    'backend': 'CAP_DSHOW',   # Windows 推荐；Linux 可设为 'V4L2' 或 None
}

# ── 音频采集配置 ────────────────────────────────────────
AUDIO_CAPTURE_CONFIG = {
    'sample_rate': 16000,
    'channels': 1,
    'chunk_size': 1600,        # 每次回调帧数（100ms @ 16kHz）
    'device_index': None,
    'queue_size': 200,
    'dtype': 'int16',
    'read_timeout': 0.2,       # AudioEngine 读取队列的超时（秒）
}

# ── 音频缓冲配置 ────────────────────────────────────────
AUDIO_BUFFER_CONFIG = {
    'target_duration': 4.0,
    'overlap_duration': 0.5,
    'flush_on_stop': True,     # 停止时是否强制刷新剩余数据
}

# ── 音频处理器配置 ───────────────────────────────────────
AUDIO_PROCESSOR_CONFIG = {
    'min_audio_ms': 300,       # 最短识别长度（毫秒）
    'energy_threshold': 0.002, # RMS 能量门限（归一化后）
    'language': 'auto',
    'use_itn': True,           # 逆文本正则化（数字转阿拉伯数字）
}

# ── SenseVoice 语音识别配置 ───────────────────────────────
SENSEVOICE_CONFIG = {
    'model': 'iic/SenseVoiceSmall',
    'vad_model': 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
    'vad_max_segment': 30000,      # 毫秒，对应 vad_kwargs 的 max_single_segment_time
    'device': 'cpu',               # 推理设备，GPU 可设为 'cuda:0'
    'disable_update': True,        # 禁止自动联网检查更新
}

# ── 降噪配置 ──────────────────────────────────────────
NOISE_REDUCTION_CONFIG = {
    'enabled': True,               # 总开关
    'noise_reduce_db': 6,
    'n_fft': 512,
    'hop_length': 256,
    'noise_smooth_frames': 5,
    'learning_rate': 0.02,
    'enable_wiener': True,
    'enable_spectral_sub': True,
}

# ── 告警冷却时间 ──────────────────────────────────────────
ALERT_COOLDOWN = {
    'leave_post': 10.0,
    'return_post': 5.0,
    'look_around': 10.0,
    'head_down': 15.0,
    'sleeping': 10.0,
    'forbidden_word': 5.0,
}

# ── 截图配置 ──────────────────────────────────────────
SCREENSHOT_CONFIG = {
    'dir': 'screenshots',
    'width': 320,
}


# ======================================================================
# 向后兼容层：导出旧版本直接使用的变量，避免立即修改所有模块
# ======================================================================

# 截图（旧代码可能直接 import SCREENSHOT_DIR / SCREENSHOT_WIDTH）
SCREENSHOT_DIR = SCREENSHOT_CONFIG['dir']
SCREENSHOT_WIDTH = SCREENSHOT_CONFIG['width']

# 旧版通用音频配置（AUDIO_CONFIG）：某些模块可能还在使用
AUDIO_CONFIG = {
    'sample_rate': AUDIO_CAPTURE_CONFIG['sample_rate'],
    'chunk_size': AUDIO_CAPTURE_CONFIG['chunk_size'],
    'device_index': AUDIO_CAPTURE_CONFIG['device_index'],
    'gain': 1.2,                      # 保留旧版增益值，尽管新架构不再使用
}

# 旧版 SenseVoice 配置可能被直接引用，我们补充可能缺失的字段
# 注意：chunk_duration 已被废弃，但为了兼容，提供一个默认值
if 'chunk_duration' not in SENSEVOICE_CONFIG:
    SENSEVOICE_CONFIG['chunk_duration'] = 10.0  # 旧代码可能用到的字段

# 如果有其他模块需要旧的结构，可以在这里继续添加
# 例如：旧版降噪配置可能直接使用 NOISE_REDUCTION_CONFIG 字典，无需更改
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
    screenshot_path: Optional[str] = None  # 违规截图路径

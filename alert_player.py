"""声音告警模块 — 使用 Windows 系统音，带防抖机制"""

import time
import winsound
from typing import Dict


class AlertPlayer:
    """声音告警播放器，同一类型告警在冷却时间内不重复播放"""

    def __init__(self, cooldowns: Dict[str, float]):
        self._cooldowns = cooldowns
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
            winsound.PlaySound('SystemExclamation', winsound.SND_ALIAS)
        except Exception:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True

"""
OBS 音频助手 — 通过 OBS WebSocket 获取音频源、配置音频监听路由
用于将 OBS 处理后的音频（含降噪滤镜）路由到虚拟声卡供监控系统采集

OBS WebSocket 协议 v5.x
"""

import json
import logging
import time
from typing import Any, Optional

import websocket

logger = logging.getLogger('audio.obs')

# OBS WebSocket 消息 ID 计数器
_msg_id_counter = 0


class OBSAudioHelper:
    """OBS 音频助手：连接 OBS WebSocket，管理音频源和监听路由"""

    def __init__(self, host: str = '192.168.80.1', port: int = 4455,
                 password: str = ''):
        self._host = host
        self._port = port
        self._password = password
        self._ws: Optional[websocket.WebSocket] = None
        self._connected = False
        self._pending: dict[str, Any] = {}

    # ── 连接管理 ──────────────────────────────────────

    def connect(self) -> bool:
        """连接 OBS WebSocket 并认证"""
        url = f'ws://{self._host}:{self._port}'
        try:
            self._ws = websocket.create_connection(url, timeout=5)
        except Exception as e:
            logger.error(f'OBS WebSocket 连接失败: {e}')
            print(f'[OBS] 连接失败 ({self._host}:{self._port}): {e}')
            return False

        # 等待 OBS 发送 Hello
        hello = self._recv_json(timeout=5)
        if not hello or hello.get('op') != 0:
            logger.error('OBS 握手失败：未收到 Hello')
            self._ws.close()
            return False

        # 发送 Identify（认证）
        self._send_json({
            'op': 1,
            'd': {
                'rpcVersion': 1,
                'authentication': self._password,
                'eventSubscriptions': 0,
            },
        })

        identified = self._recv_json(timeout=5)
        if not identified or identified.get('op') != 2:
            logger.error(f'OBS 认证失败: {identified}')
            print(f'[OBS] 认证失败。请检查密码是否正确。')
            self._ws.close()
            return False

        self._connected = True
        logger.info(f'OBS 已连接 ({self._host}:{self._port})')
        print(f'[OBS] 已连接 ✓ ({self._host}:{self._port})')
        return True

    def disconnect(self):
        if self._ws:
            self._ws.close()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # ── OBS 查询 ──────────────────────────────────────

    def get_audio_inputs(self) -> list[dict]:
        """获取 OBS 中所有音频输入源及其状态"""
        resp = self._call('GetInputList', {'inputKind': ''})
        inputs = resp.get('inputs', [])

        audio_inputs = []
        for inp in inputs:
            input_name = inp.get('inputName', '')
            input_kind = inp.get('inputKind', '')
            unversioned = inp.get('unversionedInputKind', '')

            # 只关心音频源
            kind_lower = (input_kind + unversioned).lower()
            if not any(k in kind_lower for k in
                       ['audio', 'wasapi', 'coreaudio', 'pulse', 'jack',
                        'ndi', 'v4l2', 'decklink']):
                continue

            info = {
                'name': input_name,
                'kind': input_kind,
                'unversioned_kind': unversioned,
            }

            # 获取音量
            try:
                vol = self._call('GetInputVolume', {'inputName': input_name})
                info['volume_mul'] = vol.get('inputVolumeMul', 1.0)
                info['volume_db'] = vol.get('inputVolumeDb', 0.0)
            except Exception:
                info['volume_mul'] = 'N/A'

            # 获取监听状态
            try:
                mon = self._call('GetInputAudioMonitorType',
                                 {'inputName': input_name})
                mon_type = mon.get('monitorType', '')
                info['monitor_type'] = mon_type  # OBS_MONITORING_TYPE_NONE / MONITOR_ONLY / MONITOR_AND_OUTPUT
            except Exception:
                info['monitor_type'] = 'unknown'

            # 获取音频电平
            try:
                levels = self._call('GetInputAudioBalance',
                                    {'inputName': input_name})
                info['balance'] = levels.get('inputAudioBalance', 0.0)
            except Exception:
                pass

            audio_inputs.append(info)

        return audio_inputs

    def get_audio_monitor_device(self) -> Optional[str]:
        """获取 OBS 当前音频监听输出设备"""
        try:
            resp = self._call('GetAudioMonitorType', {})
            return resp.get('monitorType', '')
        except Exception:
            return None

    def set_audio_monitor(self, input_name: str,
                          monitor_type: str = 'OBS_MONITORING_TYPE_MONITOR_ONLY'):
        """设置某个音频源的监听模式

        monitor_type:
          OBS_MONITORING_TYPE_NONE - 不监听
          OBS_MONITORING_TYPE_MONITOR_ONLY - 仅监听（不输出到流）
          OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT - 监听并输出
        """
        return self._call('SetInputAudioMonitorType', {
            'inputName': input_name,
            'monitorType': monitor_type,
        })

    def get_special_inputs(self) -> list[dict]:
        """获取特殊输入（用于发现浏览器源、媒体源等可能携带音频的源）"""
        resp = self._call('GetSpecialInputs', {})
        special = []
        for key in resp:
            if key.startswith('_') or key == 'requestType' or key == 'requestId':
                continue
            val = resp[key]
            if isinstance(val, str) and val:
                special.append({'name': key, 'value': val})
        return special

    def print_audio_summary(self):
        """打印 OBS 音频源摘要"""
        if not self._connected:
            print('[OBS] 未连接')
            return

        print('\n' + '=' * 60)
        print('  OBS 音频源摘要')
        print('=' * 60)

        # 音频输入
        audio_inputs = self.get_audio_inputs()
        if audio_inputs:
            print(f'\n  🎙 音频输入源 ({len(audio_inputs)}):')
            for inp in audio_inputs:
                mon = inp.get('monitor_type', '')
                mon_label = {'OBS_MONITORING_TYPE_NONE': '不监听',
                             'OBS_MONITORING_TYPE_MONITOR_ONLY': '仅监听',
                             'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT': '监听+输出'}.get(mon, mon)
                vol = inp.get('volume_db', 'N/A')
                vol_str = f'{vol}dB' if isinstance(vol, (int, float)) else vol
                print(f'    [{inp["kind"]}] {inp["name"]}')
                print(f'      音量: {vol_str}  监听: {mon_label}')
        else:
            print('\n  (无音频输入源)')

        # 监听设备
        mon_dev = self.get_audio_monitor_device()
        if mon_dev:
            print(f'\n  🔊 监听输出设备: {mon_dev}')

        print('=' * 60)

    # ── 内部协议方法 ──────────────────────────────────

    def _call(self, request_type: str, request_data: dict = None,
              timeout: float = 5.0) -> dict:
        """发送请求并等待响应"""
        global _msg_id_counter
        _msg_id_counter += 1
        msg_id = str(_msg_id_counter)

        payload = {
            'op': 6,
            'd': {
                'requestType': request_type,
                'requestId': msg_id,
                'requestData': request_data or {},
            },
        }

        self._send_json(payload)

        # 等待匹配的响应
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._recv_json(timeout=1.0)
            if not msg:
                continue
            if msg.get('op') == 7 and msg.get('d', {}).get('requestId') == msg_id:
                d = msg.get('d', {})
                status = d.get('requestStatus', {})
                if status.get('code') != 100:
                    raise Exception(f'OBS 错误: {status.get("comment", status)}')
                return d.get('responseData', {})
        raise TimeoutError(f'OBS 请求超时: {request_type}')

    def _send_json(self, data: dict):
        if self._ws:
            self._ws.send(json.dumps(data, ensure_ascii=False))

    def _recv_json(self, timeout: float = 1.0) -> Optional[dict]:
        if not self._ws:
            return None
        old_timeout = self._ws.gettimeout()
        self._ws.settimeout(timeout)
        try:
            raw = self._ws.recv()
            return json.loads(raw)
        except websocket.WebSocketTimeoutException:
            return None
        except Exception:
            return None
        finally:
            self._ws.settimeout(old_timeout)

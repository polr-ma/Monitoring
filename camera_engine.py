"""摄像头引擎 — 采集 + MediaPipe Tasks API + 行为状态机 + 预览窗口"""

import os
import time
import threading
import queue
from datetime import datetime
import logging
import traceback

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from models import ViolationEvent
from config import POSE_THRESHOLDS, CAMERA_CONFIG
from config import SCREENSHOT_DIR, SCREENSHOT_WIDTH

logger = logging.getLogger('camera')

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_POSE_MODEL = os.path.join(_PROJECT_DIR, 'models', 'mediapipe', 'pose_landmarker_lite.task')
_FACE_MODEL = os.path.join(_PROJECT_DIR, 'models', 'mediapipe', 'face_landmarker.task')

# 眼部关键点索引（MediaPipe Face Landmarker 478 点）
RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]


class CameraEngine(threading.Thread):
    """摄像头行为检测线程"""

    def __init__(self, event_queue: queue.Queue, stop_event: threading.Event,
                 show_preview: bool = True):
        super().__init__(daemon=True)
        self._event_queue = event_queue
        self._stop_event = stop_event
        self._show_preview = show_preview

        # 状态机
        self._absent_frames = 0
        self._is_absent = False
        self._look_around_start = None
        self._is_looking_around = False
        self._head_down_start = None
        self._is_head_down = False
        self._eye_closed_start = None
        self._is_sleeping = False

        # FPS
        self._frame_count = 0
        self._fps_start = time.time()
        self.current_fps = 0.0

        # 最新检测值
        self._latest_yaw = 0.0
        self._latest_pitch = 0.0
        self._latest_ear = 1.0
        self._latest_has_person = False
        self._latest_pose_landmarks = None
        self._latest_face_landmarks = None

        # 组件
        self.cap = None
        self._pose_lm = None
        self._face_lm = None
        self._timestamp = 0
        self._current_frame = None  # 当前帧 (BGR numpy array)

    def run(self):
        print('[CameraEngine] 初始化中...')
        self._setup()
        if not self.cap or not self.cap.isOpened():
            print('[CameraEngine] 错误：无法打开摄像头')
            return
        print('[CameraEngine] 就绪，开始实时检测')
        try:
            while not self._stop_event.is_set():
                self._process_frame()
        finally:
            self._cleanup()

    def _setup(self):
        """初始化"""
        # 截图目录
        self._screenshot_dir = os.path.join(_PROJECT_DIR, SCREENSHOT_DIR)
        os.makedirs(self._screenshot_dir, exist_ok=True)
        # Pose Landmarker
        pose_opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_POSE_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._pose_lm = vision.PoseLandmarker.create_from_options(pose_opts)

        # Face Landmarker
        face_opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_FACE_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=False,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._face_lm = vision.FaceLandmarker.create_from_options(face_opts)

        # 摄像头
        idx = CAMERA_CONFIG['index']
        self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(idx)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_CONFIG['width'])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_CONFIG['height'])

    def _process_frame(self):
        if not self.cap.isOpened():
            time.sleep(0.1)
            return

        ret, frame = self.cap.read()
        if not ret:
            time.sleep(0.01)
            return

        self._current_frame = frame.copy()  # 保存供截图使用

        self._timestamp += 1

        # FPS
        self._frame_count += 1
        elapsed = time.time() - self._fps_start
        if elapsed >= 1.0:
            self.current_fps = round(self._frame_count / elapsed, 1)
            self._frame_count = 0
            self._fps_start = time.time()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # 推理
        pose_result = self._pose_lm.detect_for_video(mp_img, self._timestamp)
        face_result = self._face_lm.detect_for_video(mp_img, self._timestamp)

        if pose_result.pose_landmarks is None and self._frame_count % 300 == 0:
            logger.debug('pose_landmarks 为空 (可能未检测到人体)')

        now = time.time()

        # 人体检测
        has_person = bool(pose_result.pose_landmarks)
        self._latest_has_person = has_person
        self._latest_pose_landmarks = pose_result.pose_landmarks
        self._latest_face_landmarks = face_result.face_landmarks

        # 头部姿态
        yaw, pitch, ear = None, None, None
        if face_result.face_landmarks:
            landmarks = face_result.face_landmarks[0]  # list of NormalizedLandmark
            h, w = frame.shape[:2]
            landmarks_2d = np.array([(lm.x * w, lm.y * h) for lm in landmarks])
            landmarks_3d = np.array([(lm.x, lm.y, lm.z) for lm in landmarks])
            yaw, pitch = self._estimate_head_pose(landmarks_2d, landmarks_3d)
            ear = self._calc_ear(landmarks_2d)
            self._latest_yaw = yaw
            self._latest_pitch = pitch
            self._latest_ear = ear

        self._update_state(has_person, yaw, pitch, ear, now)

        # 预览
        if self._show_preview:
            self._draw_preview(frame)


    def _estimate_head_pose(self, landmarks_2d, landmarks_3d):
        """估算 yaw 和 pitch"""
        nose_tip = landmarks_3d[1]
        left_eye = landmarks_3d[33]
        right_eye = landmarks_3d[263]

        eye_center = (left_eye + right_eye) / 2
        nose_to_eye = eye_center - nose_tip

        left_2d = landmarks_2d[33]
        right_2d = landmarks_2d[263]
        nose_2d = landmarks_2d[1]
        mid = (left_2d + right_2d) / 2
        yaw = (nose_2d[0] - mid[0]) / (np.linalg.norm(right_2d - left_2d) + 1e-6) * 60

        pitch = np.arctan2(-nose_to_eye[1],
                           np.linalg.norm([nose_to_eye[0], nose_to_eye[2]]) + 1e-6)
        pitch = np.degrees(pitch)

        return yaw, pitch

    def _calc_ear(self, landmarks_2d):
        """计算眼睛纵横比"""
        def ear(indices):
            pts = [landmarks_2d[i] for i in indices]
            v1 = np.linalg.norm(pts[1] - pts[5])
            v2 = np.linalg.norm(pts[2] - pts[4])
            h = np.linalg.norm(pts[0] - pts[3])
            if h < 1e-6:
                return 1.0
            return (v1 + v2) / (2.0 * h)

        return (ear(RIGHT_EYE_INDICES) + ear(LEFT_EYE_INDICES)) / 2.0

    def _update_state(self, has_person, yaw, pitch, ear, now):
        th = POSE_THRESHOLDS

        if not has_person:
            self._absent_frames += 1
            if not self._is_absent and self._absent_frames >= th['absent_frames']:
                self._is_absent = True
                self._push_event('leave_post', '主播离开工位')
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

            if yaw is not None and abs(yaw) > th['yaw_threshold']:
                if self._look_around_start is None:
                    self._look_around_start = now
                elif not self._is_looking_around and (
                        now - self._look_around_start) >= th['look_around_seconds']:
                    self._is_looking_around = True
                    direction = '左' if yaw > 0 else '右'
                    self._push_event('look_around', f'主播东张西望（偏向{direction}）')
            else:
                self._look_around_start = None
                self._is_looking_around = False

            if pitch is not None and pitch > th['pitch_threshold']:
                if self._head_down_start is None:
                    self._head_down_start = now
                elif not self._is_head_down and (
                        now - self._head_down_start) >= th['head_down_seconds']:
                    self._is_head_down = True
                    self._push_event('head_down', '主播持续低头（可能瞌睡或玩手机）')
            else:
                self._head_down_start = None
                self._is_head_down = False

            if ear is not None and ear < th['ear_threshold']:
                if self._eye_closed_start is None:
                    self._eye_closed_start = now
                elif not self._is_sleeping and (
                        now - self._eye_closed_start) >= th['sleeping_seconds']:
                    self._is_sleeping = True
                    self._push_event('sleeping', '主播疑似睡觉（长时间闭眼）')
            else:
                self._eye_closed_start = None
                self._is_sleeping = False

    def _draw_preview(self, frame):
        """在帧上绘制标注"""
        h, w = frame.shape[:2]

        from mediapipe.tasks.python.vision import drawing_utils

        # 画姿态骨架
        if self._latest_pose_landmarks:
            for landmarks in self._latest_pose_landmarks:
                drawing_utils.draw_landmarks(
                    frame, landmarks,
                    vision.PoseLandmarksConnections.POSE_LANDMARKS,
                )

        # 画人脸网格
        if self._latest_face_landmarks:
            for landmarks in self._latest_face_landmarks:
                drawing_utils.draw_landmarks(
                    frame, landmarks,
                    vision.FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION,
                    landmark_drawing_spec=drawing_utils.DrawingSpec(
                        color=(200, 200, 200), thickness=1, circle_radius=1),
                    connection_drawing_spec=drawing_utils.DrawingSpec(
                        color=(255, 255, 255), thickness=1),
                )
                # 高亮眼部
                for idx in RIGHT_EYE_INDICES + LEFT_EYE_INDICES:
                    if idx < len(landmarks):
                        lm = landmarks[idx]
                        px, py = int(lm.x * w), int(lm.y * h)
                        cv2.circle(frame, (px, py), 3, (0, 255, 255), -1)

        # ── 半透明信息面板 ──
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (300, 200), (0, 0, 0), -1)
        frame[:] = cv2.addWeighted(frame, 0.6, overlay, 0.4, 0)

        y = 28
        def put(text, color=(255, 255, 255)):
            nonlocal y
            cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, color, 1, cv2.LINE_AA)
            y += 26

        put(f'FPS: {self.current_fps}')
        person_color = (0, 255, 0) if self._latest_has_person else (0, 0, 255)
        put(f'人物: {"检测到" if self._latest_has_person else "未检测到"}', person_color)
        put(f'Yaw:{self._latest_yaw:.1f}  Pitch:{self._latest_pitch:.1f}  EAR:{self._latest_ear:.2f}')

        status_items = []
        if self._is_absent:
            status_items.append(('离开工位', (0, 0, 255)))
        if self._is_looking_around:
            status_items.append(('东张西望', (0, 165, 255)))
        if self._is_head_down:
            status_items.append(('低头', (0, 165, 255)))
        if self._is_sleeping:
            status_items.append(('闭眼/睡觉', (0, 0, 255)))
        if not status_items:
            status_items.append(('正常', (0, 255, 0)))

        for text, color in status_items:
            put(f'● {text}', color)

        cv2.imshow('监控预览 - 按Q关闭', frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            self._show_preview = False
            cv2.destroyWindow('监控预览 - 按Q关闭')

    def _push_event(self, vtype, desc):
        event = ViolationEvent(
            timestamp=datetime.now(),
            violation_type=vtype,
            description=desc,
            screenshot_path=self._capture_screenshot(vtype),
        )
        self._event_queue.put(event)

    def _capture_screenshot(self, vtype: str):
        """截取当前帧，保存为 JPEG，返回文件路径"""
        if self._current_frame is None:
            return None
        try:
            import cv2
            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            filename = f'{vtype}_{ts}.jpg'
            filepath = os.path.join(self._screenshot_dir, filename)
            h, w = self._current_frame.shape[:2]
            target_w = SCREENSHOT_WIDTH
            target_h = int(h * target_w / w)
            resized = cv2.resize(self._current_frame, (target_w, target_h))
            cv2.imwrite(filepath, resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return filepath
        except Exception:
            return None

    def _cleanup(self):
        if self.cap:
            self.cap.release()
        if self._pose_lm:
            self._pose_lm.close()
        if self._face_lm:
            self._face_lm.close()
        cv2.destroyAllWindows()

    def get_status(self) -> dict:
        return {
            'fps': self.current_fps,
            'is_absent': self._is_absent,
            'is_looking_around': self._is_looking_around,
            'is_head_down': self._is_head_down,
            'is_sleeping': self._is_sleeping,
            'has_person': self._latest_has_person,
            'yaw': round(self._latest_yaw, 1),
            'pitch': round(self._latest_pitch, 1),
            'ear': round(self._latest_ear, 2),
        }

"""
Camera capture module for IronSight.

Continuously captures webcam video into a circular buffer.
When a swing event is received, extracts a clip around the
impact moment (pre + post seconds) and saves it as an MP4 file.

Threading: Runs on a dedicated QThread. The circular buffer
is accessed only from this thread. Clip extraction is triggered
via a Qt signal from the USB reader thread.
"""

import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

from src.utils.config import Config

logger = logging.getLogger(__name__)


class CameraCapture(QThread):
    """Webcam capture with circular buffer and swing-triggered clip saving.

    Signals:
        frame_ready(ndarray): Emitted for each captured frame (for live preview).
        clip_saved(str): Emitted when a clip is saved, with the file path.
        camera_opened(): Emitted when the camera is successfully opened.
        camera_error(str): Emitted on camera errors.
    """

    frame_ready = pyqtSignal(object)     # np.ndarray
    clip_saved = pyqtSignal(str)         # file path
    camera_opened = pyqtSignal()
    camera_error = pyqtSignal(str)

    def __init__(
        self,
        camera_index: int = 0,
        fps: int = 30,
        resolution: tuple[int, int] = (1280, 720),
        pre_seconds: float = 2.0,
        post_seconds: float = 2.0,
        parent=None,
    ):
        """
        Args:
            camera_index: OpenCV camera device index (0 = default).
            fps: Target frames per second.
            resolution: (width, height) of captured frames.
            pre_seconds: Seconds of video to keep before impact.
            post_seconds: Seconds of video to record after impact.
        """
        super().__init__(parent)
        self._camera_index = camera_index
        self._fps = fps
        self._resolution = resolution
        self._pre_seconds = pre_seconds
        self._post_seconds = post_seconds
        self._running = False

        # Circular buffer: stores (frame, timestamp) tuples
        buffer_size = int((pre_seconds + 1) * fps)  # Extra second of margin
        self._buffer: deque[tuple[np.ndarray, float]] = deque(maxlen=buffer_size)
        self._buffer_mutex = QMutex()

        # Clip extraction state
        self._extract_requested = False
        self._extract_time: float = 0.0
        self._post_frames_remaining: int = 0
        self._clip_frames: list[tuple[np.ndarray, float]] = []
        self._clip_session_dir: Optional[Path] = None

        # Session clip directory
        self._setup_session_dir()

        # Clip counter
        self._clip_count = 0

    def _setup_session_dir(self):
        """Create a session-specific directory for clips."""
        clips_dir = Config.get_clips_dir()
        session_name = datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self._clip_session_dir = clips_dir / session_name
        self._clip_session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Clip directory: {self._clip_session_dir}")

    def extract_clip(self):
        """Request clip extraction around the current moment.

        Called from the USB reader thread via signal connection.
        Sets a flag that the capture loop will process.
        """
        self._extract_time = time.time()
        self._extract_requested = True
        self._post_frames_remaining = int(self._post_seconds * self._fps)
        logger.info("Clip extraction requested")

    def run(self):
        """Main capture loop: read frames, manage buffer, extract clips."""
        self._running = True
        logger.info(
            f"Camera capture starting "
            f"(index={self._camera_index}, "
            f"fps={self._fps}, "
            f"res={self._resolution})"
        )

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            msg = f"Cannot open camera {self._camera_index}"
            logger.error(msg)
            self.camera_error.emit(msg)
            return

        # Configure camera
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        cap.set(cv2.CAP_PROP_FPS, self._fps)

        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(
            f"Camera opened: {actual_w}x{actual_h} @ {actual_fps}fps"
        )
        self.camera_opened.emit()

        frame_interval = 1.0 / self._fps
        last_frame_time = 0.0

        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            now = time.time()

            # Rate limiting (if camera is faster than target fps)
            if now - last_frame_time < frame_interval * 0.8:
                continue
            last_frame_time = now

            # Add frame to circular buffer
            with QMutexLocker(self._buffer_mutex):
                self._buffer.append((frame.copy(), now))

            # Emit frame for live preview (every other frame to reduce load)
            if len(self._buffer) % 2 == 0:
                self.frame_ready.emit(frame)

            # Handle clip extraction
            if self._extract_requested:
                if self._post_frames_remaining > 0:
                    self._clip_frames.append((frame.copy(), now))
                    self._post_frames_remaining -= 1
                else:
                    # Post-impact recording complete — save the clip
                    self._save_clip()
                    self._extract_requested = False

        cap.release()
        logger.info("Camera capture stopped")

    def _save_clip(self):
        """Save the extracted clip as an MP4 file.

        Combines pre-impact frames from the circular buffer with
        post-impact frames recorded after the extraction request.
        """
        # Get pre-impact frames from the buffer
        pre_frame_count = int(self._pre_seconds * self._fps)
        with QMutexLocker(self._buffer_mutex):
            buffer_frames = list(self._buffer)

        # Find frames before the extraction time
        pre_frames = [
            (f, t) for f, t in buffer_frames
            if t <= self._extract_time
        ]
        # Take only the last N frames
        pre_frames = pre_frames[-pre_frame_count:]

        # Combine pre + post frames
        all_frames = pre_frames + self._clip_frames
        self._clip_frames = []

        if not all_frames:
            logger.warning("No frames available for clip extraction")
            return

        # Generate filename
        self._clip_count += 1
        filename = f"shot_{self._clip_count:03d}.mp4"
        filepath = self._clip_session_dir / filename

        # Write MP4
        height, width = all_frames[0][0].shape[:2]
        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            str(filepath), fourcc, self._fps, (width, height)
        )

        if not writer.isOpened():
            logger.error(f"Cannot create video writer for {filepath}")
            return

        for frame, _ in all_frames:
            writer.write(frame)

        writer.release()

        duration = len(all_frames) / self._fps
        logger.info(
            f"Clip saved: {filepath} "
            f"({len(all_frames)} frames, {duration:.1f}s)"
        )
        self.clip_saved.emit(str(filepath))

    def stop(self):
        """Signal the thread to stop."""
        self._running = False

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the most recent frame from the buffer (thread-safe)."""
        with QMutexLocker(self._buffer_mutex):
            if self._buffer:
                return self._buffer[-1][0].copy()
        return None

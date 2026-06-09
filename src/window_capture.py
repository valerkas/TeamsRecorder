from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np
import win32gui
import win32ui
from ctypes import windll

logger = logging.getLogger(__name__)


@dataclass
class WindowGeometry:
    width: int
    height: int


class WindowCapture:
    def __init__(self, hwnd: int, fps: int) -> None:
        self.hwnd = hwnd
        self.fps = max(1, fps)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_callback = None
        self._geometry = WindowGeometry(width=0, height=0)

    @property
    def geometry(self) -> WindowGeometry:
        return self._geometry

    def start(self, frame_callback) -> WindowGeometry:
        self._frame_callback = frame_callback
        self._stop_event.clear()
        self._geometry = self._read_geometry()
        if self._geometry.width <= 0 or self._geometry.height <= 0:
            raise RuntimeError("Unable to read Teams window size.")

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self._geometry

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _read_geometry(self) -> WindowGeometry:
        try:
            left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
            return WindowGeometry(width=right - left, height=bottom - top)
        except Exception as exc:
            logger.warning("Failed to read client rect for hwnd=%s: %s", self.hwnd, exc)
            return WindowGeometry(width=0, height=0)

    def _capture_frame(self) -> np.ndarray | None:
        geometry = self._read_geometry()
        width = geometry.width
        height = geometry.height
        if width <= 0 or height <= 0:
            width = self._geometry.width
            height = self._geometry.height
        if width <= 0 or height <= 0:
            return None

        self._geometry = WindowGeometry(width=width, height=height)

        hwnd_dc = win32gui.GetWindowDC(self.hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        result = windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 2)
        if result != 1:
            windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 0)

        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)

        frame = np.frombuffer(bmp_bits, dtype=np.uint8)
        frame = frame.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
        frame = frame[:, :, :3]

        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, hwnd_dc)

        return np.ascontiguousarray(frame)

    def _capture_loop(self) -> None:
        frame_interval = 1.0 / self.fps
        next_frame_at = time.perf_counter()

        while not self._stop_event.is_set():
            now = time.perf_counter()
            if now < next_frame_at:
                time.sleep(min(0.01, next_frame_at - now))
                continue

            frame = self._capture_frame()
            if frame is not None and self._frame_callback is not None:
                try:
                    self._frame_callback(frame)
                except Exception as exc:
                    logger.error("Video frame callback failed: %s", exc)
                    break

            next_frame_at += frame_interval
            if next_frame_at < time.perf_counter():
                next_frame_at = time.perf_counter()

from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from pathlib import Path

from src.audio_capture import SystemAudioCapture
from src.utils import find_ffmpeg, run_ffmpeg
from src.window_capture import WindowCapture, WindowGeometry

logger = logging.getLogger(__name__)


class MeetingRecorder:
    def __init__(
        self,
        hwnd: int,
        output_path: Path,
        fps: int,
        crf: int,
    ) -> None:
        self.hwnd = hwnd
        self.output_path = output_path
        self.fps = fps
        self.crf = crf

        self._session_id = uuid.uuid4().hex
        self._temp_dir = output_path.parent / ".tmp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._temp_video_path = self._temp_dir / f"{self._session_id}_video.mp4"
        self._temp_audio_path = self._temp_dir / f"{self._session_id}_audio.wav"

        self._ffmpeg_process: subprocess.Popen[bytes] | None = None
        self._ffmpeg_lock = threading.Lock()
        self._video_capture: WindowCapture | None = None
        self._audio_capture: SystemAudioCapture | None = None
        self._geometry = WindowGeometry(width=0, height=0)
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return

        self._video_capture = WindowCapture(self.hwnd, self.fps)
        self._geometry = self._video_capture.start(self._write_video_frame)
        self._start_video_encoder()

        self._audio_capture = SystemAudioCapture(self._temp_audio_path)
        self._audio_capture.start()

        self._started = True
        logger.info(
            "Recording started: output=%s size=%sx%s fps=%s",
            self.output_path,
            self._geometry.width,
            self._geometry.height,
            self.fps,
        )

    def stop(self) -> Path:
        if not self._started:
            return self.output_path

        self._started = False

        if self._video_capture is not None:
            self._video_capture.stop()
            self._video_capture = None

        self._stop_video_encoder()

        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None

        self._mux_final_output()
        self._cleanup_temp_files()
        logger.info("Recording saved: %s", self.output_path)
        return self.output_path

    def _start_video_encoder(self) -> None:
        ffmpeg = find_ffmpeg()
        command = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self._geometry.width}x{self._geometry.height}",
            "-r",
            str(self.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(self.crf),
            str(self._temp_video_path),
        ]

        self._ffmpeg_process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def _write_video_frame(self, frame) -> None:
        process = self._ffmpeg_process
        if process is None or process.stdin is None:
            return

        target_h = self._geometry.height
        target_w = self._geometry.width
        if frame.shape[0] != target_h or frame.shape[1] != target_w:
            frame = frame[:target_h, :target_w, :]

        with self._ffmpeg_lock:
            if process.poll() is not None:
                raise RuntimeError("FFmpeg video encoder stopped unexpectedly.")
            process.stdin.write(frame.tobytes())

    def _stop_video_encoder(self) -> None:
        process = self._ffmpeg_process
        if process is None:
            return

        with self._ffmpeg_lock:
            if process.stdin is not None:
                process.stdin.close()
            stderr = process.stderr.read().decode("utf-8", errors="ignore") if process.stderr else ""
            return_code = process.wait(timeout=30)

        self._ffmpeg_process = None
        if return_code != 0:
            raise RuntimeError(f"FFmpeg video encoding failed ({return_code}): {stderr.strip()}")

    def _mux_final_output(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._temp_video_path.exists():
            raise RuntimeError("Temporary video file was not created.")

        has_audio = self._temp_audio_path.exists() and self._temp_audio_path.stat().st_size > 44

        if has_audio:
            run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(self._temp_video_path),
                    "-i",
                    str(self._temp_audio_path),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(self.output_path),
                ],
                logger,
            )
        else:
            logger.warning("Audio file missing or empty; saving video-only recording.")
            run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(self._temp_video_path),
                    "-c:v",
                    "copy",
                    str(self.output_path),
                ],
                logger,
            )

    def _cleanup_temp_files(self) -> None:
        for path in (self._temp_video_path, self._temp_audio_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete temp file %s: %s", path, exc)

        try:
            if self._temp_dir.exists() and not any(self._temp_dir.iterdir()):
                self._temp_dir.rmdir()
        except OSError:
            pass

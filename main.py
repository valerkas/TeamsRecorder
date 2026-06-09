from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import uiautomation as auto

from src.config import AppConfig, load_config
from src.detector import MeetingWindow, find_active_meeting_window
from src.recorder import MeetingRecorder
from src.state import AppState, MeetingSession, RecorderState
from src.tray import TrayApp
from src.utils import build_output_path, setup_logging

logger = logging.getLogger(__name__)


class MeetingMonitor:
    def __init__(self, config: AppConfig, app_state: AppState) -> None:
        self.config = config
        self.app_state = app_state
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._recorder: MeetingRecorder | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._recorder is not None:
                try:
                    output = self._recorder.stop()
                    self.app_state.last_output_path = str(output)
                except Exception as exc:
                    logger.exception("Failed to stop recorder during shutdown.")
                    self.app_state.set_error(str(exc))
                finally:
                    self._recorder = None
                    self.app_state.mode = RecorderState.IDLE
                    self.app_state.session = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _run_loop(self) -> None:
        with auto.UIAutomationInitializerInThread():
            startup_polls = 3
            for attempt in range(startup_polls):
                if self._stop_event.is_set():
                    return
                try:
                    self._poll_once()
                    if self.app_state.mode == RecorderState.RECORDING:
                        logger.info(
                            "Detected active meeting on startup (attempt %s).",
                            attempt + 1,
                        )
                        break
                except Exception as exc:
                    logger.exception("Polling loop error.")
                    self.app_state.set_error(str(exc))
                if attempt + 1 < startup_polls:
                    time.sleep(0.5)

            while not self._stop_event.is_set():
                try:
                    self._poll_once()
                except Exception as exc:
                    logger.exception("Polling loop error.")
                    self.app_state.set_error(str(exc))
                time.sleep(self.config.poll_interval_sec)

    def _poll_once(self) -> None:
        meeting = find_active_meeting_window()

        with self._lock:
            if self.app_state.paused and self.app_state.mode == RecorderState.IDLE:
                self.app_state.set_status("Пауза")
                return

            if self.app_state.mode == RecorderState.IDLE:
                if self.app_state.paused:
                    self.app_state.set_status("Пауза")
                    return
                if meeting is not None:
                    self._start_recording(meeting)
                else:
                    self.app_state.set_status("Ожидание")
                return

            if self.app_state.mode == RecorderState.RECORDING:
                session = self.app_state.session
                if meeting is None:
                    session.missing_checks += 1
                    if session.missing_checks >= self.config.stop_debounce_checks:
                        self._stop_recording()
                    else:
                        self.app_state.set_status(
                            f"Запись: {session.title} (завершение...)"
                        )
                    return

                session.missing_checks = 0
                if meeting.hwnd != session.hwnd:
                    logger.info("Meeting window changed; starting a new recording.")
                    self._stop_recording(start_new=meeting)
                    return

                self.app_state.set_status(f"Запись: {session.title}")

    def _start_recording(self, meeting: MeetingWindow) -> None:
        output_path = build_output_path(self.config.output_dir, meeting.title)
        recorder = MeetingRecorder(
            hwnd=meeting.hwnd,
            output_path=output_path,
            fps=self.config.video_fps,
            crf=self.config.video_crf,
        )

        try:
            recorder.start()
        except Exception as exc:
            logger.exception("Failed to start recording.")
            self.app_state.set_error(str(exc))
            return

        self._recorder = recorder
        self.app_state.mode = RecorderState.RECORDING
        self.app_state.session = MeetingSession(
            hwnd=meeting.hwnd,
            title=meeting.title,
            output_path=str(output_path),
            missing_checks=0,
        )
        self.app_state.set_status(f"Запись: {meeting.title}")
        logger.info("Auto-recording started for meeting: %s", meeting.title)

    def _stop_recording(self, start_new: MeetingWindow | None = None) -> None:
        self.app_state.mode = RecorderState.STOPPING
        recorder = self._recorder
        self._recorder = None
        session = self.app_state.session
        self.app_state.session = None

        if recorder is not None:
            try:
                output = recorder.stop()
                self.app_state.last_output_path = str(output)
                logger.info("Auto-recording stopped: %s", output)
            except Exception as exc:
                logger.exception("Failed to stop recording.")
                self.app_state.set_error(str(exc))

        self.app_state.mode = RecorderState.IDLE
        self.app_state.set_status("Ожидание")

        if start_new is not None:
            self._start_recording(start_new)


def open_path(path: Path) -> None:
    if path.is_file():
        os.startfile(str(path))  # noqa: S606
        return
    os.startfile(str(path))  # noqa: S606


def open_recordings_folder(config: AppConfig) -> None:
    open_path(config.output_dir)


def open_last_recording(app_state: AppState) -> None:
    if not app_state.last_output_path:
        return
    open_path(Path(app_state.last_output_path))


def main() -> None:
    setup_logging()
    config = load_config()
    app_state = AppState()
    monitor = MeetingMonitor(config, app_state)

    tray = TrayApp(
        app_state=app_state,
        on_toggle_pause=lambda paused: setattr(app_state, "paused", paused),
        on_open_folder=lambda: open_recordings_folder(config),
        on_open_last=lambda: open_last_recording(app_state),
        on_exit=lambda: None,
    )

    def shutdown() -> None:
        monitor.stop()
        tray.stop()

    tray.on_exit = shutdown
    monitor.start()

    logger.info("Teams Meeting Recorder started.")
    logger.info("Recordings folder: %s", config.output_dir)

    try:
        tray.run()
    finally:
        shutdown()


if __name__ == "__main__":
    main()

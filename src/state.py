from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class RecorderState(Enum):
    IDLE = auto()
    RECORDING = auto()
    STOPPING = auto()


@dataclass
class MeetingSession:
    hwnd: int
    title: str
    output_path: str = ""
    missing_checks: int = 0


@dataclass
class AppState:
    mode: RecorderState = RecorderState.IDLE
    session: MeetingSession | None = None
    paused: bool = False
    status_message: str = "Ожидание"
    last_output_path: str = ""
    error_message: str = ""

    def set_status(self, message: str) -> None:
        self.status_message = message
        self.error_message = ""

    def set_error(self, message: str) -> None:
        self.error_message = message
        self.status_message = f"Ошибка: {message}"

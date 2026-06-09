from __future__ import annotations

import ctypes
import logging
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import uiautomation as auto
import win32gui
import win32process

logger = logging.getLogger(__name__)

TEAMS_PROCESS_NAMES = {"ms-teams.exe", "teams.exe"}
TEAMS_WINDOW_MARKERS = (
    "Microsoft Teams",
    "Teams",
)

MEETING_CONTROL_IDS = (
    "microphone-button",
    "camera-button",
    "share-button",
    "share-tray-button",
    "hangup-button",
    "leave-button",
)

MEETING_LEAVE_LABELS = (
    "Leave",
    "Hang up",
    "End call",
    "Покинуть",
    "Завершить",
)

RESUME_LABELS = (
    "Resume",
    "Возобновить",
)

EXCLUDED_TITLE_PATTERNS = (
    re.compile(r"screen sharing toolbar", re.IGNORECASE),
    re.compile(r"^Microsoft Teams Call", re.IGNORECASE),
)

SEARCH_DEPTH = 25


@dataclass(frozen=True)
class MeetingWindow:
    hwnd: int
    title: str


def _normalize_title(title: str) -> str:
    suffixes = (
        " | Microsoft Teams",
        " - Microsoft Teams",
        " | Microsoft​ Teams",
    )
    normalized = title.strip()
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
            break
    return normalized or "Meeting"


def _get_process_name(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name.lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _is_teams_process(process_name: str) -> bool:
    return process_name.lower() in TEAMS_PROCESS_NAMES


def _is_teams_window(window: auto.WindowControl, process_name: str = "") -> bool:
    name = window.Name or ""
    class_name = window.ClassName or ""
    if any(marker in name for marker in TEAMS_WINDOW_MARKERS):
        return True
    if "Teams" in class_name:
        return True

    if not process_name:
        try:
            process_name = (window.ProcessName or "").lower()
        except Exception:
            process_name = ""

    return _is_teams_process(process_name)


def _has_meeting_controls(window: auto.WindowControl) -> bool:
    for automation_id in MEETING_CONTROL_IDS:
        control = window.Control(AutomationId=automation_id, searchDepth=SEARCH_DEPTH)
        if control.Exists(0, 0):
            return True

    for label in MEETING_LEAVE_LABELS:
        leave_button = window.ButtonControl(Name=label, searchDepth=SEARCH_DEPTH)
        if leave_button.Exists(0, 0):
            return True

    return False


def _is_on_hold(window: auto.WindowControl) -> bool:
    for label in RESUME_LABELS:
        resume_button = window.ButtonControl(Name=label, searchDepth=SEARCH_DEPTH)
        if resume_button.Exists(0, 0):
            return True
    return False


def _is_main_teams_shell(window: auto.WindowControl) -> bool:
    app_bar = window.Control(AutomationId="teams-app-bar", searchDepth=12)
    if not app_bar.Exists(0, 0):
        return False
    return not _has_meeting_controls(window)


def _window_from_hwnd(hwnd: int) -> auto.WindowControl | None:
    if hwnd <= 0 or not win32gui.IsWindow(hwnd):
        return None
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception:
        return None
    if window is None or not window.Exists(0, 0):
        return None
    if window.ControlType != auto.ControlType.WindowControl:
        return None
    return window


def _iter_candidate_windows() -> list[auto.WindowControl]:
    seen_hwnds: set[int] = set()
    windows: list[auto.WindowControl] = []

    def add_window(window: auto.WindowControl | None) -> None:
        if window is None or not window.Exists(0, 0):
            return
        hwnd = int(window.NativeWindowHandle or 0)
        if hwnd <= 0 or hwnd in seen_hwnds:
            return
        seen_hwnds.add(hwnd)
        windows.append(window)

    for control in auto.GetRootControl().GetChildren():
        if control.ControlType != auto.ControlType.WindowControl:
            continue
        if isinstance(control, auto.WindowControl):
            add_window(control)
        else:
            add_window(auto.WindowControl(searchFromControl=control, searchDepth=0))

    def enum_callback(hwnd: int, _param: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        process_name = _get_process_name(hwnd)
        if not _is_teams_process(process_name):
            return True
        add_window(_window_from_hwnd(hwnd))
        return True

    win32gui.EnumWindows(enum_callback, None)
    return windows


def _evaluate_window(window: auto.WindowControl) -> MeetingWindow | None:
    process_name = ""
    try:
        process_name = (window.ProcessName or "").lower()
    except Exception:
        process_name = _get_process_name(int(window.NativeWindowHandle or 0))

    if not _is_teams_window(window, process_name):
        return None
    if not _has_meeting_controls(window):
        return None
    if _is_on_hold(window):
        return None

    title = window.Name or ""
    for pattern in EXCLUDED_TITLE_PATTERNS:
        if title and pattern.search(title):
            return None
    if _is_main_teams_shell(window):
        return None

    hwnd = int(window.NativeWindowHandle or 0)
    if hwnd <= 0:
        return None

    return MeetingWindow(hwnd=hwnd, title=_normalize_title(title))


def find_active_meeting_window() -> MeetingWindow | None:
    candidates: list[MeetingWindow] = []

    for window in _iter_candidate_windows():
        meeting = _evaluate_window(window)
        if meeting is not None:
            candidates.append(meeting)

    if not candidates:
        return None

    if len(candidates) > 1:
        logger.debug("Multiple meeting windows found, using the first match.")

    return candidates[0]

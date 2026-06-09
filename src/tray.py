from __future__ import annotations

import logging
import threading
from typing import Callable

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from src.state import AppState, RecorderState

logger = logging.getLogger(__name__)


class TrayApp:
    def __init__(
        self,
        app_state: AppState,
        on_toggle_pause: Callable[[bool], None],
        on_open_folder: Callable[[], None],
        on_open_last: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.app_state = app_state
        self.on_toggle_pause = on_toggle_pause
        self.on_open_folder = on_open_folder
        self.on_open_last = on_open_last
        self.on_exit = on_exit

        self._icon: Icon | None = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        image = self._create_icon_image(recording=False)
        menu = Menu(
            MenuItem(lambda _: self._status_text(), None, enabled=False),
            MenuItem(
                lambda item: self._pause_label(),
                self._toggle_pause,
            ),
            MenuItem("Открыть папку записей", self._handle_open_folder),
            MenuItem("Открыть последнюю запись", self._handle_open_last),
            MenuItem("Выход", self._handle_exit),
        )

        self._icon = Icon(
            "teams_meeting_recorder",
            image,
            "Teams Meeting Recorder",
            menu,
        )

        updater = threading.Thread(target=self._refresh_loop, daemon=True)
        updater.start()
        self._icon.run()

    def stop(self) -> None:
        self._stop_event.set()
        if self._icon is not None:
            self._icon.stop()

    def _refresh_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._icon is not None:
                recording = self.app_state.mode == RecorderState.RECORDING
                self._icon.icon = self._create_icon_image(recording=recording)
                self._icon.title = self._status_text()
            self._stop_event.wait(1)

    def _status_text(self) -> str:
        if self.app_state.error_message:
            return self.app_state.status_message
        return self.app_state.status_message

    def _pause_label(self) -> str:
        return "Возобновить авто-запись" if self.app_state.paused else "Пауза авто-записи"

    def _toggle_pause(self, _icon: Icon, _item: MenuItem) -> None:
        new_value = not self.app_state.paused
        self.on_toggle_pause(new_value)
        if new_value:
            self.app_state.set_status("Пауза")
        elif self.app_state.mode == RecorderState.IDLE:
            self.app_state.set_status("Ожидание")

    def _handle_open_folder(self, _icon: Icon, _item: MenuItem) -> None:
        try:
            self.on_open_folder()
        except Exception as exc:
            logger.error("Failed to open recordings folder: %s", exc)
            self.app_state.set_error(str(exc))

    def _handle_open_last(self, _icon: Icon, _item: MenuItem) -> None:
        if not self.app_state.last_output_path:
            self.app_state.set_status("Последняя запись не найдена")
            return
        try:
            self.on_open_last()
        except Exception as exc:
            logger.error("Failed to open last recording: %s", exc)
            self.app_state.set_error(str(exc))

    def _handle_exit(self, _icon: Icon, _item: MenuItem) -> None:
        self.on_exit()
        if self._icon is not None:
            self._icon.stop()

    def _create_icon_image(self, recording: bool) -> Image.Image:
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        color = (220, 53, 69, 255) if recording else (52, 58, 64, 255)
        draw.ellipse((8, 8, size - 8, size - 8), fill=color)
        if recording:
            draw.rectangle((24, 24, 40, 40), fill=(255, 255, 255, 255))
        else:
            draw.polygon([(28, 20), (28, 44), (46, 32)], fill=(255, 255, 255, 255))
        return image

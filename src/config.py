from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class AppConfig:
    output_dir: Path
    poll_interval_sec: float
    stop_debounce_checks: int
    video_fps: int
    video_crf: int
    include_microphone: bool
    autostart_with_windows: bool


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def load_config(config_path: Path | None = None) -> AppConfig:
    base_dir = Path(__file__).resolve().parent.parent
    path = config_path or (base_dir / "config.yaml")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    output_dir = _resolve_path(base_dir, raw.get("output_dir", "./recordings"))
    output_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        output_dir=output_dir,
        poll_interval_sec=float(raw.get("poll_interval_sec", 2)),
        stop_debounce_checks=int(raw.get("stop_debounce_checks", 3)),
        video_fps=int(raw.get("video_fps", 20)),
        video_crf=int(raw.get("video_crf", 23)),
        include_microphone=bool(raw.get("include_microphone", False)),
        autostart_with_windows=bool(raw.get("autostart_with_windows", False)),
    )

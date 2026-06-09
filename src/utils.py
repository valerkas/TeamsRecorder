from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("teams-recorder")


def sanitize_filename(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "meeting"
    return cleaned[:max_length]


def build_output_path(output_dir: Path, meeting_title: str) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    safe_title = sanitize_filename(meeting_title)
    return output_dir / f"{timestamp}_{safe_title}.mp4"


def find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg and add it to PATH, "
            "or install imageio-ffmpeg via pip."
        ) from exc


def run_ffmpeg(args: list[str], logger: logging.Logger) -> None:
    ffmpeg = find_ffmpeg()
    command = [ffmpeg, *args]
    logger.debug("Running FFmpeg: %s", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"FFmpeg failed ({result.returncode}): {stderr}")

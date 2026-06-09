from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path

import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAMES_PER_BUFFER = 1024


class SystemAudioCapture:
    def __init__(self, output_wav_path: Path) -> None:
        self.output_wav_path = output_wav_path
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._wave_file: wave.Wave_write | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _find_loopback_device(self, audio: pyaudio.PyAudio) -> dict:
        try:
            wasapi_info = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:
            raise RuntimeError("WASAPI is not available on this system.") from exc

        default_output = audio.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        if default_output.get("isLoopbackDevice"):
            return default_output

        if hasattr(audio, "get_loopback_device_info_generator"):
            for loopback in audio.get_loopback_device_info_generator():
                if default_output["name"] in loopback["name"]:
                    return loopback

        for index in range(audio.get_device_count()):
            device = audio.get_device_info_by_index(index)
            if device.get("isLoopbackDevice"):
                return device

        raise RuntimeError("No WASAPI loopback device found.")

    def _capture_loop(self) -> None:
        audio = pyaudio.PyAudio()
        stream = None

        try:
            loopback = self._find_loopback_device(audio)
            channels = min(int(loopback["maxInputChannels"]), CHANNELS)
            if channels <= 0:
                channels = CHANNELS

            rate = int(loopback["defaultSampleRate"] or SAMPLE_RATE)

            stream = audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                frames_per_buffer=FRAMES_PER_BUFFER,
                input=True,
                input_device_index=loopback["index"],
            )

            self.output_wav_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(self.output_wav_path), "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(rate)
                self._wave_file = wav_file

                logger.info(
                    "System audio capture started: device=%s rate=%s channels=%s",
                    loopback.get("name"),
                    rate,
                    channels,
                )

                while not self._stop_event.is_set():
                    data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
                    wav_file.writeframes(data)
        except Exception as exc:
            logger.error("System audio capture failed: %s", exc)
            raise
        finally:
            self._wave_file = None
            if stream is not None:
                stream.stop_stream()
                stream.close()
            audio.terminate()

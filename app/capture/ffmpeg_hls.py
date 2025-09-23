"""FFmpeg helpers for screen capture to HLS."""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


LOGGER = logging.getLogger(__name__)


def _parse_bitrate(value: str) -> tuple[int, str]:
    digits = ""
    suffix = ""
    for ch in value:
        if ch.isdigit():
            digits += ch
        else:
            suffix += ch
    if not digits:
        raise ValueError(f"Invalid bitrate '{value}'")
    return int(digits), suffix or "k"


@dataclass(slots=True)
class HlsProfile:
    width: int = 1920
    height: int = 1080
    fps: int = 15
    video_bitrate: str = "3500k"
    audio: bool = False
    audio_device: str = "default"
    audio_bitrate: str = "128k"
    segment_seconds: int = 2
    list_size: int = 6
    stale_after_ms: int = 8000

    def variant_name(self) -> str:
        return f"variant_{self.height}p.m3u8"

    def bufsize(self) -> str:
        rate, suffix = _parse_bitrate(self.video_bitrate)
        return f"{rate * 2}{suffix}"

    def gop(self) -> int:
        return self.fps * 2


class FfmpegHls:
    def __init__(
        self,
        display: str,
        out_dir: Path,
        profile: HlsProfile,
        *,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.display = display
        self.out_dir = out_dir
        self.profile = profile
        self._popen = popen
        self._proc: subprocess.Popen | None = None

    @property
    def master_playlist(self) -> Path:
        return self.out_dir / "index.m3u8"

    @property
    def variant_playlist(self) -> Path:
        return self.out_dir / self.profile.variant_name()

    def build_command(self) -> list[str]:
        cmd: list[str] = [
            "ffmpeg",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-f",
            "x11grab",
            "-framerate",
            str(self.profile.fps),
            "-video_size",
            f"{self.profile.width}x{self.profile.height}",
            "-i",
            self.display,
        ]

        if self.profile.audio:
            cmd.extend(
                [
                    "-f",
                    "pulse",
                    "-i",
                    self.profile.audio_device,
                ]
            )

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-b:v",
                self.profile.video_bitrate,
                "-maxrate",
                self.profile.video_bitrate,
                "-bufsize",
                self.profile.bufsize(),
                "-g",
                str(self.profile.gop()),
                "-keyint_min",
                str(self.profile.gop()),
                "-sc_threshold",
                "0",
            ]
        )

        if self.profile.audio:
            cmd.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    self.profile.audio_bitrate,
                    "-ac",
                    "2",
                ]
            )

        cmd.extend(
            [
                "-hls_time",
                str(self.profile.segment_seconds),
                "-hls_list_size",
                str(self.profile.list_size),
                "-hls_flags",
                "delete_segments+independent_segments",
                "-master_pl_name",
                self.master_playlist.name,
                "-f",
                "hls",
                str(self.variant_playlist),
            ]
        )
        return cmd

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError("FFmpeg already running")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.build_command()
        LOGGER.info("Starting ffmpeg for display %s -> %s", self.display, self.variant_playlist)
        self._proc = self._popen(cmd)

    def stop(self) -> None:
        if not self._proc:
            return

        proc, self._proc = self._proc, None
        if proc.poll() is None:
            LOGGER.info("Stopping ffmpeg pid=%s", proc.pid)
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:  # pragma: no cover
                LOGGER.warning("ffmpeg pid=%s did not exit cleanly; killing", proc.pid)
                proc.kill()

    @property
    def is_running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def freshness_ms(self) -> Optional[int]:
        newest_ms: Optional[int] = None
        for path in self.out_dir.glob("*.ts"):
            ts = int(path.stat().st_mtime * 1000)
            if newest_ms is None or ts > newest_ms:
                newest_ms = ts
        if newest_ms is None:
            if not self.master_playlist.exists():
                return None
            newest_ms = int(self.master_playlist.stat().st_mtime * 1000)
        now_ms = int(time.time() * 1000)
        return now_ms - newest_ms

    def is_fresh(self, max_ms: Optional[int] = None) -> bool:
        age = self.freshness_ms()
        if age is None:
            return False
        threshold = max_ms if max_ms is not None else self.profile.stale_after_ms
        return age <= threshold

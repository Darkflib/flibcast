from __future__ import annotations
import subprocess
import signal
from pathlib import Path
from dataclasses import dataclass


@dataclass
class HlsProfile:
    width: int = 1920
    height: int = 1080
    fps: int = 15
    video_bitrate: str = "3500k"
    audio: bool = False  # add pulse input later if needed


class FfmpegHls:
    def __init__(self, display: str, out_dir: Path, profile: HlsProfile) -> None:
        self.display = display
        self.out_dir = out_dir
        self.profile = profile
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        variant = self.out_dir / "variant_1080p.m3u8"
        master = self.out_dir / "index.m3u8"

        cmd = [
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
            str(int(int(self.profile.video_bitrate[:-1]) * 2)) + "k",
            "-g",
            str(self.profile.fps * 2),
            "-keyint_min",
            str(self.profile.fps * 2),
            "-sc_threshold",
            "0",
            "-hls_time",
            "2",
            "-hls_list_size",
            "6",
            "-hls_flags",
            "delete_segments+independent_segments",
            "-master_pl_name",
            master.name,
            "-f",
            "hls",
            str(variant),
        ]

        self._proc = subprocess.Popen(cmd)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None

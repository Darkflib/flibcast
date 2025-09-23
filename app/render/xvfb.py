from __future__ import annotations
import os
import signal
import subprocess
from dataclasses import dataclass


@dataclass
class Xvfb:
    width: int
    height: int
    display: str = ":99"
    depth: int = 24
    _proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self._proc:
            return
        cmd = [
            "Xvfb",
            self.display,
            "-screen",
            "0",
            f"{self.width}x{self.height}x{self.depth}",
            "-nolisten",
            "tcp",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.environ["DISPLAY"] = self.display

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        self._proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

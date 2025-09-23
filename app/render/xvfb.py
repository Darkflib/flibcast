"""Thin wrapper around the Xvfb binary for headless rendering."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from dataclasses import dataclass, field
from typing import Sequence


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Xvfb:
    """Context manager that starts an Xvfb server and exposes its display."""

    width: int = 1920
    height: int = 1080
    display: str = ":99"
    depth: int = 24
    extra_args: Sequence[str] = ()
    hide_cursor: bool = True
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        """Spawn an Xvfb process (if not already running) and export DISPLAY."""

        if self._proc and self._proc.poll() is None:
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
        if self.extra_args:
            cmd.extend(self.extra_args)
        if self.hide_cursor:
            cmd.append("-nocursor")

        LOGGER.info("Starting Xvfb on %s with %s", self.display, cmd)
        self._proc = subprocess.Popen(  # noqa: S603 - expected invocation of external binary
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = self.display
        LOGGER.debug("Xvfb display %s running with pid=%s", self.display, self._proc.pid)

    def stop(self) -> None:
        """Terminate the Xvfb process and unset DISPLAY if we set it."""

        if not self._proc:
            return

        proc, self._proc = self._proc, None
        if proc.poll() is None:
            LOGGER.info("Stopping Xvfb on %s (pid=%s)", self.display, proc.pid)
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception:  # pragma: no cover - fallback safety
                LOGGER.warning("Xvfb pid=%s did not exit cleanly; killing", proc.pid)
                proc.kill()
        if os.environ.get("DISPLAY") == self.display:
            os.environ.pop("DISPLAY", None)

    def __enter__(self) -> Xvfb:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    @property
    def is_running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

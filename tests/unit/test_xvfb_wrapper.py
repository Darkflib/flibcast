import os
import signal
import subprocess

import pytest

from app.render.xvfb import Xvfb


class _DummyProc:
    pid = 4242

    def __init__(self, cmd, started):
        started.append(cmd)
        self._status = None

    def poll(self):
        return self._status

    def send_signal(self, signum):
        assert signum == signal.SIGTERM
        self._status = 0

    def wait(self, timeout=3):
        assert timeout == 3
        self._status = 0

    def kill(self):
        self._status = -9


def test_xvfb_start_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(cmd, stdout=None, stderr=None):
        assert stdout is subprocess.DEVNULL
        assert stderr is subprocess.DEVNULL
        return _DummyProc(cmd, calls)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.delenv("DISPLAY", raising=False)

    xvfb = Xvfb(width=800, height=600, display=":88", extra_args=["-foo"])
    with xvfb:
        assert os.environ["DISPLAY"] == ":88"
        assert xvfb.is_running is True

    # DISPLAY should be cleared when Xvfb stops
    assert os.environ.get("DISPLAY") != ":88"
    assert xvfb.is_running is False

    # Ensure command arguments recorded (including extra args)
    assert calls
    cmd = calls[0]
    assert cmd[0] == "Xvfb"
    assert cmd[1] == ":88"
    assert "800x600x24" in cmd
    assert cmd[-1] == "-foo"


def test_xvfb_start_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class ReusableProc(_DummyProc):
        def poll(self):
            return None

    def fake_popen(cmd, stdout=None, stderr=None):
        calls.append(1)
        return ReusableProc(cmd, [])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    xvfb = Xvfb(width=640, height=480)
    xvfb.start()
    xvfb.start()
    assert len(calls) == 1
    xvfb.stop()

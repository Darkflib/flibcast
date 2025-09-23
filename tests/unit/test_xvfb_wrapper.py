import subprocess
from app.render.xvfb import Xvfb


def test_xvfb_start_stop(monkeypatch):
    started = {}

    def fake_popen(cmd, stdout=None, stderr=None):
        started["cmd"] = cmd

        class P:
            def __init__(self):
                self._ret = None

            def poll(self):
                return self._ret

            def send_signal(self, *_):
                self._ret = 0

            def wait(self, timeout=3):
                self._ret = 0

            def kill(self):
                self._ret = -9

        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    x = Xvfb(width=640, height=480, display=":99")
    x.start()
    assert "Xvfb" in started["cmd"][0]
    x.stop()

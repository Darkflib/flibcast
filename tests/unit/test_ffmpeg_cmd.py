from pathlib import Path
import subprocess
from app.capture.ffmpeg_hls import FfmpegHls, HlsProfile


def test_ffmpeg_invocation(monkeypatch, tmp_path: Path):
    called = {}

    def fake_popen(cmd):
        called["cmd"] = cmd

        class P:
            def __init__(self):
                self._ret = None

            def poll(self):
                return None

            def send_signal(self, *_):
                self._ret = 0

            def wait(self, timeout=5):
                self._ret = 0

            def kill(self):
                self._ret = -9

        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    prof = HlsProfile(width=1920, height=1080, fps=15, video_bitrate="3500k")
    enc = FfmpegHls(display=":99", out_dir=tmp_path, profile=prof)
    enc.start()

    assert called["cmd"][:2] == ["ffmpeg", "-loglevel"]
    assert "-f" in called["cmd"] and "x11grab" in called["cmd"]
    assert str(tmp_path / "variant_1080p.m3u8") in called["cmd"]
    enc.stop()

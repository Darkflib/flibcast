from __future__ import annotations

import os
import time
from pathlib import Path

from app.capture.ffmpeg_hls import FfmpegHls, HlsProfile


class StubProc:
    def __init__(self):
        self._status = None
        self.pid = 1234

    def poll(self):
        return self._status

    def send_signal(self, *_):
        self._status = 0

    def wait(self, timeout=5):
        assert timeout == 5
        self._status = 0

    def kill(self):
        self._status = -9


def test_ffmpeg_invocation(tmp_path: Path):
    recorded: dict[str, list[str]] = {}

    def fake_popen(cmd):
        recorded["cmd"] = cmd
        return StubProc()

    prof = HlsProfile(width=1920, height=1080, fps=15, video_bitrate="3500k")
    enc = FfmpegHls(display=":99", out_dir=tmp_path, profile=prof, popen=fake_popen)
    enc.start()

    assert recorded["cmd"][:2] == ["ffmpeg", "-loglevel"]
    assert "x11grab" in recorded["cmd"]
    assert str(tmp_path / "variant_1080p.m3u8") in recorded["cmd"]
    assert enc.is_running is True
    enc.stop()
    assert enc.is_running is False


def test_ffmpeg_with_audio(tmp_path: Path):
    recorded: dict[str, list[str]] = {}

    def fake_popen(cmd):
        recorded["cmd"] = cmd
        return StubProc()

    prof = HlsProfile(audio=True, audio_device="monitor", audio_bitrate="192k")
    enc = FfmpegHls(display=":0", out_dir=tmp_path, profile=prof, popen=fake_popen)
    enc.start()

    cmd = recorded["cmd"]
    audio_indices = [i for i, tok in enumerate(cmd) if tok == "pulse"]
    assert audio_indices, "pulse input not configured"
    assert "-c:a" in cmd and "aac" in cmd
    assert "192k" in cmd
    enc.stop()


def test_freshness_helpers(tmp_path: Path):
    prof = HlsProfile()
    enc = FfmpegHls(display=":99", out_dir=tmp_path, profile=prof)

    enc.out_dir.mkdir(parents=True, exist_ok=True)
    assert enc.freshness_ms() is None
    assert enc.is_fresh() is False

    master = enc.master_playlist
    master.write_text("#EXTM3U\n")
    recent = time.time() - 1
    os.utime(master, (recent, recent))
    age = enc.freshness_ms()
    assert age is not None and age < 2000
    assert enc.is_fresh(max_ms=5000) is True

    segment = enc.out_dir / "segment0.ts"
    segment.write_bytes(b"data")
    older = time.time() - 10
    os.utime(segment, (older, older))
    assert enc.is_fresh() is False

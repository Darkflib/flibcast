import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.serve import http_api
from app.sender.fcast_adapter import Receiver


class _StubXvfb:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class _StubPlaywrightDriver:
    def launch(self, *args, **kwargs) -> None:
        return None

    def close(self) -> None:
        return None


class _StubEncoder:
    def __init__(self, display, out_dir, profile):
        self.display = display
        self.out_dir = Path(out_dir)
        self.profile = profile
        self.started = False

    def start(self) -> None:
        self.started = True
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "index.m3u8").write_text("#EXTM3U\n")
        segment = self.out_dir / "segment0.ts"
        segment.write_bytes(b"data")
        now = time.time()
        os_times = (now, now)
        os.utime(segment, os_times)

    def stop(self) -> None:
        self.started = False


class _StubSender:
    def play(self, receiver_name, media_url, title=None, *, host=None, port=46899) -> None:
        assert host == "192.0.2.10"
        return None

    def stop(self, receiver_name, *, host=None, port=46899) -> None:
        return None

    def discover(self):
        return [
            Receiver(name="Living Room", id="abc"),
            Receiver(name="Kitchen", id="def"),
        ]


def test_api_smoke(tmp_path: Path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setenv("SESSIONS_DIR", str(root))
    http_api.SESSIONS_DIR = root
    root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(http_api, "Xvfb", _StubXvfb)
    monkeypatch.setattr(http_api, "PlaywrightDriver", _StubPlaywrightDriver)
    monkeypatch.setattr(http_api, "FfmpegHls", _StubEncoder)
    http_api._sender = _StubSender()
    http_api.app.mount("/cast", http_api.StaticFiles(directory=str(root), html=False), name="cast")

    http_api._sessions = http_api.SessionManager(root=root)
    http_api._runtimes.clear()

    client = TestClient(http_api.app)

    assert client.get("/healthz").status_code == 200

    # Start a session (won't actually stream in CI, but returns an id)
    resp = client.post(
        "/sessions",
        json={
            "url": "http://example.com",
            "receiver_name": "Dummy",
            "receiver_host": "192.0.2.10",
            "width": 1280,
            "height": 720,
            "fps": 15,
            "video_bitrate": "1500k",
            "audio": False,
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["id"]

    # Status exists
    st = client.get(f"/sessions/{sid}/status")
    assert st.status_code == 200
    payload = st.json()
    assert payload["source_url"].rstrip("/") == "http://example.com"
    assert payload["receiver_name"] == "Dummy"
    assert payload["receiver_host"] == "192.0.2.10"

    sessions = client.get("/sessions")
    assert sessions.status_code == 200
    body = sessions.json()
    assert any(item["id"] == sid for item in body["sessions"])

    receivers = client.get("/receivers")
    assert receivers.status_code == 200
    r_body = receivers.json()
    assert any(r["name"] == "Living Room" for r in r_body["receivers"])

    # Stop
    stop = client.delete(f"/sessions/{sid}")
    assert stop.status_code == 200

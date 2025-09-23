from pathlib import Path
from fastapi.testclient import TestClient
from app.serve.http_api import app


def test_api_smoke(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200

    # Start a session (won't actually stream in CI, but returns an id)
    resp = client.post(
        "/sessions",
        json={
            "url": "http://example.com",
            "receiver_name": "Dummy",
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

    # Stop
    stop = client.delete(f"/sessions/{sid}")
    assert stop.status_code == 200

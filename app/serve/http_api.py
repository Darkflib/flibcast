from __future__ import annotations
import os
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from app.core.session import SessionManager, Session
from app.render.xvfb import Xvfb
from app.render.playwright_driver import BrowserController
from app.capture.ffmpeg_hls import FfmpegHls, HlsProfile
from app.sender.fcast_adapter import Sender

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
HOST_ADDR = os.getenv("HOST_ADDR", "0.0.0.0")
HOST_PORT = int(os.getenv("HOST_PORT", "8080"))

app = FastAPI()
app.mount("/cast", StaticFiles(directory=str(SESSIONS_DIR), html=False), name="cast")


class StartRequest(BaseModel):
    url: HttpUrl
    receiver_name: str
    width: int = 1920
    height: int = 1080
    fps: int = 15
    video_bitrate: str = "3500k"
    audio: bool = False
    cookies_path: Optional[str] = None
    user_data_dir: Optional[str] = None
    title: Optional[str] = None


class SessionStatus(BaseModel):
    id: str
    state: str
    hls_url: Optional[str]
    last_segment_age_ms: Optional[int]


_sessions = SessionManager()
_sender = Sender()


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _orchestrate(session: Session, req: StartRequest) -> None:
    # 1) Xvfb
    xvfb = Xvfb(width=req.width, height=req.height, display=session.display)
    xvfb.start()

    # 2) Browser
    ctrl = BrowserController(width=req.width, height=req.height)
    ctrl.launch(
        url=str(req.url),
        cookies_path=Path(req.cookies_path) if req.cookies_path else None,
        user_data_dir=Path(req.user_data_dir) if req.user_data_dir else None,
    )

    # 3) FFmpeg HLS
    prof = HlsProfile(
        width=req.width,
        height=req.height,
        fps=req.fps,
        video_bitrate=req.video_bitrate,
        audio=req.audio,
    )
    enc = FfmpegHls(display=session.display, out_dir=session.dir, profile=prof)
    enc.start()

    # small warm-up
    time.sleep(3)
    session.state = "playing"
    session.last_ok_ms = int(time.time() * 1000)

    # 4) Ask receiver to play
    # Use host's reachable IP/host; in host networking, the container's IP is host.
    media_url = f"http://{os.getenv('FC_HOSTNAME_OVERRIDE','localhost')}:{HOST_PORT}{session.hls_master_url_path}"
    _sender.play(req.receiver_name, media_url, req.title or "WebCast")

    # Keep thread alive while encoding; a simplistic loop watches for stop
    while session.state == "playing":
        time.sleep(1)
        # could update last_ok_ms based on segment freshness, etc.

    # Teardown
    try:
        enc.stop()
    finally:
        try:
            ctrl.close()
        finally:
            xvfb.stop()


@app.post("/sessions", response_model=SessionStatus)
def start_session(req: StartRequest):
    s = _sessions.create()
    t = threading.Thread(target=_orchestrate, args=(s, req), daemon=True)
    t.start()
    # return initial status & URL (playlist may take ~3-5s to populate)
    return SessionStatus(
        id=s.id,
        state=s.state,
        hls_url=s.hls_master_url_path,
        last_segment_age_ms=None,
    )


@app.get("/sessions/{sid}/status", response_model=SessionStatus)
def status(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "Not found")
    return SessionStatus(
        id=s.id,
        state=s.state,
        hls_url=s.hls_master_url_path if s.hls_master_path.exists() else None,
        last_segment_age_ms=s.freshness_ms(),
    )


@app.delete("/sessions/{sid}")
def stop(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "Not found")
    s.state = "stopping"
    time.sleep(1.0)
    _sessions.delete(sid)
    return {"ok": True}

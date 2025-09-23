"""FastAPI surface for controlling cast sessions."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from app.capture.ffmpeg_hls import FfmpegHls, HlsProfile
from app.core.session import Session, SessionManager
from app.render.playwright_driver import PlaywrightDriver
from app.render.xvfb import Xvfb
from app.sender.fcast_adapter import Sender

LOGGER = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path.cwd() / "sessions"
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", str(DEFAULT_SESSIONS_DIR))).expanduser()
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
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
    audio_device: Optional[str] = None
    cookies_path: Optional[str] = None
    user_data_dir: Optional[str] = None
    title: Optional[str] = None


class SessionStatus(BaseModel):
    id: str
    state: str
    hls_url: Optional[str]
    last_segment_age_ms: Optional[int]


@dataclass(slots=True)
class SessionRuntime:
    session: Session
    driver: PlaywrightDriver
    xvfb: Xvfb
    encoder: FfmpegHls
    receiver_name: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def request_stop(self) -> None:
        self.stop_event.set()


_sessions = SessionManager(root=SESSIONS_DIR)
_sender = Sender()
_runtimes: dict[str, SessionRuntime] = {}


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


def _media_url(session: Session) -> str:
    host = os.getenv("FC_HOSTNAME_OVERRIDE", HOST_ADDR)
    return f"http://{host}:{HOST_PORT}{session.hls_master_url_path}"


def _await_initial_playlist(session: Session, runtime: SessionRuntime, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if runtime.stop_event.wait(0.5):
            return False
        if session.hls_master_path.exists():
            age = session.freshness_ms()
            if age is not None and age <= runtime.encoder.profile.stale_after_ms:
                session.state = "playing"
                session.mark_ok()
                return True
    return False


def _orchestrate(runtime: SessionRuntime, req: StartRequest) -> None:
    session = runtime.session
    session.source_url = str(req.url)
    session.receiver_name = req.receiver_name

    try:
        LOGGER.info("Session %s starting (display=%s)", session.id, session.display)
        runtime.xvfb.start()
        runtime.driver.launch(
            url=str(req.url),
            width=req.width,
            height=req.height,
            cookies_path=Path(req.cookies_path) if req.cookies_path else None,
            user_data_dir=Path(req.user_data_dir) if req.user_data_dir else None,
        )
        runtime.encoder.start()

        if not _await_initial_playlist(session, runtime):
            raise RuntimeError("Timed out waiting for initial HLS output")

        media_url = _media_url(session)
        _sender.play(req.receiver_name, media_url, req.title or "WebCast")

        while not runtime.stop_event.wait(1):
            age = session.freshness_ms()
            if age is None:
                continue
            if age <= runtime.encoder.profile.stale_after_ms:
                session.mark_ok()
            else:
                raise RuntimeError("HLS output became stale")

        LOGGER.info("Stop requested for session %s", session.id)

    except Exception as exc:  # pragma: no cover - exercised through integration
        LOGGER.exception("Session %s failed: %s", session.id, exc)
        session.state = "error"
        runtime.stop_event.set()
    finally:
        with contextlib.suppress(Exception):
            runtime.encoder.stop()
        with contextlib.suppress(Exception):
            runtime.driver.close()
        with contextlib.suppress(Exception):
            runtime.xvfb.stop()
        _sender.stop(runtime.receiver_name)
        if session.state not in {"error", "stopped"}:
            session.state = "stopped"
        _runtimes.pop(session.id, None)


def _build_profile(req: StartRequest) -> HlsProfile:
    return HlsProfile(
        width=req.width,
        height=req.height,
        fps=req.fps,
        video_bitrate=req.video_bitrate,
        audio=req.audio,
        audio_device=req.audio_device or "default",
    )


@app.post("/sessions", response_model=SessionStatus)
def start_session(req: StartRequest) -> SessionStatus:
    session = _sessions.create()
    session.source_url = str(req.url)
    session.receiver_name = req.receiver_name

    runtime = SessionRuntime(
        session=session,
        driver=PlaywrightDriver(),
        xvfb=Xvfb(width=req.width, height=req.height, display=session.display),
        encoder=FfmpegHls(display=session.display, out_dir=session.dir, profile=_build_profile(req)),
        receiver_name=req.receiver_name,
    )
    _runtimes[session.id] = runtime

    thread = threading.Thread(target=_orchestrate, args=(runtime, req), daemon=True)
    runtime.thread = thread
    thread.start()

    return SessionStatus(
        id=session.id,
        state=session.state,
        hls_url=session.hls_master_url_path,
        last_segment_age_ms=None,
    )


@app.get("/sessions/{sid}/status", response_model=SessionStatus)
def status(sid: str) -> SessionStatus:
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Not found")
    return SessionStatus(
        id=session.id,
        state=session.state,
        hls_url=session.hls_master_url_path if session.hls_master_path.exists() else None,
        last_segment_age_ms=session.freshness_ms(),
    )


@app.delete("/sessions/{sid}")
def stop(sid: str) -> dict[str, bool]:
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Not found")

    runtime = _runtimes.get(sid)
    session.state = "stopping"
    if runtime:
        runtime.request_stop()
        _sender.stop(runtime.receiver_name)
        thread = runtime.thread
        if thread:
            thread.join(timeout=10)

    _sessions.delete(sid)
    _runtimes.pop(sid, None)
    return {"ok": True}

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

from contextlib import asynccontextmanager

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

@asynccontextmanager
async def _lifespan(_: FastAPI):
    try:
        yield
    finally:
        _shutdown_sessions()


app = FastAPI(lifespan=_lifespan)
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
    receiver_host: Optional[str] = None
    receiver_port: int = 46899
    hide_browser_ui: bool = True


class SessionStatus(BaseModel):
    id: str
    state: str
    hls_url: Optional[str]
    last_segment_age_ms: Optional[int]
    source_url: Optional[str] = None
    receiver_name: Optional[str] = None
    receiver_host: Optional[str] = None
    receiver_port: Optional[int] = None
    started_at: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionStatus]


class ReceiverInfo(BaseModel):
    name: str
    id: str


class ReceiverListResponse(BaseModel):
    receivers: list[ReceiverInfo]


@dataclass(slots=True)
class SessionRuntime:
    session: Session
    driver: PlaywrightDriver
    xvfb: Xvfb
    encoder: FfmpegHls
    receiver_name: str
    receiver_host: Optional[str]
    receiver_port: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def request_stop(self) -> None:
        self.stop_event.set()


_sessions = SessionManager(root=SESSIONS_DIR)
_sender = Sender()
_runtimes: dict[str, SessionRuntime] = {}
_receiver_sessions: dict[str, str] = {}


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


def _media_url(session: Session) -> str:
    host = os.getenv("FC_HOSTNAME_OVERRIDE", HOST_ADDR)
    return f"http://{host}:{HOST_PORT}{session.hls_master_url_path}"


def _stop_receiver_if_active(
    receiver_name: Optional[str],
    session_id: str,
    *,
    host: Optional[str],
    port: Optional[int],
) -> None:
    if not receiver_name:
        return
    if _receiver_sessions.get(receiver_name) != session_id:
        return

    stop_port = port if port is not None else 46899
    _sender.stop(receiver_name, host=host, port=stop_port)
    _receiver_sessions.pop(receiver_name, None)


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
    session.receiver_host = req.receiver_host
    session.receiver_port = req.receiver_port
    session.width = req.width
    session.height = req.height

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
        if _sender.play(
            req.receiver_name,
            media_url,
            req.title or "WebCast",
            host=req.receiver_host,
            port=req.receiver_port,
        ):
            _receiver_sessions[req.receiver_name] = session.id

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
        _stop_receiver_if_active(
            runtime.receiver_name,
            session.id,
            host=runtime.receiver_host,
            port=runtime.receiver_port,
        )
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
    session.receiver_host = req.receiver_host
    session.receiver_port = req.receiver_port

    runtime = SessionRuntime(
        session=session,
        driver=PlaywrightDriver(hide_browser_ui=req.hide_browser_ui),
        xvfb=Xvfb(width=req.width, height=req.height, display=session.display),
        encoder=FfmpegHls(display=session.display, out_dir=session.dir, profile=_build_profile(req)),
        receiver_name=req.receiver_name,
        receiver_host=req.receiver_host,
        receiver_port=req.receiver_port,
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
        source_url=session.source_url,
        receiver_name=session.receiver_name,
        receiver_host=session.receiver_host,
        receiver_port=session.receiver_port,
        started_at=session.started_at.isoformat(),
        width=session.width,
        height=session.height,
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
        source_url=session.source_url,
        receiver_name=session.receiver_name,
        receiver_host=session.receiver_host,
        receiver_port=session.receiver_port,
        started_at=session.started_at.isoformat(),
        width=session.width,
        height=session.height,
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
        _stop_receiver_if_active(
            runtime.receiver_name,
            session.id,
            host=runtime.receiver_host,
            port=runtime.receiver_port,
        )
        thread = runtime.thread
        if thread:
            thread.join(timeout=10)

    _sessions.delete(sid)
    _runtimes.pop(sid, None)
    if session.receiver_name:
        _stop_receiver_if_active(
            session.receiver_name,
            session.id,
            host=session.receiver_host,
            port=session.receiver_port,
        )
    return {"ok": True}


@app.get("/sessions", response_model=SessionListResponse)
def list_sessions() -> SessionListResponse:
    items: list[SessionStatus] = []
    for session in _sessions.all():
        items.append(
            SessionStatus(
                id=session.id,
                state=session.state,
                hls_url=session.hls_master_url_path if session.hls_master_path.exists() else None,
                last_segment_age_ms=session.freshness_ms(),
                source_url=session.source_url,
                receiver_name=session.receiver_name,
                receiver_host=session.receiver_host,
                receiver_port=session.receiver_port,
                started_at=session.started_at.isoformat(),
                width=session.width,
                height=session.height,
            )
        )
    return SessionListResponse(sessions=items)


@app.get("/receivers", response_model=ReceiverListResponse)
def list_receivers() -> ReceiverListResponse:
    discovered = _sender.discover()
    receivers = [ReceiverInfo(name=r.name, id=r.id) for r in discovered]
    return ReceiverListResponse(receivers=receivers)


def _shutdown_sessions() -> None:
    sessions = list(_sessions.all())
    for session in sessions:
        runtime = _runtimes.pop(session.id, None)
        if runtime:
            runtime.request_stop()
            thread = runtime.thread
            if thread and thread.is_alive():
                thread.join(timeout=10)
            with contextlib.suppress(Exception):
                runtime.encoder.stop()
            with contextlib.suppress(Exception):
                runtime.driver.close()
            with contextlib.suppress(Exception):
                runtime.xvfb.stop()
        if session.receiver_name:
            with contextlib.suppress(Exception):
                _stop_receiver_if_active(
                    session.receiver_name,
                    session.id,
                    host=session.receiver_host,
                    port=session.receiver_port,
                )
        _sessions.delete(session.id)

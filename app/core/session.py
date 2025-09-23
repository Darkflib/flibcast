"""Session lifecycle utilities for cast recording."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import os
import shutil
import uuid


State = Literal["starting", "playing", "stopping", "stopped", "error"]


def _now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(tz=timezone.utc)


def _default_sessions_root() -> Path:
    """Determine the root folder for session artifacts."""

    default_root = Path.cwd() / "sessions"
    return Path(os.getenv("SESSIONS_DIR", str(default_root))).expanduser().resolve()


@dataclass(slots=True)
class Session:
    """Represents a single capture/streaming session."""

    id: str
    dir: Path
    state: State = "starting"
    started_at: datetime = field(default_factory=_now_utc)
    last_ok_at: Optional[datetime] = None
    display: str = ":99"
    source_url: Optional[str] = None
    receiver_name: Optional[str] = None
    receiver_host: Optional[str] = None
    receiver_port: Optional[int] = None

    def __post_init__(self) -> None:
        # Ensure the session directory exists for downstream components.
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def hls_master_path(self) -> Path:
        return self.dir / "index.m3u8"

    @property
    def hls_master_url_path(self) -> str:
        # Served under /cast/{id}/index.m3u8
        return f"/cast/{self.id}/index.m3u8"

    def freshness_ms(self) -> Optional[int]:
        """Return the age (in ms) of the newest segment, if any."""

        report = SessionFreshness(self).evaluate()
        return report.last_segment_age_ms

    def mark_ok(self) -> None:
        """Record the last successful status probe."""

        self.last_ok_at = _now_utc()

    def to_dict(self) -> dict[str, object]:
        """Serialize session metadata to a JSON-friendly dictionary."""

        return {
            "id": self.id,
            "dir": str(self.dir),
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "display": self.display,
            "source_url": self.source_url,
            "receiver_name": self.receiver_name,
            "receiver_host": self.receiver_host,
            "receiver_port": self.receiver_port,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Session:
        """Hydrate a session from :meth:`to_dict` output."""

        started_at_raw = payload.get("started_at")
        last_ok_raw = payload.get("last_ok_at")
        started_at = (
            datetime.fromisoformat(started_at_raw)
            if isinstance(started_at_raw, str)
            else _now_utc()
        )
        last_ok_at = (
            datetime.fromisoformat(last_ok_raw)
            if isinstance(last_ok_raw, str)
            else None
        )
        session = cls(
            id=str(payload["id"]),
            dir=Path(str(payload["dir"])),
            state=payload.get("state", "starting"),
            started_at=started_at,
            last_ok_at=last_ok_at,
            display=payload.get("display", ":99"),
            source_url=payload.get("source_url"),
            receiver_name=payload.get("receiver_name"),
            receiver_host=payload.get("receiver_host"),
            receiver_port=payload.get("receiver_port"),
        )
        return session

    def cleanup(self) -> None:
        """Remove all generated artifacts for the session.

        The method is idempotent and tolerates partially written files while the
        encoder is still shutting down.
        """

        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*")):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
        try:
            self.dir.rmdir()
        except OSError:
            # Directory may still contain files being written; leave it in
            # place and allow subsequent cleanup attempts to finish the job.
            pass


@dataclass(frozen=True)
class FreshnessReport:
    last_segment_age_ms: Optional[int]
    stale: bool


class SessionFreshness:
    """Inspect recency of session playlist and segments."""

    def __init__(self, session: Session, stale_after_ms: int = 8000) -> None:
        self.session = session
        self.stale_after_ms = stale_after_ms

    def evaluate(self) -> FreshnessReport:
        now_ms = int(_now_utc().timestamp() * 1000)
        master = self.session.hls_master_path
        if not master.exists():
            return FreshnessReport(last_segment_age_ms=None, stale=True)

        newest_segment_ms: Optional[int] = None
        for segment in self.session.dir.glob("*.ts"):
            segment_ms = int(segment.stat().st_mtime * 1000)
            if newest_segment_ms is None or segment_ms > newest_segment_ms:
                newest_segment_ms = segment_ms

        if newest_segment_ms is None:
            # Fall back to master playlist mtime when no segments exist yet.
            master_ms = int(master.stat().st_mtime * 1000)
            age = now_ms - master_ms
            return FreshnessReport(
                last_segment_age_ms=None, stale=age > self.stale_after_ms
            )

        age = now_ms - newest_segment_ms
        return FreshnessReport(last_segment_age_ms=age, stale=age > self.stale_after_ms)


class SessionManager:
    """In-memory registry for active sessions."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or _default_sessions_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex
        session_dir = self.root / sid
        session = Session(id=sid, dir=session_dir)
        self._sessions[sid] = session
        return session

    def get(self, sid: str) -> Optional[Session]:
        return self._sessions.get(sid)

    def delete(self, sid: str) -> None:
        session = self._sessions.pop(sid, None)
        if session:
            session.cleanup()

    def all(self) -> list[Session]:
        return list(self._sessions.values())

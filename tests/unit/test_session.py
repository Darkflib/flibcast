"""Unit tests for the session lifecycle helpers."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

from app.core.session import Session, SessionFreshness, SessionManager


def test_session_create_and_serialize(tmp_path: Path) -> None:
    manager = SessionManager(root=tmp_path / "sessions")
    session = manager.create()

    assert Path(session.dir).parent == manager.root
    # ID should be parseable as a UUID (hex-only form).
    uuid.UUID(hex=session.id)

    payload = session.to_dict()
    hydrated = Session.from_dict(payload)

    assert hydrated.id == session.id
    assert hydrated.state == session.state
    assert hydrated.dir == session.dir
    assert hydrated.dir.exists()
    assert hydrated.source_url is None
    assert hydrated.receiver_name is None
    assert hydrated.receiver_host is None
    assert hydrated.receiver_port is None


def test_session_freshness_reports(tmp_path: Path) -> None:
    manager = SessionManager(root=tmp_path / "sessions")
    session = manager.create()

    # No playlist yet -> stale with unknown age.
    report = SessionFreshness(session).evaluate()
    assert report.last_segment_age_ms is None
    assert report.stale is True

    master = session.hls_master_path
    master.write_text("#EXTM3U\n")
    segment = session.dir / "segment0001.ts"
    segment.write_bytes(b"data")

    recent = time.time() - 5
    os.utime(master, (recent, recent))
    os.utime(segment, (recent, recent))

    report = SessionFreshness(session).evaluate()
    assert report.last_segment_age_ms is not None
    assert 4000 <= report.last_segment_age_ms < 7000
    assert report.stale is False

    older = time.time() - 9
    os.utime(master, (older, older))
    os.utime(segment, (older, older))

    report = SessionFreshness(session).evaluate()
    assert report.last_segment_age_ms is not None
    assert report.last_segment_age_ms >= 8000
    assert report.stale is True


def test_session_cleanup_is_idempotent(tmp_path: Path) -> None:
    manager = SessionManager(root=tmp_path / "sessions")
    session = manager.create()
    (session.dir / "index.m3u8").write_text("#EXTM3U\n")
    (session.dir / "segment.ts").write_bytes(b"data")

    session.cleanup()
    assert not session.dir.exists()

    # Second invocation should be a no-op.
    session.cleanup()

    # Manager delete removes the record even if files are already gone.
    manager.delete(session.id)
    assert manager.get(session.id) is None


def test_session_manager_uses_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "env_sessions"
    monkeypatch.setenv("SESSIONS_DIR", str(root))
    manager = SessionManager()
    session = manager.create()

    assert session.dir.parent == root.resolve()

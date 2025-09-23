"""Adapter around fcast-client with graceful fallback."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Optional

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency with discovery support
    from fcast_client import FCastClient  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    FCastClient = None  # type: ignore[assignment]

try:  # pragma: no cover - legacy direct client
    from fcast import FCAST_Client
except Exception:  # pragma: no cover
    FCAST_Client = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Receiver:
    name: str
    id: str


class Sender:
    """Lightweight wrapper around fcast-client for discovery/playback."""

    def __init__(self, client: Optional[object] = None) -> None:
        if client is not None:
            self.client = client
        elif FCastClient is not None:
            self.client = FCastClient()
        elif FCAST_Client is not None:
            self.client = None
        else:
            LOGGER.warning("fcast client libraries not installed; sender features disabled")
            self.client = None

    def is_available(self) -> bool:
        return self.client is not None

    def discover(self) -> list[Receiver]:
        if self.client and hasattr(self.client, "discover"):
            devices = self.client.discover()
            receivers: list[Receiver] = []
            for device in devices or []:
                name = device.get("name")
                identifier = device.get("id")
                if name and identifier:
                    receivers.append(Receiver(name=name, id=identifier))
            return receivers
        return []

    def _resolve(self, receiver_name: str) -> Optional[Receiver]:
        receivers = self.discover()
        for receiver in receivers:
            if receiver.name == receiver_name:
                return receiver
        return None

    def play(
        self,
        receiver_name: str,
        media_url: str,
        title: Optional[str] = None,
        *,
        host: Optional[str] = None,
        port: int = 46899,
    ) -> bool:
        if self.client and hasattr(self.client, "discover"):
            receiver = self._resolve(receiver_name)
            if not receiver:
                LOGGER.error("Receiver '%s' not found", receiver_name)
                return False
            self.client.play(receiver.id, media_url, title or "WebCast")
            return True

        if FCAST_Client is None:
            LOGGER.warning("No FCast client available; skipping play")
            return False
        if not host:
            LOGGER.error("Receiver host required when using legacy fcast client")
            return False
        LOGGER.info("Connecting to receiver %s at %s:%s", receiver_name, host, port)
        client = FCAST_Client(host, port)
        try:
            client.play(
                container="application/vnd.apple.mpegurl",
                url=media_url,
            )
        finally:
            with contextlib.suppress(Exception):
                client.close()
        return True

    def stop(self, receiver_name: str, *, host: Optional[str] = None, port: int = 46899) -> bool:
        if self.client and hasattr(self.client, "discover"):
            receiver = self._resolve(receiver_name)
            if not receiver:
                return False
            self.client.stop(receiver.id)
            return True

        if FCAST_Client is None or not host:
            return False
        client = FCAST_Client(host, port)
        try:
            client.stop()
        finally:
            with contextlib.suppress(Exception):
                client.close()
        return True

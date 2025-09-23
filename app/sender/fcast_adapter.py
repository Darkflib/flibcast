"""Adapter around fcast-client with graceful fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from fcast_client import FCastClient
except Exception:  # pragma: no cover
    FCastClient = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Receiver:
    name: str
    id: str


class Sender:
    """Lightweight wrapper around fcast-client for discovery/playback."""

    def __init__(self, client: Optional[FCastClient] = None) -> None:
        if client is not None:
            self.client = client
        elif FCastClient is not None:
            self.client = FCastClient()
        else:
            LOGGER.warning("fcast-client not installed; sender features disabled")
            self.client = None

    def is_available(self) -> bool:
        return self.client is not None

    def discover(self) -> list[Receiver]:
        if not self.client:
            return []
        devices = self.client.discover()
        receivers: list[Receiver] = []
        for device in devices or []:
            name = device.get("name")
            identifier = device.get("id")
            if name and identifier:
                receivers.append(Receiver(name=name, id=identifier))
        return receivers

    def _resolve(self, receiver_name: str) -> Optional[Receiver]:
        receivers = self.discover()
        for receiver in receivers:
            if receiver.name == receiver_name:
                return receiver
        return None

    def play(self, receiver_name: str, media_url: str, title: Optional[str] = None) -> bool:
        if not self.client:
            LOGGER.warning("No FCast client available; skipping play")
            return False
        receiver = self._resolve(receiver_name)
        if not receiver:
            LOGGER.error("Receiver '%s' not found", receiver_name)
            return False
        self.client.play(receiver.id, media_url, title or "WebCast")
        return True

    def stop(self, receiver_name: str) -> bool:
        if not self.client:
            return False
        receiver = self._resolve(receiver_name)
        if not receiver:
            return False
        self.client.stop(receiver.id)
        return True

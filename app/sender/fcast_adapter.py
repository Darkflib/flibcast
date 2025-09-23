from __future__ import annotations
from typing import List, Optional
import logging

log = logging.getLogger(__name__)

try:
    # Optional dependency (pip install fcast-client)
    from fcast_client import FCastClient
except Exception:  # pragma: no cover
    FCastClient = None  # type: ignore


class Receiver(dict): ...


class Sender:
    def __init__(self) -> None:
        if FCastClient is None:
            log.warning("fcast-client not installed; sender features disabled.")
            self.client = None
        else:
            self.client = FCastClient()

    def discover(self) -> List[Receiver]:
        if not self.client:
            return []
        devices = self.client.discover()
        return [Receiver(name=d["name"], id=d["id"]) for d in devices]

    def play(
        self, receiver_name: str, media_url: str, title: Optional[str] = None
    ) -> bool:
        if not self.client:
            log.warning("No FCast client; cannot play.")
            return False
        devices = self.discover()
        target = next((d for d in devices if d["name"] == receiver_name), None)
        if not target:
            log.error("Receiver '%s' not found.", receiver_name)
            return False
        self.client.play(target["id"], media_url, title or "WebCast")
        return True

    def stop(self, receiver_name: str) -> bool:
        if not self.client:
            return False
        devices = self.discover()
        target = next((d for d in devices if d["name"] == receiver_name), None)
        if not target:
            return False
        self.client.stop(target["id"])
        return True

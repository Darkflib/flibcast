from __future__ import annotations

from typing import Any

from app.sender.fcast_adapter import Receiver, Sender


class DummyClient:
    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        self.devices = devices or []
        self.last_play: tuple[str, str, str | None] | None = None
        self.last_stop: str | None = None

    def discover(self) -> list[dict[str, Any]]:
        return list(self.devices)

    def play(self, receiver_id: str, media_url: str, title: str | None) -> None:
        self.last_play = (receiver_id, media_url, title)

    def stop(self, receiver_id: str) -> None:
        self.last_stop = receiver_id


def sample_devices() -> list[dict[str, Any]]:
    return [
        {"name": "Living Room", "id": "abc"},
        {"name": "Kitchen", "id": "def"},
    ]


def test_discovers_receivers() -> None:
    client = DummyClient(devices=sample_devices())
    sender = Sender(client=client)  # type: ignore[arg-type]

    receivers = sender.discover()
    assert receivers == [Receiver(name="Living Room", id="abc"), Receiver(name="Kitchen", id="def")]


def test_play_sends_command() -> None:
    client = DummyClient(devices=sample_devices())
    sender = Sender(client=client)  # type: ignore[arg-type]

    assert sender.play("Kitchen", "http://example/hls.m3u8", title="Demo") is True
    assert client.last_play == ("def", "http://example/hls.m3u8", "Demo")


def test_play_missing_receiver() -> None:
    client = DummyClient(devices=sample_devices())
    sender = Sender(client=client)  # type: ignore[arg-type]

    assert sender.play("Bedroom", "url") is False
    assert client.last_play is None


def test_stop_command() -> None:
    client = DummyClient(devices=sample_devices())
    sender = Sender(client=client)  # type: ignore[arg-type]

    assert sender.stop("Living Room") is True
    assert client.last_stop == "abc"


def test_stop_without_client() -> None:
    sender = Sender(client=None)  # type: ignore[arg-type]
    assert sender.stop("foo") is False
    assert sender.play("foo", "bar") is False

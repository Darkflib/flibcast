from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.render.playwright_driver import DEFAULT_ANTI_SLEEP_SCRIPT, PlaywrightDriver


class FakePage:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []
        self.navigations: list[tuple[str, str, int]] = []
        self.closed = False
        self.key_presses: list[str] = []

        class Keyboard:
            def __init__(self, page: "FakePage") -> None:
                self._page = page

            def press(self, key: str) -> None:
                self._page.key_presses.append(key)

        self.keyboard = Keyboard(self)

    def bring_to_front(self) -> None:
        return

    def wait_for_timeout(self, _: int) -> None:
        return

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.navigations.append((url, wait_until, timeout))

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self) -> None:
        self.headers: dict[str, str] | None = None
        self.cookies: list[dict[str, object]] = []
        self.pages: list[FakePage] = []
        self.closed = False
        self.viewport = None
        self.cdp_commands: list[tuple[str, dict[str, object]]] = []
        self.cdp_should_fail = False

    def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.headers = headers

    def add_cookies(self, cookies: list[dict[str, object]]) -> None:
        self.cookies.extend(cookies)

    def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    def new_cdp_session(self, _: FakePage) -> "FakeCdpSession":
        if self.cdp_should_fail:
            raise RuntimeError("CDP unavailable")
        return FakeCdpSession(self)

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False
        self.viewports: list[dict[str, int]] = []

    def new_context(self, viewport: dict[str, int]) -> FakeContext:
        self.viewports.append(viewport)
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.browser = FakeBrowser(self.context)
        self.launch_calls: list[tuple[bool, tuple[str, ...]]] = []
        self.launch_persistent_calls: list[tuple[str, bool, dict[str, int], tuple[str, ...]]] = []

    def launch(self, *, headless: bool, args: list[str]) -> FakeBrowser:
        self.launch_calls.append((headless, tuple(args)))
        return self.browser

    def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
        viewport: dict[str, int],
        args: list[str],
    ) -> FakeContext:
        self.launch_persistent_calls.append((user_data_dir, headless, viewport, tuple(args)))
        self.context.viewport = viewport
        return self.context


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeManager:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.started = False
        self.stopped = False

    def start(self) -> FakePlaywright:
        self.started = True
        return self.playwright

    def stop(self) -> None:
        self.stopped = True
        self.playwright.stop()


class FakeCdpSession:
    def __init__(self, context: FakeContext) -> None:
        self._context = context

    def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, object] | None:
        payload = params or {}
        self._context.cdp_commands.append((method, payload))
        if method == "Browser.getWindowForTarget":
            return {"windowId": 1}
        return None


@pytest.fixture
def fake_sync_playwright(monkeypatch: pytest.MonkeyPatch) -> FakeChromium:
    chromium = FakeChromium()
    manager = FakeManager(FakePlaywright(chromium))

    def factory():
        return manager

    monkeypatch.setattr("app.render.playwright_driver.sync_playwright", factory)
    return chromium


def test_driver_launches_ephemeral_context(tmp_path: Path, fake_sync_playwright: FakeChromium) -> None:
    cookies_path = tmp_path / "cookies.json"
    cookies_path.write_text(json.dumps([{"name": "foo", "value": "bar", "domain": "example.com"}]))

    driver = PlaywrightDriver()
    page = driver.launch(
        "https://example.test",
        width=1280,
        height=720,
        cookies_path=cookies_path,
        extra_headers={"X-Test": "1"},
    )

    assert driver.is_running is True
    assert page.navigations[0][0] == "https://example.test"
    assert page.navigations[0][1] == "networkidle"
    assert fake_sync_playwright.launch_calls
    assert fake_sync_playwright.launch_calls[0][0] is False
    assert fake_sync_playwright.browser.viewports[0] == {"width": 1280, "height": 720}
    context = driver.context
    assert context.headers == {"X-Test": "1"}
    assert context.cookies[0]["name"] == "foo"
    assert context.pages[0].init_scripts[0] == DEFAULT_ANTI_SLEEP_SCRIPT
    assert context.cdp_commands[0][0] == "Browser.getWindowForTarget"
    assert context.cdp_commands[1][0] == "Browser.setWindowBounds"
    assert page.key_presses == []

    driver.close()
    assert driver.is_running is False
    assert fake_sync_playwright.browser.closed is True


def test_driver_launches_persistent_context(tmp_path: Path, fake_sync_playwright: FakeChromium) -> None:
    driver = PlaywrightDriver()
    profile = tmp_path / "profile"
    page = driver.launch(
        "https://example.test",
        width=1024,
        height=768,
        user_data_dir=profile,
        cookies=[{"name": "baz", "value": "qux", "domain": "example.test"}],
        timeout_ms=5000,
    )

    assert page.navigations[0][2] == 5000
    assert fake_sync_playwright.launch_persistent_calls
    call = fake_sync_playwright.launch_persistent_calls[0]
    assert call[0] == str(profile)
    assert call[2] == {"width": 1024, "height": 768}
    assert call[1] is False
    assert driver.context.cookies[0]["name"] == "baz"
    assert driver.context.cdp_commands[0][0] == "Browser.getWindowForTarget"
    assert driver.context.cdp_commands[1][0] == "Browser.setWindowBounds"
    assert page.key_presses == []

    driver.close()
    assert fake_sync_playwright.context.closed is True


def test_driver_falls_back_to_f11_when_cdp_fails(fake_sync_playwright: FakeChromium) -> None:
    fake_sync_playwright.context.cdp_should_fail = True
    driver = PlaywrightDriver()
    page = driver.launch(
        "https://example.test",
        width=1280,
        height=720,
    )

    assert page.key_presses == ["F11"]

    driver.close()


def test_driver_rejects_duplicate_cookie_sources(fake_sync_playwright: FakeChromium) -> None:
    driver = PlaywrightDriver()
    with pytest.raises(ValueError):
        driver.launch(
            "https://example.test",
            width=800,
            height=600,
            cookies=[{"name": "a", "value": "b"}],
            cookies_path=Path("dummy.json"),
        )

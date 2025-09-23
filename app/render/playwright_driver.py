"""Helpers for controlling Playwright Chromium sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - optional dependency handling
    from playwright.sync_api import Browser, BrowserContext, Error, Page, Playwright, sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    Browser = BrowserContext = Page = Playwright = object  # type: ignore[assignment]

    class _PlaywrightMissingError(Exception):
        """Raised when Playwright is required but not installed."""

    Error = _PlaywrightMissingError  # type: ignore[assignment]

    def sync_playwright():  # type: ignore[override]
        raise RuntimeError("Playwright is not installed")

LOGGER = logging.getLogger(__name__)

DEFAULT_BROWSER_ARGS: tuple[str, ...] = ("--no-sandbox", "--disable-dev-shm-usage")
DEFAULT_ANTI_SLEEP_SCRIPT = """
(() => {
  const keepAwake = () => {
    if (document.hidden) {
      Object.defineProperty(document, "hidden", { value: false, configurable: true });
    }
    const noop = () => {}
    window.requestAnimationFrame(noop);
  };
  keepAwake();
  document.addEventListener("visibilitychange", keepAwake, true);
  window.addEventListener("pagehide", keepAwake, true);
})();
""".strip()


class PlaywrightDriver:
    """Manage the lifecycle of a Playwright Chromium session."""

    def __init__(
        self,
        *,
        browser_args: Sequence[str] | None = None,
        anti_sleep_script: str = DEFAULT_ANTI_SLEEP_SCRIPT,
    ) -> None:
        self.browser_args: tuple[str, ...] = tuple(browser_args or DEFAULT_BROWSER_ARGS)
        self.anti_sleep_script = anti_sleep_script
        self._manager = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def launch(
        self,
        url: str,
        *,
        width: int,
        height: int,
        cookies: Iterable[Mapping[str, object]] | None = None,
        cookies_path: Path | None = None,
        user_data_dir: Path | None = None,
        extra_headers: Mapping[str, str] | None = None,
        wait_until: str = "networkidle",
        timeout_ms: int = 30_000,
    ) -> Page:
        """Launch Chromium, navigate to *url*, and return the loaded page."""

        if self._context is not None:
            raise RuntimeError("Browser already launched")

        if cookies and cookies_path:
            raise ValueError("Provide either cookies or cookies_path, not both")

        LOGGER.info("Starting Playwright Chromium (persistent=%s)", bool(user_data_dir))
        self._manager = sync_playwright()
        self._playwright = self._manager.start()

        viewport = {"width": width, "height": height}
        if user_data_dir:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                viewport=viewport,
                args=list(self.browser_args),
            )
        else:
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=list(self.browser_args),
            )
            self._context = self._browser.new_context(viewport=viewport)

        if extra_headers:
            self._context.set_extra_http_headers(dict(extra_headers))

        cookie_payload: list[MutableMapping[str, object]] = []
        if cookies_path:
            cookie_payload.extend(self._load_cookies_from_file(cookies_path))
        elif cookies:
            for cookie in cookies:
                cookie_payload.append(dict(cookie))
        if cookie_payload:
            LOGGER.debug("Injecting %s cookies", len(cookie_payload))
            self._context.add_cookies(cookie_payload)

        self._page = self._context.new_page()
        if self.anti_sleep_script:
            self._page.add_init_script(self.anti_sleep_script)
        LOGGER.info("Navigating to %s", url)
        self._page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        return self._page

    def close(self) -> None:
        """Close the browser context and release Playwright resources."""

        try:
            if self._page:
                LOGGER.debug("Closing Playwright page")
                self._page.close()
        except Error:
            LOGGER.exception("Failed to close page cleanly")
        finally:
            self._page = None

        try:
            if self._context is not None:
                LOGGER.debug("Closing Playwright context")
                self._context.close()
        except Error:
            LOGGER.exception("Failed to close context cleanly")
        finally:
            self._context = None

        try:
            if self._browser is not None:
                LOGGER.debug("Closing Playwright browser")
                self._browser.close()
        except Error:
            LOGGER.exception("Failed to close browser cleanly")
        finally:
            self._browser = None

        if self._playwright is not None and self._manager is not None:
            LOGGER.info("Stopping Playwright")
            try:
                self._manager.stop()
            except Error:
                LOGGER.exception("Failed to stop Playwright cleanly")
            finally:
                self._playwright = None
                self._manager = None

    def __enter__(self) -> PlaywrightDriver:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Browser not launched")
        return self._context

    @property
    def is_running(self) -> bool:
        return self._context is not None

    @staticmethod
    def _load_cookies_from_file(path: Path) -> list[MutableMapping[str, object]]:
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            raise ValueError("Cookies JSON must be a list")
        cookies: list[MutableMapping[str, object]] = []
        for entry in data:
            if not isinstance(entry, Mapping):
                raise ValueError("Invalid cookie entry")
            cookies.append(dict(entry))
        return cookies

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, Iterable
from playwright.sync_api import sync_playwright


class BrowserController:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def launch(
        self,
        url: str,
        cookies_path: Optional[Path] = None,
        user_data_dir: Optional[Path] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        wait_until: str = "networkidle",
        timeout_ms: int = 25000,
    ) -> None:
        self._pw = sync_playwright().start()
        # user_data_dir enables persistent profile (auth sessions)
        self._browser = (
            self._pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir) if user_data_dir else None,
                headless=True,
                viewport={"width": self.width, "height": self.height},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            if user_data_dir
            else None
        )

        if self._browser is None:
            browser = self._pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            self._context = browser.new_context(
                viewport={"width": self.width, "height": self.height}
            )
        else:
            self._context = self._browser

        if extra_headers:
            self._context.set_extra_http_headers(extra_headers)

        if cookies_path and cookies_path.exists():
            import json

            cookies: Iterable[Dict[str, Any]] = json.loads(cookies_path.read_text())
            # normalize domains (Playwright expects leading dot sometimes)
            self._context.add_cookies(list(cookies))

        self._page = self._context.new_page()
        # small keepalive/anti-sleep
        self._page.add_init_script(
            "document.addEventListener('visibilitychange', ()=>{ Object.defineProperty(document,'hidden',{get(){return false}});});"
        )
        self._page.goto(url, wait_until=wait_until, timeout=timeout_ms)

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

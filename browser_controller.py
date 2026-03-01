import os
import re
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

import config


class BrowserController:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _is_blocked_url(self, url: str) -> bool:
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in config.BLOCKED_URL_PATTERNS)

    async def _ensure_browser(self):
        """Lazy-launch browser on first use."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            print("[browser] Chromium launched")

    async def _ensure_page(self) -> Page:
        await self._ensure_browser()
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
        return self._page

    async def navigate(self, url: str) -> str:
        page = await self._ensure_page()
        # If it doesn't look like a URL, search with DuckDuckGo (no bot detection)
        if not re.match(r'^https?://', url) and '.' not in url.split()[0]:
            url = f"https://duckduckgo.com/?q={url}"
        elif not re.match(r'^https?://', url):
            url = f"https://{url}"

        # Security: block local network and sensitive URLs
        if self._is_blocked_url(url):
            return f"BLOCKED: Navigation to '{url}' is not allowed for security reasons"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=config.BROWSER_NAV_TIMEOUT)
            return f"Navigated to {page.url}"
        except Exception as e:
            return f"Navigation error: {e}"

    async def click(self, selector: str) -> str:
        page = await self._ensure_page()
        try:
            # Try CSS selector first
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.click(timeout=5000)
                return f"Clicked: {selector}"
        except Exception:
            pass
        try:
            # Fallback: match by visible text
            el = page.get_by_text(selector, exact=False).first
            await el.click(timeout=5000)
            return f"Clicked element with text: {selector}"
        except Exception as e:
            return f"Click failed: {e}"

    async def type_text(self, selector: str, text: str) -> str:
        page = await self._ensure_page()
        try:
            el = page.locator(selector).first
            await el.fill(text, timeout=5000)
            return f"Typed into {selector}"
        except Exception:
            pass
        try:
            el = page.get_by_placeholder(selector, exact=False).first
            await el.fill(text, timeout=5000)
            return f"Typed into field matching: {selector}"
        except Exception as e:
            return f"Type failed: {e}"

    async def read_page(self) -> str:
        page = await self._ensure_page()
        try:
            text = await page.inner_text("body", timeout=5000)
            truncated = text[:2000]
            return truncated
        except Exception as e:
            return f"Read failed: {e}"

    async def screenshot(self) -> str:
        page = await self._ensure_page()
        os.makedirs(config.SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(config.SCREENSHOT_DIR, "screenshot.png")
        try:
            await page.screenshot(path=path)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Screenshot failed: {e}"

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
            print("[browser] Closed")

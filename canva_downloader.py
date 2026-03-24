"""
Canva Page Downloader

Downloads every page of a public Canva design as PNG images
using Playwright to render and screenshot the design.
"""

import logging
import os
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(__file__).parent / "downloads"


def _clean_downloads():
    """Remove all previous downloads to avoid stale images."""
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _dismiss_overlays(page):
    """Close cookie banners, modals, or popups that may block the design."""
    overlay_selectors = [
        'button:has-text("Accept")',
        'button:has-text("Accept all")',
        'button:has-text("Got it")',
        'button:has-text("Close")',
        '[aria-label="Close"]',
        '[data-testid="cookie-banner"] button',
    ]
    for selector in overlay_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                el.click()
                time.sleep(0.5)
        except (PlaywrightTimeout, Exception):
            continue


def _get_page_count(page) -> int:
    """Detect how many pages the Canva design has."""
    # Look for page indicator text like "1 / 5" or "1 of 5"
    page_indicator_selectors = [
        '[class*="page-number"]',
        '[class*="PageNumber"]',
        '[data-testid*="page"]',
        'span:has-text("/")',
    ]

    for selector in page_indicator_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                text = el.inner_text()
                # Parse "1 / 5" or "1/5" or "Page 1 of 5"
                if "/" in text:
                    parts = text.split("/")
                    return int(parts[-1].strip())
                if " of " in text.lower():
                    parts = text.lower().split(" of ")
                    return int(parts[-1].strip())
        except (PlaywrightTimeout, ValueError, Exception):
            continue

    # Fallback: count page thumbnails in the sidebar/filmstrip
    thumbnail_selectors = [
        '[class*="thumbnail"]',
        '[class*="Thumbnail"]',
        '[data-testid*="thumbnail"]',
        '[class*="filmstrip"] > div',
        '[class*="page-list"] > div',
    ]

    for selector in thumbnail_selectors:
        try:
            count = page.locator(selector).count()
            if count > 0:
                return count
        except Exception:
            continue

    # If we can't detect, assume single page
    logger.warning("Could not detect page count, assuming 1 page")
    return 1


def _navigate_to_page(page, page_num: int):
    """Navigate to a specific page in the Canva design."""
    if page_num == 1:
        return  # Already on first page

    # Try clicking the next arrow button
    next_selectors = [
        'button[aria-label="Next page"]',
        'button[aria-label="Next"]',
        '[class*="next"]',
        '[data-testid*="next"]',
        'button:has-text("›")',
        'button:has-text("→")',
    ]

    for selector in next_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                btn.click()
                time.sleep(1.5)  # Wait for page transition
                return
        except (PlaywrightTimeout, Exception):
            continue

    # Fallback: try keyboard navigation
    try:
        page.keyboard.press("ArrowRight")
        time.sleep(1.5)
    except Exception:
        logger.warning(f"Could not navigate to page {page_num}")


def _screenshot_design(page, output_path: str):
    """Take a screenshot of the design canvas area."""
    # Try to find the main design/canvas element
    canvas_selectors = [
        '[class*="canvas"]',
        '[class*="Canvas"]',
        '[data-testid*="canvas"]',
        '[class*="design-surface"]',
        '[class*="DesignSurface"]',
        '[role="main"] [class*="view"]',
        'main [class*="presenter"]',
        '[class*="presenter"]',
        '[class*="Presenter"]',
    ]

    for selector in canvas_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                # Wait for any animations to finish
                time.sleep(1)
                el.screenshot(path=output_path, type="png")
                logger.info(f"Saved page screenshot: {output_path}")
                return
        except (PlaywrightTimeout, Exception):
            continue

    # Fallback: full page screenshot with clipping
    logger.warning("Could not find canvas element, taking full viewport screenshot")
    page.screenshot(path=output_path, type="png", full_page=False)
    logger.info(f"Saved full viewport screenshot: {output_path}")


def download_pages(canva_url: str, headless: bool = True) -> list[str]:
    """
    Download all pages from a public Canva design as PNG images.

    Args:
        canva_url: Public Canva design URL
        headless: Run browser in headless mode

    Returns:
        List of file paths to downloaded images
    """
    _clean_downloads()
    image_paths = []

    logger.info(f"Opening Canva design: {canva_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            page.goto(canva_url, wait_until="networkidle", timeout=60000)
            time.sleep(3)  # Extra wait for Canva rendering

            _dismiss_overlays(page)

            total_pages = _get_page_count(page)
            logger.info(f"Detected {total_pages} page(s)")

            for i in range(1, total_pages + 1):
                if i > 1:
                    _navigate_to_page(page, i)

                output_path = str(DOWNLOADS_DIR / f"page_{i}.png")
                _screenshot_design(page, output_path)
                image_paths.append(output_path)

        except PlaywrightTimeout:
            logger.error("Timed out loading Canva design")
            raise
        except Exception as e:
            logger.error(f"Error downloading Canva pages: {e}")
            raise
        finally:
            browser.close()

    logger.info(f"Downloaded {len(image_paths)} page(s)")
    return image_paths


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python canva_downloader.py <canva_public_url>")
        sys.exit(1)

    paths = download_pages(sys.argv[1], headless=True)
    for p in paths:
        print(p)

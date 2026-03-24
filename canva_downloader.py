"""
Canva Page Downloader

Logs into Canva, opens the design in the editor, and uses the native
download feature to export all pages as JPG (size x2, quality 100).
Downloads a ZIP file, extracts the images.

Uses a persistent browser context (canva_browser_data/) to keep the
Canva session alive between runs. Uses stealth mode to bypass
Cloudflare bot detection.
"""

import glob
import logging
import os
import shutil
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

stealth = Stealth()

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
CANVA_BROWSER_DATA = Path(__file__).parent / "canva_browser_data"

# Chrome args to bypass bot detection (Cloudflare, etc.)
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]


def _clean_downloads():
    """Remove all previous downloads to avoid stale images."""
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _convert_view_url_to_edit_url(url: str) -> str:
    """
    Convert a public Canva view URL to an editor URL.
    e.g. https://www.canva.com/design/DAGXXXXXXXXX/view -> https://www.canva.com/design/DAGXXXXXXXXX/edit
    """
    # Remove query params and trailing slash
    clean = url.split("?")[0].rstrip("/")

    # Replace /view with /edit at the end
    if clean.endswith("/view"):
        return clean[:-5] + "/edit"

    # If it already ends with /edit, keep it
    if clean.endswith("/edit"):
        return clean

    # Otherwise append /edit
    return clean + "/edit"


def _dismiss_overlays(page):
    """Close cookie banners, modals, or popups."""
    overlay_selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("Got it")',
        'button:has-text("Maybe later")',
        'button:has-text("Skip")',
        'button:has-text("Not now")',
        '[aria-label="Close"]',
        '[aria-label="Dismiss"]',
    ]
    for selector in overlay_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1500):
                el.click()
                time.sleep(0.5)
        except Exception:
            continue


def _wait_for_editor(page, timeout: int = 60000):
    """Wait until the Canva editor is fully loaded."""
    logger.info("Waiting for Canva editor to load...")

    editor_selectors = [
        '[class*="toolbar"]',
        '[data-testid="toolbar"]',
        '[aria-label="Design"]',
        '[class*="editor"]',
        'button:has-text("Share")',
    ]

    for selector in editor_selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout)
            logger.info("Canva editor is ready")
            time.sleep(2)
            return True
        except PlaywrightTimeout:
            continue

    raise TimeoutError(
        "Canva editor did not load in time. "
        "Run 'python main.py --setup-canva' to log in."
    )


def _select_all_pages(page):
    """In the download dialog, select all pages."""
    # Look for "All pages" or "Select all" option
    all_pages_selectors = [
        'button:has-text("All pages")',
        'label:has-text("All pages")',
        'span:has-text("All pages")',
        '[data-testid*="all-pages"]',
        'input[type="radio"][value="all"]',
    ]

    for selector in all_pages_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(1)
                logger.info("Selected 'All pages'")
                return True
        except Exception:
            continue

    # It might already be set to all pages by default
    logger.info("Could not find 'All pages' option - may already be selected")
    return False


def _open_download_dialog(page):
    """Open the Share > Download dialog in Canva editor."""
    # Step 1: Click "Share" button
    share_selectors = [
        'button:has-text("Share")',
        '[aria-label="Share"]',
        '[data-testid*="share"]',
    ]

    clicked = False
    for selector in share_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=5000):
                el.click()
                time.sleep(2)
                clicked = True
                logger.info("Clicked Share button")
                break
        except Exception:
            continue

    if not clicked:
        raise RuntimeError("Could not find Share button")

    # Step 2: Click "Download" option in the share menu
    download_selectors = [
        'button:has-text("Download")',
        'a:has-text("Download")',
        '[role="menuitem"]:has-text("Download")',
        'li:has-text("Download")',
        'span:has-text("Download")',
    ]

    clicked = False
    for selector in download_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=5000):
                el.click()
                time.sleep(2)
                clicked = True
                logger.info("Clicked Download option")
                break
        except Exception:
            continue

    if not clicked:
        raise RuntimeError("Could not find Download option in Share menu")


def _set_file_type_jpg(page):
    """Set the file type to JPG in the download dialog."""
    # Click the file type dropdown (usually shows "PNG" by default)
    type_dropdown_selectors = [
        'button:has-text("PNG")',
        'button:has-text("JPG")',
        'button:has-text("File type")',
        '[class*="file-type"] button',
        '[data-testid*="file-type"]',
    ]

    for selector in type_dropdown_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(1)
                break
        except Exception:
            continue

    # Select JPG from the dropdown options
    jpg_selectors = [
        'button:has-text("JPG")',
        'li:has-text("JPG")',
        '[role="option"]:has-text("JPG")',
        'span:has-text("JPG")',
    ]

    for selector in jpg_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(1)
                logger.info("Selected JPG format")
                return True
        except Exception:
            continue

    logger.warning("Could not select JPG format - may already be selected or using PNG")
    return False


def _set_size_2x(page):
    """Set the size multiplier to 2x in the download dialog."""
    size_selectors = [
        'button:has-text("2x")',
        'button:has-text("×2")',
        'button:has-text("x2")',
        '[data-testid*="size"] button:has-text("2")',
        'label:has-text("2x")',
    ]

    for selector in size_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(1)
                logger.info("Selected size 2x")
                return True
        except Exception:
            continue

    # Try using a slider or input field for size
    size_input_selectors = [
        'input[type="range"]',
        '[class*="size"] input',
        '[data-testid*="size"] input',
    ]

    for selector in size_input_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                # Set to maximum (2x)
                el.fill("2")
                time.sleep(0.5)
                logger.info("Set size to 2x via input")
                return True
        except Exception:
            continue

    logger.warning("Could not set size to 2x")
    return False


def _set_quality_100(page):
    """Set the quality to 100 in the download dialog."""
    quality_input_selectors = [
        'input[type="range"]',
        'input[type="number"]',
        '[class*="quality"] input',
        '[data-testid*="quality"] input',
    ]

    for selector in quality_input_selectors:
        try:
            elements = page.locator(selector).all()
            for el in elements:
                if el.is_visible(timeout=1000):
                    # Check if this is a quality slider/input (range 1-100)
                    current_val = el.input_value()
                    try:
                        val = int(current_val)
                        if 0 < val <= 100:
                            el.fill("100")
                            time.sleep(0.5)
                            logger.info("Set quality to 100")
                            return True
                    except ValueError:
                        continue
        except Exception:
            continue

    # Try dragging a slider to max
    logger.warning("Could not set quality to 100 - using default")
    return False


def _click_download_button(page, download_timeout: int = 120000) -> str:
    """Click the final Download button and wait for the file to download."""
    download_btn_selectors = [
        'button:has-text("Download")',
        '[data-testid*="download-button"]',
        'button[type="submit"]:has-text("Download")',
    ]

    for selector in download_btn_selectors:
        try:
            # Find the download button (often the last one, inside the dialog)
            buttons = page.locator(selector).all()
            # Use the last matching button (the one in the download panel, not menu)
            if buttons:
                btn = buttons[-1]
                if btn.is_visible(timeout=3000):
                    # Start waiting for download before clicking
                    with page.expect_download(timeout=download_timeout) as download_info:
                        btn.click()
                        logger.info("Clicked Download button, waiting for file...")

                    download = download_info.value
                    # Save to downloads dir
                    download_path = str(DOWNLOADS_DIR / download.suggested_filename)
                    download.save_as(download_path)
                    logger.info(f"Downloaded: {download_path}")
                    return download_path
        except PlaywrightTimeout:
            logger.warning(f"Download timed out with selector: {selector}")
            continue
        except Exception as e:
            logger.warning(f"Error with selector {selector}: {e}")
            continue

    raise RuntimeError("Could not click Download button or download timed out")


def _extract_zip(zip_path: str) -> list[str]:
    """Extract a ZIP file and return the list of extracted image paths."""
    extract_dir = DOWNLOADS_DIR / "extracted"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Collect all image files
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    image_paths = []
    for f in sorted(extract_dir.iterdir()):
        if f.suffix.lower() in image_extensions:
            image_paths.append(str(f))

    # Remove the ZIP file
    os.remove(zip_path)

    logger.info(f"Extracted {len(image_paths)} image(s) from ZIP")
    return image_paths


def download_pages(canva_url: str, headless: bool = True) -> list[str]:
    """
    Download all pages from a Canva design using the native download feature.

    Logs into Canva (using a persistent browser session), opens the design
    in edit mode, and downloads all pages as JPG (size x2, quality 100).

    Args:
        canva_url: Canva design URL (view or edit link)
        headless: Run browser in headless mode

    Returns:
        List of file paths to downloaded images
    """
    _clean_downloads()
    CANVA_BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    edit_url = _convert_view_url_to_edit_url(canva_url)
    logger.info(f"Opening Canva design: {edit_url}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CANVA_BROWSER_DATA),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            accept_downloads=True,
            args=STEALTH_ARGS,
        )

        page = context.new_page()
        stealth.apply_stealth_sync(page)

        try:
            page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)

            _dismiss_overlays(page)
            _wait_for_editor(page)
            _dismiss_overlays(page)

            # Open download dialog
            _open_download_dialog(page)

            # Configure download settings
            _set_file_type_jpg(page)
            time.sleep(1)
            _set_size_2x(page)
            time.sleep(1)
            _set_quality_100(page)
            time.sleep(1)
            _select_all_pages(page)
            time.sleep(1)

            # Download
            downloaded_file = _click_download_button(page)

            # Handle result: ZIP (multi-page) or single image
            if downloaded_file.endswith(".zip"):
                image_paths = _extract_zip(downloaded_file)
            else:
                image_paths = [downloaded_file]

        except PlaywrightTimeout:
            logger.error("Timed out during Canva download flow")
            raise
        except Exception as e:
            logger.error(f"Error downloading Canva pages: {e}")
            raise
        finally:
            context.close()

    logger.info(f"Downloaded {len(image_paths)} page(s)")
    return image_paths


def setup_canva_login():
    """
    Open Canva in a visible browser for first-time login.
    The session is saved to canva_browser_data/ for future headless runs.
    """
    CANVA_BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    logger.info("Opening Canva for login...")
    logger.info("Please log in to your Canva account.")
    logger.info("After you see your Canva dashboard, close this browser window.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CANVA_BROWSER_DATA),
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=STEALTH_ARGS,
        )

        page = context.new_page()
        stealth.apply_stealth_sync(page)
        page.goto("https://www.canva.com/login", wait_until="domcontentloaded")

        logger.info("Waiting for login... (will wait up to 5 minutes)")
        try:
            # Wait for the user to log in (dashboard or home page loads)
            page.wait_for_url("**/design/**", timeout=300000)
            logger.info("Login successful! Session saved.")
            time.sleep(3)
        except PlaywrightTimeout:
            # User may have logged in but stayed on home page
            logger.info("Session saved. You can close the browser now.")
            time.sleep(5)
        finally:
            context.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--setup" in sys.argv:
        setup_canva_login()
    elif len(sys.argv) >= 2:
        url = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        if url:
            paths = download_pages(url[0], headless="--no-headless" not in sys.argv)
            for p in paths:
                print(p)
        else:
            print("Usage: python canva_downloader.py <canva_url>")
    else:
        print("Usage: python canva_downloader.py <canva_url>")
        print("       python canva_downloader.py --setup")

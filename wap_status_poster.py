"""
WhatsApp Status Poster

Posts images as WhatsApp status updates using Playwright
to automate WhatsApp Web. Uses a persistent browser context
to maintain the login session.
"""

import logging
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

BROWSER_DATA_DIR = Path(__file__).parent / "browser_data"


def _wait_for_whatsapp_ready(page, timeout: int = 120000):
    """Wait until WhatsApp Web is fully loaded and authenticated."""
    logger.info("Waiting for WhatsApp Web to load...")

    # Wait for the main app to be ready (chat list visible = logged in)
    ready_selectors = [
        '[data-testid="chatlist-header"]',
        '[data-testid="chat-list"]',
        '#pane-side',
        '[aria-label="Chat list"]',
        'div[data-testid="default-user"]',
    ]

    for selector in ready_selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout)
            logger.info("WhatsApp Web is ready")
            return True
        except PlaywrightTimeout:
            continue

    raise TimeoutError(
        "WhatsApp Web did not load in time. "
        "Run 'python main.py --setup' to log in manually."
    )


def _navigate_to_status(page):
    """Navigate to the Status tab in WhatsApp Web."""
    status_selectors = [
        '[data-testid="status-v3-tab"]',
        '[aria-label="Status"]',
        'button[title="Status"]',
        'span[data-testid="status-v3-tab"]',
        'div[data-testid="tab-btn-status"]',
    ]

    for selector in status_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(2)
                logger.info("Navigated to Status tab")
                return True
        except (PlaywrightTimeout, Exception):
            continue

    # Fallback: try via the menu/channels area
    logger.warning("Could not find Status tab via selectors, trying alternative navigation")
    return False


def _post_single_status(page, image_path: str) -> bool:
    """Post a single image as a WhatsApp status."""
    logger.info(f"Posting status: {image_path}")

    # Click the "Add status" / pencil / camera / + button
    add_status_selectors = [
        '[data-testid="status-v3-add"]',
        '[aria-label="Add status"]',
        '[data-testid="pencil-btn"]',
        'button[aria-label="My status"]',
        '[data-testid="status-v3-compose"]',
    ]

    clicked = False
    for selector in add_status_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=3000):
                el.click()
                time.sleep(1)
                clicked = True
                break
        except (PlaywrightTimeout, Exception):
            continue

    if not clicked:
        logger.error("Could not find 'Add status' button")
        return False

    # Look for photo/image option if a menu appears
    photo_selectors = [
        '[data-testid="status-v3-photo"]',
        'button:has-text("Photo")',
        'button:has-text("Photos")',
        '[aria-label="Photo"]',
        'li:has-text("Photo")',
    ]

    for selector in photo_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(1)
                break
        except (PlaywrightTimeout, Exception):
            continue

    # Upload the image via file chooser
    try:
        # Trigger file input - WhatsApp Web uses a hidden file input
        file_input = page.locator('input[type="file"][accept*="image"]').first

        if file_input.count() > 0:
            file_input.set_input_files(image_path)
        else:
            # Use file chooser dialog approach
            with page.expect_file_chooser(timeout=10000) as fc_info:
                # Click any remaining upload trigger
                upload_triggers = [
                    '[data-testid="media-upload"]',
                    'input[type="file"]',
                    '[aria-label="Upload"]',
                ]
                for sel in upload_triggers:
                    try:
                        page.locator(sel).first.click(timeout=2000)
                        break
                    except Exception:
                        continue
            file_chooser = fc_info.value
            file_chooser.set_files(image_path)

        time.sleep(2)  # Wait for image preview to load
    except Exception as e:
        logger.error(f"Failed to upload image: {e}")
        return False

    # Click send/post button
    send_selectors = [
        '[data-testid="send"]',
        '[data-testid="send-btn"]',
        'button[aria-label="Send"]',
        '[data-testid="status-v3-send"]',
        'span[data-icon="send"]',
    ]

    for selector in send_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=5000):
                el.click()
                time.sleep(3)  # Wait for upload to complete
                logger.info(f"Status posted: {image_path}")
                return True
        except (PlaywrightTimeout, Exception):
            continue

    logger.error("Could not find send button")
    return False


def post_statuses(
    image_paths: list[str],
    headless: bool = True,
    delay: int = 5,
) -> dict:
    """
    Post multiple images as WhatsApp status updates.

    Args:
        image_paths: List of image file paths to post
        headless: Run browser in headless mode (False for setup/debugging)
        delay: Seconds to wait between posting each status

    Returns:
        Dict with 'posted' (count) and 'failed' (list of paths)
    """
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    results = {"posted": 0, "failed": []}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        try:
            page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=60000)
            _wait_for_whatsapp_ready(page)
            _navigate_to_status(page)

            for i, image_path in enumerate(image_paths):
                if not Path(image_path).exists():
                    logger.warning(f"Image not found, skipping: {image_path}")
                    results["failed"].append(image_path)
                    continue

                success = _post_single_status(page, image_path)
                if success:
                    results["posted"] += 1
                else:
                    results["failed"].append(image_path)

                # Delay between posts (skip after last one)
                if i < len(image_paths) - 1:
                    logger.info(f"Waiting {delay}s before next status...")
                    time.sleep(delay)

        except Exception as e:
            logger.error(f"Error posting statuses: {e}")
            raise
        finally:
            context.close()

    return results


def setup_login():
    """
    Open WhatsApp Web in a visible browser for first-time login.
    The session is saved to browser_data/ for future headless runs.
    """
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Opening WhatsApp Web for login...")
    logger.info("Please scan the QR code with your phone or link your device.")
    logger.info("After you see your chats, close this browser window.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        # Wait for user to log in (check for chat list)
        logger.info("Waiting for login... (this will wait up to 5 minutes)")
        try:
            _wait_for_whatsapp_ready(page, timeout=300000)
            logger.info("Login successful! Session saved.")
            time.sleep(3)  # Let session data persist
        except TimeoutError:
            logger.warning("Login timed out. Please try again.")
        finally:
            context.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--setup" in sys.argv:
        setup_login()
    elif len(sys.argv) > 1:
        paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        result = post_statuses(paths, headless=True)
        print(f"Posted: {result['posted']}, Failed: {len(result['failed'])}")
    else:
        print("Usage:")
        print("  python wap_status_poster.py --setup          # First-time login")
        print("  python wap_status_poster.py img1.png img2.png  # Post statuses")

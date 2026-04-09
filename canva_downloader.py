"""
Canva Page Downloader (Hybrid: Playwright + API)

Uses Playwright to detect which pages are visible (not hidden) in the
Canva editor, then exports only those pages via the Canva Connect API.

Setup:
    1. Create an integration at https://www.canva.dev
    2. Set CANVA_CLIENT_ID and CANVA_CLIENT_SECRET in .env
    3. Run `python main.py --setup-canva` to authorize (one-time)
"""

import hashlib
import http.server
import json
import logging
import os
import secrets
import shutil
import time
import urllib.parse
import zipfile
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
TOKEN_FILE = Path(__file__).parent / "canva_tokens.json"
CANVA_BROWSER_DATA = Path(__file__).parent / "canva_browser_data"

CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_EXPORT_URL = "https://api.canva.com/rest/v1/exports"
CANVA_API_BASE = "https://api.canva.com/rest/v1"

REDIRECT_PORT = 8420
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/oauth/callback"

# Scopes needed: read designs + export
SCOPES = "design:content:read design:meta:read"


def _clean_downloads():
    """Remove all previous downloads to avoid stale images."""
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR, ignore_errors=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _extract_design_id(canva_url: str) -> str:
    """
    Extract the design ID from a Canva URL.
    e.g. https://www.canva.com/design/DAGxxxxxxxxx/view -> DAGxxxxxxxxx
         https://www.canva.com/design/DAGxxxxxxxxx/abcdef/edit -> DAGxxxxxxxxx
    """
    parts = canva_url.rstrip("/").split("/")
    # Find 'design' in the path and take the next segment
    for i, part in enumerate(parts):
        if part == "design" and i + 1 < len(parts):
            return parts[i + 1]
    raise ValueError(f"Could not extract design ID from URL: {canva_url}")


# ---------------------------------------------------------------------------
# OAuth 2.0 with PKCE
# ---------------------------------------------------------------------------

def _generate_pkce():
    """Generate PKCE code verifier and challenge (S256)."""
    import base64

    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _save_tokens(tokens: dict):
    """Save OAuth tokens to disk."""
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    logger.info("Tokens saved to canva_tokens.json")


def _load_tokens() -> dict | None:
    """Load OAuth tokens from disk."""
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _refresh_access_token(refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token."""
    client_id = os.getenv("CANVA_CLIENT_ID")
    client_secret = os.getenv("CANVA_CLIENT_SECRET")

    resp = requests.post(
        CANVA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["obtained_at"] = time.time()
    _save_tokens(tokens)
    logger.info("Access token refreshed successfully")
    return tokens


def _get_access_token() -> str:
    """
    Get a valid access token. Refreshes if expired.
    Raises RuntimeError if no tokens are available.
    """
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError(
            "No Canva tokens found. Run 'python main.py --setup-canva' to authorize."
        )

    # Check if token is expired (tokens last 4 hours)
    obtained_at = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 14400)
    if time.time() - obtained_at > expires_in - 300:  # refresh 5 min early
        logger.info("Access token expired, refreshing...")
        tokens = _refresh_access_token(tokens["refresh_token"])

    return tokens["access_token"]


# ---------------------------------------------------------------------------
# Setup: OAuth authorization flow
# ---------------------------------------------------------------------------

def setup_canva_browser():
    """
    Open a visible Chromium browser for the user to log into Canva.
    The session is saved to canva_browser_data/ for future headless use.
    """
    logger.info("Opening Canva for browser login...")
    logger.info("Log in to your Canva account, then close the browser.")

    CANVA_BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CANVA_BROWSER_DATA),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto("https://www.canva.com/login", wait_until="domcontentloaded")

        logger.info("Please log in to Canva in the browser window.")
        logger.info("Once you are logged in, close the browser window.")

        # Wait until the user closes the browser
        try:
            page.wait_for_event("close", timeout=300_000)
        except PlaywrightTimeout:
            pass
        except Exception:
            pass

        context.close()

    logger.info("Canva browser session saved to canva_browser_data/")


def setup_canva_login():
    """
    Run the OAuth 2.0 authorization flow with PKCE, then open a browser
    for Canva login (needed for page visibility detection).
    """
    client_id = os.getenv("CANVA_CLIENT_ID")
    client_secret = os.getenv("CANVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.error(
            "CANVA_CLIENT_ID and CANVA_CLIENT_SECRET must be set in .env\n"
            "Create an integration at https://www.canva.dev to get these values.\n"
            "Set the redirect URL to: http://127.0.0.1:8420/oauth/callback"
        )
        return

    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{CANVA_AUTH_URL}?{urllib.parse.urlencode(params)}"

    # Start local server to capture the callback
    authorization_code = None
    received_state = None

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal authorization_code, received_state
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)

            if "code" in params:
                authorization_code = params["code"][0]
                received_state = params.get("state", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Authorization successful!</h1>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                    b"</body></html>"
                )
            else:
                error = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    f"<html><body><h1>Error: {error}</h1></body></html>".encode()
                )

        def log_message(self, format, *args):
            pass  # Suppress HTTP server logs

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
    server.timeout = 300  # 5 minutes

    print("\n" + "=" * 60)
    print("  Canva API Authorization")
    print("=" * 60)
    print(f"\nOpen this URL in your browser:\n")
    print(f"  {auth_url}\n")
    print("Waiting for authorization (up to 5 minutes)...")
    print("=" * 60 + "\n")

    # Try to open the browser automatically
    try:
        import webbrowser
        webbrowser.open(auth_url)
    except Exception:
        pass  # User will open manually

    # Wait for the callback
    while authorization_code is None:
        server.handle_request()

    server.server_close()

    # Verify state
    if received_state != state:
        logger.error("OAuth state mismatch - possible CSRF attack")
        return

    # Exchange authorization code for tokens
    logger.info("Exchanging authorization code for tokens...")
    resp = requests.post(
        CANVA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        logger.error(f"Token exchange failed: {resp.status_code} {resp.text}")
        return

    tokens = resp.json()
    tokens["obtained_at"] = time.time()
    _save_tokens(tokens)

    logger.info("Canva API authorization complete! Tokens saved.")

    # Also set up the browser session for page visibility detection
    logger.info("\n--- Now setting up Canva browser session ---")
    logger.info("This is needed to detect which pages are visible in your design.")
    setup_canva_browser()


# ---------------------------------------------------------------------------
# Detect visible pages via Playwright
# ---------------------------------------------------------------------------

def _detect_visible_pages(canva_url: str, headless: bool = True) -> list[int] | None:
    """
    Open the Canva editor and detect which pages are visible (not hidden).

    Returns a list of 1-indexed page numbers that are visible, or None if
    detection fails (in which case all pages will be exported).
    """
    design_id = _extract_design_id(canva_url)
    # Convert URL to edit mode
    edit_url = f"https://www.canva.com/design/{design_id}/edit"

    if not CANVA_BROWSER_DATA.exists():
        logger.warning(
            "No Canva browser session found. Run 'python main.py --setup-canva' "
            "to log in. Exporting all pages."
        )
        return None

    logger.info("Detecting visible pages via Canva editor...")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(CANVA_BROWSER_DATA),
                headless=headless,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            page.goto(edit_url, wait_until="domcontentloaded", timeout=60_000)

            # Wait for the editor to fully load (toolbar or canvas)
            page.wait_for_selector(
                '[class*="toolbar"], [class*="editor"], [data-testid*="editor"]',
                timeout=30_000,
            )
            # Give the page panel time to render
            page.wait_for_timeout(3000)

            # Try to open the page/grid panel if not already visible
            # Canva has a "Grid View" or page list in the bottom or side panel
            # Look for page thumbnails
            visible_pages = _read_page_visibility(page)

            context.close()
            return visible_pages

    except PlaywrightTimeout:
        logger.warning("Canva editor timed out. Will export all pages.")
        return None
    except Exception as e:
        logger.warning(f"Page detection failed: {e}. Will export all pages.")
        return None


def _read_page_visibility(page) -> list[int] | None:
    """
    Read page thumbnails from the Canva editor and determine which are visible.

    Canva marks hidden pages with aria-label containing 'Hidden' or a
    hide/show icon overlay on the page thumbnail. This function inspects
    the page grid/list to find visible (non-hidden) pages.
    """
    # Strategy 1: Look for page thumbnails in the bottom page navigator
    # Each page thumbnail is typically in a container with page number info
    page_items = page.query_selector_all(
        '[class*="page_thumbnail"], '
        '[class*="pageThumbnail"], '
        '[data-testid*="page-thumbnail"], '
        '[class*="grid_page"], '
        '[class*="gridPage"]'
    )

    if not page_items:
        # Strategy 2: Try the bottom page navigation bar
        # Click on the page grid button if it exists
        grid_btn = page.query_selector(
            '[aria-label*="Grid"], '
            '[aria-label*="grid"], '
            '[data-testid*="grid-view"], '
            '[class*="page_grid_button"], '
            '[aria-label*="pages"], '
            '[aria-label*="Pages"]'
        )
        if grid_btn:
            grid_btn.click()
            page.wait_for_timeout(2000)
            page_items = page.query_selector_all(
                '[class*="page_thumbnail"], '
                '[class*="pageThumbnail"], '
                '[data-testid*="page-thumbnail"], '
                '[class*="grid_page"], '
                '[class*="gridPage"]'
            )

    if not page_items:
        # Strategy 3: Look for any thumbnail-like containers in the footer/nav
        page_items = page.query_selector_all(
            '#pages-scrubber [role="listitem"], '
            '[class*="scrubber"] [role="listitem"], '
            '[class*="PageScrubber"] [role="listitem"], '
            '[class*="footer"] [role="listitem"]'
        )

    if not page_items:
        logger.warning("Could not locate page thumbnails in the editor.")
        # Fallback: try to extract from the page using JavaScript
        result = page.evaluate("""
            () => {
                // Look for elements with 'hidden' indicators
                const allEls = document.querySelectorAll('[aria-label*="Page"]');
                if (allEls.length === 0) return null;

                const pages = [];
                allEls.forEach((el, i) => {
                    const label = el.getAttribute('aria-label') || '';
                    const isHidden = label.toLowerCase().includes('hidden') ||
                                     el.querySelector('[aria-label*="Hidden"]') !== null ||
                                     el.querySelector('[aria-label*="hidden"]') !== null;
                    pages.push({ index: i + 1, hidden: isHidden, label: label });
                });
                return pages.length > 0 ? pages : null;
            }
        """)

        if result:
            visible = [p["index"] for p in result if not p["hidden"]]
            total = len(result)
            logger.info(f"Detected {len(visible)} visible pages out of {total} total (JS fallback)")
            return visible if visible else None

        logger.warning("Page visibility detection failed. Will export all pages.")
        return None

    # Process found page items
    total = len(page_items)
    visible_pages = []

    for i, item in enumerate(page_items, 1):
        # Check for hidden indicators
        is_hidden = False

        # Check aria-label for 'hidden'
        aria_label = item.get_attribute("aria-label") or ""
        if "hidden" in aria_label.lower():
            is_hidden = True

        # Check for hidden icon overlay (eye-slash icon)
        if not is_hidden:
            hidden_indicator = item.query_selector(
                '[aria-label*="Hidden"], '
                '[aria-label*="hidden"], '
                '[class*="hidden"], '
                '[class*="Hidden"], '
                '[data-testid*="hidden"]'
            )
            if hidden_indicator:
                is_hidden = True

        # Check opacity (hidden pages often have reduced opacity)
        if not is_hidden:
            opacity = item.evaluate("el => window.getComputedStyle(el).opacity")
            if opacity and float(opacity) < 0.5:
                is_hidden = True

        if not is_hidden:
            visible_pages.append(i)

    logger.info(f"Detected {len(visible_pages)} visible pages out of {total} total")

    if len(visible_pages) == 0:
        logger.warning("All pages appear hidden — exporting all as fallback.")
        return None

    return visible_pages


# ---------------------------------------------------------------------------
# Export design pages via API
# ---------------------------------------------------------------------------

def _create_export_job(access_token: str, design_id: str, pages: list[int] | None = None) -> str:
    """Create an export job and return the job ID.

    Args:
        access_token: Valid Canva API access token.
        design_id: The Canva design ID.
        pages: Optional list of 1-indexed page numbers to export.
               If None, all pages are exported.
    """
    format_opts = {
        "type": "jpg",
        "quality": 100,
    }
    if pages:
        format_opts["pages"] = pages
        logger.info(f"Exporting pages: {pages}")
    else:
        logger.info("Exporting all pages")

    resp = requests.post(
        CANVA_EXPORT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "design_id": design_id,
            "format": format_opts,
        },
    )

    if resp.status_code == 401:
        raise RuntimeError(
            "Canva API returned 401 Unauthorized. "
            "Run 'python main.py --setup-canva' to re-authorize."
        )

    if not resp.ok:
        logger.error(f"Export API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    data = resp.json()
    job_id = data["job"]["id"]
    logger.info(f"Export job created: {job_id}")
    return job_id


def _poll_export_job(access_token: str, job_id: str, timeout: int = 120) -> list[str]:
    """
    Poll the export job until it completes.
    Returns a list of download URLs.
    """
    url = f"{CANVA_EXPORT_URL}/{job_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    start_time = time.time()
    poll_interval = 2  # Start with 2 seconds

    while time.time() - start_time < timeout:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        status = data["job"]["status"]

        if status == "success":
            raw_urls = data["job"]["urls"]
            # URLs may be plain strings or dicts with "url" key
            if raw_urls and isinstance(raw_urls[0], str):
                urls = raw_urls
            else:
                urls = [u["url"] for u in raw_urls]
            logger.info(f"Export complete: {len(urls)} file(s) ready")
            return urls
        elif status == "failed":
            error = data["job"].get("error", {})
            raise RuntimeError(f"Export job failed: {error}")
        else:
            logger.info(f"Export in progress... (waiting {poll_interval}s)")
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 10)  # Exponential backoff, max 10s

    raise TimeoutError(f"Export job did not complete within {timeout} seconds")


def _download_files(urls: list[str]) -> list[str]:
    """Download exported files and return local paths."""
    extract_dir = DOWNLOADS_DIR / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []

    for i, url in enumerate(urls, 1):
        resp = requests.get(url, stream=True)
        resp.raise_for_status()

        # Determine filename from Content-Disposition or URL
        content_type = resp.headers.get("Content-Type", "")
        if "zip" in content_type or url.endswith(".zip"):
            # Multi-page export as ZIP
            zip_path = DOWNLOADS_DIR / f"export_{i}.zip"
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Downloaded ZIP: {zip_path}")

            # Extract ZIP
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            os.remove(zip_path)

            # Collect extracted images
            image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
            for f in sorted(extract_dir.iterdir()):
                if f.suffix.lower() in image_extensions:
                    image_paths.append(str(f))
        else:
            # Single image file
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"
            filename = f"page-{i}{ext}"
            file_path = extract_dir / filename
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Downloaded: {file_path}")
            image_paths.append(str(file_path))

    return image_paths


def download_pages(canva_url: str, headless: bool = True) -> list[str]:
    """
    Download visible pages from a Canva design.

    Uses Playwright to detect which pages are visible (not hidden) in the
    editor, then exports only those pages via the Canva Connect API.

    Args:
        canva_url: Canva design URL (view or edit link)
        headless: Whether to run the detection browser in headless mode

    Returns:
        List of file paths to downloaded images
    """
    _clean_downloads()

    design_id = _extract_design_id(canva_url)
    logger.info(f"Design ID: {design_id}")

    # Step 1: Detect which pages are visible via Playwright
    visible_pages = _detect_visible_pages(canva_url, headless=headless)
    if visible_pages:
        logger.info(f"Visible pages: {visible_pages}")
    else:
        logger.info("Could not detect page visibility — exporting all pages")

    # Step 2: Get valid access token (auto-refreshes if expired)
    access_token = _get_access_token()

    # Step 3: Create export job (only visible pages if detected)
    job_id = _create_export_job(access_token, design_id, pages=visible_pages)

    # Step 4: Poll until complete
    download_urls = _poll_export_job(access_token, job_id)

    # Step 5: Download files
    image_paths = _download_files(download_urls)

    logger.info(f"Downloaded {len(image_paths)} page(s)")
    return image_paths


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if "--setup" in sys.argv:
        from dotenv import load_dotenv
        load_dotenv()
        setup_canva_login()
    elif len(sys.argv) >= 2:
        from dotenv import load_dotenv
        load_dotenv()
        url = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        if url:
            paths = download_pages(url[0])
            for p in paths:
                print(p)
        else:
            print("Usage: python canva_downloader.py <canva_url>")
    else:
        print("Usage: python canva_downloader.py <canva_url>")
        print("       python canva_downloader.py --setup")

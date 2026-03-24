"""
Canva Page Downloader (API-based)

Uses the Canva Connect API to export all pages of a design as JPG images.
Authenticates via OAuth 2.0 with PKCE. Tokens are persisted to
canva_tokens.json for reuse across runs.

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

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
TOKEN_FILE = Path(__file__).parent / "canva_tokens.json"

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
        shutil.rmtree(DOWNLOADS_DIR)
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

def setup_canva_login():
    """
    Run the OAuth 2.0 authorization flow with PKCE.
    Opens the user's browser to Canva for authorization, then captures
    the callback on a local HTTP server.
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


# ---------------------------------------------------------------------------
# Export design pages via API
# ---------------------------------------------------------------------------

def _create_export_job(access_token: str, design_id: str) -> str:
    """Create an export job and return the job ID."""
    resp = requests.post(
        CANVA_EXPORT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "design_id": design_id,
            "format": {
                "type": "jpg",
            },
        },
    )

    if resp.status_code == 401:
        raise RuntimeError(
            "Canva API returned 401 Unauthorized. "
            "Run 'python main.py --setup-canva' to re-authorize."
        )

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
            urls = [u["url"] for u in data["job"]["urls"]]
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
    Download all pages from a Canva design using the Canva Connect API.

    Exports the design as JPG via the API, downloads the resulting files,
    and returns a list of local image paths.

    Args:
        canva_url: Canva design URL (view or edit link)
        headless: Ignored (kept for backward compatibility with main.py)

    Returns:
        List of file paths to downloaded images
    """
    _clean_downloads()

    design_id = _extract_design_id(canva_url)
    logger.info(f"Design ID: {design_id}")

    # Get valid access token (auto-refreshes if expired)
    access_token = _get_access_token()

    # Create export job
    job_id = _create_export_job(access_token, design_id)

    # Poll until complete
    download_urls = _poll_export_job(access_token, job_id)

    # Download files
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

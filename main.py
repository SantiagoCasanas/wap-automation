#!/usr/bin/env python3
"""
Canva to WhatsApp Status Automation

Logs into Canva, downloads every page of a design as JPG (x2, quality 100),
then posts each image as a WhatsApp status.

Usage:
    python main.py                  # Run with .env config
    python main.py --url <URL>      # Override Canva URL
    python main.py --setup-canva    # First-time Canva login
    python main.py --setup-wap      # First-time WhatsApp Web login
    python main.py --download-only  # Only download images (skip posting)
    python main.py --list-pages     # List visible (non-hidden) pages
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

from canva_downloader import download_pages, setup_canva_login, get_visible_pages
from wap_status_poster import post_statuses, setup_login as setup_wap_login

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("automation.log"),
    ],
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Canva to WhatsApp Status Automation"
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Canva design URL (overrides .env)",
    )
    parser.add_argument(
        "--setup-canva",
        action="store_true",
        help="Authorize Canva API access (one-time OAuth flow)",
    )
    parser.add_argument(
        "--setup-wap",
        action="store_true",
        help="Open WhatsApp Web for first-time login",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download Canva images, skip WhatsApp posting",
    )
    parser.add_argument(
        "--list-pages",
        action="store_true",
        help="List visible (non-hidden) pages of the Canva design",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browsers in visible mode (for debugging)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Setup flows
    if args.setup_canva:
        logger.info("=== Canva Login Setup ===")
        setup_canva_login()
        return

    if args.setup_wap:
        logger.info("=== WhatsApp Web Setup ===")
        setup_wap_login()
        return

    # Get Canva URL
    canva_url = args.url or os.getenv("CANVA_URL")
    if not canva_url:
        logger.error("No Canva URL provided. Set CANVA_URL in .env or use --url")
        sys.exit(1)

    # List pages command
    if args.list_pages:
        logger.info(f"=== Visible Pages for: {canva_url} ===")
        try:
            pages = get_visible_pages(canva_url)
            logger.info(f"Total visible pages: {len(pages)}")
            logger.info(f"Page indices: {pages}")
        except Exception as e:
            logger.error(f"Failed to get pages: {e}")
            sys.exit(1)
        return

    # Config
    headless = not args.no_headless and os.getenv("HEADLESS", "true").lower() == "true"
    delay = int(os.getenv("DELAY_BETWEEN_STATUSES", "5"))

    logger.info("=== Canva to WhatsApp Status Automation ===")
    logger.info(f"Canva URL: {canva_url}")
    logger.info(f"Headless: {headless}")

    # Step 1: Download Canva pages
    logger.info("--- Step 1: Downloading Canva pages ---")
    try:
        image_paths = download_pages(canva_url, headless=headless)
    except Exception as e:
        logger.error(f"Failed to download Canva pages: {e}")
        sys.exit(1)

    if not image_paths:
        logger.error("No images downloaded. Check the Canva URL and your login session.")
        sys.exit(1)

    logger.info(f"Downloaded {len(image_paths)} page(s)")

    # Step 2: Post to WhatsApp status
    if args.download_only:
        logger.info("--download-only flag set, skipping WhatsApp posting")
        logger.info("Downloaded images:")
        for p in image_paths:
            logger.info(f"  {p}")
        return

    logger.info("--- Step 2: Posting to WhatsApp Status ---")
    try:
        results = post_statuses(
            image_paths,
            headless=headless,
            delay=delay,
        )
    except Exception as e:
        logger.error(f"Failed to post statuses: {e}")
        sys.exit(1)

    # Summary
    logger.info("=== Done ===")
    logger.info(f"Posted: {results['posted']} status(es)")
    if results["failed"]:
        logger.warning(f"Failed: {len(results['failed'])} image(s)")
        for f in results["failed"]:
            logger.warning(f"  - {f}")


if __name__ == "__main__":
    main()

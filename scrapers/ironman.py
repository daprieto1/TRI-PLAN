from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from scrapers.config import (
    IRONMAN_RESULTS_URL,
    DATA_RAW_DIR,
    HTML_DIR,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_TIMEOUT,
    ensure_dirs,
    validate_credentials,
)
from scrapers.auth import authenticate
from scrapers.models import (
    RaceResult,
    RaceSplit,
    parse_time_to_seconds,
    parse_float,
    parse_int,
    save_results,
)
from scrapers.parsers import parse_race_list, parse_race_detail, click_race_row

logger = logging.getLogger(__name__)

RACES_DIR = DATA_RAW_DIR / "races"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape personal IRONMAN race results from my.ironman.com"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode (default: headed for debugging)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discovery mode: save screenshot + HTML of the results page, then exit",
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="Pause for manual login (useful if CAPTCHA is triggered)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Delay between race detail page requests (default: {DEFAULT_DELAY_SECONDS}s)",
    )
    parser.add_argument(
        "--race-index",
        type=int,
        default=None,
        help="Only scrape a specific race by index (0-based)",
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Only scrape the race list, skip detail pages",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def _safe_filename(name: str) -> str:
    """Create a filesystem-safe filename from a race name."""
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()


def run_discover(page):
    """Discovery mode: save page screenshot and HTML for selector development."""
    logger.info("Discovery mode: capturing results page...")

    screenshot_path = DATA_RAW_DIR / "discover_results.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    logger.info(f"Screenshot saved to {screenshot_path}")

    html_path = DATA_RAW_DIR / "discover_results.html"
    html_content = page.content()
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML saved to {html_path}")

    logger.info(f"Page URL: {page.url}")
    logger.info(f"Page title: {page.title()}")
    logger.info(f"HTML size: {len(html_content)} chars")

    print(f"\nDiscovery complete. Inspect the files in {DATA_RAW_DIR}:")
    print(f"  Screenshot: {screenshot_path}")
    print(f"  HTML:       {html_path}")


def _save_race_files(result: RaceResult, page, safe_name: str):
    """Save per-race JSON, HTML, and PNG."""
    race_dir = RACES_DIR / safe_name
    race_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = race_dir / f"{safe_name}.json"
    with open(json_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    logger.info(f"  JSON saved to {json_path}")

    # Screenshot
    png_path = race_dir / f"{safe_name}.png"
    page.screenshot(path=str(png_path), full_page=True)
    logger.info(f"  Screenshot saved to {png_path}")

    # Raw HTML
    html_path = race_dir / f"{safe_name}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page.content())
    logger.info(f"  HTML saved to {html_path}")


def _navigate_back_to_results(page):
    """Navigate back to the results list page."""
    page.go_back(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    # Wait for the DataGrid to reappear
    try:
        page.locator(".MuiDataGrid-root").wait_for(state="visible", timeout=10_000)
    except Exception:
        # Fallback: navigate directly
        logger.warning("DataGrid not found after go_back, navigating directly...")
        page.goto(IRONMAN_RESULTS_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        page.locator(".MuiDataGrid-root").wait_for(state="visible", timeout=10_000)


def scrape_races(page, args) -> list[RaceResult]:
    """Main scraping flow: parse race list, click into each race, scrape details."""
    results: list[RaceResult] = []
    RACES_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Parse race list
    logger.info("Parsing race list...")
    race_list = parse_race_list(page)

    if not race_list:
        logger.error(
            "No races found on the results page. "
            "Run with --discover to inspect the page structure."
        )
        page.screenshot(path=str(DATA_RAW_DIR / "error_no_races.png"), full_page=True)
        return results

    logger.info(f"Found {len(race_list)} races:")
    for i, race in enumerate(race_list):
        logger.info(f"  [{i}] {race.get('race_name', '?')} — {race.get('race_date', '?')} — {race.get('overall_time', '?')}")

    # Filter to specific race if requested
    if args.race_index is not None:
        if args.race_index >= len(race_list):
            logger.error(f"Race index {args.race_index} out of range (0-{len(race_list)-1})")
            return results
        race_list = [race_list[args.race_index]]
        logger.info(f"Scraping only race index {args.race_index}")

    # Step 2: Click into each race and scrape details
    for i, race_info in enumerate(race_list):
        race_name = race_info.get("race_name", f"unknown_race_{i}")
        row_index = race_info.get("row_index", i)
        safe_name = _safe_filename(race_name)
        logger.info(f"\n--- [{i+1}/{len(race_list)}] {race_name} ---")

        try:
            result = RaceResult(
                race_name=race_name,
                race_date=race_info.get("race_date", ""),
                age_group=race_info.get("age_group", ""),
                overall_time_seconds=parse_time_to_seconds(race_info.get("overall_time", "")),
                points=parse_float(race_info.get("points", "")),
            )

            if not args.skip_details:
                # Click into the race detail
                logger.info(f"Clicking race row {row_index}...")
                click_race_row(page, row_index)
                logger.info(f"Detail page loaded: {page.url}")
                result.detail_url = page.url

                # Parse detail page
                detail = parse_race_detail(page)

                result.bib = detail.get("bib")
                result.division = detail.get("division")
                result.country = detail.get("country")
                result.designation = detail.get("designation")
                result.div_rank = detail.get("div_rank")
                result.gender_rank = detail.get("gender_rank")
                result.overall_rank = detail.get("overall_rank")
                result.splits = detail.get("splits", [])

                if detail.get("points"):
                    result.points = parse_float(detail["points"])

                # Save per-race files (JSON, PNG, HTML)
                _save_race_files(result, page, safe_name)

                # Navigate back to results list
                logger.info("Navigating back to results list...")
                _navigate_back_to_results(page)

                # Delay before next race
                if i < len(race_list) - 1:
                    logger.info(f"Waiting {args.delay}s before next race...")
                    time.sleep(args.delay)

            results.append(result)
            logger.info(f"Successfully scraped: {race_name}")

        except Exception as e:
            logger.error(f"Failed to scrape race '{race_name}': {e}")
            try:
                error_path = DATA_RAW_DIR / f"error_{i}.png"
                page.screenshot(path=str(error_path))
                logger.info(f"Error screenshot saved to {error_path}")
            except Exception:
                pass

            # Try to get back to results page
            try:
                _navigate_back_to_results(page)
            except Exception:
                logger.error("Failed to navigate back to results page")
                break

    return results


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)
    ensure_dirs()

    if not args.manual_login:
        ok, msg = validate_credentials()
        if not ok:
            logger.error(msg)
            sys.exit(1)

    results: list[RaceResult] = []

    try:
        with sync_playwright() as pw:
            context, page = authenticate(
                pw,
                headless=args.headless,
                manual_login=args.manual_login,
            )

            try:
                if args.discover:
                    run_discover(page)
                    return

                results = scrape_races(page, args)
            finally:
                context.close()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        if results:
            save_results(results, DATA_RAW_DIR)


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging

from playwright.sync_api import Page, BrowserContext, sync_playwright, Playwright

from scrapers.config import (
    IRONMAN_EMAIL,
    IRONMAN_PASSWORD,
    IRONMAN_LOGIN_URL,
    IRONMAN_RESULTS_URL,
    STATE_FILE,
    STATE_DIR,
    LOGIN_TIMEOUT,
    DEFAULT_TIMEOUT,
)

logger = logging.getLogger(__name__)


def _is_on_results_page(page: Page) -> bool:
    """Check if the page is showing the results content (not redirected to login)."""
    url = page.url.lower()
    return "results" in url and "login" not in url


def _accept_cookies(page: Page):
    """Wait for the cookie consent banner to appear, then accept it."""
    # Wait for the Accept All button to become visible (up to 10s)
    try:
        accept_btn = page.get_by_role("button", name="Accept All")
        accept_btn.wait_for(state="visible", timeout=10_000)
        accept_btn.click()
        logger.info("Cookie consent accepted.")
        page.wait_for_timeout(1000)
    except Exception:
        logger.debug("No cookie consent banner appeared within 10s, continuing.")


def _do_login(page: Page, manual: bool = False):
    """Perform the login flow."""
    logger.info("Navigating to login page...")
    page.goto(IRONMAN_LOGIN_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
    # Don't wait for networkidle — SPA login pages often never reach it
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        logger.debug("networkidle not reached on login page (normal for SPAs)")

    # Dismiss cookie consent banner if present
    _accept_cookies(page)

    if manual:
        print("\n" + "=" * 60)
        print("MANUAL LOGIN MODE")
        print("=" * 60)
        print("A browser window should be open on the IRONMAN login page.")
        print("1. Log in with your credentials")
        print("2. Navigate to your results page")
        print("The script will detect when you reach the results page.")
        print("=" * 60 + "\n")

        # Poll until the page URL contains "results"
        import time as _time
        timeout_sec = LOGIN_TIMEOUT / 1000
        start = _time.time()
        while _time.time() - start < timeout_sec:
            try:
                url = page.url
                if _is_on_results_page(page):
                    logger.info(f"Detected results page: {url}")
                    # Give the page a moment to fully render
                    _time.sleep(2)
                    return
            except Exception:
                break  # Page/browser was closed
            _time.sleep(1)

        raise RuntimeError(
            "Timed out waiting for manual login. "
            f"Last URL: {page.url}"
        )
    else:
        logger.info("Filling login form (two-step flow)...")

        # Step 1: Fill email and click NEXT
        email_filled = False
        email_selectors = [
            lambda: page.get_by_label("Email"),
            lambda: page.locator("input[type='email']"),
            lambda: page.locator("input[name='email']"),
            lambda: page.locator("#email"),
            lambda: page.locator("input[placeholder*='Email' i]"),
        ]
        for selector_fn in email_selectors:
            try:
                el = selector_fn()
                if el.count() > 0:
                    el.first.fill(IRONMAN_EMAIL, timeout=DEFAULT_TIMEOUT)
                    email_filled = True
                    break
            except Exception:
                continue

        if not email_filled:
            raise RuntimeError(
                "Could not find email input field. Run with --discover to inspect the page, "
                "or use --manual-login."
            )

        # Click NEXT button
        next_clicked = False
        next_selectors = [
            lambda: page.get_by_role("button", name="Next"),
            lambda: page.get_by_role("button", name="NEXT"),
            lambda: page.locator("button[type='submit']"),
        ]
        for selector_fn in next_selectors:
            try:
                el = selector_fn()
                if el.count() > 0:
                    el.first.click(timeout=DEFAULT_TIMEOUT)
                    next_clicked = True
                    break
            except Exception:
                continue

        if not next_clicked:
            raise RuntimeError(
                "Could not find NEXT button. Run with --discover to inspect the page, "
                "or use --manual-login."
            )

        # Step 2: Wait for the password field to appear after clicking NEXT
        logger.info("Waiting for password field to appear...")
        password_el = page.locator("input[type='password']")
        try:
            password_el.wait_for(state="visible", timeout=15_000)
        except Exception:
            raise RuntimeError(
                "Password field did not appear after clicking NEXT. "
                "Run with --discover to inspect the page, or use --manual-login."
            )

        password_el.fill(IRONMAN_PASSWORD, timeout=DEFAULT_TIMEOUT)
        logger.info("Password filled.")

        # Click Sign In button
        sign_in_clicked = False
        button_selectors = [
            lambda: page.get_by_role("button", name="Sign In"),
            lambda: page.get_by_role("button", name="SIGN IN"),
            lambda: page.get_by_role("button", name="Log In"),
            lambda: page.get_by_role("button", name="Login"),
            lambda: page.locator("button[type='submit']"),
        ]
        for selector_fn in button_selectors:
            try:
                el = selector_fn()
                if el.count() > 0:
                    el.first.click(timeout=DEFAULT_TIMEOUT)
                    sign_in_clicked = True
                    break
            except Exception:
                continue

        if not sign_in_clicked:
            raise RuntimeError(
                "Could not find sign-in button. Run with --discover to inspect the page, "
                "or use --manual-login."
            )

    # Wait for login to complete (page navigates away from signIn)
    logger.info("Waiting for login to complete...")
    try:
        page.wait_for_url(lambda url: "signIn" not in url and "login" not in url.lower(), timeout=LOGIN_TIMEOUT)
    except Exception:
        screenshot_path = STATE_DIR / "login_failed.png"
        page.screenshot(path=str(screenshot_path))
        raise RuntimeError(
            f"Login did not complete. Current URL: {page.url}. "
            f"Screenshot saved to {screenshot_path}. "
            "This might be a CAPTCHA — try --manual-login."
        )

    logger.info(f"Login successful. Current URL: {page.url}")

    # Navigate to Results page if not already there
    if not _is_on_results_page(page):
        logger.info("Clicking 'Results' to navigate to race results...")
        try:
            results_link = page.get_by_role("link", name="Results")
            results_link.wait_for(state="visible", timeout=10_000)
            results_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            logger.info(f"Navigated to results: {page.url}")
        except Exception:
            # Fallback: navigate directly
            logger.info("Could not find Results link, navigating directly...")
            page.goto(IRONMAN_RESULTS_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass


def _save_state(context: BrowserContext):
    """Save browser state for session reuse."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STATE_FILE))
    logger.info(f"Session state saved to {STATE_FILE}")


def authenticate(
    playwright: Playwright,
    headless: bool = True,
    manual_login: bool = False,
) -> tuple[BrowserContext, Page]:
    """
    Authenticate with IRONMAN and return (context, page) on the results page.

    Tries saved session state first; falls back to fresh login.
    """
    browser = playwright.chromium.launch(headless=headless)

    # Try existing session state
    if STATE_FILE.exists() and not manual_login:
        logger.info("Found saved session state, attempting to reuse...")
        context = browser.new_context(storage_state=str(STATE_FILE))
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT)

        try:
            page.goto(IRONMAN_RESULTS_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            if _is_on_results_page(page):
                logger.info("Session state is valid, reusing existing session.")
                return context, page
            else:
                logger.info("Session expired, performing fresh login...")
        except Exception as e:
            logger.warning(f"Failed to reuse session: {e}")

        page.close()
        context.close()

    # Fresh login
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT)

    _do_login(page, manual=manual_login)

    # Save state for next time
    _save_state(context)

    # Navigate to results if not already there
    if not _is_on_results_page(page):
        page.goto(IRONMAN_RESULTS_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass

    return context, page

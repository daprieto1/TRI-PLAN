import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Credentials
IRONMAN_EMAIL = os.getenv("IRONMAN_EMAIL", "")
IRONMAN_PASSWORD = os.getenv("IRONMAN_PASSWORD", "")

# Strava API
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN", "")

# URLs
IRONMAN_LOGIN_URL = "https://my.ironman.com/signIn"
IRONMAN_RESULTS_URL = "https://my.ironman.com/results"

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
HTML_DIR = DATA_RAW_DIR / "html"
STATE_DIR = PROJECT_ROOT / "playwright-state"
STATE_FILE = STATE_DIR / "state.json"

# Timeouts (milliseconds)
DEFAULT_TIMEOUT = 30_000
LOGIN_TIMEOUT = 300_000  # 5 minutes for manual login

# Scraping
DEFAULT_DELAY_SECONDS = 3


def ensure_dirs():
    """Create output directories if they don't exist."""
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def validate_credentials():
    """Check that credentials are set. Returns (ok, message)."""
    if not IRONMAN_EMAIL or IRONMAN_EMAIL == "your_email@example.com":
        return False, "IRONMAN_EMAIL not set. Copy .env.example to .env and fill in credentials."
    if not IRONMAN_PASSWORD or IRONMAN_PASSWORD == "your_password":
        return False, "IRONMAN_PASSWORD not set. Copy .env.example to .env and fill in credentials."
    return True, ""

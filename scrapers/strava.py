"""Download Strava activities for the last N months."""

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from pathlib import Path

import requests

from scrapers.config import (
    DATA_RAW_DIR,
    STRAVA_CLIENT_ID,
    STRAVA_CLIENT_SECRET,
    STRAVA_REFRESH_TOKEN,
)

logger = logging.getLogger(__name__)

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

ACTIVITY_FIELDS = [
    "id", "name", "type", "sport_type", "start_date", "start_date_local",
    "distance", "moving_time", "elapsed_time", "total_elevation_gain",
    "average_speed", "max_speed", "average_heartrate", "max_heartrate",
    "average_watts", "max_watts", "weighted_average_watts", "kilojoules",
    "suffer_score", "average_cadence", "gear_id", "workout_type",
    "has_heartrate", "elev_high", "elev_low",
]


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange refresh token for a fresh access token."""
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    logger.info("Access token obtained, expires at %s",
                datetime.fromtimestamp(data["expires_at"], tz=timezone.utc).isoformat())
    return data["access_token"]


def fetch_activities(access_token: str, after_epoch: int) -> list[dict]:
    """Fetch all activities after the given epoch timestamp, handling pagination."""
    activities = []
    page = 1
    per_page = 200

    while True:
        logger.info("Fetching page %d...", page)
        resp = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after_epoch, "page": page, "per_page": per_page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        logger.info("  Got %d activities (total: %d)", len(batch), len(activities))
        if len(batch) < per_page:
            break
        page += 1

    return activities


def flatten_activity(activity: dict) -> dict:
    """Extract relevant fields from a raw Strava activity."""
    return {field: activity.get(field) for field in ACTIVITY_FIELDS}


def save_results(activities: list[dict], output_dir: Path):
    """Save activities as JSON (raw) and CSV (flat)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "strava_activities.json"
    with open(json_path, "w") as f:
        json.dump(activities, f, indent=2, default=str)
    logger.info("Saved %d activities to %s", len(activities), json_path)

    flat = [flatten_activity(a) for a in activities]
    if flat:
        csv_path = output_dir / "strava_activities.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ACTIVITY_FIELDS)
            writer.writeheader()
            writer.writerows(flat)
        logger.info("Saved CSV to %s", csv_path)


def main():
    parser = argparse.ArgumentParser(description="Download Strava activities")
    parser.add_argument("--months", type=int, default=6,
                        help="Number of months of history to download (default: 6)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help=f"Output directory (default: {DATA_RAW_DIR})")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET or not STRAVA_REFRESH_TOKEN:
        logger.error("Missing Strava credentials. Set STRAVA_CLIENT_ID, "
                      "STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN in .env")
        sys.exit(1)

    cutoff = datetime.now(tz=timezone.utc) - relativedelta(months=args.months)
    after_epoch = int(cutoff.timestamp())
    logger.info("Fetching activities since %s (%d months)", cutoff.date().isoformat(), args.months)

    access_token = get_access_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN)
    activities = fetch_activities(access_token, after_epoch)
    logger.info("Fetched %d activities total", len(activities))

    output_dir = args.output_dir or DATA_RAW_DIR
    save_results(activities, output_dir)


if __name__ == "__main__":
    main()

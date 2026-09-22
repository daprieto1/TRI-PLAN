from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


def parse_time_to_seconds(time_str: str) -> int | None:
    """Parse HH:MM:SS or MM:SS or H:MM:SS to total seconds. Returns None if unparseable."""
    if not time_str:
        return None
    time_str = time_str.strip().replace("—", "").replace("-", "").strip()
    if not time_str:
        return None

    # Try HH:MM:SS or H:MM:SS
    match = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})$", time_str)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return h * 3600 + m * 60 + s

    # Try MM:SS
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if match:
        m, s = int(match.group(1)), int(match.group(2))
        return m * 60 + s

    return None


def format_seconds(seconds: int | None) -> str:
    """Format seconds as HH:MM:SS for display."""
    if seconds is None:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def parse_date(date_str: str) -> str:
    """Try to normalize a date string to ISO 8601 YYYY-MM-DD."""
    if not date_str:
        return ""
    date_str = date_str.strip()

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    # Common formats from IRONMAN site
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str  # Return as-is if we can't parse


def parse_int(value: str) -> int | None:
    """Parse an integer from a string, returning None if unparseable."""
    if not value:
        return None
    value = value.strip().replace(",", "")
    try:
        return int(value)
    except ValueError:
        return None


def parse_float(value: str) -> float | None:
    """Parse a float from a string, returning None if unparseable."""
    if not value:
        return None
    value = value.strip().replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


@dataclass
class RaceSplit:
    name: str              # "swim", "t1", "bike", "t2", "run"
    time_seconds: int | None

    def to_dict(self) -> dict:
        return {"name": self.name, "time_seconds": self.time_seconds}


@dataclass
class RaceResult:
    race_name: str
    race_date: str                    # ISO 8601 "YYYY-MM-DD"
    country: str = ""
    age_group: str = ""               # "M30-34"
    overall_time_seconds: int | None = None
    points: float | None = None
    location: str | None = None
    bib: str | None = None
    division: str | None = None
    div_rank: int | None = None
    gender_rank: int | None = None
    overall_rank: int | None = None
    designation: str | None = None
    splits: list[RaceSplit] = field(default_factory=list)
    detail_url: str | None = None
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["splits"] = [s.to_dict() for s in self.splits]
        # Add formatted time for readability
        d["overall_time_display"] = format_seconds(self.overall_time_seconds)
        return d

    def to_flat_dict(self) -> dict:
        """Flatten splits into columns for CSV export."""
        d = self.to_dict()
        del d["splits"]
        d["overall_time_display"] = format_seconds(self.overall_time_seconds)
        for split in self.splits:
            key = f"{split.name}_seconds"
            d[key] = split.time_seconds
            d[f"{split.name}_display"] = format_seconds(split.time_seconds)
        return d


def save_results(results: list[RaceResult], output_dir: Path):
    """Save results as both JSON and CSV."""
    if not results:
        print("No results to save.")
        return

    # JSON
    json_path = output_dir / "ironman_results.json"
    data = [r.to_dict() for r in results]
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(results)} results to {json_path}")

    # CSV
    csv_path = output_dir / "ironman_results.csv"
    flat = [r.to_flat_dict() for r in results]
    # Collect all keys (splits may vary)
    all_keys: list[str] = []
    for row in flat:
        for k in row:
            if k not in all_keys:
                all_keys.append(k)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat)
    print(f"Saved {len(results)} results to {csv_path}")

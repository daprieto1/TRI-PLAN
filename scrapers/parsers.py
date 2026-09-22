from __future__ import annotations

import logging
import re

from playwright.sync_api import Page

from scrapers.models import (
    RaceResult,
    RaceSplit,
    parse_time_to_seconds,
    parse_date,
    parse_int,
    parse_float,
)

logger = logging.getLogger(__name__)

# Standard IRONMAN split names (normalized to lowercase)
SPLIT_NAMES = ["swim", "bike", "run", "transitions"]


def parse_race_list(page: Page) -> list[dict]:
    """
    Parse the race list from the MUI DataGrid on the results page.

    Each row is a div[role="row"] inside the MUI DataGrid with cells containing:
    - Country flag
    - Race name (data-field="_wtc_eventid_value_formatted")
    - Date (data-field="wtc_eventdate_formatted")
    - Age Group (data-field="_wtc_agegroupid_value_formatted")
    - Overall Finish Time (data-field="wtc_finishtimeformatted")
    - Points
    - Navigate chevron (data-field="record")

    Returns a list of dicts with keys:
    - race_name, race_date, age_group, overall_time, points, row_index
    """
    races = []

    # Wait for the data grid to be visible
    try:
        page.locator(".MuiDataGrid-root").wait_for(state="visible", timeout=10_000)
    except Exception:
        logger.error("MUI DataGrid not found on page.")
        return races

    rows = page.locator("div.MuiDataGrid-row")
    count = rows.count()
    logger.info(f"Found {count} race rows in DataGrid")

    for i in range(count):
        row = rows.nth(i)
        try:
            row_index = row.get_attribute("data-rowindex")

            # Extract text from each cell by data-field
            race_name = _cell_text(row, "_wtc_eventid_value_formatted")
            race_date = _cell_text(row, "wtc_eventdate_formatted")
            age_group = _cell_text(row, "_wtc_agegroupid_value_formatted")
            overall_time = _cell_text(row, "wtc_finishtimeformatted")
            points = _cell_text(row, "wtc_points") or _cell_text(row, "points")

            # Points might be in a different field — try getting from the row text
            if not points:
                row_text = row.inner_text(timeout=5000)
                points_match = re.search(r"\b(\d{3,4})\b", row_text)
                if points_match and overall_time:
                    # Only grab it if it looks like a points value (not part of time)
                    candidate = points_match.group(1)
                    if candidate not in overall_time:
                        points = candidate

            race = {
                "race_name": race_name,
                "race_date": parse_date(race_date),
                "age_group": age_group,
                "overall_time": overall_time,
                "points": points,
                "row_index": int(row_index) if row_index else i,
            }
            if race_name:
                races.append(race)
                logger.debug(f"  [{i}] {race_name} — {race_date} — {overall_time}")

        except Exception as e:
            logger.warning(f"Failed to parse row {i}: {e}")

    return races


def _cell_text(row, data_field: str) -> str:
    """Extract visible text from a MUI DataGrid cell by its data-field attribute."""
    try:
        cell = row.locator(f"div[data-field='{data_field}']")
        if cell.count() > 0:
            # Get text from <p> tags inside (MUI wraps values in Typography <p>)
            p_tags = cell.locator("p")
            if p_tags.count() > 0:
                texts = []
                for j in range(p_tags.count()):
                    t = p_tags.nth(j).inner_text(timeout=3000).strip()
                    if t:
                        texts.append(t)
                return " ".join(texts)
            # Fallback to cell text
            return cell.inner_text(timeout=3000).strip()
    except Exception:
        pass
    return ""


def click_race_row(page: Page, row_index: int):
    """Click the navigate chevron on a race row to open its detail page."""
    row = page.locator(f"div.MuiDataGrid-row[data-rowindex='{row_index}']")
    row.wait_for(state="visible", timeout=10_000)

    # Click the chevron icon (NavigateNextOutlinedIcon) in the "record" column
    chevron = row.locator("div[data-field='record'] svg")
    if chevron.count() > 0:
        chevron.first.click()
    else:
        # Fallback: click the row itself
        row.click()

    # Wait for navigation or detail view to load
    page.wait_for_load_state("domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass


def extract_labeled_value(page: Page, label: str) -> str | None:
    """
    Find a visible label text on the page and return its associated value.

    Tries multiple strategies:
    1. Exact text match -> parent -> sibling/child value element
    2. Case-insensitive text match
    3. XPath following-sibling approach
    """
    try:
        label_el = page.get_by_text(label, exact=True)
        if label_el.count() > 0:
            parent = label_el.first.locator("..")
            parent_text = parent.inner_text(timeout=5000)
            if parent_text:
                value = parent_text.replace(label, "").strip()
                if value:
                    return value

            sibling = label_el.first.locator("xpath=following-sibling::*[1]")
            if sibling.count() > 0:
                value = sibling.inner_text(timeout=5000).strip()
                if value:
                    return value
    except Exception:
        pass

    try:
        label_el = page.get_by_text(re.compile(f"^{re.escape(label)}$", re.IGNORECASE))
        if label_el.count() > 0:
            parent = label_el.first.locator("..")
            parent_text = parent.inner_text(timeout=5000)
            if parent_text:
                value = re.sub(re.escape(label), "", parent_text, flags=re.IGNORECASE).strip()
                if value:
                    return value
    except Exception:
        pass

    try:
        xpath = f"//*[contains(text(), '{label}')]/following-sibling::*[1]"
        el = page.locator(xpath)
        if el.count() > 0:
            value = el.first.inner_text(timeout=5000).strip()
            if value:
                return value
    except Exception:
        pass

    return None


def parse_race_detail(page: Page) -> dict:
    """
    Parse a race detail page to extract rankings, general info, and splits.

    Returns a dict with keys: bib, division, country, points, designation,
    div_rank, gender_rank, overall_rank, splits.
    """
    detail = {
        "bib": None,
        "division": None,
        "country": None,
        "points": None,
        "designation": None,
        "div_rank": None,
        "gender_rank": None,
        "overall_rank": None,
        "splits": [],
    }

    # Extract labeled values for general info
    label_map = {
        "BIB": "bib",
        "DIVISION": "division",
        "COUNTRY": "country",
        "POINTS": "points",
        "DESIGNATION": "designation",
    }

    for label, key in label_map.items():
        value = extract_labeled_value(page, label)
        if value:
            detail[key] = value
            logger.debug(f"  {label}: {value}")

    # Extract rankings
    rank_labels = {
        "DIV RANK": "div_rank",
        "GENDER RANK": "gender_rank",
        "OVERALL RANK": "overall_rank",
        "Division Rank": "div_rank",
        "Div Rank": "div_rank",
        "Gender Rank": "gender_rank",
        "Overall Rank": "overall_rank",
    }

    for label, key in rank_labels.items():
        if detail[key] is None:
            value = extract_labeled_value(page, label)
            if value:
                detail[key] = parse_int(value)
                logger.debug(f"  {label}: {value}")

    # Extract splits from MUI structure:
    # Each split block has h6 (label) + h4 (time) inside a MuiBox-root container.
    # T1/T2 are just button separators on the page — no individual times shown.
    leg_splits = {}
    for split_name in ("swim", "bike", "run"):
        time_str = None
        try:
            label_el = page.locator(
                f"h6.MuiTypography-h6:text-is('{split_name.upper()}')"
            )
            if label_el.count() > 0:
                container = label_el.first.locator("..")
                h4 = container.locator("h4.MuiTypography-h4")
                if h4.count() > 0:
                    time_str = h4.first.inner_text(timeout=5000).strip()
        except Exception as e:
            logger.debug(f"  {split_name}: selector failed: {e}")

        time_seconds = parse_time_to_seconds(time_str) if time_str else None
        leg_splits[split_name] = time_seconds
        detail["splits"].append(RaceSplit(name=split_name, time_seconds=time_seconds))

        if time_str:
            logger.debug(f"  {split_name}: {time_str} ({time_seconds}s)")
        else:
            logger.warning(f"  {split_name}: not found")

    # Also grab the overall time from the detail page
    overall_str = None
    try:
        label_el = page.locator("h6.MuiTypography-h6:text-is('Overall')")
        if label_el.count() > 0:
            container = label_el.first.locator("..")
            h4 = container.locator("h4.MuiTypography-h4")
            if h4.count() > 0:
                overall_str = h4.first.inner_text(timeout=5000).strip()
    except Exception:
        pass
    overall_seconds = parse_time_to_seconds(overall_str)

    # Compute combined transition time: overall - (swim + bike + run)
    leg_total = sum(v for v in leg_splits.values() if v is not None)
    if overall_seconds and leg_total and overall_seconds > leg_total:
        transition_seconds = overall_seconds - leg_total
        detail["splits"].append(RaceSplit(name="transitions", time_seconds=transition_seconds))
        logger.debug(f"  transitions: {transition_seconds}s (computed from overall {overall_str})")

    return detail

#!/usr/bin/env python3
"""
Race projection, nutrition planning, and training analysis for IRONMAN 70.3.

Reads historic race results, Strava training data, and objective race info
to produce a comprehensive projection JSON.

Usage: python analysis/race_projection.py
"""

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATHLETE_WEIGHT_KG = 70
RACE_DATE = "2027-03-01"

# Standard 70.3 distances
SWIM_DISTANCE_KM = 1.9
BIKE_DISTANCE_KM = 90.0
RUN_DISTANCE_KM = 21.1

RECENT_WEEKS = 8
HILLY_RIDE_THRESHOLD_M = 300  # elevation gain to classify a ride as "hilly"
HEAT_PENALTY_RUN_PCT = 5  # conservative run penalty for tropical conditions

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "analysis"

NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(seconds):
    """Format seconds as H:MM:SS."""
    if seconds is None:
        return "--:--:--"
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def pace_display(minutes_per_unit):
    """Format decimal minutes as M:SS (e.g., 5.27 -> '5:16')."""
    m = int(minutes_per_unit)
    s = int(round((minutes_per_unit - m) * 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"


def linear_regression(xs, ys):
    """Simple least-squares linear regression. Returns (slope, intercept, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    if denom == 0:
        return 0.0, sy / n, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, intercept, r_squared


def parse_dt(iso_str):
    """Parse ISO date string to datetime."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_races():
    """Load race results, filtered to 70.3 only, sorted chronologically."""
    races = json.loads((DATA_DIR / "ironman_results.json").read_text())
    races_703 = [r for r in races if "70.3" in r.get("race_name", "")]
    races_703.sort(key=lambda r: r.get("race_date", ""))
    return races_703


def load_all_races():
    """Load all race results (including full IRONMAN)."""
    return json.loads((DATA_DIR / "ironman_results.json").read_text())


def load_strava():
    """Load Strava activities."""
    return json.loads((DATA_DIR / "strava_activities.json").read_text())


def load_objective():
    """Load objective race info."""
    return json.loads((DATA_DIR / "objectiveRace" / "objectiveRace.json").read_text())


# ---------------------------------------------------------------------------
# Race pace analysis
# ---------------------------------------------------------------------------

def get_split_seconds(race, name):
    """Get split time in seconds from a race dict."""
    for s in race.get("splits", []):
        if s["name"] == name:
            return s.get("time_seconds")
    return None


def compute_race_paces(races):
    """Compute paces per discipline for each 70.3 race."""
    paces = []
    for r in races:
        swim_s = get_split_seconds(r, "swim")
        bike_s = get_split_seconds(r, "bike")
        run_s = get_split_seconds(r, "run")
        overall_s = r.get("overall_time_seconds")

        # Transition = overall - sum of legs
        leg_total = sum(x for x in [swim_s, bike_s, run_s] if x)
        transition_s = (overall_s - leg_total) if overall_s and leg_total else None

        swim_pace = (swim_s / (SWIM_DISTANCE_KM * 10) / 60) if swim_s else None  # min per 100m
        bike_speed = (BIKE_DISTANCE_KM / (bike_s / 3600)) if bike_s else None  # km/h
        run_pace = (run_s / RUN_DISTANCE_KM / 60) if run_s else None  # min per km

        paces.append({
            "race_name": r["race_name"],
            "race_date": r["race_date"],
            "overall_seconds": overall_s,
            "overall_display": fmt(overall_s),
            "swim_seconds": swim_s,
            "swim_pace_min_100m": round(swim_pace, 2) if swim_pace else None,
            "swim_pace_display": f"{pace_display(swim_pace)} /100m" if swim_pace else None,
            "bike_seconds": bike_s,
            "bike_speed_kph": round(bike_speed, 1) if bike_speed else None,
            "run_seconds": run_s,
            "run_pace_min_km": round(run_pace, 2) if run_pace else None,
            "run_pace_display": f"{pace_display(run_pace)} /km" if run_pace else None,
            "transition_seconds": transition_s,
            "transition_display": fmt(transition_s),
            "div_rank": r.get("div_rank"),
            "points": r.get("points"),
        })
    return paces


def compute_progression(race_paces):
    """Compute trend per discipline using linear regression."""
    progression = {}
    xs = list(range(len(race_paces)))

    for leg, key, invert in [
        ("swim", "swim_pace_min_100m", True),    # lower pace = faster
        ("bike", "bike_speed_kph", False),        # higher speed = faster
        ("run", "run_pace_min_km", True),          # lower pace = faster
    ]:
        values = [p[key] for p in race_paces if p[key] is not None]
        if len(values) < 2:
            progression[leg] = {"trend": "insufficient_data", "note": "Not enough data points."}
            continue

        slope, _, r_sq = linear_regression(xs[:len(values)], values)

        # Determine trend direction
        improving = (slope < 0) if invert else (slope > 0)
        mean_val = statistics.mean(values)
        relative_slope = abs(slope) / mean_val if mean_val else 0

        if relative_slope < 0.02:
            trend = "stable"
        elif r_sq < 0.3:
            trend = "inconsistent"
        elif improving:
            trend = "improving"
        else:
            trend = "declining"

        # Variance check
        cv = statistics.stdev(values) / mean_val if mean_val and len(values) > 1 else 0

        note_parts = []
        if cv > 0.3:
            note_parts.append(f"High variance (CV={cv:.0%}).")
        val_range = f"{min(values):.2f}-{max(values):.2f}"

        if leg == "swim":
            note_parts.append(f"Range: {val_range} min/100m.")
            # Check for Panama outlier
            if min(values) < 1.5 and max(values) > 2.0:
                note_parts.append(
                    "Panama swim pace is a significant outlier — may reflect favorable "
                    "current or short course. Excluding it gives a more reliable estimate."
                )
        elif leg == "bike":
            note_parts.append(f"Range: {val_range} km/h.")
        elif leg == "run":
            note_parts.append(f"Range: {val_range} min/km.")

        progression[leg] = {
            "trend": trend,
            "slope_per_race": round(slope, 3),
            "r_squared": round(r_sq, 2),
            "note": " ".join(note_parts),
        }

    return progression


# ---------------------------------------------------------------------------
# Finish time projection
# ---------------------------------------------------------------------------

def compute_bike_hill_factor(activities):
    """Compute speed ratio between hilly and flat rides from Strava data."""
    hilly_speeds = []
    flat_speeds = []
    for a in activities:
        if a.get("sport_type") != "Ride":
            continue
        dist = a.get("distance", 0)
        time_s = a.get("moving_time", 0)
        elev = a.get("total_elevation_gain", 0)
        if dist < 10000 or time_s < 1800:  # skip short rides
            continue
        speed_kph = (dist / 1000) / (time_s / 3600)
        if elev > HILLY_RIDE_THRESHOLD_M:
            hilly_speeds.append(speed_kph)
        else:
            flat_speeds.append(speed_kph)

    if not hilly_speeds or not flat_speeds:
        return 0.95, None, None  # default moderate factor

    hilly_avg = statistics.mean(hilly_speeds)
    flat_avg = statistics.mean(flat_speeds)
    raw_ratio = hilly_avg / flat_avg

    # Puerto Rico is moderately hilly — apply partial factor
    hill_factor = 1 - (1 - raw_ratio) * 0.5

    return round(hill_factor, 3), round(hilly_avg, 1), round(flat_avg, 1)


def project_finish_time(race_paces, activities):
    """Project finish time with optimistic/expected/conservative scenarios."""

    # Separate swim values with and without Panama outlier
    swim_paces = [p["swim_pace_min_100m"] for p in race_paces if p["swim_pace_min_100m"]]
    swim_paces_no_outlier = [s for s in swim_paces if s > 1.5]  # exclude sub-1:30 outlier
    bike_speeds = [p["bike_speed_kph"] for p in race_paces if p["bike_speed_kph"]]
    run_paces = [p["run_pace_min_km"] for p in race_paces if p["run_pace_min_km"]]
    transitions = [p["transition_seconds"] for p in race_paces if p["transition_seconds"]]

    avg_transition = statistics.mean(transitions) if transitions else 360  # default 6 min

    # Weighted average (recent races get 2x weight)
    def weighted_avg(values):
        if not values:
            return 0
        weights = [1] * len(values)
        for i in range(max(0, len(values) - 2), len(values)):
            weights[i] = 2
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    # Bike elevation adjustment
    hill_factor, hilly_avg, flat_avg = compute_bike_hill_factor(activities)

    # --- Optimistic ---
    # Best pace from recent 2 races per leg
    recent_swim = min(swim_paces[-2:]) if len(swim_paces) >= 2 else min(swim_paces)
    recent_bike = max(bike_speeds[-2:]) if len(bike_speeds) >= 2 else max(bike_speeds)
    recent_run = min(run_paces[-2:]) if len(run_paces) >= 2 else min(run_paces)

    opt_swim_s = recent_swim * SWIM_DISTANCE_KM * 10 * 60
    opt_bike_s = (BIKE_DISTANCE_KM / (recent_bike * hill_factor)) * 3600
    opt_run_s = recent_run * RUN_DISTANCE_KM * 60
    opt_total = opt_swim_s + opt_bike_s + opt_run_s + avg_transition

    # --- Expected ---
    # Weighted average, excluding swim outlier, with hill adjustment
    exp_swim_pace = weighted_avg(swim_paces_no_outlier) if swim_paces_no_outlier else weighted_avg(swim_paces)
    exp_bike_speed = weighted_avg(bike_speeds)
    exp_run_pace = weighted_avg(run_paces)

    exp_swim_s = exp_swim_pace * SWIM_DISTANCE_KM * 10 * 60
    exp_bike_s = (BIKE_DISTANCE_KM / (exp_bike_speed * hill_factor)) * 3600
    exp_run_s = exp_run_pace * RUN_DISTANCE_KM * 60
    exp_total = exp_swim_s + exp_bike_s + exp_run_s + avg_transition

    # --- Conservative ---
    # Worst pace from recent 2 races, plus heat penalty on run
    cons_swim = max(swim_paces_no_outlier[-2:]) if len(swim_paces_no_outlier) >= 2 else max(swim_paces_no_outlier or swim_paces)
    cons_bike = min(bike_speeds[-2:]) if len(bike_speeds) >= 2 else min(bike_speeds)
    cons_run = max(run_paces[-2:]) if len(run_paces) >= 2 else max(run_paces)

    cons_swim_s = cons_swim * SWIM_DISTANCE_KM * 10 * 60
    cons_bike_s = (BIKE_DISTANCE_KM / (cons_bike * hill_factor)) * 3600
    cons_run_s = cons_run * RUN_DISTANCE_KM * 60 * (1 + HEAT_PENALTY_RUN_PCT / 100)
    cons_total = cons_swim_s + cons_bike_s + cons_run_s + avg_transition * 1.2  # slower transitions too

    def scenario(swim_s, bike_s, run_s, total_s, swim_pace, bike_spd, run_p, note):
        return {
            "total_seconds": int(round(total_s)),
            "total_display": fmt(total_s),
            "swim_seconds": int(round(swim_s)),
            "swim_display": fmt(swim_s),
            "swim_pace": f"{pace_display(swim_pace)} /100m",
            "bike_seconds": int(round(bike_s)),
            "bike_display": fmt(bike_s),
            "bike_speed_kph": round(BIKE_DISTANCE_KM / (bike_s / 3600), 1),
            "run_seconds": int(round(run_s)),
            "run_display": fmt(run_s),
            "run_pace": f"{pace_display(run_p)} /km",
            "transition_seconds": int(round(total_s - swim_s - bike_s - run_s)),
            "note": note,
        }

    scenarios = {
        "optimistic": scenario(
            opt_swim_s, opt_bike_s, opt_run_s, opt_total,
            recent_swim, recent_bike * hill_factor, recent_run,
            "Best recent paces with hill-adjusted bike. Assumes good conditions and strong race execution."
        ),
        "expected": scenario(
            exp_swim_s, exp_bike_s, exp_run_s, exp_total,
            exp_swim_pace, exp_bike_speed * hill_factor, exp_run_pace,
            "Weighted average of 70.3 paces (recent races 2x weight), swim outlier excluded, "
            "bike adjusted for Puerto Rico hills."
        ),
        "conservative": scenario(
            cons_swim_s, cons_bike_s, cons_run_s, cons_total,
            cons_swim, cons_bike * hill_factor, cons_run * (1 + HEAT_PENALTY_RUN_PCT / 100),
            f"Worst recent paces with {HEAT_PENALTY_RUN_PCT}% heat penalty on run for tropical conditions."
        ),
    }

    adjustments = {
        "bike_elevation": {
            "description": (
                "Puerto Rico course includes hill sections. Training data shows speed reduction "
                "on hilly rides. Applied moderate hill factor to bike pace."
            ),
            "training_hilly_speed_kph": hilly_avg,
            "training_flat_speed_kph": flat_avg,
            "hill_penalty_factor": hill_factor,
        },
        "heat": {
            "description": (
                f"Puerto Rico tropical conditions (28-33C, high humidity). Applied "
                f"{HEAT_PENALTY_RUN_PCT}% penalty to conservative run estimate."
            ),
            "penalty_percent": HEAT_PENALTY_RUN_PCT,
        },
        "swim_outlier": {
            "description": (
                "Panama swim (1:16/100m) excluded from expected/conservative scenarios "
                "as it is a significant outlier vs other races (2:00+/100m). "
                "May reflect favorable current or course measurement."
            ),
        },
    }

    confidence = {
        "level": "low-moderate",
        "notes": [
            f"Based on only {len(race_paces)} half-distance races. Small sample limits reliability.",
            "Swim pace has extremely high variance. Panama swim is a clear outlier.",
            "Bike and run show improvement trends but with some regression in most recent race.",
            "Puerto Rico bike elevation is described as having 'hill sections' but exact profile is unknown.",
            "Tropical heat/humidity impact varies greatly by individual heat acclimatization.",
        ],
    }

    return {"scenarios": scenarios, "adjustments": adjustments, "confidence": confidence}


# ---------------------------------------------------------------------------
# Nutrition plan
# ---------------------------------------------------------------------------

def generate_nutrition_plan(expected_scenario, weight_kg):
    """Generate race-day nutrition plan based on projected duration."""
    bike_s = expected_scenario["bike_seconds"]
    run_s = expected_scenario["run_seconds"]
    swim_s = expected_scenario["swim_seconds"]
    bike_hrs = bike_s / 3600
    run_hrs = run_s / 3600

    def nutrient_range(low_rate, high_rate, hours):
        target = (low_rate + high_rate) / 2
        return {
            "min": int(round(low_rate * hours)),
            "max": int(round(high_rate * hours)),
            "target": int(round(target * hours)),
            "rate_min": low_rate,
            "rate_max": high_rate,
            "rate_target": (low_rate + high_rate) / 2,
        }

    plan = {
        "based_on": {
            "projected_duration_display": expected_scenario["total_display"],
            "projected_duration_seconds": expected_scenario["total_seconds"],
            "athlete_weight_kg": weight_kg,
            "conditions": "Tropical (Puerto Rico, expected 28-33C, 70-90% humidity)",
        },
        "by_leg": {
            "swim": {
                "duration_display": fmt(swim_s),
                "intake": "None (open water swim)",
                "pre_race": (
                    "2-3 hours before start: 100-150g carbs (low fiber), "
                    "500ml fluid with electrolytes. "
                    "Small top-up (gel + water) 15 min before start."
                ),
            },
            "t1": {
                "intake": "Quick sip of water or electrolyte drink. Keep transition fast.",
            },
            "bike": {
                "duration_display": fmt(bike_s),
                "duration_hours": round(bike_hrs, 2),
                "carbs_g": nutrient_range(80, 90, bike_hrs),
                "sodium_mg": nutrient_range(800, 1000, bike_hrs),
                "fluid_ml": nutrient_range(750, 1000, bike_hrs),
                "practical_notes": [
                    "Primary fueling window. Front-load calories in first 90 min.",
                    "Example: 1 bottle (500ml) sports drink/hr + 1 gel (25g carbs) every 30 min.",
                    "Set bike computer alerts every 15-20 min as intake reminders.",
                    "Finish the bike well-fueled — underfueling here destroys the run.",
                ],
            },
            "t2": {
                "intake": "1 gel (25g carbs) + 200ml water to bridge into run nutrition.",
            },
            "run": {
                "duration_display": fmt(run_s),
                "duration_hours": round(run_hrs, 2),
                "carbs_g": nutrient_range(60, 70, run_hrs),
                "sodium_mg": nutrient_range(600, 800, run_hrs),
                "fluid_ml": nutrient_range(500, 750, run_hrs),
                "practical_notes": [
                    "Use aid stations (~every 1.5-2km). Alternate water and electrolyte drink.",
                    "Carry 2-3 gels. Take at start, ~8km, and ~15km.",
                    "If stomach distress: switch to liquid calories only (cola, sports drink).",
                    "Ice sponge and cold water on head/neck at aid stations for cooling.",
                ],
            },
        },
    }

    # Totals
    bike_carbs = plan["by_leg"]["bike"]["carbs_g"]
    run_carbs = plan["by_leg"]["run"]["carbs_g"]
    bike_sodium = plan["by_leg"]["bike"]["sodium_mg"]
    run_sodium = plan["by_leg"]["run"]["sodium_mg"]
    bike_fluid = plan["by_leg"]["bike"]["fluid_ml"]
    run_fluid = plan["by_leg"]["run"]["fluid_ml"]

    plan["race_totals"] = {
        "total_carbs_g": {
            "min": bike_carbs["min"] + run_carbs["min"],
            "max": bike_carbs["max"] + run_carbs["max"],
            "target": bike_carbs["target"] + run_carbs["target"],
        },
        "total_sodium_mg": {
            "min": bike_sodium["min"] + run_sodium["min"],
            "max": bike_sodium["max"] + run_sodium["max"],
            "target": bike_sodium["target"] + run_sodium["target"],
        },
        "total_fluid_ml": {
            "min": bike_fluid["min"] + run_fluid["min"],
            "max": bike_fluid["max"] + run_fluid["max"],
            "target": bike_fluid["target"] + run_fluid["target"],
        },
    }

    plan["assumptions_and_caveats"] = [
        "Sweat rate assumed 1.0-1.5 L/hr for tropical conditions. Individual sweat testing recommended.",
        "Sodium loss assumed 800-1000 mg/L sweat. Actual range is 200-2000 mg/L between individuals.",
        "Carb targets of 80-90 g/hr on bike assume trained gut tolerance. Test in training first.",
        "Lower carb rate on run (60-70 g/hr) accounts for higher GI stress during running.",
        "These are general sports-nutrition heuristics, not medical advice.",
        "Puerto Rico heat may require upward fluid adjustment. Monitor urine color and body weight loss in training.",
        "Caffeine (100-200mg via gels) can help in the second half — test tolerance first.",
    ]

    return plan


# ---------------------------------------------------------------------------
# Training analysis
# ---------------------------------------------------------------------------

def aggregate_training(activities):
    """Aggregate Strava activities by discipline with weekly breakdown."""
    tri_sports = {"Swim", "Ride", "Run"}

    # Per-week and per-sport accumulators
    weeks = defaultdict(lambda: {s: {"distance": 0, "time": 0, "count": 0,
                                     "elevation": 0, "hr_sum": 0, "hr_count": 0,
                                     "speed_sum": 0, "speed_count": 0,
                                     "watts_sum": 0, "watts_count": 0}
                                 for s in tri_sports})
    totals = {s: {"distance": 0, "time": 0, "count": 0, "elevation": 0,
                  "hr_sum": 0, "hr_count": 0, "max_hrs": [],
                  "speed_sum": 0, "speed_count": 0,
                  "watts_sum": 0, "watts_count": 0}
              for s in tri_sports}

    for a in activities:
        sport = a.get("sport_type")
        if sport not in tri_sports:
            continue
        dt = parse_dt(a["start_date"])
        week_key = dt.strftime("%Y-W%W")
        dist = a.get("distance", 0)
        time_s = a.get("moving_time", 0)
        elev = a.get("total_elevation_gain", 0)

        for store in [weeks[week_key][sport], totals[sport]]:
            store["distance"] += dist
            store["time"] += time_s
            store["count"] += 1
            store["elevation"] += elev

        if a.get("has_heartrate") and a.get("average_heartrate"):
            for store in [weeks[week_key][sport], totals[sport]]:
                store["hr_sum"] += a["average_heartrate"]
                store["hr_count"] += 1
            if a.get("max_heartrate"):
                totals[sport]["max_hrs"].append(a["max_heartrate"])

        if a.get("average_speed"):
            for store in [weeks[week_key][sport], totals[sport]]:
                store["speed_sum"] += a["average_speed"]
                store["speed_count"] += 1

        if a.get("average_watts") and sport == "Ride":
            for store in [weeks[week_key][sport], totals[sport]]:
                store["watts_sum"] += a["average_watts"]
                store["watts_count"] += 1

    # Build weekly list
    sorted_weeks = sorted(weeks.keys())
    num_weeks = len(sorted_weeks) or 1
    recent_cutoff = (NOW - timedelta(weeks=RECENT_WEEKS)).strftime("%Y-W%W")

    # Per-discipline summary
    by_discipline = {}
    for sport in tri_sports:
        t = totals[sport]
        total_km = t["distance"] / 1000
        total_hrs = t["time"] / 3600
        avg_hr = round(t["hr_sum"] / t["hr_count"]) if t["hr_count"] else None

        # Compute average pace/speed
        if sport == "Swim" and t["speed_count"]:
            avg_speed_ms = t["speed_sum"] / t["speed_count"]
            avg_pace_min_100m = round((100 / avg_speed_ms) / 60, 2) if avg_speed_ms > 0 else None
            sport_specific = {"avg_pace_min_100m": avg_pace_min_100m,
                              "avg_pace_display": f"{pace_display(avg_pace_min_100m)} /100m" if avg_pace_min_100m else None}
        elif sport == "Ride" and t["speed_count"]:
            avg_speed_kph = round((t["speed_sum"] / t["speed_count"]) * 3.6, 1)
            avg_watts = round(t["watts_sum"] / t["watts_count"]) if t["watts_count"] else None
            sport_specific = {"avg_speed_kph": avg_speed_kph, "avg_watts": avg_watts,
                              "avg_elevation_m": round(t["elevation"] / t["count"]) if t["count"] else 0}
        elif sport == "Run" and t["speed_count"]:
            avg_speed_ms = t["speed_sum"] / t["speed_count"]
            avg_pace_min_km = round((1000 / avg_speed_ms) / 60, 2) if avg_speed_ms > 0 else None
            sport_specific = {"avg_pace_min_km": avg_pace_min_km,
                              "avg_pace_display": f"{pace_display(avg_pace_min_km)} /km" if avg_pace_min_km else None}
        else:
            sport_specific = {}

        # Recent 8 weeks
        recent_dist = 0
        recent_time = 0
        recent_count = 0
        recent_hr_sum = 0
        recent_hr_count = 0
        recent_speed_sum = 0
        recent_speed_count = 0
        recent_week_count = 0
        for wk in sorted_weeks:
            if wk >= recent_cutoff:
                recent_week_count += 1
                w = weeks[wk][sport]
                recent_dist += w["distance"]
                recent_time += w["time"]
                recent_count += w["count"]
                recent_hr_sum += w["hr_sum"]
                recent_hr_count += w["hr_count"]
                recent_speed_sum += w["speed_sum"]
                recent_speed_count += w["speed_count"]

        recent_weeks_actual = recent_week_count or 1
        recent_weekly_km = recent_dist / 1000 / recent_weeks_actual
        overall_weekly_km = total_km / num_weeks

        change_pct = ((recent_weekly_km - overall_weekly_km) / overall_weekly_km * 100
                      if overall_weekly_km > 0 else 0)

        recent_data = {
            "weekly_avg_km": round(recent_weekly_km, 1),
            "weekly_avg_sessions": round(recent_count / recent_weeks_actual, 1),
            "change_vs_overall_pct": round(change_pct, 1),
        }

        by_discipline[sport.lower()] = {
            "total_sessions": t["count"],
            "total_km": round(total_km, 1),
            "total_hours": round(total_hrs, 1),
            "weekly_avg_km": round(overall_weekly_km, 1),
            "weekly_avg_sessions": round(t["count"] / num_weeks, 1),
            "avg_hr_bpm": avg_hr,
            **sport_specific,
            "recent_8wk": recent_data,
        }

    # Weekly data for flags
    weekly_volumes = {s.lower(): [] for s in tri_sports}
    for wk in sorted_weeks:
        for sport in tri_sports:
            weekly_volumes[sport.lower()].append({
                "week": wk,
                "km": weeks[wk][sport]["distance"] / 1000,
                "sessions": weeks[wk][sport]["count"],
            })

    return by_discipline, totals, weekly_volumes, num_weeks


def estimate_hr_zones(totals):
    """Estimate HR zones from observed max heart rates."""
    all_max_hrs = []
    for sport_data in totals.values():
        all_max_hrs.extend(sport_data.get("max_hrs", []))

    if not all_max_hrs:
        return None

    # Use 95th percentile to avoid sensor spikes
    all_max_hrs.sort()
    idx_95 = int(len(all_max_hrs) * 0.95)
    estimated_max = int(all_max_hrs[min(idx_95, len(all_max_hrs) - 1)])
    actual_max = int(max(all_max_hrs))

    zones = {
        "zone1_recovery": {"min_bpm": int(estimated_max * 0.50), "max_bpm": int(estimated_max * 0.60)},
        "zone2_aerobic": {"min_bpm": int(estimated_max * 0.60), "max_bpm": int(estimated_max * 0.70)},
        "zone3_tempo": {"min_bpm": int(estimated_max * 0.70), "max_bpm": int(estimated_max * 0.80)},
        "zone4_threshold": {"min_bpm": int(estimated_max * 0.80), "max_bpm": int(estimated_max * 0.90)},
        "zone5_vo2max": {"min_bpm": int(estimated_max * 0.90), "max_bpm": estimated_max},
    }

    return {
        "estimated_max_hr": estimated_max,
        "observed_max_hr": actual_max,
        "max_hr_method": (
            f"95th percentile of observed max HRs. "
            f"Raw max ({actual_max} bpm) may be a sensor artifact."
            if actual_max > estimated_max + 10
            else "95th percentile of observed max HRs."
        ),
        "zones": zones,
    }


def identify_weakest_discipline(race_paces, training_stats):
    """Identify the weakest discipline based on race consistency and training trends."""
    assessments = {}

    for leg, race_key, training_key in [
        ("swim", "swim_pace_min_100m", "avg_pace_min_100m"),
        ("bike", "bike_speed_kph", "avg_speed_kph"),
        ("run", "run_pace_min_km", "avg_pace_min_km"),
    ]:
        race_values = [p[race_key] for p in race_paces if p[race_key] is not None]
        if not race_values:
            continue

        cv = statistics.stdev(race_values) / statistics.mean(race_values) if len(race_values) > 1 else 0
        recent_change = training_stats.get(leg, {}).get("recent_8wk", {}).get("change_vs_overall_pct", 0)

        # Score: higher = weaker (more inconsistent + declining training)
        score = cv * 100 - recent_change * 0.5  # variance hurts, volume decline hurts
        assessments[leg] = {"cv": round(cv, 3), "recent_change_pct": recent_change, "score": round(score, 1)}

    if not assessments:
        return None

    weakest = max(assessments, key=lambda k: assessments[k]["score"])

    suggestions = {
        "swim": [
            "Increase swim frequency to 3x/week minimum.",
            "Add open water practice to simulate race conditions.",
            "Focus on sighting and straight-line swimming to reduce actual distance.",
            "Consider swim stroke analysis to improve efficiency.",
        ],
        "bike": [
            "Include more hill-specific training to match Puerto Rico course.",
            "Practice race-pace efforts at target power/speed.",
            "Work on nutrition strategy during long rides.",
            "Add brick sessions (bike-to-run) to practice transitions.",
        ],
        "run": [
            "Add a weekly long run at race pace.",
            "Include heat acclimatization sessions for Puerto Rico conditions.",
            "Practice running off the bike (brick sessions).",
            "Focus on consistent pacing — avoid going out too fast.",
        ],
    }

    return {
        "discipline": weakest,
        "scores": assessments,
        "reasoning": (
            f"{weakest.capitalize()} has the highest inconsistency in race results "
            f"(CV={assessments[weakest]['cv']:.1%}) combined with "
            f"{'declining' if assessments[weakest]['recent_change_pct'] < 0 else 'stable'} "
            f"training volume ({assessments[weakest]['recent_change_pct']:+.1f}% recent vs overall)."
        ),
        "improvement_suggestions": suggestions.get(weakest, []),
    }


def flag_training_issues(weekly_volumes, num_weeks):
    """Flag potential training issues from weekly data."""
    flags = []

    for sport in ["swim", "ride", "run"]:
        volumes = weekly_volumes.get(sport, [])
        if not volumes:
            continue

        # Check recent 8 weeks for missing sessions
        recent = volumes[-RECENT_WEEKS:]
        zero_weeks = sum(1 for w in recent if w["sessions"] == 0)
        if zero_weeks > 0:
            flags.append({
                "type": "concern",
                "discipline": sport,
                "message": f"{sport.capitalize()}: {zero_weeks} week(s) with zero sessions in last {RECENT_WEEKS} weeks.",
            })

        # Check for sharp volume jumps (>20% week-over-week in recent period)
        recent_kms = [w["km"] for w in recent if w["km"] > 0]
        for i in range(1, len(recent_kms)):
            if recent_kms[i - 1] > 0:
                jump = (recent_kms[i] - recent_kms[i - 1]) / recent_kms[i - 1]
                if jump > 0.20:
                    flags.append({
                        "type": "caution",
                        "discipline": sport,
                        "message": f"{sport.capitalize()}: Volume jump of {jump:.0%} detected week-over-week. "
                                   f"Monitor for overtraining risk.",
                    })
                    break  # only flag once per sport

        # Overall volume trend in recent weeks
        if len(recent_kms) >= 3:
            xs = list(range(len(recent_kms)))
            slope, _, _ = linear_regression(xs, recent_kms)
            avg_km = statistics.mean(recent_kms) if recent_kms else 1
            if slope > 0 and abs(slope / avg_km) > 0.05:
                flags.append({
                    "type": "positive",
                    "discipline": sport,
                    "message": f"{sport.capitalize()}: Volume trending upward in recent {RECENT_WEEKS} weeks — building well.",
                })
            elif slope < 0 and abs(slope / avg_km) > 0.1:
                flags.append({
                    "type": "concern",
                    "discipline": sport,
                    "message": f"{sport.capitalize()}: Volume declining in recent weeks. Review if intentional (taper) or unplanned.",
                })

    return flags


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading data...")
    races_703 = load_races()
    all_races = load_all_races()
    activities = load_strava()
    objective = load_objective()

    excluded = [r for r in all_races if "70.3" not in r.get("race_name", "")]

    print(f"  {len(races_703)} 70.3 races, {len(excluded)} excluded (full IRONMAN)")
    print(f"  {len(activities)} Strava activities")

    # Race pace analysis
    print("Analyzing race paces...")
    race_paces = compute_race_paces(races_703)
    progression = compute_progression(race_paces)

    # Finish time projection
    print("Projecting finish times...")
    projection = project_finish_time(race_paces, activities)

    # Nutrition plan
    print("Generating nutrition plan...")
    nutrition = generate_nutrition_plan(projection["scenarios"]["expected"], ATHLETE_WEIGHT_KG)

    # Training analysis
    print("Analyzing training data...")
    by_discipline, totals, weekly_volumes, num_weeks = aggregate_training(activities)
    hr_zones = estimate_hr_zones(totals)
    weakest = identify_weakest_discipline(race_paces, by_discipline)
    training_flags = flag_training_issues(weekly_volumes, num_weeks)

    # Build output
    output = {
        "generated_at": NOW.isoformat(),
        "athlete": {
            "weight_kg": ATHLETE_WEIGHT_KG,
            "age_group": races_703[0].get("age_group", "M30-34") if races_703 else "M30-34",
        },
        "objective_race": {
            "name": objective["race_name"],
            "date": RACE_DATE,
            "location": f"{objective['location']['city']}, {objective['location']['country']}",
            "distances": {
                "swim_km": objective["course"]["swim"]["distance_km"],
                "bike_km": objective["course"]["bike"]["distance_km"],
                "run_km": objective["course"]["run"]["distance_km"],
            },
            "course_notes": {
                "swim": objective["course"]["swim"].get("notes", ""),
                "bike": objective["course"]["bike"].get("notes", ""),
                "run": objective["course"]["run"].get("notes", ""),
            },
        },
        "historical_analysis": {
            "races_used": len(races_703),
            "races_excluded": [
                {"name": r["race_name"], "reason": "Full IRONMAN distance, not comparable to 70.3"}
                for r in excluded
            ],
            "race_paces": race_paces,
            "progression": progression,
        },
        "finish_time_projection": projection,
        "nutrition_plan": nutrition,
        "training_analysis": {
            "period": {
                "total_weeks": num_weeks,
                "recent_weeks": RECENT_WEEKS,
            },
            "by_discipline": by_discipline,
            "hr_zones": hr_zones,
            "weakest_discipline": weakest,
            "training_flags": training_flags,
        },
    }

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "race_projection.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nProjection saved to {output_path}")

    # Print summary
    exp = projection["scenarios"]["expected"]
    opt = projection["scenarios"]["optimistic"]
    cons = projection["scenarios"]["conservative"]
    print(f"\n{'='*60}")
    print(f"  IRONMAN 70.3 Puerto Rico — Finish Time Projection")
    print(f"{'='*60}")
    print(f"  Optimistic:   {opt['total_display']}")
    print(f"  Expected:     {exp['total_display']}")
    print(f"  Conservative: {cons['total_display']}")
    print(f"{'='*60}")
    print(f"  Weakest discipline: {weakest['discipline'].upper() if weakest else 'N/A'}")
    print(f"  Nutrition target:   {nutrition['race_totals']['total_carbs_g']['target']}g carbs total")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

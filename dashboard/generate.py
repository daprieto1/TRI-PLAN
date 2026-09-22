#!/usr/bin/env python3
"""Generate the TRI-PLAN race intelligence dashboard."""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUTPUT = Path(__file__).resolve().parent / "index.html"

COUNTRY_FLAGS = {
    "Cartagena": "\U0001F1E8\U0001F1F4",
    "Barranquilla": "\U0001F1E8\U0001F1F4",
    "Fortaleza": "\U0001F1E7\U0001F1F7",
    "Panama": "\U0001F1F5\U0001F1E6",
    "Portugal": "\U0001F1F5\U0001F1F9",
    "Puerto Rico": "\U0001F1F5\U0001F1F7",
}


def get_flag(race_name: str) -> str:
    for key, flag in COUNTRY_FLAGS.items():
        if key.lower() in race_name.lower():
            return flag
    return ""


def fmt_time(seconds: int | None) -> str:
    if seconds is None:
        return "--:--:--"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def load_races() -> list[dict]:
    races_dir = DATA_DIR / "races"
    races = []
    for race_dir in sorted(races_dir.iterdir()):
        if not race_dir.is_dir():
            continue
        for jf in race_dir.glob("*.json"):
            race = json.loads(jf.read_text())
            race["flag"] = get_flag(race.get("race_name", ""))
            race["is_full"] = "70.3" not in race.get("race_name", "")
            races.append(race)
            break
    races.sort(key=lambda r: r.get("race_date", ""))
    return races


def load_objective() -> dict:
    obj_path = DATA_DIR / "objectiveRace" / "objectiveRace.json"
    obj = json.loads(obj_path.read_text())
    obj["flag"] = get_flag(obj.get("race_name", ""))
    return obj


def process_strava() -> tuple[list[dict], dict]:
    strava_path = DATA_DIR / "strava_activities.json"
    activities = json.loads(strava_path.read_text())

    tri_sports = {"Swim", "Ride", "Run"}
    tri = [a for a in activities if a.get("sport_type") in tri_sports]

    weeks = defaultdict(lambda: {s: {"distance": 0, "time": 0, "count": 0, "elevation": 0} for s in tri_sports})
    totals = {s: {"distance": 0, "time": 0, "count": 0, "elevation": 0, "hr_sum": 0, "hr_count": 0} for s in tri_sports}

    for a in tri:
        dt = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
        week_key = dt.strftime("%Y-W%W")
        sport = a["sport_type"]
        dist = a.get("distance", 0)
        time_s = a.get("moving_time", 0)
        elev = a.get("total_elevation_gain", 0)

        weeks[week_key][sport]["distance"] += dist
        weeks[week_key][sport]["time"] += time_s
        weeks[week_key][sport]["count"] += 1
        weeks[week_key][sport]["elevation"] += elev

        totals[sport]["distance"] += dist
        totals[sport]["time"] += time_s
        totals[sport]["count"] += 1
        totals[sport]["elevation"] += elev
        if a.get("has_heartrate") and a.get("average_heartrate"):
            totals[sport]["hr_sum"] += a["average_heartrate"]
            totals[sport]["hr_count"] += 1

    weekly = []
    for wk in sorted(weeks.keys()):
        entry = {"week": wk}
        for s in tri_sports:
            entry[f"{s.lower()}_km"] = round(weeks[wk][s]["distance"] / 1000, 1)
            entry[f"{s.lower()}_hrs"] = round(weeks[wk][s]["time"] / 3600, 1)
            entry[f"{s.lower()}_count"] = weeks[wk][s]["count"]
        weekly.append(entry)

    summary = {}
    for s in tri_sports:
        t = totals[s]
        summary[s.lower()] = {
            "km": round(t["distance"] / 1000),
            "hours": round(t["time"] / 3600),
            "sessions": t["count"],
            "elevation": round(t["elevation"]),
            "avg_hr": round(t["hr_sum"] / t["hr_count"]) if t["hr_count"] else None,
        }
    summary["total_km"] = sum(v["km"] for v in summary.values() if isinstance(v, dict))
    summary["total_hours"] = sum(v["hours"] for v in summary.values() if isinstance(v, dict))
    summary["total_sessions"] = sum(v["sessions"] for v in summary.values() if isinstance(v, dict))

    return weekly, summary


def load_oura() -> dict:
    oura_path = DATA_DIR / "oura.json"
    data = json.loads(oura_path.read_text())
    return {
        "sleep": data.get("daily_sleep", []),
        "readiness": data.get("daily_readiness", []),
        "sessions": data.get("sleep_sessions", []),
        "stress": data.get("daily_stress", []),
        "period": data.get("period", {}),
    }


def load_cronometer() -> dict:
    crono_path = DATA_DIR / "cronometer.json"
    data = json.loads(crono_path.read_text())
    return {
        "daily": data.get("daily_summaries", []),
        "targets": data.get("targets", {}),
        "biometrics": data.get("biometrics_log", []),
    }


def load_projection() -> dict:
    proj_path = DATA_DIR.parent / "analysis" / "race_projection.json"
    return json.loads(proj_path.read_text())


def load_nutrition_strategy() -> dict:
    ns_path = DATA_DIR.parent / "analysis" / "nutrition_strategy.json"
    return json.loads(ns_path.read_text())


def build_html(races, objective, weekly_training, training_summary, oura, cronometer, projection, nutri_strategy):
    races_json = json.dumps(races)
    objective_json = json.dumps(objective)
    weekly_json = json.dumps(weekly_training)
    summary_json = json.dumps(training_summary)
    oura_json = json.dumps(oura)
    cronometer_json = json.dumps(cronometer)
    projection_json = json.dumps(projection)
    nutri_strat_json = json.dumps(nutri_strategy)

    # Best 70.3 time
    times_703 = [r["overall_time_seconds"] for r in races if not r["is_full"] and r.get("overall_time_seconds")]
    best_703 = min(times_703) if times_703 else 0
    first_703 = times_703[0] if times_703 else 0
    improvement = first_703 - best_703 if first_703 and best_703 else 0

    # Best div rank
    div_ranks = [r["div_rank"] for r in races if r.get("div_rank")]
    best_div = min(div_ranks) if div_ranks else 0

    # Points range
    points = [r["points"] for r in races if r.get("points")]
    first_points = points[0] if points else 0
    best_points = max(points) if points else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TRI-PLAN | Race Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#06060b;--bg2:#0c0c14;--bg3:#12121c;
  --card:rgba(255,255,255,0.03);--card-hover:rgba(255,255,255,0.06);
  --border:rgba(255,255,255,0.06);--border-light:rgba(255,255,255,0.1);
  --text:#f1f5f9;--text2:#94a3b8;--text3:#475569;
  --red:#dc2626;--red-glow:rgba(220,38,38,0.15);
  --swim:#06b6d4;--bike:#22c55e;--run:#f97316;
  --gold:#eab308;--purple:#a855f7;
  --swim-bg:rgba(6,182,212,0.1);--bike-bg:rgba(34,197,94,0.1);--run-bg:rgba(249,115,22,0.1);
}}
html{{scroll-behavior:smooth}}
body{{
  font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);
  line-height:1.6;overflow-x:hidden;
}}
body::before{{
  content:'';position:fixed;top:0;left:0;right:0;bottom:0;
  background:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(220,38,38,0.08),transparent),
             radial-gradient(ellipse 60% 40% at 80% 50%,rgba(6,182,212,0.04),transparent);
  pointer-events:none;z-index:0;
}}

/* NAV */
nav{{
  position:fixed;top:0;left:0;right:0;z-index:100;
  padding:1rem 2rem;display:flex;align-items:center;justify-content:space-between;
  background:rgba(6,6,11,0.8);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);
}}
.logo{{font-size:1.1rem;font-weight:800;letter-spacing:2px;color:var(--text)}}
.logo span{{color:var(--red)}}
nav a{{color:var(--text2);text-decoration:none;font-size:0.8rem;font-weight:500;letter-spacing:1px;text-transform:uppercase;transition:color 0.3s}}
nav a:hover{{color:var(--text)}}
.nav-links{{display:flex;gap:2rem}}

/* SECTIONS */
section{{position:relative;z-index:1;padding:6rem 2rem 4rem}}
.container{{max-width:1200px;margin:0 auto}}

/* HERO */
.hero{{
  min-height:100vh;display:flex;flex-direction:column;justify-content:center;
  padding-top:5rem;text-align:center;
}}
.hero-badge{{
  display:inline-flex;align-items:center;gap:0.5rem;margin:0 auto 1.5rem;
  padding:0.4rem 1rem;border-radius:100px;font-size:0.75rem;font-weight:600;
  letter-spacing:1.5px;text-transform:uppercase;color:var(--red);
  border:1px solid rgba(220,38,38,0.3);background:rgba(220,38,38,0.06);
}}
.hero-badge::before{{content:'';width:6px;height:6px;border-radius:50%;background:var(--red);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.3}}}}
.hero h1{{
  font-size:clamp(3rem,8vw,6rem);font-weight:900;line-height:1;
  background:linear-gradient(135deg,#fff 0%,#94a3b8 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:0.5rem;
}}
.hero .subtitle{{font-size:1.2rem;color:var(--text2);font-weight:400;margin-bottom:3rem}}
.hero-stats{{
  display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  background:var(--border);border-radius:16px;overflow:hidden;max-width:800px;margin:0 auto;
}}
.hero-stat{{
  background:var(--bg2);padding:2rem 1rem;text-align:center;
}}
.hero-stat .number{{font-size:2.2rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.hero-stat .label{{font-size:0.7rem;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;margin-top:0.3rem}}
.hero-stat.swim .number{{color:var(--swim)}}
.hero-stat.bike .number{{color:var(--bike)}}
.hero-stat.run .number{{color:var(--run)}}
.hero-stat.total .number{{color:var(--gold)}}

/* SECTION HEADERS */
.section-label{{
  font-size:0.7rem;font-weight:600;letter-spacing:2px;text-transform:uppercase;
  color:var(--red);margin-bottom:0.5rem;
}}
.section-title{{font-size:2rem;font-weight:800;margin-bottom:0.5rem}}
.section-sub{{color:var(--text2);margin-bottom:3rem;max-width:600px}}

/* OBJECTIVE RACE */
.objective-card{{
  position:relative;border-radius:20px;overflow:hidden;
  background:linear-gradient(135deg,var(--bg3),var(--bg2));
  border:1px solid var(--border-light);
}}
.objective-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,var(--red),var(--run),var(--gold));
}}
.obj-content{{padding:3rem;display:grid;grid-template-columns:1fr 1fr;gap:3rem;align-items:center}}
.obj-left h2{{font-size:1.8rem;font-weight:800;margin-bottom:0.5rem}}
.obj-left .location{{color:var(--text2);font-size:1rem;margin-bottom:2rem}}
.obj-courses{{display:flex;flex-direction:column;gap:1rem}}
.course-item{{
  display:flex;align-items:center;gap:1rem;padding:1rem 1.2rem;
  border-radius:12px;border:1px solid var(--border);
}}
.course-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.course-dot.swim{{background:var(--swim)}}
.course-dot.bike{{background:var(--bike)}}
.course-dot.run{{background:var(--run)}}
.course-name{{font-weight:600;min-width:50px}}
.course-dist{{color:var(--text2);font-size:0.9rem}}
.course-notes{{color:var(--text3);font-size:0.8rem;margin-left:auto;max-width:300px;text-align:right}}
.obj-right{{text-align:center}}
.countdown-label{{font-size:0.7rem;color:var(--text3);text-transform:uppercase;letter-spacing:2px;margin-bottom:1rem}}
.countdown{{display:flex;gap:1rem;justify-content:center}}
.countdown-unit{{text-align:center}}
.countdown-unit .num{{
  font-size:3rem;font-weight:900;font-family:'JetBrains Mono',monospace;
  background:linear-gradient(180deg,var(--text),var(--text2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1;
}}
.countdown-unit .lbl{{font-size:0.6rem;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;margin-top:0.3rem}}
.obj-target{{margin-top:2rem;padding:1.5rem;border-radius:12px;background:rgba(220,38,38,0.06);border:1px solid rgba(220,38,38,0.15)}}
.obj-target .t-label{{font-size:0.65rem;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px}}
.obj-target .t-time{{font-size:2rem;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--red)}}

/* ACHIEVEMENTS */
.achievements{{display:grid;grid-template-columns:repeat(4,1fr);gap:1.5rem;margin-bottom:4rem}}
.achievement{{
  padding:2rem;border-radius:16px;background:var(--card);border:1px solid var(--border);
  text-align:center;transition:all 0.3s;
}}
.achievement:hover{{background:var(--card-hover);border-color:var(--border-light);transform:translateY(-2px)}}
.achievement .icon{{font-size:2rem;margin-bottom:0.8rem}}
.achievement .val{{font-size:2rem;font-weight:800;font-family:'JetBrains Mono',monospace;margin-bottom:0.3rem}}
.achievement .desc{{font-size:0.8rem;color:var(--text2)}}
.achievement.red .val{{color:var(--red)}}
.achievement.gold .val{{color:var(--gold)}}
.achievement.purple .val{{color:var(--purple)}}
.achievement.swim .val{{color:var(--swim)}}

/* RACE TIMELINE */
.race-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.5rem;margin-bottom:3rem}}
.race-card{{
  padding:1.5rem;border-radius:16px;background:var(--card);border:1px solid var(--border);
  transition:all 0.3s;position:relative;overflow:hidden;
}}
.race-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:var(--red);opacity:0;transition:opacity 0.3s;
}}
.race-card:hover{{background:var(--card-hover);transform:translateY(-3px)}}
.race-card:hover::before{{opacity:1}}
.race-card .flag{{font-size:1.5rem;margin-bottom:0.5rem}}
.race-card .r-name{{font-weight:700;font-size:0.95rem;margin-bottom:0.2rem}}
.race-card .r-date{{font-size:0.75rem;color:var(--text3);margin-bottom:1rem}}
.race-card .r-time{{
  font-size:1.8rem;font-weight:800;font-family:'JetBrains Mono',monospace;margin-bottom:0.8rem;
}}
.race-card .r-meta{{display:flex;flex-direction:column;gap:0.3rem}}
.race-card .r-meta span{{font-size:0.75rem;color:var(--text2)}}
.race-card .r-meta strong{{color:var(--text);font-weight:600}}
.race-card .r-badge{{
  position:absolute;top:1rem;right:1rem;padding:0.2rem 0.6rem;
  border-radius:6px;font-size:0.65rem;font-weight:700;letter-spacing:0.5px;
}}
.badge-full{{background:rgba(168,85,247,0.15);color:var(--purple);border:1px solid rgba(168,85,247,0.3)}}
.badge-pr{{background:rgba(234,179,8,0.15);color:var(--gold);border:1px solid rgba(234,179,8,0.3)}}

/* CHARTS */
.chart-grid{{display:grid;grid-template-columns:2fr 1fr;gap:1.5rem;margin-bottom:3rem}}
.chart-card{{
  padding:2rem;border-radius:16px;background:var(--card);border:1px solid var(--border);
}}
.chart-card h3{{font-size:1rem;font-weight:700;margin-bottom:0.3rem}}
.chart-card .chart-sub{{font-size:0.8rem;color:var(--text3);margin-bottom:1.5rem}}
.chart-card canvas{{width:100%!important}}

/* TRAINING */
.training-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin-bottom:3rem}}
.t-metric{{
  padding:2rem;border-radius:16px;border:1px solid var(--border);text-align:center;
}}
.t-metric.swim{{background:var(--swim-bg);border-color:rgba(6,182,212,0.15)}}
.t-metric.bike{{background:var(--bike-bg);border-color:rgba(34,197,94,0.15)}}
.t-metric.run{{background:var(--run-bg);border-color:rgba(249,115,22,0.15)}}
.t-metric .sport-icon{{font-size:1.5rem;margin-bottom:0.8rem}}
.t-metric .sport-name{{font-size:0.65rem;text-transform:uppercase;letter-spacing:2px;font-weight:600;margin-bottom:0.8rem}}
.t-metric.swim .sport-name{{color:var(--swim)}}
.t-metric.bike .sport-name{{color:var(--bike)}}
.t-metric.run .sport-name{{color:var(--run)}}
.t-metric .big-num{{font-size:2.5rem;font-weight:800;font-family:'JetBrains Mono',monospace;line-height:1}}
.t-metric .unit{{font-size:0.8rem;color:var(--text2);margin-bottom:1rem}}
.t-metric .sub-stats{{display:flex;justify-content:center;gap:1.5rem}}
.t-metric .sub-stat{{text-align:center}}
.t-metric .sub-val{{font-size:1rem;font-weight:700;font-family:'JetBrains Mono',monospace}}
.t-metric .sub-lbl{{font-size:0.6rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px}}

/* SPLITS */
.splits-section{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}}
.split-bar{{
  display:flex;align-items:center;gap:1rem;padding:1.2rem 1.5rem;
  border-radius:12px;background:var(--card);border:1px solid var(--border);
}}
.split-bar .s-label{{font-weight:600;min-width:50px}}
.split-bar .s-bar-bg{{flex:1;height:8px;border-radius:4px;background:rgba(255,255,255,0.05);overflow:hidden}}
.split-bar .s-bar{{height:100%;border-radius:4px;transition:width 1.5s ease}}
.split-bar .s-time{{font-family:'JetBrains Mono',monospace;font-weight:600;font-size:0.9rem;min-width:70px;text-align:right}}

/* RECOVERY & BODY */
.recovery-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:0.8rem;margin-bottom:3rem}}
.day-card{{
  padding:1.2rem 0.8rem;border-radius:14px;background:var(--card);border:1px solid var(--border);
  text-align:center;transition:all 0.3s;
}}
.day-card:hover{{background:var(--card-hover);transform:translateY(-2px)}}
.day-card .day-name{{font-size:0.65rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px;margin-bottom:0.6rem}}
.day-card .day-date{{font-size:0.7rem;color:var(--text2);margin-bottom:1rem}}
.score-ring{{
  width:56px;height:56px;border-radius:50%;margin:0 auto 0.5rem;
  display:flex;align-items:center;justify-content:center;
  font-size:1.3rem;font-weight:800;font-family:'JetBrains Mono',monospace;
  position:relative;
}}
.score-ring::before{{
  content:'';position:absolute;inset:-3px;border-radius:50%;
  background:conic-gradient(var(--ring-color) calc(var(--ring-pct) * 3.6deg), rgba(255,255,255,0.05) 0);
  z-index:-1;
}}
.score-ring::after{{
  content:'';position:absolute;inset:0;border-radius:50%;background:var(--bg2);z-index:-1;
}}
.score-label{{font-size:0.6rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px}}
.sleep-score .score-ring{{--ring-color:#818cf8}}
.readiness-score .score-ring{{--ring-color:#34d399}}
.day-divider{{height:1px;background:var(--border);margin:0.8rem 0}}
.day-card .mini-stat{{font-size:0.7rem;color:var(--text2);margin-top:0.3rem}}
.day-card .mini-stat strong{{color:var(--text);font-family:'JetBrains Mono',monospace}}

.body-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:1.5rem;margin-bottom:3rem}}
.body-card{{
  padding:1.5rem;border-radius:16px;background:var(--card);border:1px solid var(--border);text-align:center;
}}
.body-card .b-icon{{font-size:1.5rem;margin-bottom:0.5rem}}
.body-card .b-val{{font-size:2rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.body-card .b-unit{{font-size:0.75rem;color:var(--text2)}}
.body-card .b-label{{font-size:0.65rem;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;margin-top:0.5rem}}
.body-card .b-delta{{font-size:0.75rem;margin-top:0.3rem;font-weight:600}}
.delta-down{{color:#34d399}}
.delta-up{{color:var(--run)}}
.delta-neutral{{color:var(--text3)}}

/* NUTRITION */
.nutri-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:0.8rem;margin-bottom:3rem}}
.nutri-day{{
  padding:1.2rem 0.8rem;border-radius:14px;background:var(--card);border:1px solid var(--border);
  text-align:center;transition:all 0.3s;
}}
.nutri-day:hover{{background:var(--card-hover);transform:translateY(-2px)}}
.nutri-day .nd-date{{font-size:0.65rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px;margin-bottom:0.8rem}}
.nutri-day .nd-kcal{{font-size:1.6rem;font-weight:800;font-family:'JetBrains Mono',monospace;line-height:1}}
.nutri-day .nd-kcal-label{{font-size:0.6rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px;margin-bottom:0.8rem}}
.macro-bars{{display:flex;flex-direction:column;gap:0.4rem;margin-top:0.5rem}}
.macro-bar{{display:flex;align-items:center;gap:0.4rem}}
.macro-bar .mb-label{{font-size:0.55rem;color:var(--text3);width:10px;text-align:right;font-weight:600}}
.macro-bar .mb-bg{{flex:1;height:5px;border-radius:3px;background:rgba(255,255,255,0.05);overflow:hidden}}
.macro-bar .mb-fill{{height:100%;border-radius:3px}}
.macro-bar .mb-val{{font-size:0.6rem;color:var(--text2);width:28px;font-family:'JetBrains Mono',monospace}}
.mb-protein{{background:#818cf8}}
.mb-carbs{{background:var(--gold)}}
.mb-fat{{background:#f472b6}}
.nutri-day .nd-water{{font-size:0.7rem;color:var(--swim);margin-top:0.6rem}}
.nutri-day .nd-water strong{{font-family:'JetBrains Mono',monospace}}
.nutri-day.high-day{{border-color:rgba(234,179,8,0.25);background:rgba(234,179,8,0.03)}}

/* PROJECTION */
.scenario-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin-bottom:3rem}}
.scenario-card{{
  padding:2rem;border-radius:16px;border:1px solid var(--border);
  text-align:center;transition:all 0.3s;position:relative;overflow:hidden;
}}
.scenario-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
}}
.scenario-card:hover{{transform:translateY(-3px)}}
.sc-optimistic{{background:rgba(34,197,94,0.04)}}
.sc-optimistic::before{{background:var(--bike)}}
.sc-optimistic .sc-time{{color:var(--bike)}}
.sc-expected{{background:rgba(6,182,212,0.04);border-color:rgba(6,182,212,0.2)}}
.sc-expected::before{{background:var(--swim)}}
.sc-expected .sc-time{{color:var(--swim)}}
.sc-conservative{{background:rgba(249,115,22,0.04)}}
.sc-conservative::before{{background:var(--run)}}
.sc-conservative .sc-time{{color:var(--run)}}
.sc-label{{font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:2px;margin-bottom:1rem;color:var(--text2)}}
.sc-time{{font-size:2.8rem;font-weight:900;font-family:'JetBrains Mono',monospace;line-height:1;margin-bottom:1.2rem}}
.sc-splits{{display:flex;flex-direction:column;gap:0.5rem;text-align:left}}
.sc-split{{display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.8rem;border-radius:8px;background:rgba(255,255,255,0.02);font-size:0.8rem}}
.sc-split .sc-s-name{{color:var(--text2);font-weight:500}}
.sc-split .sc-s-time{{font-family:'JetBrains Mono',monospace;font-weight:600}}
.sc-split .sc-s-pace{{font-size:0.7rem;color:var(--text3)}}
.sc-note{{font-size:0.7rem;color:var(--text3);margin-top:1rem;line-height:1.4;font-style:italic}}

.adjustments-row{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:3rem}}
.adj-card{{
  padding:1.2rem;border-radius:12px;background:var(--card);border:1px solid var(--border);
  display:flex;gap:1rem;align-items:flex-start;
}}
.adj-icon{{font-size:1.5rem;flex-shrink:0}}
.adj-card h4{{font-size:0.85rem;font-weight:700;margin-bottom:0.3rem}}
.adj-card p{{font-size:0.75rem;color:var(--text2);line-height:1.4}}

/* NUTRITION PLAN */
.nutri-plan-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:3rem}}
.np-card{{
  padding:2rem;border-radius:16px;background:var(--card);border:1px solid var(--border);
}}
.np-card h3{{font-size:1rem;font-weight:700;margin-bottom:0.3rem;display:flex;align-items:center;gap:0.5rem}}
.np-card .np-duration{{font-size:0.8rem;color:var(--text3);margin-bottom:1.5rem}}
.np-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:1.2rem}}
.np-metric{{text-align:center;padding:1rem 0.5rem;border-radius:10px;background:rgba(255,255,255,0.02)}}
.np-metric .npm-val{{font-size:1.4rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.np-metric .npm-unit{{font-size:0.65rem;color:var(--text3)}}
.np-metric .npm-rate{{font-size:0.6rem;color:var(--text2);margin-top:0.2rem}}
.np-notes{{list-style:none;padding:0}}
.np-notes li{{font-size:0.75rem;color:var(--text2);padding:0.4rem 0;border-bottom:1px solid var(--border);display:flex;gap:0.5rem}}
.np-notes li:last-child{{border-bottom:none}}
.np-notes li::before{{content:'\\2022';color:var(--run);flex-shrink:0}}

.race-totals{{
  display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin-bottom:3rem;
}}
.rt-card{{
  padding:1.5rem;border-radius:16px;background:var(--card);border:1px solid var(--border);text-align:center;
}}
.rt-card .rt-icon{{font-size:1.5rem;margin-bottom:0.5rem}}
.rt-card .rt-val{{font-size:2rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.rt-card .rt-range{{font-size:0.7rem;color:var(--text3);margin-top:0.3rem}}
.rt-card .rt-label{{font-size:0.65rem;color:var(--text2);text-transform:uppercase;letter-spacing:1.5px;margin-top:0.5rem}}

/* TRAINING FLAGS */
.flags-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}}
.flag-card{{
  padding:1rem 1.2rem;border-radius:12px;display:flex;gap:1rem;align-items:flex-start;font-size:0.8rem;
}}
.flag-caution{{background:rgba(234,179,8,0.06);border:1px solid rgba(234,179,8,0.15);color:var(--gold)}}
.flag-concern{{background:rgba(249,115,22,0.06);border:1px solid rgba(249,115,22,0.15);color:var(--run)}}
.flag-icon{{font-size:1.2rem;flex-shrink:0}}
.flag-text{{color:var(--text2);line-height:1.4}}
.flag-text strong{{color:var(--text)}}

.weakness-card{{
  padding:2rem;border-radius:16px;background:rgba(220,38,38,0.04);
  border:1px solid rgba(220,38,38,0.15);margin-bottom:3rem;
}}
.weakness-card h3{{font-size:1rem;font-weight:700;margin-bottom:0.5rem;color:var(--red)}}
.weakness-card .wk-reason{{font-size:0.85rem;color:var(--text2);margin-bottom:1rem}}
.weakness-card ul{{list-style:none;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:0.5rem}}
.weakness-card li{{font-size:0.8rem;color:var(--text2);padding:0.5rem 0.8rem;border-radius:8px;background:rgba(255,255,255,0.02);display:flex;gap:0.5rem}}
.weakness-card li::before{{content:'\\279C';color:var(--red);flex-shrink:0}}

.confidence-bar{{
  padding:1.5rem 2rem;border-radius:16px;background:var(--card);border:1px solid var(--border);margin-bottom:3rem;
}}
/* CARB LOADING & TIMELINE */
.carb-load-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin-bottom:3rem}}
.cl-day{{padding:1.5rem;border-radius:16px;background:var(--card);border:1px solid var(--border);position:relative;overflow:hidden}}
.cl-day::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--gold)}}
.cl-day .cl-label{{font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:var(--gold);margin-bottom:0.3rem}}
.cl-day .cl-focus{{font-size:0.85rem;color:var(--text2);margin-bottom:1rem}}
.cl-day .cl-macros{{display:grid;grid-template-columns:repeat(3,1fr);gap:0.8rem;margin-bottom:1rem}}
.cl-macro{{text-align:center;padding:0.6rem 0;border-radius:8px;background:rgba(255,255,255,0.02)}}
.cl-macro .clm-val{{font-size:1.3rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.cl-macro .clm-label{{font-size:0.55rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px}}
.cl-notes{{font-size:0.7rem;color:var(--text3);line-height:1.5}}
.cl-meals{{list-style:none;padding:0;margin-top:0.8rem}}
.cl-meals li{{font-size:0.7rem;color:var(--text2);padding:0.3rem 0;border-bottom:1px solid var(--border)}}
.cl-meals li:last-child{{border-bottom:none}}

.pre-race-card{{
  padding:2rem;border-radius:16px;background:var(--card);border:1px solid var(--border);margin-bottom:3rem;
  display:grid;grid-template-columns:1fr 1fr;gap:2rem;
}}
.pre-race-card h3{{font-size:1rem;font-weight:700;margin-bottom:0.5rem}}
.meal-option{{padding:1.2rem;border-radius:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border);margin-bottom:1rem}}
.meal-option h4{{font-size:0.85rem;font-weight:700;margin-bottom:0.5rem;color:var(--gold)}}
.meal-option .meal-items{{list-style:none;padding:0}}
.meal-option .meal-items li{{font-size:0.75rem;color:var(--text2);padding:0.2rem 0;display:flex;justify-content:space-between}}
.meal-option .meal-items li span{{color:var(--text3)}}
.meal-total{{font-size:0.8rem;font-weight:700;margin-top:0.5rem;padding-top:0.5rem;border-top:1px solid var(--border)}}
.meal-note{{font-size:0.7rem;color:var(--text3);font-style:italic;margin-top:0.3rem}}

.timeline-section{{margin-bottom:3rem}}
.tl-header{{display:flex;align-items:center;gap:1rem;margin-bottom:1rem}}
.tl-header h3{{font-size:1rem;font-weight:700}}
.tl-header .tl-meta{{font-size:0.8rem;color:var(--text3)}}
.tl-table{{width:100%;border-collapse:separate;border-spacing:0;font-size:0.78rem}}
.tl-table th{{text-align:left;padding:0.6rem 0.8rem;font-size:0.6rem;text-transform:uppercase;letter-spacing:1.5px;color:var(--text3);border-bottom:1px solid var(--border)}}
.tl-table td{{padding:0.6rem 0.8rem;border-bottom:1px solid var(--border);color:var(--text2)}}
.tl-table tr:last-child td{{border-bottom:none}}
.tl-table td:first-child{{font-family:'JetBrains Mono',monospace;font-weight:600;color:var(--text)}}
.tl-table td:nth-child(2){{color:var(--text)}}
.tl-table .tl-cumul{{font-family:'JetBrains Mono',monospace;color:var(--gold);font-weight:600}}
.tl-carry{{margin-top:0.8rem;padding:1rem;border-radius:10px;background:rgba(255,255,255,0.02)}}
.tl-carry h4{{font-size:0.75rem;font-weight:700;margin-bottom:0.5rem;color:var(--text2)}}
.tl-carry li{{font-size:0.7rem;color:var(--text3);padding:0.2rem 0}}

.gap-alert{{
  padding:1.5rem 2rem;border-radius:16px;margin-bottom:3rem;
  background:rgba(234,179,8,0.06);border:1px solid rgba(234,179,8,0.2);
  display:flex;gap:1rem;align-items:flex-start;
}}
.gap-alert .ga-icon{{font-size:2rem;flex-shrink:0}}
.gap-alert h4{{font-size:0.9rem;font-weight:700;color:var(--gold);margin-bottom:0.3rem}}
.gap-alert p{{font-size:0.8rem;color:var(--text2);line-height:1.5}}
.gap-alert .ga-numbers{{display:flex;gap:2rem;margin-top:0.8rem}}
.gap-alert .ga-num{{text-align:center}}
.gap-alert .ga-val{{font-size:1.5rem;font-weight:800;font-family:'JetBrains Mono',monospace}}
.gap-alert .ga-lbl{{font-size:0.6rem;color:var(--text3);text-transform:uppercase;letter-spacing:1px}}

.reminders-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0.8rem;margin-bottom:3rem}}
.reminder-item{{
  padding:0.8rem 1rem;border-radius:10px;background:var(--card);border:1px solid var(--border);
  font-size:0.78rem;color:var(--text2);display:flex;gap:0.6rem;align-items:flex-start;
}}
.reminder-item::before{{content:'\\2713';color:var(--bike);font-weight:700;flex-shrink:0}}

.confidence-bar h4{{font-size:0.85rem;font-weight:700;margin-bottom:0.8rem}}
.conf-track{{height:10px;border-radius:5px;background:rgba(255,255,255,0.05);position:relative;margin-bottom:1rem}}
.conf-fill{{height:100%;border-radius:5px;background:linear-gradient(90deg,var(--red),var(--gold),var(--bike));position:absolute;left:0;top:0}}
.conf-notes{{font-size:0.7rem;color:var(--text3);line-height:1.5}}
.conf-notes li{{margin-bottom:0.3rem}}

/* ARCHITECTURE */
.arch-flow{{display:flex;flex-direction:column;gap:0;align-items:center}}
.arch-layer{{width:100%;display:flex;flex-direction:column;align-items:center}}
.arch-label{{
  font-size:0.6rem;font-weight:700;text-transform:uppercase;letter-spacing:2px;
  color:var(--text3);margin-bottom:0.8rem;text-align:center;
}}
.arch-row{{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin-bottom:0}}
.arch-node{{
  padding:1rem 1.4rem;border-radius:14px;text-align:center;min-width:140px;
  transition:all 0.3s;position:relative;
}}
.arch-node:hover{{transform:translateY(-3px)}}
.arch-node .an-icon{{font-size:1.6rem;margin-bottom:0.4rem;display:block}}
.arch-node .an-name{{font-size:0.8rem;font-weight:700;margin-bottom:0.2rem}}
.arch-node .an-desc{{font-size:0.65rem;color:var(--text3);line-height:1.3}}
.arch-node.future{{opacity:0.45}}
.arch-node.future .an-name::after{{content:' *';color:var(--text3)}}

.an-source{{background:rgba(6,182,212,0.06);border:1px solid rgba(6,182,212,0.15)}}
.an-source .an-name{{color:var(--swim)}}
.an-ingest{{background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.15)}}
.an-ingest .an-name{{color:var(--purple)}}
.an-storage{{background:rgba(234,179,8,0.06);border:1px solid rgba(234,179,8,0.15)}}
.an-storage .an-name{{color:var(--gold)}}
.an-analysis{{background:rgba(220,38,38,0.06);border:1px solid rgba(220,38,38,0.15)}}
.an-analysis .an-name{{color:var(--red)}}
.an-output{{background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.15)}}
.an-output .an-name{{color:var(--bike)}}

.arch-arrow{{
  display:flex;flex-direction:column;align-items:center;padding:0.6rem 0;color:var(--text3);
}}
.arch-arrow svg{{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}

.arch-connector{{
  display:flex;align-items:center;justify-content:center;gap:0.5rem;
  padding:0.4rem 0;width:100%;
}}
.arch-line{{
  width:2px;height:32px;background:linear-gradient(180deg,var(--border-light),var(--text3),var(--border-light));
  border-radius:1px;
}}
.arch-lines{{display:flex;gap:3rem;justify-content:center;padding:0.5rem 0}}

.arch-detail-grid{{
  display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin-top:3rem;
}}
.arch-detail{{
  padding:1.5rem;border-radius:14px;background:var(--card);border:1px solid var(--border);
}}
.arch-detail h4{{font-size:0.85rem;font-weight:700;margin-bottom:0.5rem;display:flex;align-items:center;gap:0.5rem}}
.arch-detail p{{font-size:0.75rem;color:var(--text2);line-height:1.5}}
.arch-detail code{{
  font-family:'JetBrains Mono',monospace;font-size:0.7rem;
  background:rgba(255,255,255,0.05);padding:0.1rem 0.4rem;border-radius:4px;
  color:var(--text);
}}
.arch-detail ul{{list-style:none;padding:0;margin-top:0.5rem}}
.arch-detail li{{font-size:0.7rem;color:var(--text2);padding:0.2rem 0;display:flex;gap:0.4rem}}
.arch-detail li::before{{content:'\\2022';color:var(--purple);flex-shrink:0}}

/* FOOTER */
footer{{
  text-align:center;padding:3rem 2rem;color:var(--text3);font-size:0.75rem;
  border-top:1px solid var(--border);
}}
footer a{{color:var(--text2);text-decoration:none}}

/* ANIMATIONS */
.reveal{{opacity:0;transform:translateY(30px);transition:all 0.8s cubic-bezier(0.16,1,0.3,1)}}
.reveal.visible{{opacity:1;transform:translateY(0)}}

/* RESPONSIVE */
@media(max-width:768px){{
  section{{padding:4rem 1rem 3rem}}
  .hero h1{{font-size:2.5rem}}
  .hero-stats{{grid-template-columns:repeat(2,1fr)}}
  .obj-content{{grid-template-columns:1fr}}
  .achievements{{grid-template-columns:repeat(2,1fr)}}
  .chart-grid{{grid-template-columns:1fr}}
  .training-metrics{{grid-template-columns:1fr}}
  .race-grid{{grid-template-columns:repeat(2,1fr)}}
  .splits-section{{grid-template-columns:1fr}}
  .recovery-grid{{grid-template-columns:repeat(3,1fr)}}
  .body-metrics{{grid-template-columns:repeat(2,1fr)}}
  .nutri-grid{{grid-template-columns:repeat(3,1fr)}}
  .scenario-grid{{grid-template-columns:1fr}}
  .adjustments-row{{grid-template-columns:1fr}}
  .nutri-plan-grid{{grid-template-columns:1fr}}
  .race-totals{{grid-template-columns:1fr}}
  .flags-grid{{grid-template-columns:1fr}}
  .weakness-card ul{{grid-template-columns:1fr}}
  .carb-load-grid{{grid-template-columns:1fr}}
  .pre-race-card{{grid-template-columns:1fr}}
  .reminders-grid{{grid-template-columns:1fr}}
  .arch-detail-grid{{grid-template-columns:1fr}}
  .arch-row{{flex-direction:column;align-items:center}}
  .nav-links{{display:none}}
}}
</style>
</head>
<body>

<nav>
  <div class="logo">TRI<span>PLAN</span></div>
  <div class="nav-links">
    <a href="#objective">Objective</a>
    <a href="#races">Races</a>
    <a href="#performance">Performance</a>
    <a href="#training">Training</a>
    <a href="#projection">Projection</a>
    <a href="#recovery">Recovery</a>
    <a href="#nutrition">Nutrition</a>
    <a href="#architecture">Architecture</a>
  </div>
</nav>

<section class="hero" id="hero">
  <div class="container">
    <div class="hero-badge">Race Intelligence Dashboard</div>
    <h1>IRONMAN Athlete</h1>
    <p class="subtitle">M30-34 &middot; 5 Races &middot; 6 Months Training Data</p>
    <div class="hero-stats">
      <div class="hero-stat total">
        <div class="number" data-count="{training_summary['total_km']}">{training_summary['total_km']:,}</div>
        <div class="label">Total Kilometers</div>
      </div>
      <div class="hero-stat total">
        <div class="number" data-count="{training_summary['total_hours']}">{training_summary['total_hours']}</div>
        <div class="label">Training Hours</div>
      </div>
      <div class="hero-stat total">
        <div class="number" data-count="{training_summary['total_sessions']}">{training_summary['total_sessions']}</div>
        <div class="label">Sessions</div>
      </div>
      <div class="hero-stat total">
        <div class="number" data-count="{len(races)}">{len(races)}</div>
        <div class="label">Races Completed</div>
      </div>
    </div>
  </div>
</section>

<section id="objective">
  <div class="container">
    <div class="section-label">Next Target</div>
    <div class="objective-card reveal">
      <div class="obj-content">
        <div class="obj-left">
          <h2>{objective.get('flag', '')} {objective['race_name']}</h2>
          <p class="location">{objective['location']['city']}, {objective['location']['country']}</p>
          <div class="obj-courses">
            <div class="course-item">
              <div class="course-dot swim"></div>
              <span class="course-name">Swim</span>
              <span class="course-dist">{objective['course']['swim']['distance_km']}km &mdash; {objective['course']['swim']['location']}</span>
            </div>
            <div class="course-item">
              <div class="course-dot bike"></div>
              <span class="course-name">Bike</span>
              <span class="course-dist">{objective['course']['bike']['distance_km']}km</span>
            </div>
            <div class="course-item">
              <div class="course-dot run"></div>
              <span class="course-name">Run</span>
              <span class="course-dist">{objective['course']['run']['distance_km']}km &mdash; {objective['course']['run']['loops']} loops</span>
            </div>
          </div>
        </div>
        <div class="obj-right">
          <div class="countdown-label">Race Day Countdown</div>
          <div class="countdown" id="countdown"></div>
          <div class="obj-target">
            <div class="t-label">PR Target (70.3)</div>
            <div class="t-time">{fmt_time(best_703)}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section id="milestones">
  <div class="container">
    <div class="section-label">Key Milestones</div>
    <div class="section-title">The Journey So Far</div>
    <div class="achievements reveal">
      <div class="achievement red">
        <div class="icon">&#9201;</div>
        <div class="val">-{improvement // 60}:{improvement % 60:02d}</div>
        <div class="desc">70.3 Time Improvement<br>First to Best</div>
      </div>
      <div class="achievement gold">
        <div class="icon">&#127942;</div>
        <div class="val">#{best_div}</div>
        <div class="desc">Best Division Rank<br>M30-34</div>
      </div>
      <div class="achievement purple">
        <div class="icon">&#127775;</div>
        <div class="val">{best_points:.0f}</div>
        <div class="desc">Peak IRONMAN Points<br>From {first_points:.0f}</div>
      </div>
      <div class="achievement swim">
        <div class="icon">&#127946;</div>
        <div class="val">140.6</div>
        <div class="desc">Full IRONMAN<br>Portugal-Cascais</div>
      </div>
    </div>
  </div>
</section>

<section id="races">
  <div class="container">
    <div class="section-label">Race History</div>
    <div class="section-title">Every Start Line Tells a Story</div>
    <p class="section-sub">From first 70.3 to Full IRONMAN &mdash; consistent progression across {len(races)} races.</p>
    <div class="race-grid reveal" id="race-cards"></div>

    <div class="chart-grid reveal">
      <div class="chart-card">
        <h3>IRONMAN Points Evolution</h3>
        <p class="chart-sub">Tracking ranking points across all races</p>
        <canvas id="pointsChart" height="250"></canvas>
      </div>
      <div class="chart-card">
        <h3>70.3 Finish Times</h3>
        <p class="chart-sub">Half-distance race comparison</p>
        <canvas id="timesChart" height="250"></canvas>
      </div>
    </div>
  </div>
</section>

<section id="performance">
  <div class="container">
    <div class="section-label">Split Analysis</div>
    <div class="section-title">Barranquilla Breakdown</div>
    <p class="section-sub">Best race with split data &mdash; IRONMAN 70.3 Barranquilla (5:08:03)</p>
    <div class="splits-section reveal">
      <div style="display:flex;flex-direction:column;gap:1rem" id="split-bars"></div>
      <div class="chart-card">
        <h3>Time Distribution</h3>
        <p class="chart-sub">Percentage of total race time per discipline</p>
        <canvas id="splitsDonut" height="250"></canvas>
      </div>
    </div>
  </div>
</section>

<section id="training">
  <div class="container">
    <div class="section-label">Training Load</div>
    <div class="section-title">6 Months of Preparation</div>
    <p class="section-sub">Swim, bike, run volume tracked from Strava &mdash; building toward race day.</p>

    <div class="training-metrics reveal">
      <div class="t-metric swim">
        <div class="sport-icon">&#127946;&#8205;&#9794;&#65039;</div>
        <div class="sport-name">Swim</div>
        <div class="big-num">{training_summary['swim']['km']}</div>
        <div class="unit">kilometers</div>
        <div class="sub-stats">
          <div class="sub-stat"><div class="sub-val">{training_summary['swim']['hours']}</div><div class="sub-lbl">Hours</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['swim']['sessions']}</div><div class="sub-lbl">Sessions</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['swim']['avg_hr'] or '--'}</div><div class="sub-lbl">Avg HR</div></div>
        </div>
      </div>
      <div class="t-metric bike">
        <div class="sport-icon">&#128692;</div>
        <div class="sport-name">Bike</div>
        <div class="big-num">{training_summary['ride']['km']:,}</div>
        <div class="unit">kilometers</div>
        <div class="sub-stats">
          <div class="sub-stat"><div class="sub-val">{training_summary['ride']['hours']}</div><div class="sub-lbl">Hours</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['ride']['sessions']}</div><div class="sub-lbl">Sessions</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['ride']['elevation']:,}m</div><div class="sub-lbl">Elevation</div></div>
        </div>
      </div>
      <div class="t-metric run">
        <div class="sport-icon">&#127939;</div>
        <div class="sport-name">Run</div>
        <div class="big-num">{training_summary['run']['km']}</div>
        <div class="unit">kilometers</div>
        <div class="sub-stats">
          <div class="sub-stat"><div class="sub-val">{training_summary['run']['hours']}</div><div class="sub-lbl">Hours</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['run']['sessions']}</div><div class="sub-lbl">Sessions</div></div>
          <div class="sub-stat"><div class="sub-val">{training_summary['run']['avg_hr'] or '--'}</div><div class="sub-lbl">Avg HR</div></div>
        </div>
      </div>
    </div>

    <div class="chart-grid reveal">
      <div class="chart-card">
        <h3>Weekly Training Volume</h3>
        <p class="chart-sub">Hours per discipline per week</p>
        <canvas id="volumeChart" height="280"></canvas>
      </div>
      <div class="chart-card">
        <h3>Sport Distribution</h3>
        <p class="chart-sub">Total hours by discipline</p>
        <canvas id="distChart" height="280"></canvas>
      </div>
    </div>
  </div>
</section>

<section id="projection">
  <div class="container">
    <div class="section-label">Race Projection</div>
    <div class="section-title">IRONMAN 70.3 Puerto Rico &mdash; Predicted Finish</div>
    <p class="section-sub">Three scenarios based on 4 half-distance races, training data, course adjustments, and tropical conditions.</p>

    <div class="scenario-grid reveal" id="scenario-cards"></div>

    <div class="adjustments-row reveal" id="adjustments"></div>

    <div class="confidence-bar reveal" id="confidence"></div>

    <div class="chart-grid reveal">
      <div class="chart-card">
        <h3>Historical vs Projected Paces</h3>
        <p class="chart-sub">Split paces across all 70.3 races with projected range</p>
        <canvas id="paceChart" height="280"></canvas>
      </div>
      <div class="chart-card">
        <h3>Projected Split Breakdown</h3>
        <p class="chart-sub">Expected scenario time distribution</p>
        <canvas id="projSplitDonut" height="280"></canvas>
      </div>
    </div>

    <div class="section-label" style="margin-top:3rem">Race Week</div>
    <div class="section-title">Carb Loading Protocol</div>
    <p class="section-sub">3-day protocol ramping from 6.2 to 10 g/kg/day &mdash; maximizing muscle glycogen while tapering fiber.</p>
    <div class="carb-load-grid reveal" id="carb-load"></div>

    <div class="section-label">Race Morning</div>
    <div class="section-title">Pre-Race Meal</div>
    <p class="section-sub">2.5&ndash;3 hours before swim start &mdash; target 149g carbs (2 g/kg), ~715 kcal.</p>
    <div class="pre-race-card reveal" id="pre-race-meal"></div>

    <div class="section-label">Race Day Nutrition</div>
    <div class="section-title">Fueling Timeline</div>
    <p class="section-sub">Minute-by-minute fueling plan for bike &amp; run based on projected 5:34:51 finish.</p>

    <div class="race-totals reveal" id="race-totals"></div>

    <div class="gap-alert reveal" id="gap-alert"></div>

    <div class="timeline-section reveal" id="bike-timeline"></div>
    <div class="timeline-section reveal" id="run-timeline"></div>

    <div class="section-label" style="margin-top:2rem">Key Reminders</div>
    <div class="reminders-grid reveal" id="reminders"></div>

    <div class="section-label" style="margin-top:3rem">Training Insights</div>
    <div class="section-title">Areas to Watch</div>

    <div class="weakness-card reveal" id="weakness"></div>
    <div class="flags-grid reveal" id="training-flags"></div>
  </div>
</section>

<section id="recovery">
  <div class="container">
    <div class="section-label">Recovery &amp; Body</div>
    <div class="section-title">Sleep, Readiness &amp; Body Composition</div>
    <p class="section-sub">7-day snapshot from Oura Ring &amp; Cronometer &mdash; tracking recovery quality alongside training load.</p>

    <div class="body-metrics reveal" id="body-metrics"></div>
    <div class="recovery-grid reveal" id="recovery-days"></div>

    <div class="chart-grid reveal">
      <div class="chart-card">
        <h3>Sleep &amp; Readiness Scores</h3>
        <p class="chart-sub">Daily scores over the last 7 days</p>
        <canvas id="sleepReadinessChart" height="250"></canvas>
      </div>
      <div class="chart-card">
        <h3>Sleep Quality Breakdown</h3>
        <p class="chart-sub">Average contributor scores</p>
        <canvas id="sleepRadar" height="250"></canvas>
      </div>
    </div>
  </div>
</section>

<section id="nutrition">
  <div class="container">
    <div class="section-label">Nutrition</div>
    <div class="section-title">Fueling the Engine</div>
    <p class="section-sub">Daily intake tracked in Cronometer &mdash; calories, macros, hydration, and key micronutrients.</p>

    <div class="nutri-grid reveal" id="nutri-days"></div>

    <div class="chart-grid reveal">
      <div class="chart-card">
        <h3>Daily Calories &amp; Macros</h3>
        <p class="chart-sub">Stacked macro breakdown with calorie target line</p>
        <canvas id="macroChart" height="250"></canvas>
      </div>
      <div class="chart-card">
        <h3>Hydration &amp; Sodium</h3>
        <p class="chart-sub">Key electrolyte tracking for race prep</p>
        <canvas id="hydroChart" height="250"></canvas>
      </div>
    </div>
  </div>
</section>

<section id="architecture">
  <div class="container">
    <div class="section-label">System Architecture</div>
    <div class="section-title">How TRI-PLAN Works</div>
    <p class="section-sub">End-to-end pipeline: from raw data sources to race-day intelligence &mdash; built with Claude Code.</p>

    <div class="arch-flow reveal">

      <!-- Layer 1: Data Sources -->
      <div class="arch-layer">
        <div class="arch-label">Data Sources</div>
        <div class="arch-row">
          <div class="arch-node an-source">
            <span class="an-icon">&#127942;</span>
            <div class="an-name">IRONMAN</div>
            <div class="an-desc">Race results, splits,<br>rankings &amp; points</div>
          </div>
          <div class="arch-node an-source">
            <span class="an-icon">&#128692;</span>
            <div class="an-name">Strava</div>
            <div class="an-desc">Training activities,<br>HR, pace, power</div>
          </div>
          <div class="arch-node an-source">
            <span class="an-icon">&#128564;</span>
            <div class="an-name">Oura Ring</div>
            <div class="an-desc">Sleep, readiness,<br>HRV &amp; stress</div>
          </div>
          <div class="arch-node an-source">
            <span class="an-icon">&#127838;</span>
            <div class="an-name">Cronometer</div>
            <div class="an-desc">Nutrition, macros,<br>weight &amp; body comp</div>
          </div>
          <div class="arch-node an-source future">
            <span class="an-icon">&#9201;</span>
            <div class="an-name">Garmin</div>
            <div class="an-desc">Device metrics,<br>training load</div>
          </div>
        </div>
      </div>

      <!-- Arrow -->
      <div class="arch-connector">
        <div class="arch-arrow">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
        </div>
      </div>

      <!-- Layer 2: Ingestion -->
      <div class="arch-layer">
        <div class="arch-label">Ingestion Layer</div>
        <div class="arch-row">
          <div class="arch-node an-ingest">
            <span class="an-icon">&#128375;</span>
            <div class="an-name">Playwright Scraper</div>
            <div class="an-desc">Browser automation<br>for IRONMAN results</div>
          </div>
          <div class="arch-node an-ingest">
            <span class="an-icon">&#128268;</span>
            <div class="an-name">MCP Servers</div>
            <div class="an-desc">Strava, Oura, Cronometer<br>API connectors via MCP</div>
          </div>
          <div class="arch-node an-ingest">
            <span class="an-icon">&#129302;</span>
            <div class="an-name">Claude Code</div>
            <div class="an-desc">Orchestration, data<br>extraction &amp; validation</div>
          </div>
        </div>
      </div>

      <!-- Arrow -->
      <div class="arch-connector">
        <div class="arch-arrow">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
        </div>
      </div>

      <!-- Layer 3: Storage -->
      <div class="arch-layer">
        <div class="arch-label">Raw Storage</div>
        <div class="arch-row">
          <div class="arch-node an-storage">
            <span class="an-icon">&#128451;</span>
            <div class="an-name">data/raw/</div>
            <div class="an-desc">JSON per source &mdash;<br>races, activities, sleep, nutrition</div>
          </div>
        </div>
      </div>

      <!-- Arrow -->
      <div class="arch-connector">
        <div class="arch-arrow">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
        </div>
      </div>

      <!-- Layer 4: Analysis -->
      <div class="arch-layer">
        <div class="arch-label">Analysis Engine</div>
        <div class="arch-row">
          <div class="arch-node an-analysis">
            <span class="an-icon">&#128200;</span>
            <div class="an-name">Race Projection</div>
            <div class="an-desc">Pace trends, scenarios,<br>confidence intervals</div>
          </div>
          <div class="arch-node an-analysis">
            <span class="an-icon">&#127836;</span>
            <div class="an-name">Nutrition Strategy</div>
            <div class="an-desc">Carb loading, fueling<br>timeline, gap analysis</div>
          </div>
        </div>
      </div>

      <!-- Arrow -->
      <div class="arch-connector">
        <div class="arch-arrow">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
        </div>
      </div>

      <!-- Layer 5: Output -->
      <div class="arch-layer">
        <div class="arch-label">Presentation</div>
        <div class="arch-row">
          <div class="arch-node an-output">
            <span class="an-icon">&#127760;</span>
            <div class="an-name">Dashboard</div>
            <div class="an-desc">Single-page HTML<br>with Chart.js visualizations</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Detail cards -->
    <div class="arch-detail-grid reveal">
      <div class="arch-detail">
        <h4><span style="color:var(--swim)">&#128375;</span> IRONMAN Scraper</h4>
        <p>Playwright-based browser automation that handles cookie consent, two-step login, and MUI DataGrid navigation on <code>my.ironman.com</code>.</p>
        <ul>
          <li>Automated login with session reuse</li>
          <li>Per-race JSON + screenshot export</li>
          <li>Splits, rankings &amp; points extraction</li>
          <li>Rate-limited with configurable delay</li>
        </ul>
      </div>
      <div class="arch-detail">
        <h4><span style="color:var(--purple)">&#128268;</span> MCP Integration</h4>
        <p>Model Context Protocol servers provide structured API access. Claude Code calls these directly to fetch and normalize athlete data.</p>
        <ul>
          <li><strong>Strava</strong> &mdash; 6 months of swim/bike/run activities with HR, pace, power</li>
          <li><strong>Oura</strong> &mdash; Sleep scores, readiness, HRV, resting HR</li>
          <li><strong>Cronometer</strong> &mdash; Daily macros, micros, hydration, body composition</li>
          <li><strong>Garmin*</strong> &mdash; Future: device-level training metrics</li>
        </ul>
      </div>
      <div class="arch-detail">
        <h4><span style="color:var(--red)">&#128200;</span> Analysis Pipeline</h4>
        <p>Python scripts correlate training load with race performance to build projections. No ML &mdash; transparent statistical methods for small samples.</p>
        <ul>
          <li>Weighted pace trends with outlier detection</li>
          <li>Course-specific adjustments (elevation, heat)</li>
          <li>3-scenario projections with confidence ranges</li>
          <li>Personalized nutrition plan from tracked intake</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<footer>
  <p>TRI-PLAN Race Intelligence &middot; Data from IRONMAN, Strava, Oura &amp; Cronometer &middot; Built with Claude Code</p>
</footer>

<script>
const RACES = {races_json};
const OBJECTIVE = {objective_json};
const WEEKLY = {weekly_json};
const SUMMARY = {summary_json};
const PROJ = {projection_json};
const NS = {nutri_strat_json};
const OURA = {oura_json};
const CRONO = {cronometer_json};
const RACE_DATE = '2026-12-07';

// Chart defaults
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = 'rgba(255,255,255,0.04)';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 16;

// Countdown
function updateCountdown() {{
  const target = new Date(RACE_DATE + 'T06:00:00');
  const now = new Date();
  const diff = target - now;
  const el = document.getElementById('countdown');
  if (diff <= 0) {{
    el.innerHTML = '<div class="countdown-unit"><div class="num">RACE DAY</div></div>';
    return;
  }}
  const d = Math.floor(diff / 86400000);
  const h = Math.floor((diff % 86400000) / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  el.innerHTML = `
    <div class="countdown-unit"><div class="num">${{d}}</div><div class="lbl">Days</div></div>
    <div class="countdown-unit"><div class="num">${{h}}</div><div class="lbl">Hours</div></div>
    <div class="countdown-unit"><div class="num">${{m}}</div><div class="lbl">Min</div></div>
    <div class="countdown-unit"><div class="num">${{s}}</div><div class="lbl">Sec</div></div>
  `;
}}
updateCountdown();
setInterval(updateCountdown, 1000);

// Race cards
const raceCardsEl = document.getElementById('race-cards');
const bestTime = Math.min(...RACES.filter(r => r.race_name.includes('70.3')).map(r => r.overall_time_seconds || Infinity));
RACES.forEach(r => {{
  const flag = r.flag || '';
  const time = r.overall_time_display || '--:--:--';
  const isFull = r.is_full;
  const isPR = !isFull && r.overall_time_seconds === bestTime;
  let badge = '';
  if (isFull) badge = '<span class="r-badge badge-full">FULL 140.6</span>';
  else if (isPR) badge = '<span class="r-badge badge-pr">PR</span>';

  const splits = (r.splits || []).filter(s => s.time_seconds).map(s => {{
    const m = Math.floor(s.time_seconds / 60);
    const sec = s.time_seconds % 60;
    return `<span>${{s.name.toUpperCase()}}: <strong>${{Math.floor(s.time_seconds/3600)}}:${{String(Math.floor((s.time_seconds%3600)/60)).padStart(2,'0')}}:${{String(s.time_seconds%60).padStart(2,'0')}}</strong></span>`;
  }}).join('');

  raceCardsEl.innerHTML += `
    <div class="race-card">
      ${{badge}}
      <div class="flag">${{flag}}</div>
      <div class="r-name">${{r.race_name}}</div>
      <div class="r-date">${{r.race_date}}</div>
      <div class="r-time">${{time}}</div>
      <div class="r-meta">
        <span>Points: <strong>${{r.points || '--'}}</strong></span>
        <span>Div Rank: <strong>#${{r.div_rank || '--'}}</strong></span>
        <span>Overall: <strong>#${{r.overall_rank || '--'}}</strong></span>
        ${{splits}}
      </div>
    </div>`;
}});

// Points chart
new Chart(document.getElementById('pointsChart'), {{
  type: 'line',
  data: {{
    labels: RACES.map(r => r.race_name.replace('IRONMAN ','').replace('70.3 ','')),
    datasets: [{{
      label: 'Points',
      data: RACES.map(r => r.points),
      borderColor: '#eab308',
      backgroundColor: 'rgba(234,179,8,0.1)',
      fill: true,
      tension: 0.4,
      pointRadius: 6,
      pointHoverRadius: 9,
      pointBackgroundColor: '#eab308',
      pointBorderColor: '#0c0c14',
      pointBorderWidth: 3,
      borderWidth: 3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ beginAtZero: true, grid: {{ color: 'rgba(255,255,255,0.03)' }} }},
      x: {{ grid: {{ display: false }} }}
    }}
  }}
}});

// Times chart (70.3 only)
const races703 = RACES.filter(r => !r.is_full && r.overall_time_seconds);
new Chart(document.getElementById('timesChart'), {{
  type: 'bar',
  data: {{
    labels: races703.map(r => r.race_name.replace('IRONMAN 70.3 ','')),
    datasets: [{{
      label: 'Time (hours)',
      data: races703.map(r => (r.overall_time_seconds / 3600).toFixed(2)),
      backgroundColor: races703.map(r => r.overall_time_seconds === bestTime ? 'rgba(234,179,8,0.6)' : 'rgba(220,38,38,0.4)'),
      borderColor: races703.map(r => r.overall_time_seconds === bestTime ? '#eab308' : '#dc2626'),
      borderWidth: 1,
      borderRadius: 8,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: ctx => {{
            const secs = races703[ctx.dataIndex].overall_time_seconds;
            const h = Math.floor(secs/3600);
            const m = String(Math.floor((secs%3600)/60)).padStart(2,'0');
            const s = String(secs%60).padStart(2,'0');
            return `${{h}}:${{m}}:${{s}}`;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ display: false }},
      y: {{ grid: {{ display: false }} }}
    }}
  }}
}});

// Splits
const barranquilla = RACES.find(r => r.race_name.includes('Barranquilla'));
if (barranquilla) {{
  const splits = barranquilla.splits.filter(s => s.time_seconds);
  const total = splits.reduce((a,s) => a + s.time_seconds, 0);
  const colors = {{ swim: '#06b6d4', t1: '#94a3b8', bike: '#22c55e', t2: '#94a3b8', run: '#f97316' }};
  const barsEl = document.getElementById('split-bars');

  splits.forEach(s => {{
    const pct = (s.time_seconds / total * 100).toFixed(1);
    const h = Math.floor(s.time_seconds/3600);
    const m = String(Math.floor((s.time_seconds%3600)/60)).padStart(2,'0');
    const sec = String(s.time_seconds%60).padStart(2,'0');
    barsEl.innerHTML += `
      <div class="split-bar">
        <span class="s-label" style="color:${{colors[s.name] || '#94a3b8'}}">${{s.name.toUpperCase()}}</span>
        <div class="s-bar-bg"><div class="s-bar" style="width:${{pct}}%;background:${{colors[s.name] || '#94a3b8'}}"></div></div>
        <span class="s-time">${{h}}:${{m}}:${{sec}}</span>
      </div>`;
  }});

  new Chart(document.getElementById('splitsDonut'), {{
    type: 'doughnut',
    data: {{
      labels: splits.map(s => s.name.toUpperCase()),
      datasets: [{{
        data: splits.map(s => s.time_seconds),
        backgroundColor: splits.map(s => colors[s.name] || '#475569'),
        borderColor: '#12121c',
        borderWidth: 3,
      }}]
    }},
    options: {{
      responsive: true,
      cutout: '65%',
      plugins: {{
        legend: {{ position: 'bottom' }},
        tooltip: {{
          callbacks: {{
            label: ctx => {{
              const secs = ctx.raw;
              const h = Math.floor(secs/3600);
              const m = String(Math.floor((secs%3600)/60)).padStart(2,'0');
              const s = String(secs%60).padStart(2,'0');
              const pct = (secs/total*100).toFixed(1);
              return ` ${{h}}:${{m}}:${{s}} (${{pct}}%)`;
            }}
          }}
        }}
      }}
    }}
  }});
}}

// Weekly volume chart
new Chart(document.getElementById('volumeChart'), {{
  type: 'bar',
  data: {{
    labels: WEEKLY.map(w => {{
      const parts = w.week.split('-W');
      return 'W' + parts[1];
    }}),
    datasets: [
      {{
        label: 'Swim',
        data: WEEKLY.map(w => w.swim_hrs),
        backgroundColor: 'rgba(6,182,212,0.7)',
        borderRadius: 3,
        borderSkipped: false,
      }},
      {{
        label: 'Bike',
        data: WEEKLY.map(w => w.ride_hrs),
        backgroundColor: 'rgba(34,197,94,0.7)',
        borderRadius: 3,
        borderSkipped: false,
      }},
      {{
        label: 'Run',
        data: WEEKLY.map(w => w.run_hrs),
        backgroundColor: 'rgba(249,115,22,0.7)',
        borderRadius: 3,
        borderSkipped: false,
      }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{ stacked: true, title: {{ display: true, text: 'Hours' }}, grid: {{ color: 'rgba(255,255,255,0.03)' }} }}
    }},
    plugins: {{ legend: {{ position: 'top' }} }}
  }}
}});

// Distribution donut
new Chart(document.getElementById('distChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Swim','Bike','Run'],
    datasets: [{{
      data: [SUMMARY.swim.hours, SUMMARY.ride.hours, SUMMARY.run.hours],
      backgroundColor: ['rgba(6,182,212,0.8)','rgba(34,197,94,0.8)','rgba(249,115,22,0.8)'],
      borderColor: '#12121c',
      borderWidth: 3,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '60%',
    plugins: {{
      legend: {{ position: 'bottom' }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.raw}} hours (${{(ctx.raw / (SUMMARY.swim.hours+SUMMARY.ride.hours+SUMMARY.run.hours)*100).toFixed(0)}}%)`
        }}
      }}
    }}
  }}
}});

// ===== PROJECTION =====
const scEl = document.getElementById('scenario-cards');
const scenarios = PROJ.finish_time_projection.scenarios;
const scMeta = [
  {{ key: 'optimistic', cls: 'sc-optimistic', label: 'Optimistic' }},
  {{ key: 'expected', cls: 'sc-expected', label: 'Expected' }},
  {{ key: 'conservative', cls: 'sc-conservative', label: 'Conservative' }},
];
scMeta.forEach(sm => {{
  const sc = scenarios[sm.key];
  scEl.innerHTML += `
    <div class="scenario-card ${{sm.cls}}">
      <div class="sc-label">${{sm.label}}</div>
      <div class="sc-time">${{sc.total_display}}</div>
      <div class="sc-splits">
        <div class="sc-split">
          <span class="sc-s-name" style="color:var(--swim)">Swim</span>
          <span class="sc-s-time">${{sc.swim_display}}</span>
          <span class="sc-s-pace">${{sc.swim_pace}}</span>
        </div>
        <div class="sc-split">
          <span class="sc-s-name" style="color:var(--bike)">Bike</span>
          <span class="sc-s-time">${{sc.bike_display}}</span>
          <span class="sc-s-pace">${{sc.bike_speed_kph}} km/h</span>
        </div>
        <div class="sc-split">
          <span class="sc-s-name" style="color:var(--run)">Run</span>
          <span class="sc-s-time">${{sc.run_display}}</span>
          <span class="sc-s-pace">${{sc.run_pace}}</span>
        </div>
        <div class="sc-split">
          <span class="sc-s-name">Transitions</span>
          <span class="sc-s-time">${{Math.floor(sc.transition_seconds/60)}}:${{String(sc.transition_seconds%60).padStart(2,'0')}}</span>
          <span class="sc-s-pace"></span>
        </div>
      </div>
      <div class="sc-note">${{sc.note}}</div>
    </div>`;
}});

// Adjustments
const adjEl = document.getElementById('adjustments');
const adj = PROJ.finish_time_projection.adjustments;
adjEl.innerHTML = `
  <div class="adj-card">
    <div class="adj-icon">&#9968;</div>
    <div><h4>Bike Elevation</h4><p>${{adj.bike_elevation.description}} Hill penalty: ${{((1-adj.bike_elevation.hill_penalty_factor)*100).toFixed(1)}}%</p></div>
  </div>
  <div class="adj-card">
    <div class="adj-icon">&#127777;&#65039;</div>
    <div><h4>Heat Adjustment</h4><p>${{adj.heat.description}}</p></div>
  </div>
  <div class="adj-card">
    <div class="adj-icon">&#127754;</div>
    <div><h4>Swim Outlier</h4><p>${{adj.swim_outlier.description}}</p></div>
  </div>
`;

// Confidence
const confEl = document.getElementById('confidence');
const confLevel = PROJ.finish_time_projection.confidence.level;
const confPct = confLevel === 'low' ? 25 : confLevel === 'low-moderate' ? 40 : confLevel === 'moderate' ? 60 : confLevel === 'high' ? 85 : 40;
confEl.innerHTML = `
  <h4>Confidence Level: ${{confLevel.replace('-',' ').replace(/\\b\\w/g, l => l.toUpperCase())}}</h4>
  <div class="conf-track"><div class="conf-fill" style="width:${{confPct}}%"></div></div>
  <ul class="conf-notes">
    ${{PROJ.finish_time_projection.confidence.notes.map(n => `<li>${{n}}</li>`).join('')}}
  </ul>
`;

// Pace comparison chart
const racePaces = PROJ.historical_analysis.race_paces;
const projExp = scenarios.expected;
new Chart(document.getElementById('paceChart'), {{
  type: 'bar',
  data: {{
    labels: [...racePaces.map(r => r.race_name.replace('IRONMAN 70.3 ','')), 'Puerto Rico\\n(Projected)'],
    datasets: [
      {{
        label: 'Swim (min)',
        data: [...racePaces.map(r => (r.swim_seconds/60).toFixed(1)), (projExp.swim_seconds/60).toFixed(1)],
        backgroundColor: [...racePaces.map(()=>'rgba(6,182,212,0.7)'), 'rgba(6,182,212,0.35)'],
        borderColor: [...racePaces.map(()=>'#06b6d4'), '#06b6d4'],
        borderWidth: [...racePaces.map(()=>0), 2],
        borderDash: [5,5],
        borderRadius: 4,
      }},
      {{
        label: 'Bike (min)',
        data: [...racePaces.map(r => (r.bike_seconds/60).toFixed(1)), (projExp.bike_seconds/60).toFixed(1)],
        backgroundColor: [...racePaces.map(()=>'rgba(34,197,94,0.7)'), 'rgba(34,197,94,0.35)'],
        borderColor: [...racePaces.map(()=>'#22c55e'), '#22c55e'],
        borderWidth: [...racePaces.map(()=>0), 2],
        borderDash: [5,5],
        borderRadius: 4,
      }},
      {{
        label: 'Run (min)',
        data: [...racePaces.map(r => (r.run_seconds/60).toFixed(1)), (projExp.run_seconds/60).toFixed(1)],
        backgroundColor: [...racePaces.map(()=>'rgba(249,115,22,0.7)'), 'rgba(249,115,22,0.35)'],
        borderColor: [...racePaces.map(()=>'#f97316'), '#f97316'],
        borderWidth: [...racePaces.map(()=>0), 2],
        borderDash: [5,5],
        borderRadius: 4,
      }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{ title: {{ display: true, text: 'Minutes' }}, grid: {{ color: 'rgba(255,255,255,0.03)' }} }}
    }},
    plugins: {{ legend: {{ position: 'top' }} }}
  }}
}});

// Projected split donut
new Chart(document.getElementById('projSplitDonut'), {{
  type: 'doughnut',
  data: {{
    labels: ['Swim','Bike','Run','Transitions'],
    datasets: [{{
      data: [projExp.swim_seconds, projExp.bike_seconds, projExp.run_seconds, projExp.transition_seconds],
      backgroundColor: ['rgba(6,182,212,0.8)','rgba(34,197,94,0.8)','rgba(249,115,22,0.8)','rgba(148,163,184,0.5)'],
      borderColor: '#12121c',
      borderWidth: 3,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '60%',
    plugins: {{
      legend: {{ position: 'bottom' }},
      tooltip: {{
        callbacks: {{
          label: ctx => {{
            const secs = ctx.raw;
            const h = Math.floor(secs/3600);
            const m = String(Math.floor((secs%3600)/60)).padStart(2,'0');
            const s = String(secs%60).padStart(2,'0');
            const pct = (secs/projExp.total_seconds*100).toFixed(1);
            return ` ${{h}}:${{m}}:${{s}} (${{pct}}%)`;
          }}
        }}
      }}
    }}
  }}
}});

// Carb loading protocol
const clEl = document.getElementById('carb-load');
NS.race_week_carb_loading.days.forEach(d => {{
  const meals = d.meal_ideas ? `<ul class="cl-meals">${{d.meal_ideas.map(m => `<li>${{m}}</li>`).join('')}}</ul>` : '';
  clEl.innerHTML += `
    <div class="cl-day">
      <div class="cl-label">${{d.label}}</div>
      <div class="cl-focus">${{d.focus}}</div>
      <div class="cl-macros">
        <div class="cl-macro"><div class="clm-val" style="color:var(--gold)">${{d.carbs_g}}g</div><div class="clm-label">Carbs (${{d.carbs_g_per_kg}} g/kg)</div></div>
        <div class="cl-macro"><div class="clm-val" style="color:#818cf8">${{d.protein_g}}g</div><div class="clm-label">Protein</div></div>
        <div class="cl-macro"><div class="clm-val" style="color:#f472b6">${{d.fat_g}}g</div><div class="clm-label">Fat</div></div>
      </div>
      <div class="cl-notes">
        <p>&#127813; ${{d.fiber_note}}</p>
        <p>&#128167; ${{d.hydration_ml}}ml &mdash; ${{d.sodium_note}}</p>
        ${{d.important ? `<p style="color:var(--gold);margin-top:0.5rem"><strong>&#9888; ${{d.important}}</strong></p>` : ''}}
      </div>
      ${{meals}}
    </div>`;
}});

// Pre-race meal
const prm = NS.race_morning_pre_race_meal;
const optA = prm.recommended_meal.option_a;
const optB = prm.recommended_meal.option_b;
function mealHtml(opt) {{
  return `
    <div class="meal-option">
      <h4>${{opt.name}}</h4>
      <ul class="meal-items">
        ${{opt.items.map(i => `<li>${{i.food}} <span>${{i.amount}} &mdash; ${{i.carbs_g}}g C</span></li>`).join('')}}
      </ul>
      <div class="meal-total">Total carbs: <span style="color:var(--gold)">${{opt.total_carbs_g}}g</span></div>
      <div class="meal-note">${{opt.note}}</div>
    </div>`;
}}
document.getElementById('pre-race-meal').innerHTML = `
  <div>
    <h3>&#127859; Pre-Race Meal Options</h3>
    <p style="font-size:0.8rem;color:var(--text3);margin-bottom:1rem">${{prm.timing}} before swim start &mdash; target ${{prm.carb_target_g}}g carbs (${{prm.carb_target_g_per_kg}} g/kg)</p>
    ${{mealHtml(optA)}}
    ${{mealHtml(optB)}}
  </div>
  <div>
    <h3>&#9749; Top-Up &amp; Principles</h3>
    <div class="meal-option" style="margin-top:1.5rem">
      <h4>15-20 min before swim</h4>
      <p style="font-size:0.8rem;color:var(--text2)">${{prm.top_up.items}}</p>
      <div class="meal-note">${{prm.top_up.note}}</div>
    </div>
    <ul class="np-notes" style="margin-top:1rem">
      ${{prm.principles.map(p => `<li>${{p}}</li>`).join('')}}
    </ul>
  </div>
`;

// Race totals
const rts = NS.race_totals_summary;
document.getElementById('race-totals').innerHTML = `
  <div class="rt-card">
    <div class="rt-icon">&#127838;</div>
    <div class="rt-val" style="color:var(--gold)">${{rts.total_carbs_g}}g</div>
    <div class="rt-range">~${{rts.caloric_intake_estimate_kcal}} kcal</div>
    <div class="rt-label">Total Carbs</div>
  </div>
  <div class="rt-card">
    <div class="rt-icon">&#129474;</div>
    <div class="rt-val" style="color:var(--run)">${{rts.total_sodium_mg}}mg</div>
    <div class="rt-range">${{rts.projected_duration}}</div>
    <div class="rt-label">Total Sodium</div>
  </div>
  <div class="rt-card">
    <div class="rt-icon">&#128167;</div>
    <div class="rt-val" style="color:var(--swim)">${{(rts.total_fluid_ml/1000).toFixed(1)}}L</div>
    <div class="rt-range">Tropical conditions</div>
    <div class="rt-label">Total Fluid</div>
  </div>
`;

// Gap alert
const gap = NS.race_day_nutrition_timeline.fueling_gap_analysis;
document.getElementById('gap-alert').innerHTML = `
  <div class="ga-icon">&#9888;&#65039;</div>
  <div>
    <h4>Fueling Gap: Gut Training Required</h4>
    <p>${{gap.recommendation}}</p>
    <div class="ga-numbers">
      <div class="ga-num"><div class="ga-val" style="color:var(--text2)">${{gap.current_workout_rate_g_per_hr}}</div><div class="ga-lbl">Current g/hr</div></div>
      <div class="ga-num"><div class="ga-val" style="color:var(--gold)">${{gap.bike_target_rate_g_per_hr}}</div><div class="ga-lbl">Target g/hr</div></div>
      <div class="ga-num"><div class="ga-val" style="color:var(--red)">+${{gap.gap_g_per_hr}}</div><div class="ga-lbl">Gap g/hr</div></div>
    </div>
  </div>
`;

// Timeline tables
function renderTimeline(containerId, legKey, icon, color) {{
  const leg = NS.race_day_nutrition_timeline[legKey];
  const el = document.getElementById(containerId);
  const schedule = leg.fueling_schedule;

  el.innerHTML = `
    <div class="tl-header">
      <h3>${{icon}} ${{legKey.charAt(0).toUpperCase() + legKey.slice(1)}} Fueling Timeline</h3>
      <span class="tl-meta">${{leg.duration_display}} &mdash; ${{leg.target_carb_rate_g_per_hr}}g carbs/hr &mdash; ${{leg.target_fluid_rate_ml_per_hr}}ml fluid/hr</span>
    </div>
    <table class="tl-table">
      <thead><tr>
        <th>Time</th>
        ${{legKey === 'run' ? '<th>~km</th>' : ''}}
        <th>Action</th>
        <th>Carbs</th>
        <th>Sodium</th>
        <th>Fluid</th>
        <th>Cumul. Carbs</th>
      </tr></thead>
      <tbody>
        ${{schedule.map(s => `
          <tr>
            <td>${{s.elapsed}}</td>
            ${{legKey === 'run' ? `<td>${{s.approx_km}}</td>` : ''}}
            <td>${{s.action}}</td>
            <td>${{s.carbs_g}}g</td>
            <td>${{s.sodium_mg}}mg</td>
            <td>${{s.fluid_ml}}ml</td>
            <td class="tl-cumul">${{s.cumulative_carbs_g}}g</td>
          </tr>
        `).join('')}}
      </tbody>
    </table>
    <div class="tl-carry">
      <h4>What to carry:</h4>
      <ul>${{leg.what_to_carry.map(w => `<li>${{w}}</li>`).join('')}}</ul>
    </div>
  `;
}}
renderTimeline('bike-timeline', 'bike', '&#128692;', 'var(--bike)');
renderTimeline('run-timeline', 'run', '&#127939;', 'var(--run)');

// Key reminders
const remEl = document.getElementById('reminders');
NS.key_reminders.forEach(r => {{
  remEl.innerHTML += `<div class="reminder-item">${{r}}</div>`;
}});

// Weakness
const wk = PROJ.training_analysis.weakest_discipline;
document.getElementById('weakness').innerHTML = `
  <h3>&#9888;&#65039; Weakest Discipline: ${{wk.discipline.charAt(0).toUpperCase() + wk.discipline.slice(1)}}</h3>
  <p class="wk-reason">${{wk.reasoning}}</p>
  <ul>
    ${{wk.improvement_suggestions.map(s => `<li>${{s}}</li>`).join('')}}
  </ul>
`;

// Training flags
const flagsEl = document.getElementById('training-flags');
PROJ.training_analysis.training_flags.forEach(f => {{
  const cls = f.type === 'caution' ? 'flag-caution' : 'flag-concern';
  const icon = f.type === 'caution' ? '&#9888;&#65039;' : '&#128680;';
  flagsEl.innerHTML += `
    <div class="flag-card ${{cls}}">
      <span class="flag-icon">${{icon}}</span>
      <span class="flag-text">${{f.message}}</span>
    </div>`;
}});

// ===== RECOVERY / OURA =====
const dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const recoveryEl = document.getElementById('recovery-days');
const bodyEl = document.getElementById('body-metrics');

// Body metrics from cronometer biometrics
if (CRONO.biometrics && CRONO.biometrics.length) {{
  const latest = CRONO.biometrics[CRONO.biometrics.length - 1];
  const first = CRONO.biometrics[0];
  const wDelta = (latest.weight_kg - first.weight_kg).toFixed(1);
  const fDelta = (latest.body_fat_pct - first.body_fat_pct).toFixed(1);
  const wClass = wDelta < 0 ? 'delta-down' : wDelta > 0 ? 'delta-up' : 'delta-neutral';
  const fClass = fDelta < 0 ? 'delta-down' : fDelta > 0 ? 'delta-up' : 'delta-neutral';

  // Avg sleep + readiness
  const avgSleep = OURA.sleep.length ? Math.round(OURA.sleep.reduce((a,s) => a + s.score, 0) / OURA.sleep.length) : '--';
  const avgReady = OURA.readiness.length ? Math.round(OURA.readiness.reduce((a,r) => a + r.score, 0) / OURA.readiness.length) : '--';

  bodyEl.innerHTML = `
    <div class="body-card">
      <div class="b-icon">&#9878;&#65039;</div>
      <div class="b-val">${{latest.weight_kg}}</div>
      <div class="b-unit">kg</div>
      <div class="b-label">Weight</div>
      <div class="b-delta ${{wClass}}">${{wDelta > 0 ? '+' : ''}}${{wDelta}} kg this week</div>
    </div>
    <div class="body-card">
      <div class="b-icon">&#128170;</div>
      <div class="b-val">${{latest.body_fat_pct}}</div>
      <div class="b-unit">%</div>
      <div class="b-label">Body Fat</div>
      <div class="b-delta ${{fClass}}">${{fDelta > 0 ? '+' : ''}}${{fDelta}}% this week</div>
    </div>
    <div class="body-card">
      <div class="b-icon">&#128564;</div>
      <div class="b-val" style="color:#818cf8">${{avgSleep}}</div>
      <div class="b-unit">/ 100</div>
      <div class="b-label">Avg Sleep Score</div>
    </div>
    <div class="body-card">
      <div class="b-icon">&#9889;</div>
      <div class="b-val" style="color:#34d399">${{avgReady}}</div>
      <div class="b-unit">/ 100</div>
      <div class="b-label">Avg Readiness</div>
    </div>
  `;
}}

// Daily recovery cards
OURA.sleep.forEach(s => {{
  const dt = new Date(s.day + 'T12:00:00');
  const dayName = dayNames[dt.getDay()];
  const dateStr = s.day.slice(5); // MM-DD

  // Find matching readiness
  const ready = OURA.readiness.find(r => r.day === s.day);
  const readyScore = ready ? ready.score : null;

  // Find matching sleep session for HR/HRV
  const session = OURA.sessions ? OURA.sessions.find(ss => ss.day === s.day) : null;

  let sessionHtml = '';
  if (session) {{
    sessionHtml = `
      <div class="mini-stat">RHR: <strong>${{session.average_heart_rate}}</strong> bpm</div>
      <div class="mini-stat">HRV: <strong>${{session.average_hrv}}</strong> ms</div>
      <div class="mini-stat">Sleep: <strong>${{(session.total_sleep_duration_sec/3600).toFixed(1)}}</strong>h</div>
    `;
  }}

  recoveryEl.innerHTML += `
    <div class="day-card">
      <div class="day-name">${{dayName}}</div>
      <div class="day-date">${{dateStr}}</div>
      <div class="sleep-score">
        <div class="score-ring" style="--ring-color:#818cf8;--ring-pct:${{s.score}}">${{s.score}}</div>
        <div class="score-label">Sleep</div>
      </div>
      <div class="day-divider"></div>
      ${{readyScore !== null ? `
        <div class="readiness-score">
          <div class="score-ring" style="--ring-color:#34d399;--ring-pct:${{readyScore}}">${{readyScore}}</div>
          <div class="score-label">Readiness</div>
        </div>
      ` : ''}}
      ${{sessionHtml}}
    </div>
  `;
}});

// Sleep & Readiness chart
new Chart(document.getElementById('sleepReadinessChart'), {{
  type: 'line',
  data: {{
    labels: OURA.sleep.map(s => s.day.slice(5)),
    datasets: [
      {{
        label: 'Sleep Score',
        data: OURA.sleep.map(s => s.score),
        borderColor: '#818cf8',
        backgroundColor: 'rgba(129,140,248,0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: 5,
        pointBackgroundColor: '#818cf8',
        pointBorderColor: '#0c0c14',
        pointBorderWidth: 2,
        borderWidth: 2.5,
      }},
      {{
        label: 'Readiness',
        data: OURA.readiness.map(r => r.score),
        borderColor: '#34d399',
        backgroundColor: 'rgba(52,211,153,0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: 5,
        pointBackgroundColor: '#34d399',
        pointBorderColor: '#0c0c14',
        pointBorderWidth: 2,
        borderWidth: 2.5,
      }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      y: {{ min: 30, max: 100, grid: {{ color: 'rgba(255,255,255,0.03)' }} }},
      x: {{ grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ position: 'top' }} }}
  }}
}});

// Sleep radar
if (OURA.sleep.length) {{
  const contributors = ['deep_sleep','efficiency','latency','rem_sleep','restfulness','timing','total_sleep'];
  const labels = ['Deep Sleep','Efficiency','Latency','REM Sleep','Restfulness','Timing','Total Sleep'];
  const avgContribs = contributors.map(c => {{
    const vals = OURA.sleep.map(s => s.contributors[c]).filter(v => v != null);
    return vals.length ? Math.round(vals.reduce((a,v) => a+v, 0) / vals.length) : 0;
  }});

  new Chart(document.getElementById('sleepRadar'), {{
    type: 'radar',
    data: {{
      labels: labels,
      datasets: [{{
        label: '7-Day Avg',
        data: avgContribs,
        borderColor: '#818cf8',
        backgroundColor: 'rgba(129,140,248,0.15)',
        pointBackgroundColor: '#818cf8',
        pointBorderColor: '#0c0c14',
        pointBorderWidth: 2,
        borderWidth: 2,
      }}]
    }},
    options: {{
      responsive: true,
      scales: {{
        r: {{
          beginAtZero: true, max: 100,
          grid: {{ color: 'rgba(255,255,255,0.05)' }},
          angleLines: {{ color: 'rgba(255,255,255,0.05)' }},
          pointLabels: {{ font: {{ size: 10 }} }},
          ticks: {{ display: false }}
        }}
      }},
      plugins: {{ legend: {{ display: false }} }}
    }}
  }});
}}

// ===== NUTRITION / CRONOMETER =====
const nutriEl = document.getElementById('nutri-days');
const maxKcal = Math.max(...CRONO.daily.map(d => d.energy_kcal));
const targetKcal = CRONO.targets.energy_kcal || 3200;
const targetProtein = CRONO.targets.protein_g || 165;
const targetCarbs = CRONO.targets.carbs_g || 430;
const targetFat = CRONO.targets.fat_g || 95;

CRONO.daily.forEach(d => {{
  const dt = new Date(d.date + 'T12:00:00');
  const dayName = dayNames[dt.getDay()];
  const isHigh = d.energy_kcal > targetKcal * 1.15;
  const m = d.macros;

  nutriEl.innerHTML += `
    <div class="nutri-day ${{isHigh ? 'high-day' : ''}}">
      <div class="nd-date">${{dayName}} ${{d.date.slice(5)}}</div>
      <div class="nd-kcal">${{d.energy_kcal.toLocaleString()}}</div>
      <div class="nd-kcal-label">kcal</div>
      <div class="macro-bars">
        <div class="macro-bar">
          <span class="mb-label">P</span>
          <div class="mb-bg"><div class="mb-fill mb-protein" style="width:${{Math.min(100, m.protein_g/targetProtein*100).toFixed(0)}}%"></div></div>
          <span class="mb-val">${{m.protein_g}}g</span>
        </div>
        <div class="macro-bar">
          <span class="mb-label">C</span>
          <div class="mb-bg"><div class="mb-fill mb-carbs" style="width:${{Math.min(100, m.carbs_g/targetCarbs*100).toFixed(0)}}%"></div></div>
          <span class="mb-val">${{m.carbs_g}}g</span>
        </div>
        <div class="macro-bar">
          <span class="mb-label">F</span>
          <div class="mb-bg"><div class="mb-fill mb-fat" style="width:${{Math.min(100, m.fat_g/targetFat*100).toFixed(0)}}%"></div></div>
          <span class="mb-val">${{m.fat_g}}g</span>
        </div>
      </div>
      <div class="nd-water">&#128167; <strong>${{(d.water_ml/1000).toFixed(1)}}L</strong></div>
    </div>
  `;
}});

// Macro stacked bar chart
new Chart(document.getElementById('macroChart'), {{
  type: 'bar',
  data: {{
    labels: CRONO.daily.map(d => d.date.slice(5)),
    datasets: [
      {{
        label: 'Protein',
        data: CRONO.daily.map(d => d.macros.protein_g * 4),
        backgroundColor: 'rgba(129,140,248,0.8)',
        borderRadius: 2,
        borderSkipped: false,
      }},
      {{
        label: 'Carbs',
        data: CRONO.daily.map(d => d.macros.carbs_g * 4),
        backgroundColor: 'rgba(234,179,8,0.8)',
        borderRadius: 2,
        borderSkipped: false,
      }},
      {{
        label: 'Fat',
        data: CRONO.daily.map(d => d.macros.fat_g * 9),
        backgroundColor: 'rgba(244,114,182,0.8)',
        borderRadius: 2,
        borderSkipped: false,
      }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }} }},
      y: {{
        stacked: true,
        title: {{ display: true, text: 'kcal' }},
        grid: {{ color: 'rgba(255,255,255,0.03)' }}
      }}
    }},
    plugins: {{
      legend: {{ position: 'top' }},
      annotation: undefined,
    }}
  }}
}});

// Hydration & Sodium chart
new Chart(document.getElementById('hydroChart'), {{
  type: 'bar',
  data: {{
    labels: CRONO.daily.map(d => d.date.slice(5)),
    datasets: [
      {{
        label: 'Water (L)',
        data: CRONO.daily.map(d => (d.water_ml / 1000).toFixed(1)),
        backgroundColor: 'rgba(6,182,212,0.7)',
        borderRadius: 6,
        yAxisID: 'y',
      }},
      {{
        label: 'Sodium (mg)',
        data: CRONO.daily.map(d => d.key_micronutrients.sodium_mg),
        type: 'line',
        borderColor: '#f97316',
        backgroundColor: 'rgba(249,115,22,0.1)',
        pointBackgroundColor: '#f97316',
        pointBorderColor: '#0c0c14',
        pointBorderWidth: 2,
        pointRadius: 5,
        borderWidth: 2.5,
        tension: 0.4,
        fill: false,
        yAxisID: 'y1',
      }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      y: {{
        position: 'left',
        title: {{ display: true, text: 'Liters' }},
        grid: {{ color: 'rgba(255,255,255,0.03)' }},
      }},
      y1: {{
        position: 'right',
        title: {{ display: true, text: 'mg' }},
        grid: {{ display: false }},
      }},
      x: {{ grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ position: 'top' }} }}
  }}
}});

// Scroll reveal
const observer = new IntersectionObserver((entries) => {{
  entries.forEach(e => {{ if (e.isIntersecting) {{ e.target.classList.add('visible'); }} }});
}}, {{ threshold: 0.1 }});
document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
</script>
</body>
</html>"""


def main():
    races = load_races()
    objective = load_objective()
    weekly_training, training_summary = process_strava()
    oura = load_oura()
    cronometer = load_cronometer()
    projection = load_projection()
    nutri_strategy = load_nutrition_strategy()
    html = build_html(races, objective, weekly_training, training_summary, oura, cronometer, projection, nutri_strategy)
    OUTPUT.write_text(html)
    print(f"Dashboard generated: {OUTPUT}")
    print(f"Open in browser: file://{OUTPUT}")


if __name__ == "__main__":
    main()

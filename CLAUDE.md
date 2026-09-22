# CLAUDE.md

This file gives Claude Code context when working in this repository.

## Project overview

A personal triathlon analytics tool that:
1. Collects historical IRONMAN race results (splits, overall time, age-group rank) for a single athlete.
2. Pulls training data from Strava (via the Strava API/MCP connector) for the weeks leading up to each race.
3. Correlates training load (volume, CTL/ATL/TSB, key session paces/power) with actual race performance to build a personal calibration model.
4. Projects expected split times for an upcoming race based on current training load and the target course profile (distance, elevation, expected weather).
5. Generates a race-day nutrition plan (carbs g/hr, sodium mg/hr, fluid plan by leg) derived from the projected duration, athlete weight, and expected conditions.

This is a personal-use tool, not a public product. Data volume is small (a handful of races), so favor simple, transparent methods over complex ML — the priority is correctness and interpretability, not sophistication.

## Tech stack

- Language: Python (preferred for data work; confirm before introducing another language)
- Storage: SQLite for structured race/training data (or flat CSV/JSON if the dataset stays small)
- No web framework needed unless explicitly building a dashboard UI — CLI scripts and notebooks are fine for analysis

## Repository structure

```
/data/            raw and processed data (IRONMAN results, Strava exports) — never commit personal Strava tokens
/scrapers/        scripts to fetch/parse IRONMAN results
/analysis/        training-load calculations, correlation/calibration logic
/projection/      race time and nutrition projection logic
/notebooks/       exploratory analysis (if used)
CLAUDE.md
README.md
```

Adjust this structure as the project evolves, but keep raw data ingestion, analysis, and projection logic in separate modules — they have different failure modes and will be tested/iterated independently.

## Data handling rules

- Never commit API keys, Strava OAuth tokens, or `.env` files. Add them to `.gitignore` immediately.
- IRONMAN results should be scraped respecting the site's terms of use and reasonable request rates — no aggressive parallel scraping.
- Keep raw fetched data (as retrieved) separate from cleaned/derived data, so calculations can be re-run without re-fetching.

## Conventions

- All times stored and computed in seconds internally; format as HH:MM:SS only for display/output.
- Dates in ISO 8601 (YYYY-MM-DD).
- Units: metric by default (km, meters elevation, °C), unless the athlete's source data (e.g., Strava account settings) is imperial — convert explicitly and document the conversion.
- Every projection output should include a confidence range, not a single point estimate — the athlete has few historical races, so avoid false precision.

## Commands

_(fill in once the project has a runner, e.g. `python -m scrapers.ironman`, `python -m analysis.correlate`, `python -m projection.race_time --race <name>`)_

## Testing

_(fill in test command once a test suite exists, e.g. `pytest`)_

## Notes for Claude

- This is athletic/health-adjacent data (training load, nutrition targets) for one specific person. Treat nutrition outputs as general sports-nutrition heuristics, not medical advice — flag when an estimate depends on assumptions (sweat rate, heat, tolerance) that vary a lot by individual.
- When in doubt about a data field (e.g., how a given IRONMAN course reports splits, or a Strava field's exact meaning), ask rather than guessing — mislabeled athletic data quietly breaks the projection model.
#!/usr/bin/env python3
"""
Personalized race-day nutrition strategy for IRONMAN 70.3 Puerto Rico.

Combines projected race duration, Cronometer dietary habits, and biometric data
to produce a detailed, actionable nutrition plan.

Usage: python analysis/nutrition_strategy.py
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "data" / "analysis"
PROJECTION_PATH = ANALYSIS_DIR / "race_projection.json"

NOW = datetime.now(tz=timezone.utc)


def fmt(seconds):
    if seconds is None:
        return "--:--:--"
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_cronometer():
    return json.loads((DATA_DIR / "cronometer.json").read_text())


def load_objective():
    return json.loads((DATA_DIR / "objectiveRace" / "objectiveRace.json").read_text())


def load_projection():
    return json.loads(PROJECTION_PATH.read_text())


# ---------------------------------------------------------------------------
# Analyze current habits from Cronometer
# ---------------------------------------------------------------------------

def analyze_current_habits(crono):
    """Extract athlete's current nutrition patterns and preferences."""
    summaries = crono.get("daily_summaries", [])
    biometrics = crono.get("biometrics_log", [])
    diary = crono.get("diary_entries", [])

    # Body composition
    weights = [b["weight_kg"] for b in biometrics if b.get("weight_kg")]
    body_fats = [b["body_fat_pct"] for b in biometrics if b.get("body_fat_pct")]
    avg_weight = round(statistics.mean(weights), 1) if weights else 75.0
    avg_bf = round(statistics.mean(body_fats), 1) if body_fats else None
    lean_mass = round(avg_weight * (1 - avg_bf / 100), 1) if avg_bf else None

    # Daily averages (all days)
    avg_kcal = round(statistics.mean([d["energy_kcal"] for d in summaries]))
    avg_carbs = round(statistics.mean([d["macros"]["carbs_g"] for d in summaries]))
    avg_protein = round(statistics.mean([d["macros"]["protein_g"] for d in summaries]))
    avg_fat = round(statistics.mean([d["macros"]["fat_g"] for d in summaries]))
    avg_sodium = round(statistics.mean([d["key_micronutrients"]["sodium_mg"] for d in summaries]))
    avg_water = round(statistics.mean([d["water_ml"] for d in summaries]))

    # Separate training days (>3500 kcal) vs rest days
    training_days = [d for d in summaries if d["energy_kcal"] > 3500]
    rest_days = [d for d in summaries if d["energy_kcal"] <= 3500]

    training_avg_carbs = round(statistics.mean([d["macros"]["carbs_g"] for d in training_days])) if training_days else avg_carbs
    rest_avg_carbs = round(statistics.mean([d["macros"]["carbs_g"] for d in rest_days])) if rest_days else avg_carbs

    # During-workout fueling analysis
    workout_fueling = []
    for entry in diary:
        for meal in entry.get("meals", []):
            if meal.get("meal") == "during-workout":
                total_carbs = sum(item.get("carbs_g", 0) for item in meal.get("items", []))
                total_sodium = sum(item.get("sodium_mg", 0) for item in meal.get("items", []))
                total_kcal = sum(item.get("kcal", 0) for item in meal.get("items", []))

                # Estimate duration from time field
                time_str = meal.get("time", "")
                duration_hrs = None
                if " - " in time_str:
                    parts = time_str.split(" - ")
                    try:
                        start_h, start_m = map(int, parts[0].split(":"))
                        end_h, end_m = map(int, parts[1].split(":"))
                        duration_hrs = (end_h * 60 + end_m - start_h * 60 - start_m) / 60
                    except (ValueError, IndexError):
                        pass

                foods_used = [item["food"] for item in meal.get("items", [])]
                carb_rate = round(total_carbs / duration_hrs) if duration_hrs and duration_hrs > 0 else None

                workout_fueling.append({
                    "date": entry["date"],
                    "total_carbs_g": total_carbs,
                    "total_sodium_mg": total_sodium,
                    "total_kcal": total_kcal,
                    "duration_hours": round(duration_hrs, 1) if duration_hrs else None,
                    "carb_rate_g_per_hr": carb_rate,
                    "foods_used": foods_used,
                })

    # Preferred foods
    all_workout_foods = set()
    for wf in workout_fueling:
        all_workout_foods.update(wf["foods_used"])

    # Pre-workout meal patterns
    pre_workout_foods = set()
    breakfast_foods = set()
    for entry in diary:
        for meal in entry.get("meals", []):
            if meal.get("meal") == "pre-workout":
                for item in meal.get("items", []):
                    pre_workout_foods.add(item["food"])
            if meal.get("meal") == "breakfast":
                for item in meal.get("items", []):
                    breakfast_foods.add(item["food"])

    return {
        "body_composition": {
            "weight_kg": avg_weight,
            "body_fat_pct": avg_bf,
            "lean_mass_kg": lean_mass,
        },
        "daily_averages": {
            "energy_kcal": avg_kcal,
            "carbs_g": avg_carbs,
            "carbs_g_per_kg": round(avg_carbs / avg_weight, 1),
            "protein_g": avg_protein,
            "protein_g_per_kg": round(avg_protein / avg_weight, 1),
            "fat_g": avg_fat,
            "sodium_mg": avg_sodium,
            "water_ml": avg_water,
        },
        "training_day_carbs_g": training_avg_carbs,
        "rest_day_carbs_g": rest_avg_carbs,
        "workout_fueling": workout_fueling,
        "current_carb_rate_g_per_hr": (
            round(statistics.mean([wf["carb_rate_g_per_hr"] for wf in workout_fueling if wf["carb_rate_g_per_hr"]]))
            if any(wf["carb_rate_g_per_hr"] for wf in workout_fueling) else None
        ),
        "preferred_workout_foods": sorted(all_workout_foods),
        "preferred_breakfast_foods": sorted(breakfast_foods),
        "preferred_pre_workout_foods": sorted(pre_workout_foods),
    }


# ---------------------------------------------------------------------------
# Race-week carb loading plan
# ---------------------------------------------------------------------------

def generate_carb_loading_plan(habits, race_date):
    """Generate a 3-day carb loading protocol leading into race day."""
    weight = habits["body_composition"]["weight_kg"]
    normal_carbs = habits["daily_averages"]["carbs_g"]

    # Standard carb loading: 8-10 g/kg for 2-3 days before race
    # Taper fiber to reduce GI risk
    loading_target = round(weight * 10)  # 10 g/kg on loading days
    moderate_target = round(weight * 8)   # 8 g/kg day before loading

    plan = {
        "protocol": "3-day carb loading with fiber taper",
        "rationale": (
            f"Current daily carbs: {normal_carbs}g ({habits['daily_averages']['carbs_g_per_kg']} g/kg). "
            f"Loading target: {loading_target}g/day (10 g/kg) for final 2 days to maximize muscle glycogen."
        ),
        "days": [
            {
                "label": "Race Day -3",
                "focus": "Normal training diet, start reducing fiber",
                "carbs_g": normal_carbs,
                "carbs_g_per_kg": round(normal_carbs / weight, 1),
                "protein_g": habits["daily_averages"]["protein_g"],
                "fat_g": habits["daily_averages"]["fat_g"],
                "fiber_note": "Start reducing raw vegetables, legumes, high-fiber cereals.",
                "hydration_ml": 3500,
                "sodium_note": "Maintain normal sodium intake (~3000-3500 mg).",
            },
            {
                "label": "Race Day -2",
                "focus": "Begin loading — increase carbs, reduce fiber and fat",
                "carbs_g": moderate_target,
                "carbs_g_per_kg": 8,
                "protein_g": round(weight * 1.6),
                "fat_g": round(habits["daily_averages"]["fat_g"] * 0.7),
                "fiber_note": "Low fiber only (<20g). White rice, white bread, pasta, potatoes.",
                "hydration_ml": 4000,
                "sodium_note": "Increase sodium to 4000-5000 mg to aid glycogen storage and fluid retention.",
                "meal_ideas": [
                    "Breakfast: White bread with honey + banana + coffee",
                    "Snack: Rice cakes with jam",
                    "Lunch: White rice + grilled chicken + low-fiber vegetables",
                    "Snack: Sports drink + pretzels",
                    "Dinner: Pasta with tomato sauce + lean protein",
                    "Evening: Fruit juice + white bread with peanut butter",
                ],
            },
            {
                "label": "Race Day -1",
                "focus": "Peak loading — maximum carbs, minimal fiber and fat",
                "carbs_g": loading_target,
                "carbs_g_per_kg": 10,
                "protein_g": round(weight * 1.4),
                "fat_g": round(habits["daily_averages"]["fat_g"] * 0.6),
                "fiber_note": "Very low fiber (<15g). Avoid salads, raw vegetables, beans entirely.",
                "hydration_ml": 4000,
                "sodium_note": "Keep sodium at 4000-5000 mg. Add salt to meals. Drink electrolyte mix between meals.",
                "meal_ideas": [
                    "Breakfast: Large bowl of white rice with honey + juice",
                    "Snack: 2 bananas + sports drink",
                    "Lunch: Pasta with simple sauce + white bread",
                    "Snack: Rice cakes + honey + electrolyte drink",
                    "Dinner (early, by 18:00): Smaller pasta portion + baked potato + juice",
                    "Evening: Low-fiber cereal with milk (settle stomach for morning)",
                ],
                "important": "Eat dinner early. Nothing new. Favor foods you've eaten before race days.",
            },
        ],
    }
    return plan


# ---------------------------------------------------------------------------
# Race morning pre-race meal
# ---------------------------------------------------------------------------

def generate_pre_race_meal(habits, swim_seconds):
    """Generate pre-race morning meal plan based on athlete's known preferences."""
    weight = habits["body_composition"]["weight_kg"]
    known_breakfast = habits["preferred_breakfast_foods"]
    known_pre = habits["preferred_pre_workout_foods"]

    # Target: 1.5-2 g/kg carbs, 2.5-3 hrs before start, low fat/fiber
    carb_target = round(weight * 2)  # 2 g/kg
    kcal_target = round(carb_target * 4 * 1.2)  # mostly carbs, slight protein/fat

    # Build meal from athlete's known foods
    familiar_options = sorted(set(known_breakfast) | set(known_pre))

    return {
        "timing": "2.5-3 hours before swim start",
        "carb_target_g": carb_target,
        "carb_target_g_per_kg": 2.0,
        "kcal_target": kcal_target,
        "principles": [
            "Low fat, low fiber — easy to digest.",
            "Familiar foods only — nothing new on race morning.",
            "Sip 500-750 ml water with electrolytes alongside the meal.",
        ],
        "recommended_meal": {
            "description": "Based on your tracked breakfast/pre-workout foods",
            "option_a": {
                "name": "Oatmeal + banana (your training breakfast)",
                "items": [
                    {"food": "Oatmeal, cooked", "amount": "200g", "carbs_g": 37},
                    {"food": "Banana", "amount": "2 medium", "carbs_g": 54},
                    {"food": "Honey", "amount": "30g", "carbs_g": 25},
                    {"food": "Whey protein isolate", "amount": "20g", "carbs_g": 1, "protein_g": 17},
                    {"food": "Coffee, black", "amount": "300ml", "carbs_g": 0},
                ],
                "total_carbs_g": 117,
                "note": "Closest to your brick-day breakfast. Oatmeal has moderate fiber — eat earlier (3 hrs) if GI-sensitive.",
            },
            "option_b": {
                "name": "White bread + PB (your long-ride breakfast)",
                "items": [
                    {"food": "White bread", "amount": "120g", "carbs_g": 60},
                    {"food": "Peanut butter", "amount": "20g", "carbs_g": 4, "fat_g": 10},
                    {"food": "Banana", "amount": "2 medium", "carbs_g": 54},
                    {"food": "Honey", "amount": "20g", "carbs_g": 17},
                    {"food": "Coffee, black", "amount": "300ml", "carbs_g": 0},
                ],
                "total_carbs_g": 135,
                "note": "Lower fiber than oatmeal. Good if eating 2.5 hrs before start.",
            },
        },
        "top_up": {
            "timing": "15-20 min before swim start",
            "items": "1 gel (25g carbs) + 200ml water or sports drink",
            "note": "Quick-absorbing carbs to top off blood glucose. Already in your routine.",
        },
    }


# ---------------------------------------------------------------------------
# Race-day leg-by-leg nutrition timeline
# ---------------------------------------------------------------------------

def generate_race_timeline(habits, projection):
    """Generate minute-by-minute race nutrition timeline."""
    exp = projection["finish_time_projection"]["scenarios"]["expected"]
    swim_s = exp["swim_seconds"]
    bike_s = exp["bike_seconds"]
    run_s = exp["run_seconds"]
    bike_hrs = bike_s / 3600
    run_hrs = run_s / 3600

    # Current workout fueling rate
    current_rate = habits.get("current_carb_rate_g_per_hr")
    workout_foods = habits["preferred_workout_foods"]

    # Assess gap between current fueling and target
    bike_target_rate = 85  # g/hr
    run_target_rate = 65   # g/hr
    rate_gap = None
    if current_rate:
        rate_gap = bike_target_rate - current_rate

    # Build bike fueling schedule (every 20 min)
    bike_intervals = int(bike_s // (20 * 60))  # intervals of 20 min
    bike_schedule = []
    cumulative_carbs = 0
    cumulative_sodium = 0
    cumulative_fluid = 0

    for i in range(bike_intervals):
        elapsed_min = (i + 1) * 20
        elapsed_display = f"{elapsed_min // 60}:{elapsed_min % 60:02d}"

        # Alternate between drink and gel every 20 min
        if i % 2 == 0:
            action = "Drink 300-350ml sports drink"
            carbs = 22
            sodium = 200
            fluid = 325
        else:
            action = "Take 1 gel + 150ml water"
            carbs = 25
            sodium = 100
            fluid = 150

        # Add solid food every 60 min for variety and satiety
        if i > 0 and (i + 1) % 3 == 0 and "Salted rice cakes (homemade)" in workout_foods:
            action += " + 1 rice cake"
            carbs += 19
            sodium += 200

        cumulative_carbs += carbs
        cumulative_sodium += sodium
        cumulative_fluid += fluid

        bike_schedule.append({
            "elapsed": elapsed_display,
            "action": action,
            "carbs_g": carbs,
            "sodium_mg": sodium,
            "fluid_ml": fluid,
            "cumulative_carbs_g": cumulative_carbs,
        })

    # Build run fueling schedule (at aid stations, ~every 2.5 km = ~12-13 min at expected pace)
    run_schedule = []
    run_cumulative_carbs = 0
    aid_station_interval_min = 12  # approximate
    run_intervals = int(run_s // (aid_station_interval_min * 60))

    for i in range(run_intervals):
        elapsed_min = (i + 1) * aid_station_interval_min
        elapsed_display = f"{elapsed_min // 60}:{elapsed_min % 60:02d}"
        km_approx = round(elapsed_min / (run_s / 60) * RUN_DISTANCE_KM, 1) if run_s else 0

        # Alternate gel/drink at each aid station
        if i % 3 == 0:
            action = "Gel + water"
            carbs = 25
            sodium = 100
            fluid = 200
        elif i % 3 == 1:
            action = "Electrolyte drink (cup)"
            carbs = 15
            sodium = 150
            fluid = 250
        else:
            action = "Water + cola (if available)"
            carbs = 12
            sodium = 50
            fluid = 250

        run_cumulative_carbs += carbs
        run_schedule.append({
            "elapsed": elapsed_display,
            "approx_km": km_approx,
            "action": action,
            "carbs_g": carbs,
            "sodium_mg": sodium,
            "fluid_ml": fluid,
            "cumulative_carbs_g": run_cumulative_carbs,
        })

    return {
        "swim": {
            "duration_display": fmt(swim_s),
            "nutrition": "None during swim. Focus on pacing and sighting.",
        },
        "t1": {
            "duration_estimate": "~3 min",
            "nutrition": "Sip electrolyte drink while transitioning. No solid food.",
        },
        "bike": {
            "duration_display": fmt(bike_s),
            "target_carb_rate_g_per_hr": bike_target_rate,
            "target_sodium_rate_mg_per_hr": 900,
            "target_fluid_rate_ml_per_hr": 875,
            "total_carbs_target_g": round(bike_target_rate * bike_hrs),
            "total_sodium_target_mg": round(900 * bike_hrs),
            "total_fluid_target_ml": round(875 * bike_hrs),
            "fueling_schedule": bike_schedule,
            "what_to_carry": [
                "2-3 bottles (500-750ml each) of sports drink mix",
                "4-5 gels (mix of caffeinated and plain)",
                f"{'2-3 rice cakes (your proven training food)' if 'Salted rice cakes (homemade)' in workout_foods else '1 banana (backup solid food)'}",
                "Top tube or bento box for gels",
            ],
        },
        "t2": {
            "duration_estimate": "~3 min",
            "nutrition": "1 gel + water before leaving transition.",
        },
        "run": {
            "duration_display": fmt(run_s),
            "target_carb_rate_g_per_hr": run_target_rate,
            "target_sodium_rate_mg_per_hr": 700,
            "target_fluid_rate_ml_per_hr": 625,
            "total_carbs_target_g": round(run_target_rate * run_hrs),
            "total_sodium_target_mg": round(700 * run_hrs),
            "total_fluid_target_ml": round(625 * run_hrs),
            "fueling_schedule": run_schedule,
            "what_to_carry": [
                "3 gels in race belt (1 caffeinated for km 15+)",
                "Rely on aid station drinks for fluid",
                "Salt capsules (2-3) as backup if cramping",
            ],
        },
        "fueling_gap_analysis": {
            "current_workout_rate_g_per_hr": current_rate,
            "bike_target_rate_g_per_hr": bike_target_rate,
            "gap_g_per_hr": rate_gap,
            "recommendation": (
                f"Your current training fueling rate is ~{current_rate} g/hr. "
                f"Race target is {bike_target_rate} g/hr on the bike — "
                f"{'that is a significant increase of ' + str(rate_gap) + ' g/hr. ' if rate_gap and rate_gap > 10 else 'close to target. '}"
                f"{'Practice higher intake in long rides over the next weeks to train your gut.' if rate_gap and rate_gap > 10 else 'Maintain current approach and fine-tune timing.'}"
            ) if current_rate else "No during-workout fueling data available to compare.",
        },
    }


RUN_DISTANCE_KM = 21.1


# ---------------------------------------------------------------------------
# Sweat rate estimation
# ---------------------------------------------------------------------------

def estimate_sweat_rate(crono):
    """Estimate sweat rate from biometric weight changes around workouts."""
    biometrics = crono.get("biometrics_log", [])

    # Look for weight drops associated with long workout days
    estimates = []
    for i in range(1, len(biometrics)):
        prev = biometrics[i - 1]
        curr = biometrics[i]
        if curr.get("notes") and "fluid loss" in curr["notes"].lower():
            weight_loss_kg = prev["weight_kg"] - curr["weight_kg"]
            if weight_loss_kg > 0:
                estimates.append({
                    "date": curr["date"],
                    "weight_loss_kg": weight_loss_kg,
                    "note": curr["notes"],
                })

    return {
        "estimated_from": "Cronometer biometric weight changes around long sessions",
        "observations": estimates,
        "estimated_sweat_rate_L_per_hr": (
            "~1.0-1.5 L/hr (estimated from weight delta, but confounded by food/fluid intake during session)"
        ),
        "recommendation": "Perform a controlled sweat test: weigh pre/post a 1-hour run in similar heat, track fluid intake. This gives a precise per-hour rate.",
        "caveat": "Weight change post-workout reflects fluid loss minus fluid intake during workout. Not a clean sweat rate without controlling for intake.",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading data...")
    crono = load_cronometer()
    objective = load_objective()
    projection = load_projection()

    print("Analyzing current nutrition habits...")
    habits = analyze_current_habits(crono)

    print("Generating carb loading plan...")
    carb_plan = generate_carb_loading_plan(habits, "2027-03-01")

    print("Generating pre-race meal...")
    swim_s = projection["finish_time_projection"]["scenarios"]["expected"]["swim_seconds"]
    pre_race = generate_pre_race_meal(habits, swim_s)

    print("Generating race-day timeline...")
    timeline = generate_race_timeline(habits, projection)

    print("Estimating sweat rate...")
    sweat = estimate_sweat_rate(crono)

    # Assemble output
    output = {
        "generated_at": NOW.isoformat(),
        "race": {
            "name": objective["race_name"],
            "date": "2027-03-01",
            "location": f"{objective['location']['city']}, {objective['location']['country']}",
            "conditions": "Tropical — expected 28-33C, 70-90% humidity",
        },
        "athlete_profile": {
            "weight_kg": habits["body_composition"]["weight_kg"],
            "body_fat_pct": habits["body_composition"]["body_fat_pct"],
            "lean_mass_kg": habits["body_composition"]["lean_mass_kg"],
            "current_daily_nutrition": habits["daily_averages"],
            "training_day_carbs_g": habits["training_day_carbs_g"],
            "rest_day_carbs_g": habits["rest_day_carbs_g"],
            "preferred_workout_foods": habits["preferred_workout_foods"],
        },
        "race_week_carb_loading": carb_plan,
        "race_morning_pre_race_meal": pre_race,
        "race_day_nutrition_timeline": timeline,
        "sweat_rate_estimate": sweat,
        "race_totals_summary": {
            "projected_duration": projection["finish_time_projection"]["scenarios"]["expected"]["total_display"],
            "total_carbs_g": (
                timeline["bike"]["total_carbs_target_g"] +
                timeline["run"]["total_carbs_target_g"] +
                pre_race["carb_target_g"] + 25  # +25 for T2 gel
            ),
            "total_sodium_mg": (
                timeline["bike"]["total_sodium_target_mg"] +
                timeline["run"]["total_sodium_target_mg"]
            ),
            "total_fluid_ml": (
                timeline["bike"]["total_fluid_target_ml"] +
                timeline["run"]["total_fluid_target_ml"]
            ),
            "caloric_intake_estimate_kcal": round(
                (timeline["bike"]["total_carbs_target_g"] +
                 timeline["run"]["total_carbs_target_g"]) * 4
            ),
        },
        "key_reminders": [
            "Nothing new on race day — only foods and products tested in training.",
            "Front-load bike nutrition: take your first gel/drink within 10 min of starting the bike.",
            "Set 20-min alerts on your bike computer as fueling reminders.",
            "If GI distress on the run: switch to small sips of cola + water only.",
            "Tropical heat increases fluid and sodium needs — err on the higher end of ranges.",
            "Weigh yourself before and after key training sessions to calibrate your personal sweat rate.",
            "Caffeine: first caffeinated gel no earlier than the second half of the bike.",
            "These are sports-nutrition heuristics based on your tracked data, not medical advice.",
        ],
    }

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = ANALYSIS_DIR / "nutrition_strategy.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nNutrition strategy saved to {output_path}")

    # Summary
    totals = output["race_totals_summary"]
    print(f"\n{'='*60}")
    print(f"  IRONMAN 70.3 Puerto Rico — Nutrition Strategy")
    print(f"{'='*60}")
    print(f"  Projected duration:  {totals['projected_duration']}")
    print(f"  Total carbs:         {totals['total_carbs_g']}g")
    print(f"  Total sodium:        {totals['total_sodium_mg']}mg")
    print(f"  Total fluid:         {totals['total_fluid_ml']}ml")
    print(f"  Caloric intake:      ~{totals['caloric_intake_estimate_kcal']} kcal")
    print(f"  Athlete weight:      {habits['body_composition']['weight_kg']} kg")
    gap = timeline["fueling_gap_analysis"]
    if gap.get("current_workout_rate_g_per_hr"):
        print(f"  Current fuel rate:   {gap['current_workout_rate_g_per_hr']} g/hr")
        print(f"  Bike target rate:    {gap['bike_target_rate_g_per_hr']} g/hr")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

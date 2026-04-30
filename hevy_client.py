"""
Hevy API client for fetching gym workouts, exercise templates, and managing routines.
"""
import json
import requests
from datetime import datetime, timedelta
from config import HEVY_API_KEY, HEVY_API_BASE, DEBUG
from database import (
    save_gym_workout,
    get_most_recent_gym_workout_time,
    save_exercise_templates,
    get_exercise_templates,
    get_exercise_templates_cached_at,
)


def _headers():
    return {"api-key": HEVY_API_KEY, "Content-Type": "application/json"}


def _epley_1rm(weight_kg, reps):
    """Estimate 1RM using Epley formula."""
    if reps == 1:
        return weight_kg
    return weight_kg * (1 + reps / 30)


def _parse_workout(raw):
    """Parse a raw Hevy workout response into storage format."""
    start_time = raw.get("start_time")
    end_time = raw.get("end_time")

    duration_seconds = None
    if start_time and end_time:
        try:
            fmt = "%Y-%m-%dT%H:%M:%S%z"
            s = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_seconds = int((e - s).total_seconds())
        except Exception:
            pass

    exercises = []
    for ex in raw.get("exercises", []):
        sets = []
        best_1rm = 0
        for s in ex.get("sets", []):
            weight = s.get("weight_kg") or 0
            reps = s.get("reps") or 0
            estimated_1rm = _epley_1rm(weight, reps) if reps > 0 else 0
            if estimated_1rm > best_1rm:
                best_1rm = estimated_1rm
            sets.append({
                "set_type": s.get("set_type", "normal"),
                "weight_kg": weight,
                "reps": reps,
                "rpe": s.get("rpe"),
                "estimated_1rm": round(estimated_1rm, 1),
            })
        raw_muscles = ex.get("muscle_group") or ex.get("primary_muscle_group") or {}
        if isinstance(raw_muscles, dict):
            muscle_group = raw_muscles.get("primary") or raw_muscles.get("name") or ""
        elif isinstance(raw_muscles, str):
            muscle_group = raw_muscles
        else:
            muscle_group = ""

        exercises.append({
            "template_id": ex.get("exercise_template_id"),
            "title": ex.get("title"),
            "muscle_group": muscle_group,
            "sets": sets,
            "best_1rm": round(best_1rm, 1),
        })

    return {
        "hevy_id": str(raw["id"]),
        "title": raw.get("title", "Workout"),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "exercises_json": json.dumps(exercises),
        "raw_json": json.dumps(raw),
    }


# ── Workouts ────────────────────────────────────────────────────────────────

def fetch_workouts(after_time=None, page_size=10):
    """Fetch workouts from Hevy, optionally filtered to after a given ISO timestamp."""
    workouts = []
    page = 1

    while True:
        params = {"page": page, "pageSize": page_size}
        resp = requests.get(f"{HEVY_API_BASE}/workouts", headers=_headers(), params=params)
        if resp.status_code != 200:
            raise Exception(f"Hevy API error: {resp.text}")

        data = resp.json()
        page_workouts = data.get("workouts", [])
        if not page_workouts:
            break

        for w in page_workouts:
            if after_time and w.get("start_time", "") <= after_time:
                return workouts  # reached already-cached workouts
            workouts.append(_parse_workout(w))

        if len(page_workouts) < page_size:
            break
        page += 1

    return workouts


def fetch_and_cache_recent_workouts():
    """Fetch workouts newer than the most recent cached one and store them."""
    most_recent = get_most_recent_gym_workout_time()
    if DEBUG:
        print(f"Most recent cached gym workout: {most_recent}")

    workouts = fetch_workouts(after_time=most_recent)
    for w in workouts:
        save_gym_workout(w)

    if DEBUG:
        print(f"Cached {len(workouts)} new gym workouts")
    return workouts


def fetch_workout_detail(workout_id):
    """Fetch a single workout with full detail."""
    resp = requests.get(f"{HEVY_API_BASE}/workouts/{workout_id}", headers=_headers())
    if resp.status_code != 200:
        raise Exception(f"Hevy API error: {resp.text}")
    return _parse_workout(resp.json())


def fetch_exercise_history(template_id, page_size=10):
    """Fetch history for a specific exercise template (for progression tracking)."""
    resp = requests.get(
        f"{HEVY_API_BASE}/exercise_history/{template_id}",
        headers=_headers(),
        params={"page": 1, "pageSize": page_size},
    )
    if resp.status_code != 200:
        raise Exception(f"Hevy API error: {resp.text}")
    return resp.json()


# ── Exercise Templates ───────────────────────────────────────────────────────

def fetch_and_cache_exercise_templates(force=False):
    """Fetch all exercise templates from Hevy and cache them. Refreshes weekly."""
    cached_at = get_exercise_templates_cached_at()
    if not force and cached_at:
        try:
            age = datetime.utcnow() - datetime.fromisoformat(cached_at[:19])
            if age < timedelta(days=7):
                return get_exercise_templates()
        except Exception:
            pass

    templates = []
    page = 1
    while True:
        resp = requests.get(
            f"{HEVY_API_BASE}/exercise_templates",
            headers=_headers(),
            params={"page": page, "pageSize": 100},
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        page_templates = data.get("exercise_templates", [])
        if not page_templates:
            break

        for t in page_templates:
            muscles = t.get("muscle_group", {})
            templates.append({
                "template_id": t["id"],
                "name": t.get("title", ""),
                "muscle_group": muscles.get("primary", "") if isinstance(muscles, dict) else str(muscles),
                "secondary_muscles": ",".join(muscles.get("secondary", [])) if isinstance(muscles, dict) else "",
                "equipment": t.get("equipment_category", ""),
            })

        if len(page_templates) < 100:
            break
        page += 1

    if templates:
        save_exercise_templates(templates)
    return templates or get_exercise_templates()


def find_template_id(exercise_name, templates=None):
    """Fuzzy-match an exercise name to a Hevy template ID."""
    if templates is None:
        templates = get_exercise_templates()
    if not templates:
        return None

    name_lower = exercise_name.lower()

    # Exact match first
    for t in templates:
        if t["name"].lower() == name_lower:
            return t["template_id"]

    # Partial match — name contains query
    for t in templates:
        if name_lower in t["name"].lower():
            return t["template_id"]

    # Partial match — query contains template name word
    query_words = set(name_lower.split())
    for t in templates:
        template_words = set(t["name"].lower().split())
        if query_words & template_words:
            return t["template_id"]

    return None


# ── Routines ─────────────────────────────────────────────────────────────────

def fetch_routines():
    """Fetch all saved Hevy routines."""
    resp = requests.get(f"{HEVY_API_BASE}/routines", headers=_headers())
    if resp.status_code != 200:
        raise Exception(f"Hevy API error: {resp.text}")
    return resp.json().get("routines", [])


def create_routine(title, exercises):
    """
    Create a new Hevy routine.
    exercises: list of dicts with keys: template_id, sets (list of {weight_kg, reps, set_type})
    """
    payload = {
        "routine": {
            "title": title,
            "exercises": [
                {
                    "exercise_template_id": ex["template_id"],
                    "sets": [
                        {
                            "set_type": s.get("set_type", "normal"),
                            "weight_kg": s.get("weight_kg"),
                            "reps": s.get("reps"),
                        }
                        for s in ex.get("sets", [])
                    ],
                }
                for ex in exercises
                if ex.get("template_id")
            ],
        }
    }
    resp = requests.post(f"{HEVY_API_BASE}/routines", headers=_headers(), json=payload)
    if resp.status_code not in (200, 201):
        raise Exception(f"Hevy create routine error: {resp.text}")
    return resp.json().get("routine", {})


def update_routine(routine_id, title, exercises):
    """Update an existing Hevy routine."""
    payload = {
        "routine": {
            "title": title,
            "exercises": [
                {
                    "exercise_template_id": ex["template_id"],
                    "sets": [
                        {
                            "set_type": s.get("set_type", "normal"),
                            "weight_kg": s.get("weight_kg"),
                            "reps": s.get("reps"),
                        }
                        for s in ex.get("sets", [])
                    ],
                }
                for ex in exercises
                if ex.get("template_id")
            ],
        }
    }
    resp = requests.put(f"{HEVY_API_BASE}/routines/{routine_id}", headers=_headers(), json=payload)
    if resp.status_code != 200:
        raise Exception(f"Hevy update routine error: {resp.text}")
    return resp.json().get("routine", {})

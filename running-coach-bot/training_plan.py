import json
import logging
from datetime import date, timedelta
from typing import Optional

import anthropic

import database as db
from config import ANTHROPIC_API_KEY, CLAUDE_SONNET_MODEL, SYSTEM_PROMPT

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

RACE_DATE = date(2026, 10, 11)
PLAN_START_DATE = date(2026, 4, 28)  # Next Monday after today (2026-04-25)


PLAN_GENERATION_PROMPT = """Generate a complete 24-week half marathon training plan for the athlete described in the system prompt.

Plan start date: {start_date}
Race date: {race_date}
Total weeks: 24

Return ONLY valid JSON with this exact structure (no prose, no markdown fences):
{{
  "metadata": {{
    "race_date": "YYYY-MM-DD",
    "goal_pace_per_km": 6.0,
    "stretch_goal_pace_per_km": 5.5,
    "current_phase": "base_building",
    "total_weeks": 24
  }},
  "sessions": [
    {{
      "week_number": 1,
      "day_of_week": 0,
      "session_date": "YYYY-MM-DD",
      "session_type": "easy|tempo|intervals|long_run|rest|recovery",
      "description": "Easy run 5km at conversational pace, stay in Zone 2",
      "target_distance_km": 5.0,
      "target_pace_min_per_km": 7.0,
      "target_hr_zone": "Zone 2 (120-140 bpm)"
    }}
  ]
}}

Rules:
- Weeks 1-8: Phase 1 base building. 3 sessions/week (Mon/Wed/Sat). All easy runs.
  Week 1: 3x runs totalling ~12km. Each week +10% max. By week 8: ~25-30km total.
- Weeks 9-16: Phase 2 development. Add one quality session (tempo or intervals). 3-4 sessions.
  Volume builds to 35-40km/week.
- Weeks 17-22: Phase 3 race specific. Goal-pace work, race simulations. Peak volume.
- Weeks 23-24: Phase 4 taper. Cut volume 40-50%, keep some intensity.
- Always include rest days (session_type: rest) on non-running days within each week.
- Only generate running and rest sessions — no cross-training.
- target_pace_min_per_km is a float representing minutes (e.g. 6.5 = 6:30/km).
- day_of_week: 0=Monday through 6=Sunday.
- Generate ALL 7 days for EVERY week (including rest days). That's 168 sessions total.
"""


def generate_initial_plan() -> bool:
    """Call Claude Sonnet to generate the 24-week plan and store it in the DB."""
    logger.info("Generating 24-week training plan via Claude Sonnet...")

    prompt = PLAN_GENERATION_PROMPT.format(
        start_date=PLAN_START_DATE.isoformat(),
        race_date=RACE_DATE.isoformat(),
    )

    try:
        response = client.messages.create(
            model=CLAUDE_SONNET_MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except anthropic.APIError as e:
        logger.error(f"Claude API error generating plan: {e}")
        return False

    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse plan JSON: {e}\nRaw response:\n{raw[:500]}")
        return False

    sessions = plan.get("sessions", [])
    if not sessions:
        logger.error("Plan JSON contained no sessions.")
        return False

    # Persist metadata
    meta = plan.get("metadata", {})
    meta["plan_context_json"] = json.dumps({"prompt": prompt, "model": CLAUDE_SONNET_MODEL})
    db.save_plan_metadata(meta)

    # Persist sessions
    db.bulk_insert_plan_sessions(sessions)
    logger.info(f"Stored {len(sessions)} plan sessions in the database.")
    return True


def get_current_week_number() -> int:
    """Return the training week we're currently in (1-based)."""
    today = date.today()
    delta = (today - PLAN_START_DATE).days
    if delta < 0:
        return 0
    return (delta // 7) + 1


def get_current_phase() -> str:
    week = get_current_week_number()
    if week <= 8:
        return "base_building"
    elif week <= 16:
        return "development"
    elif week <= 22:
        return "race_specific"
    return "taper"


def match_activity_to_session(activity: dict) -> Optional[dict]:
    """Attempt to match a Strava activity to a planned session."""
    try:
        start = activity.get("start_date", "")[:10]
        session = db.get_session_for_date(start)
        if not session:
            return None

        # If session is already matched, skip
        if session.get("completed"):
            return None

        distance_km = (activity.get("distance_metres") or 0) / 1000
        planned_km = session.get("target_distance_km") or 0

        # Accept if within 30% of planned distance or no distance set
        if planned_km == 0 or abs(distance_km - planned_km) / max(planned_km, 1) <= 0.30:
            return session

        return None
    except Exception as e:
        logger.warning(f"Error matching activity to session: {e}")
        return None


def process_new_activity(activity: dict) -> Optional[str]:
    """Match a new activity, mark session complete, return session notes summary."""
    session = match_activity_to_session(activity)
    if not session:
        logger.info(f"Activity {activity.get('strava_id')} did not match any planned session.")
        return None

    distance_km = (activity.get("distance_metres") or 0) / 1000
    pace = activity.get("average_pace_per_km")
    hr = activity.get("average_heartrate")

    notes_parts = [f"Completed {distance_km:.1f}km"]
    if pace:
        from strava_client import seconds_to_pace
        notes_parts.append(f"@ {seconds_to_pace(pace * 60)}/km")
    if hr:
        notes_parts.append(f"HR {hr:.0f}bpm avg")

    notes = ", ".join(notes_parts)
    db.mark_session_complete(session["id"], activity["strava_id"], notes)
    logger.info(f"Marked session {session['id']} complete for activity {activity['strava_id']}.")
    return session["session_type"]


def format_week_schedule(week_number: int) -> str:
    """Return a formatted string of the week's sessions."""
    sessions = db.get_sessions_for_week_number(week_number)
    if not sessions:
        return f"No sessions found for week {week_number}."

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines = [f"Week {week_number} schedule:"]
    for s in sessions:
        day = day_names[s["day_of_week"]]
        status = "✓" if s["completed"] else "·"
        if s["session_type"] == "rest":
            lines.append(f"  {status} {day} {s['session_date']}: Rest")
        else:
            dist = f" {s['target_distance_km']:.0f}km" if s.get("target_distance_km") else ""
            lines.append(f"  {status} {day} {s['session_date']}: {s['session_type'].replace('_', ' ').title()}{dist} — {s['description'][:60]}")

    return "\n".join(lines)


def apply_plan_adjustments(adjustments: list[dict]):
    """Apply a list of session adjustments from Claude's weekly review."""
    for adj in adjustments:
        session = db.get_session_for_date(adj.get("session_date", ""))
        if not session:
            continue
        field = adj.get("field")
        new_value = adj.get("new_value")
        if field and new_value is not None:
            db.update_session(session["id"], {field: new_value})
    db.update_plan_last_adjusted()

import logging
from datetime import date, timedelta
from typing import Optional

import anthropic

import database as db
import strava_client as strava
from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_HAIKU_MODEL,
    CLAUDE_SONNET_MODEL,
    SYSTEM_PROMPT,
    CONVERSATION_HISTORY_LIMIT,
)

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_context_block() -> str:
    """Build a dynamic context block injected before user messages."""
    today = date.today()
    lines = [f"Today's date: {today.isoformat()}"]

    # Today's planned session
    session = db.get_session_for_date(today.isoformat())
    if session:
        lines.append(f"\nToday's planned session (week {session['week_number']}):")
        lines.append(f"  Type: {session['session_type']}")
        lines.append(f"  Description: {session['description']}")
        if session.get("target_distance_km"):
            lines.append(f"  Target distance: {session['target_distance_km']}km")
        if session.get("target_pace_min_per_km"):
            pace = strava.seconds_to_pace(session["target_pace_min_per_km"] * 60)
            lines.append(f"  Target pace: {pace}/km")
        if session.get("target_hr_zone"):
            lines.append(f"  Target HR zone: {session['target_hr_zone']}")
        lines.append(f"  Status: {'completed' if session['completed'] else 'not yet completed'}")
    else:
        lines.append("\nNo session planned for today.")

    # Latest activity
    latest = db.get_latest_activity()
    if latest:
        lines.append("\nMost recent activity:")
        lines.append(strava.format_activity_summary(latest))

    # Recent week summary
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (today + timedelta(days=6 - today.weekday())).isoformat()
    week_sessions = db.get_sessions_for_week(week_start, week_end)
    if week_sessions:
        done = sum(1 for s in week_sessions if s["completed"])
        total = len([s for s in week_sessions if s["session_type"] != "rest"])
        lines.append(f"\nThis week: {done}/{total} sessions completed.")

    # Plan metadata
    meta = db.get_plan_metadata()
    if meta:
        lines.append(f"\nPlan: {meta['total_weeks']}-week program, race on {meta['race_date']}")
        if meta.get("current_phase"):
            lines.append(f"Current phase: {meta['current_phase']}")

    return "\n".join(lines)


def ask_coach(user_message: str, use_sonnet: bool = False) -> str:
    """Send a message to the coach and return its reply."""
    model = CLAUDE_SONNET_MODEL if use_sonnet else CLAUDE_HAIKU_MODEL

    # Persist user message
    db.add_message("user", user_message)

    # Conversation history
    history = db.get_recent_messages(CONVERSATION_HISTORY_LIMIT)
    # History already includes the message we just added; exclude last so we
    # inject it with the context block prepended.
    messages_without_last = history[:-1]

    context = _build_context_block()
    augmented_user_message = f"[Context]\n{context}\n\n[Athlete message]\n{user_message}"

    messages = messages_without_last + [{"role": "user", "content": augmented_user_message}]

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply = response.content[0].text
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        reply = "Coach is temporarily unavailable — try again in a minute."

    db.add_message("assistant", reply)
    db.clear_old_messages(keep=30)
    return reply


def analyse_run(activity: dict, planned_session: Optional[dict] = None) -> str:
    """Generate detailed coaching feedback for a completed run."""
    activity_summary = strava.format_activity_summary(activity)

    planned_block = ""
    if planned_session:
        planned_block = (
            f"\nPlanned session for this day:\n"
            f"  Type: {planned_session['session_type']}\n"
            f"  Description: {planned_session['description']}\n"
        )
        if planned_session.get("target_distance_km"):
            planned_block += f"  Target distance: {planned_session['target_distance_km']}km\n"
        if planned_session.get("target_pace_min_per_km"):
            pace = strava.seconds_to_pace(planned_session["target_pace_min_per_km"] * 60)
            planned_block += f"  Target pace: {pace}/km\n"

    max_hr = strava.estimate_max_hr_from_activities()
    hr_context = f"\nEstimated max HR from history: {max_hr:.0f} bpm" if max_hr else ""

    prompt = (
        f"Analyse this completed run and give me coaching feedback.\n\n"
        f"{activity_summary}"
        f"{planned_block}"
        f"{hr_context}\n\n"
        "Structure your response as: quick verdict → what went well → what to improve → "
        "how it fits the bigger picture. Keep it concise."
    )
    return ask_coach(prompt)


def generate_weekly_plan_adjustment(week_number: int) -> str:
    """Use Sonnet to analyse a completed week and suggest next week adjustments."""
    completed = db.get_recent_completed_sessions(limit=7)
    upcoming = db.get_sessions_for_week_number(week_number + 1)
    meta = db.get_plan_metadata()

    def _completed_line(s):
        hr = s.get("average_heartrate")
        hr_part = f", HR {hr:.0f}" if hr else ""
        km = (s.get("distance_metres") or 0) / 1000
        pace = strava.seconds_to_pace((s.get("average_pace_per_km") or 0) * 60)
        return f"- {s['session_date']} ({s['session_type']}): {km:.1f}km @ {pace}/km{hr_part}"

    completed_summary = "\n".join([_completed_line(s) for s in completed]) or "No completed sessions."

    upcoming_summary = "\n".join([
        f"- {s['session_date']} ({s['session_type']}): {s['description']}"
        for s in upcoming
    ]) or "No upcoming sessions found."

    prompt = (
        f"Weekly review — Week {week_number} just completed.\n\n"
        f"Completed sessions:\n{completed_summary}\n\n"
        f"Planned sessions for next week (Week {week_number + 1}):\n{upcoming_summary}\n\n"
        "Review the completed week against expectations. Are adjustments needed for next week? "
        "Return your assessment and any specific changes to sessions as JSON with key 'adjustments' "
        "(list of {{session_date, field, new_value}} objects) and key 'summary' (coaching message to athlete)."
    )

    db.add_message("user", f"[Weekly review week {week_number}]")
    context = _build_context_block()

    try:
        response = client.messages.create(
            model=CLAUDE_SONNET_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"[Context]\n{context}\n\n{prompt}"}],
        )
        reply = response.content[0].text
    except anthropic.APIError as e:
        logger.error(f"Claude API error during weekly review: {e}")
        reply = "Could not complete weekly review — Claude API unavailable."

    db.add_message("assistant", reply)
    return reply


def check_plan_exists_and_ask_for_adjustment(user_message: str) -> str:
    """Handle plan-adjustment requests using Sonnet for deeper reasoning."""
    return ask_coach(user_message, use_sonnet=True)

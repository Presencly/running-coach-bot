"""
Training plan generation, storage, and adjustment logic.
"""
import json
from datetime import datetime, timedelta
from config import ATHLETE_PROFILE, PLAN_WEEKS, PHASE_STRUCTURE
from database import (
    save_plan_sessions_bulk,
    save_plan_metadata,
    get_plan_metadata,
    update_plan_phase,
    get_plan_week,
    get_recent_activities
)
from ai_coach import AiCoach


def calculate_phase_for_week(week_number):
    """Determine which phase a week belongs to."""
    if week_number <= 8:
        return "base_building"
    elif week_number <= 16:
        return "development"
    elif week_number <= 22:
        return "race_specific"
    else:
        return "taper"


def parse_plan_from_claude(plan_data):
    """
    Parse the JSON plan from Claude and convert to database format.
    Expected format: list of weeks with sessions.
    """
    sessions_to_save = []
    race_date = datetime.strptime(ATHLETE_PROFILE['race_date'], '%Y-%m-%d').date()
    
    # Calculate start date (24 weeks before race)
    start_date = race_date - timedelta(weeks=PLAN_WEEKS)
    
    # Handle both single list and list of dicts format
    if isinstance(plan_data, list):
        weeks = plan_data
    else:
        weeks = plan_data.get('weeks', []) if isinstance(plan_data, dict) else []
    
    for week_entry in weeks:
        week_num = week_entry.get('week', 0)
        if week_num == 0:
            continue
        
        # Calculate the start of this week (Monday)
        week_start = start_date + timedelta(weeks=week_num - 1)
        
        for session in week_entry.get('sessions', []):
            session_date = week_start + timedelta(days=session.get('day', 0))
            
            sessions_to_save.append({
                'week_number': week_num,
                'day_of_week': session.get('day', 0),
                'session_date': session_date.isoformat(),
                'session_type': session.get('type', 'easy'),
                'description': session.get('description', ''),
                'target_distance_km': session.get('distance_km'),
                'target_pace_min_per_km': session.get('pace_min_per_km'),
                'target_hr_zone': session.get('hr_zone')
            })
    
    return sessions_to_save


def generate_and_store_plan():
    """
    Generate a complete training plan using Claude and store it in the database.
    """
    print("Generating training plan with Claude...")
    coach = AiCoach()
    
    try:
        plan_data = coach.generate_training_plan()
    except Exception as e:
        print(f"Error generating plan: {e}")
        raise
    
    # Parse and store sessions
    sessions = parse_plan_from_claude(plan_data)
    
    if not sessions:
        raise ValueError("No sessions parsed from Claude response")
    
    save_plan_sessions_bulk(sessions)
    
    # Store metadata
    race_date = ATHLETE_PROFILE['race_date']
    goal_pace = ATHLETE_PROFILE['goal_pace_per_km']
    stretch_pace = ATHLETE_PROFILE['stretch_goal_pace_per_km']
    
    save_plan_metadata(
        race_date=race_date,
        goal_pace=goal_pace,
        stretch_goal_pace=stretch_pace,
        context_json=json.dumps(ATHLETE_PROFILE)
    )
    
    # Set initial phase
    update_plan_phase("base_building")
    
    print(f"Plan generated and stored: {len(sessions)} sessions across 24 weeks")
    return sessions


def get_today_session():
    """Get today's prescribed training session."""
    from database import get_plan_session_by_date
    today = datetime.now().date().isoformat()
    sessions = get_plan_session_by_date(today)
    return sessions


def match_activity_to_plan(activity):
    """
    Attempt to match a completed activity to a planned session.
    Returns the matched session or None.
    """
    from database import get_plan_session_by_date
    
    # Parse activity date
    activity_date = activity['start_date'].split('T')[0]  # ISO format: YYYY-MM-DD
    
    # Get planned sessions for this date
    planned_sessions = get_plan_session_by_date(activity_date)
    
    if not planned_sessions:
        return None
    
    # Match by session type or distance
    # Priority: match by type first, then by distance
    distance_km = activity['distance_metres'] / 1000
    
    for session in planned_sessions:
        # Exact type match
        if session['session_type'] == 'long_run' and distance_km > 8:
            return session
        elif session['session_type'] == 'easy' and 5 <= distance_km <= 8:
            return session
        elif session['session_type'] == 'tempo' and 6 <= distance_km <= 12:
            return session
        elif session['session_type'] == 'intervals' and 8 <= distance_km <= 14:
            return session
    
    # Fallback: return first session of the day if distance is reasonable
    if planned_sessions and 3 <= distance_km <= 20:
        return planned_sessions[0]
    
    return None


def get_week_summary(week_number):
    """Get a formatted summary of a week's training."""
    sessions = get_plan_week(week_number)
    
    if not sessions:
        return None
    
    summary = f"**Week {week_number}**\n"
    total_km = 0
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    for session in sessions:
        day_name = days[session['day_of_week']]
        dist = f" — {session['target_distance_km']:.1f}km" if session['target_distance_km'] else ""
        summary += f"{day_name} ({session['session_date']}): {session['session_type'].capitalize()}{dist}\n{session['description']}\n\n"
        if session['target_distance_km']:
            total_km += session['target_distance_km']
    
    summary += f"\nTotal: {total_km:.1f}km"
    return summary


def assess_progress(weeks_back=4):
    """Assess training progress over the last N weeks, broken down by week and session type."""
    from datetime import date, timedelta
    from config import HR_ZONES

    activities = get_recent_activities(limit=weeks_back * 7)
    metadata = get_plan_metadata()

    if not activities:
        return "No recent activities to assess."

    goal_pace = metadata['goal_pace_per_km'] if metadata else ATHLETE_PROFILE['goal_pace_per_km']
    today = date.today()

    # Group by week
    weekly = {}
    for a in activities:
        act_date = date.fromisoformat((a.get('start_date_local') or a['start_date'])[:10])
        week_start = act_date - timedelta(days=act_date.weekday())
        key = week_start.isoformat()
        weekly.setdefault(key, []).append(a)

    lines = [f"Training progress — last {weeks_back} weeks:\n"]

    for week_start in sorted(weekly.keys(), reverse=True)[:weeks_back]:
        week_acts = weekly[week_start]
        week_km = sum(a['distance_metres'] for a in week_acts) / 1000
        week_end = date.fromisoformat(week_start) + timedelta(days=6)
        label = "This week" if date.fromisoformat(week_start) <= today <= week_end else week_start

        # Separate long runs from easy runs for meaningful pace comparison
        long_runs = [a for a in week_acts if a['distance_metres'] >= 8000]
        easy_runs = [a for a in week_acts if a['distance_metres'] < 8000]

        lines.append(f"{label}: {week_km:.1f}km across {len(week_acts)} run(s)")

        if easy_runs:
            avg_easy_pace = sum(a['average_pace_per_km'] for a in easy_runs) / len(easy_runs)
            avg_easy_hr = [a['average_heartrate'] for a in easy_runs if a.get('average_heartrate')]
            hr_str = f" avg HR{sum(avg_easy_hr)/len(avg_easy_hr):.0f}" if avg_easy_hr else ""
            # Flag if HR is above Z2
            if avg_easy_hr:
                mean_hr = sum(avg_easy_hr) / len(avg_easy_hr)
                z2_max = HR_ZONES[2][1]
                hr_str += " ✓ Z2" if mean_hr <= z2_max else f" ⚠ Z3+ (target <{z2_max}bpm)"
            lines.append(f"  Easy runs: {avg_easy_pace:.2f}/km{hr_str}")

        if long_runs:
            avg_long_pace = sum(a['average_pace_per_km'] for a in long_runs) / len(long_runs)
            lines.append(f"  Long run: {long_runs[0]['distance_metres']/1000:.1f}km @{avg_long_pace:.2f}/km")

    # Overall trend: compare first vs last two weeks
    sorted_weeks = sorted(weekly.keys())
    if len(sorted_weeks) >= 2:
        early = [a for w in sorted_weeks[:2] for a in weekly[w]]
        recent = [a for w in sorted_weeks[-2:] for a in weekly[w]]
        early_pace = sum(a['average_pace_per_km'] for a in early) / len(early)
        recent_pace = sum(a['average_pace_per_km'] for a in recent) / len(recent)
        diff = early_pace - recent_pace
        if diff > 0.1:
            lines.append(f"\nTrend: improving — {diff:.2f}/km faster than {weeks_back} weeks ago ✓")
        elif diff < -0.1:
            lines.append(f"\nTrend: slowing — {abs(diff):.2f}/km slower than {weeks_back} weeks ago")
        else:
            lines.append("\nTrend: consistent pace across the period")

    lines.append(f"\nGoal race pace: {goal_pace:.2f}/km")
    return "\n".join(lines)

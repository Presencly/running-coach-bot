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
    """Assess training progress over the last N weeks."""
    activities = get_recent_activities(limit=weeks_back * 3)  # Rough estimate
    metadata = get_plan_metadata()
    
    if not activities:
        return "No recent activities to assess."
    
    total_distance = sum(a['distance_metres'] for a in activities) / 1000
    avg_pace = sum(a['average_pace_per_km'] for a in activities) / len(activities)
    
    goal_pace = metadata['goal_pace_per_km'] if metadata else ATHLETE_PROFILE['goal_pace_per_km']
    
    pace_diff = avg_pace - goal_pace
    
    assessment = f"Over the last {weeks_back} weeks:\n"
    assessment += f"- Total distance: {total_distance:.1f}km\n"
    assessment += f"- Average pace: {avg_pace:.2f}/km\n"
    assessment += f"- vs goal pace ({goal_pace:.2f}/km): "
    
    if pace_diff < -0.2:
        assessment += "🔥 Faster than goal (good!)"
    elif pace_diff < 0.2:
        assessment += "✓ On pace"
    elif pace_diff < 0.5:
        assessment += "⚠ Slightly slower than goal"
    else:
        assessment += "❌ Significantly slower than goal"
    
    return assessment

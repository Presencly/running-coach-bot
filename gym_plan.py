"""
Gym plan generation, storage, matching, and Hevy routine creation.
"""
import json
from datetime import datetime, date, timedelta
from config import ATHLETE_PROFILE, PLAN_WEEKS
from database import (
    save_gym_plan_sessions_bulk,
    get_gym_plan_session_by_date,
    get_gym_plan_week,
    get_recent_gym_workouts,
    mark_gym_session_completed,
    update_gym_session_routine_id,
)
from hevy_client import (
    fetch_and_cache_exercise_templates,
    find_template_id,
    create_routine,
    update_routine,
    get_exercise_templates,
)


def generate_and_store_gym_plan(coach, running_sessions=None):
    """
    Generate a 24-week gym plan using Claude, coordinated with the running plan.
    coach: AiCoach instance
    running_sessions: optional list of running sessions for cross-training awareness
    """
    running_context = ""
    if running_sessions:
        sample = running_sessions[:10]
        running_context = "\n".join([
            f"Week {s['week_number']} Day {s['day_of_week']}: {s['session_type']} run"
            for s in sample
        ])

    plan_prompt = f"""Generate a 24-week gym training plan for {ATHLETE_PROFILE['name']} that complements the running plan for the Nike Melbourne Half Marathon on {ATHLETE_PROFILE['race_date']}.

Athlete: Intermediate gym experience, targeting 3 gym sessions/week.
Running plan sample (avoid scheduling heavy lower body the day before these):
{running_context or 'Standard 3-run week: easy Tuesday, quality Thursday, long Sunday'}

The plan must:
1. Follow 4 phases matching the running plan:
   - Weeks 1-8 (Base): Full body or upper/lower, 2-3x/week, moderate intensity
   - Weeks 9-16 (Development): Push/pull/legs or upper/lower, 3x/week, increasing intensity
   - Weeks 17-22 (Race Specific): Maintain frequency, reduce volume, prioritise running
   - Weeks 23-24 (Taper): 1-2x/week max, upper body only, no heavy lower body
2. Never schedule heavy lower body (squats, deadlifts) the day before a quality run
3. Focus on compound movements: squat, deadlift, bench press, overhead press, rows, pull-ups
4. Include progressive overload — weight/volume increases week to week

Return JSON array:
[{{"week": 1, "sessions": [{{"day": 0, "type": "upper_push", "description": "string", "exercises": [{{"name": "Bench Press", "sets": 3, "reps": "8-10", "weight_note": "moderate"}}]}}]}}]

Day numbering: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday
Session types: upper_push, upper_pull, lower, full_body, rest, mobility
Generate all 24 weeks."""

    plan_data = coach.generate_plan_raw(plan_prompt)

    sessions = _parse_gym_plan(plan_data)
    if not sessions:
        raise ValueError("No gym sessions parsed from Claude response")

    save_gym_plan_sessions_bulk(sessions)
    return sessions


def _parse_gym_plan(plan_data):
    """Parse Claude's JSON gym plan into database rows."""
    sessions = []
    race_date = datetime.strptime(ATHLETE_PROFILE['race_date'], '%Y-%m-%d').date()
    start_date = race_date - timedelta(weeks=PLAN_WEEKS)

    weeks = plan_data if isinstance(plan_data, list) else plan_data.get('weeks', [])

    for week_entry in weeks:
        week_num = week_entry.get('week', 0)
        if not week_num:
            continue
        week_start = start_date + timedelta(weeks=week_num - 1)

        for session in week_entry.get('sessions', []):
            day = session.get('day', 0)
            session_date = week_start + timedelta(days=day)
            exercises = session.get('exercises', [])

            sessions.append({
                'week_number': week_num,
                'day_of_week': day,
                'session_date': session_date.isoformat(),
                'session_type': session.get('type', 'full_body'),
                'description': session.get('description', ''),
                'exercises_json': json.dumps(exercises) if exercises else None,
            })

    return sessions


def get_today_gym_session():
    """Get today's prescribed gym session."""
    today = date.today().isoformat()
    return get_gym_plan_session_by_date(today)


def get_gym_week_summary(week_number):
    """Get a formatted summary of a week's gym sessions."""
    sessions = get_gym_plan_week(week_number)
    if not sessions:
        return None

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    summary = f"**Gym — Week {week_number}**\n"

    for s in sessions:
        day_name = days[s['day_of_week']]
        exercises = json.loads(s['exercises_json']) if s.get('exercises_json') else []
        ex_line = ", ".join(e['name'] for e in exercises[:4]) if exercises else ""
        summary += f"{day_name} ({s['session_date']}): {s['session_type'].replace('_', ' ').title()}"
        if ex_line:
            summary += f" — {ex_line}"
        summary += "\n"

    return summary


def match_workout_to_plan(workout):
    """Match a completed gym workout to a planned session by date and type."""
    workout_date = (workout.get('start_time') or '')[:10]
    if not workout_date:
        return None

    planned = get_gym_plan_session_by_date(workout_date)
    if not planned:
        return None

    exercises = json.loads(workout.get('exercises_json', '[]'))
    exercise_names = {e.get('title', '').lower() for e in exercises}

    # Match by session type based on exercises performed
    type_keywords = {
        'upper_push': {'bench', 'press', 'tricep', 'shoulder', 'dip'},
        'upper_pull': {'row', 'pull', 'curl', 'lat', 'bicep'},
        'lower': {'squat', 'deadlift', 'lunge', 'leg', 'calf', 'hip'},
        'full_body': set(),
    }

    for session in planned:
        stype = session['session_type']
        keywords = type_keywords.get(stype, set())
        if keywords and any(k in name for k in keywords for name in exercise_names):
            return session

    return planned[0] if planned else None


def create_hevy_routines_for_week(week_number):
    """Create Hevy routines for all gym sessions in a given week."""
    sessions = get_gym_plan_week(week_number)
    templates = fetch_and_cache_exercise_templates()
    created = []

    for session in sessions:
        if session['session_type'] in ('rest', 'mobility') or not session.get('exercises_json'):
            continue

        exercises_raw = json.loads(session['exercises_json'])
        exercises_for_hevy = []

        for ex in exercises_raw:
            template_id = find_template_id(ex['name'], templates)
            if not template_id:
                continue

            # Parse reps range (e.g. "8-10" → 9)
            reps_str = str(ex.get('reps', '8'))
            try:
                if '-' in reps_str:
                    parts = reps_str.split('-')
                    reps = int((int(parts[0]) + int(parts[1])) / 2)
                else:
                    reps = int(reps_str)
            except ValueError:
                reps = 8

            sets = [{"set_type": "normal", "weight_kg": None, "reps": reps}
                    for _ in range(ex.get('sets', 3))]
            exercises_for_hevy.append({"template_id": template_id, "sets": sets})

        if not exercises_for_hevy:
            continue

        title = f"W{week_number} {session['session_type'].replace('_', ' ').title()} — {session['session_date']}"

        if session.get('hevy_routine_id'):
            routine = update_routine(session['hevy_routine_id'], title, exercises_for_hevy)
        else:
            routine = create_routine(title, exercises_for_hevy)
            if routine.get('id'):
                update_gym_session_routine_id(session['id'], routine['id'])

        created.append(routine.get('title', title))

    return created

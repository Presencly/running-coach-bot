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


def _gym_prompt(start_week, end_week, running_context):
    return f"""Generate a gym training plan for weeks {start_week}-{end_week} for {ATHLETE_PROFILE['name']}, complementing their half marathon training.

Running schedule (avoid heavy lower body day before quality runs):
{running_context or 'Easy Tuesday, quality Thursday, long Sunday'}

Phase guide:
- Weeks 1-8: Full body/upper-lower, 2-3x/week, moderate intensity
- Weeks 9-16: Push/pull/legs, 3x/week, increasing intensity
- Weeks 17-22: Maintain frequency, reduce volume
- Weeks 23-24: Upper body only, 1-2x/week max

Rules: never schedule lower body the day before Thursday runs or Sunday long runs.
Session types: upper_push, upper_pull, lower, full_body
Day numbering: 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun

Return ONLY a JSON array for weeks {start_week} to {end_week}:
[{{"week": {start_week}, "sessions": [{{"day": 0, "type": "upper_push", "description": "Upper Push — bench press focus", "exercises": [{{"name": "Bench Press", "sets": 3, "reps": "8-10"}}]}}]}}]"""


def generate_and_store_gym_plan(coach, running_sessions=None):
    """Generate a 24-week gym plan in two 12-week batches to avoid token limits."""
    running_context = ""
    if running_sessions:
        running_context = "\n".join([
            f"Week {s['week_number']} Day {s['day_of_week']}: {s['session_type']}"
            for s in running_sessions[:12]
        ])

    all_sessions = []
    for start, end in [(1, 12), (13, 24)]:
        prompt = _gym_prompt(start, end, running_context)
        plan_data = coach.generate_plan_raw(prompt)
        batch = _parse_gym_plan(plan_data)
        all_sessions.extend(batch)

    if not all_sessions:
        raise ValueError("No gym sessions parsed from Claude response")

    save_gym_plan_sessions_bulk(all_sessions)
    return all_sessions


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

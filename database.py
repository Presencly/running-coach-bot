"""
SQLite database initialization, migrations, and CRUD operations.
"""
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
from config import DATABASE_PATH


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database with all required tables."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Migrate existing activities table if needed
        try:
            cursor.execute("ALTER TABLE activities ADD COLUMN start_date_local TIMESTAMP")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE activities ADD COLUMN kilojoules REAL")
        except Exception:
            pass
        
        # Strava OAuth tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strava_tokens (
                id INTEGER PRIMARY KEY DEFAULT 1,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Cached Strava activities
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                strava_id INTEGER PRIMARY KEY,
                name TEXT,
                start_date TIMESTAMP,
                start_date_local TIMESTAMP,
                distance_metres REAL,
                moving_time_seconds INTEGER,
                elapsed_time_seconds INTEGER,
                average_pace_per_km REAL,
                average_heartrate REAL,
                max_heartrate REAL,
                total_elevation_gain REAL,
                kilojoules REAL,
                suffer_score INTEGER,
                splits_json TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Training plan sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plan_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_number INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                session_date DATE NOT NULL,
                session_type TEXT NOT NULL,
                description TEXT NOT NULL,
                target_distance_km REAL,
                target_pace_min_per_km REAL,
                target_hr_zone TEXT,
                completed BOOLEAN DEFAULT FALSE,
                matched_activity_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (matched_activity_id) REFERENCES activities(strava_id)
            )
        """)
        
        # Plan metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plan_metadata (
                id INTEGER PRIMARY KEY DEFAULT 1,
                race_date DATE NOT NULL,
                goal_pace_per_km REAL NOT NULL,
                stretch_goal_pace_per_km REAL,
                current_phase TEXT,
                total_weeks INTEGER,
                plan_generated_at TIMESTAMP,
                last_adjusted_at TIMESTAMP,
                plan_context_json TEXT
            )
        """)
        
        # Conversation history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Hevy gym workouts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gym_workouts (
                hevy_id TEXT PRIMARY KEY,
                title TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_seconds INTEGER,
                exercises_json TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Hevy exercise templates (cached)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exercise_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                muscle_group TEXT,
                secondary_muscles TEXT,
                equipment TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Exercise personal bests (1RM per exercise)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exercise_pbs (
                template_id TEXT PRIMARY KEY,
                exercise_name TEXT NOT NULL,
                best_1rm REAL NOT NULL,
                achieved_date DATE NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Gym training plan sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gym_plan_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_number INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                session_date DATE NOT NULL,
                session_type TEXT NOT NULL,
                description TEXT NOT NULL,
                exercises_json TEXT,
                completed BOOLEAN DEFAULT FALSE,
                matched_workout_id TEXT,
                hevy_routine_id TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (matched_workout_id) REFERENCES gym_workouts(hevy_id)
            )
        """)

        conn.commit()
        
        conn.commit()


# Strava Tokens CRUD
def save_strava_tokens(access_token, refresh_token, expires_at):
    """Save or update Strava tokens."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO strava_tokens 
            (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (access_token, refresh_token, expires_at))
        conn.commit()


def get_strava_tokens():
    """Retrieve current Strava tokens. Env vars take priority to allow Railway resets."""
    import os
    access_token = os.getenv('STRAVA_ACCESS_TOKEN')
    refresh_token = os.getenv('STRAVA_REFRESH_TOKEN')
    expires_at = os.getenv('STRAVA_EXPIRES_AT')
    if access_token and refresh_token and expires_at:
        tokens = {'access_token': access_token, 'refresh_token': refresh_token, 'expires_at': int(expires_at)}
        save_strava_tokens(access_token, refresh_token, int(expires_at))
        return tokens

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT access_token, refresh_token, expires_at FROM strava_tokens WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return dict(row)

    return None


# Activities CRUD
def save_activity(activity_data):
    """Save or update a Strava activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO activities
            (strava_id, name, start_date, start_date_local, distance_metres, moving_time_seconds,
             elapsed_time_seconds, average_pace_per_km, average_heartrate, max_heartrate,
             total_elevation_gain, kilojoules, suffer_score, splits_json, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            activity_data['strava_id'],
            activity_data['name'],
            activity_data['start_date'],
            activity_data['start_date_local'],
            activity_data['distance_metres'],
            activity_data['moving_time_seconds'],
            activity_data['elapsed_time_seconds'],
            activity_data['average_pace_per_km'],
            activity_data['average_heartrate'],
            activity_data['max_heartrate'],
            activity_data['total_elevation_gain'],
            activity_data['kilojoules'],
            activity_data['suffer_score'],
            activity_data['splits_json'],
            activity_data['raw_json']
        ))
        conn.commit()


def get_activity(strava_id):
    """Get a specific activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM activities WHERE strava_id = ?", (strava_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_recent_activities(limit=10):
    """Get most recent activities."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM activities ORDER BY start_date DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_most_recent_activity_date():
    """Get the date of the most recent cached activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(start_date) as max_date FROM activities")
        row = cursor.fetchone()
        if row and row['max_date']:
            return row['max_date']
        return None


# Plan Sessions CRUD
def save_plan_session(session_data):
    """Save a training plan session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO plan_sessions
            (week_number, day_of_week, session_date, session_type, description,
             target_distance_km, target_pace_min_per_km, target_hr_zone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_data['week_number'],
            session_data['day_of_week'],
            session_data['session_date'],
            session_data['session_type'],
            session_data['description'],
            session_data['target_distance_km'],
            session_data['target_pace_min_per_km'],
            session_data['target_hr_zone']
        ))
        conn.commit()


def save_plan_sessions_bulk(sessions):
    """Save multiple plan sessions at once."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO plan_sessions
            (week_number, day_of_week, session_date, session_type, description,
             target_distance_km, target_pace_min_per_km, target_hr_zone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (s['week_number'], s['day_of_week'], s['session_date'], s['session_type'],
             s['description'], s['target_distance_km'], s['target_pace_min_per_km'],
             s['target_hr_zone'])
            for s in sessions
        ])
        conn.commit()


def get_plan_session_by_date(session_date):
    """Get plan session(s) for a specific date."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM plan_sessions WHERE session_date = ? ORDER BY session_type
        """, (session_date,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_plan_week(week_number):
    """Get all sessions for a specific week."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM plan_sessions WHERE week_number = ? ORDER BY day_of_week
        """, (week_number,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_session_completed(session_id, activity_id):
    """Mark a plan session as completed and link to activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE plan_sessions
            SET completed = TRUE, matched_activity_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (activity_id, session_id))
        conn.commit()


def get_uncompleted_sessions(limit_days=30):
    """Get uncompleted sessions within the last N days."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM plan_sessions
            WHERE completed = FALSE
            AND session_date >= date('now', '-' || ? || ' days')
            ORDER BY session_date
        """, (limit_days,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# Plan Metadata CRUD
def save_plan_metadata(race_date, goal_pace, stretch_goal_pace, context_json=None):
    """Save or update plan metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO plan_metadata
            (id, race_date, goal_pace_per_km, stretch_goal_pace_per_km,
             plan_generated_at, plan_context_json)
            VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (race_date, goal_pace, stretch_goal_pace, context_json))
        conn.commit()


def get_plan_metadata():
    """Get current plan metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plan_metadata WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def update_plan_phase(phase_name):
    """Update the current training phase."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE plan_metadata
            SET current_phase = ?, last_adjusted_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (phase_name,))
        conn.commit()


# Conversation CRUD
def add_conversation_message(role, content):
    """Add a message to conversation history."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (role, content)
            VALUES (?, ?)
        """, (role, content))
        conn.commit()


def get_conversation_history(limit=10):
    """Get recent conversation history."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM conversations
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        # Reverse to get chronological order
        messages = [dict(row) for row in reversed(rows)]
        return messages


def clear_conversation_history():
    """Clear all conversation history."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations")
        conn.commit()


def prune_conversation_history(keep=50):
    """Delete all but the most recent N messages."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM conversations WHERE id NOT IN (
                SELECT id FROM conversations ORDER BY id DESC LIMIT ?
            )
        """, (keep,))
        conn.commit()


# Gym Workouts CRUD
def save_gym_workout(workout_data):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO gym_workouts
            (hevy_id, title, start_time, end_time, duration_seconds, exercises_json, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            workout_data['hevy_id'],
            workout_data['title'],
            workout_data['start_time'],
            workout_data['end_time'],
            workout_data['duration_seconds'],
            workout_data['exercises_json'],
            workout_data['raw_json'],
        ))
        conn.commit()


def get_recent_gym_workouts(limit=10):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM gym_workouts ORDER BY start_time DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]


def get_most_recent_gym_workout_time():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(start_time) as max_time FROM gym_workouts")
        row = cursor.fetchone()
        return row['max_time'] if row and row['max_time'] else None


# Exercise Templates CRUD
def save_exercise_templates(templates):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO exercise_templates
            (template_id, name, muscle_group, secondary_muscles, equipment, cached_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, [(t['template_id'], t['name'], t['muscle_group'],
               t['secondary_muscles'], t['equipment']) for t in templates])
        conn.commit()


def get_exercise_templates():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM exercise_templates ORDER BY name")
        return [dict(r) for r in cursor.fetchall()]


def get_muscle_group_for_template(template_id):
    """Look up the primary muscle group for an exercise template ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT muscle_group FROM exercise_templates WHERE template_id = ?", (template_id,))
        row = cursor.fetchone()
        return row['muscle_group'] if row else ""


def get_exercise_templates_cached_at():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(cached_at) as oldest FROM exercise_templates")
        row = cursor.fetchone()
        return row['oldest'] if row else None


# Gym Plan Sessions CRUD
def save_gym_plan_sessions_bulk(sessions):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO gym_plan_sessions
            (week_number, day_of_week, session_date, session_type, description, exercises_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [(s['week_number'], s['day_of_week'], s['session_date'],
               s['session_type'], s['description'], s.get('exercises_json')) for s in sessions])
        conn.commit()


def get_gym_plan_session_by_date(session_date):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM gym_plan_sessions WHERE session_date = ?", (session_date,))
        return [dict(r) for r in cursor.fetchall()]


def get_gym_plan_week(week_number):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM gym_plan_sessions WHERE week_number = ? ORDER BY day_of_week
        """, (week_number,))
        return [dict(r) for r in cursor.fetchall()]


def mark_gym_session_completed(session_id, workout_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE gym_plan_sessions
            SET completed = TRUE, matched_workout_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (workout_id, session_id))
        conn.commit()


def update_gym_session_routine_id(session_id, routine_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE gym_plan_sessions SET hevy_routine_id = ? WHERE id = ?
        """, (routine_id, session_id))
        conn.commit()


# Exercise PBs CRUD
def get_exercise_pb(template_id):
    """Return the stored best 1RM for an exercise, or 0 if none."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT best_1rm FROM exercise_pbs WHERE template_id = ?", (template_id,))
        row = cursor.fetchone()
        return row['best_1rm'] if row else 0


def upsert_exercise_pb(template_id, exercise_name, best_1rm, achieved_date):
    """Insert or update a PB only if the new value beats the stored one. Returns True if new PB."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT best_1rm FROM exercise_pbs WHERE template_id = ?", (template_id,))
        row = cursor.fetchone()
        if row is None or best_1rm > row['best_1rm']:
            cursor.execute("""
                INSERT OR REPLACE INTO exercise_pbs
                (template_id, exercise_name, best_1rm, achieved_date, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (template_id, exercise_name, best_1rm, achieved_date))
            conn.commit()
            return True
        return False


def get_all_exercise_pbs():
    """Return all stored exercise PBs ordered by exercise name."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM exercise_pbs ORDER BY exercise_name")
        return [dict(r) for r in cursor.fetchall()]

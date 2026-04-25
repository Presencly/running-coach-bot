import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from config import DATABASE_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS strava_tokens (
                id INTEGER PRIMARY KEY DEFAULT 1,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS activities (
                strava_id INTEGER PRIMARY KEY,
                name TEXT,
                start_date TIMESTAMP,
                distance_metres REAL,
                moving_time_seconds INTEGER,
                elapsed_time_seconds INTEGER,
                average_pace_per_km REAL,
                average_heartrate REAL,
                max_heartrate REAL,
                total_elevation_gain REAL,
                suffer_score INTEGER,
                splits_json TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

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
            );

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
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ── Strava tokens ──────────────────────────────────────────────────────────────

def save_strava_tokens(access_token: str, refresh_token: str, expires_at: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO strava_tokens (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
        """, (access_token, refresh_token, expires_at))


def get_strava_tokens() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM strava_tokens WHERE id = 1").fetchone()
        return dict(row) if row else None


# ── Activities ─────────────────────────────────────────────────────────────────

def upsert_activity(activity: dict):
    distance = activity.get("distance", 0)
    moving_time = activity.get("moving_time", 0)
    pace = (moving_time / 60) / (distance / 1000) if distance > 0 else None

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO activities (
                strava_id, name, start_date, distance_metres, moving_time_seconds,
                elapsed_time_seconds, average_pace_per_km, average_heartrate,
                max_heartrate, total_elevation_gain, suffer_score,
                splits_json, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strava_id) DO UPDATE SET
                name = excluded.name,
                start_date = excluded.start_date,
                distance_metres = excluded.distance_metres,
                moving_time_seconds = excluded.moving_time_seconds,
                elapsed_time_seconds = excluded.elapsed_time_seconds,
                average_pace_per_km = excluded.average_pace_per_km,
                average_heartrate = excluded.average_heartrate,
                max_heartrate = excluded.max_heartrate,
                total_elevation_gain = excluded.total_elevation_gain,
                suffer_score = excluded.suffer_score,
                splits_json = excluded.splits_json,
                raw_json = excluded.raw_json
        """, (
            activity["id"],
            activity.get("name"),
            activity.get("start_date"),
            distance,
            moving_time,
            activity.get("elapsed_time"),
            pace,
            activity.get("average_heartrate"),
            activity.get("max_heartrate"),
            activity.get("total_elevation_gain"),
            activity.get("suffer_score"),
            json.dumps(activity.get("splits_metric", [])),
            json.dumps(activity),
        ))


def get_latest_activity() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM activities ORDER BY start_date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_most_recent_activity_date() -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT start_date FROM activities ORDER BY start_date DESC LIMIT 1"
        ).fetchone()
        if row:
            dt = datetime.fromisoformat(row["start_date"].replace("Z", "+00:00"))
            return int(dt.timestamp())
        return None


def get_activities_since(since_date: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activities WHERE start_date >= ? ORDER BY start_date DESC",
            (since_date,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Plan sessions ──────────────────────────────────────────────────────────────

def insert_plan_session(session: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO plan_sessions (
                week_number, day_of_week, session_date, session_type,
                description, target_distance_km, target_pace_min_per_km, target_hr_zone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["week_number"],
            session["day_of_week"],
            session["session_date"],
            session["session_type"],
            session["description"],
            session.get("target_distance_km"),
            session.get("target_pace_min_per_km"),
            session.get("target_hr_zone"),
        ))
        return cur.lastrowid


def bulk_insert_plan_sessions(sessions: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO plan_sessions (
                week_number, day_of_week, session_date, session_type,
                description, target_distance_km, target_pace_min_per_km, target_hr_zone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                s["week_number"], s["day_of_week"], s["session_date"],
                s["session_type"], s["description"],
                s.get("target_distance_km"), s.get("target_pace_min_per_km"),
                s.get("target_hr_zone"),
            )
            for s in sessions
        ])


def get_session_for_date(date_str: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plan_sessions WHERE session_date = ? ORDER BY id LIMIT 1",
            (date_str,),
        ).fetchone()
        return dict(row) if row else None


def get_sessions_for_week(week_start: str, week_end: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_sessions WHERE session_date BETWEEN ? AND ? ORDER BY session_date",
            (week_start, week_end),
        ).fetchall()
        return [dict(r) for r in rows]


def get_sessions_for_week_number(week_number: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_sessions WHERE week_number = ? ORDER BY day_of_week",
            (week_number,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_session_complete(session_id: int, activity_id: int, notes: str = None):
    with get_conn() as conn:
        conn.execute("""
            UPDATE plan_sessions
            SET completed = TRUE, matched_activity_id = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (activity_id, notes, session_id))


def update_session(session_id: int, updates: dict):
    fields = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [session_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE plan_sessions SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )


def get_recent_completed_sessions(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ps.*, a.distance_metres, a.average_pace_per_km, a.average_heartrate
            FROM plan_sessions ps
            LEFT JOIN activities a ON ps.matched_activity_id = a.strava_id
            WHERE ps.completed = TRUE
            ORDER BY ps.session_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ── Plan metadata ──────────────────────────────────────────────────────────────

def save_plan_metadata(meta: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO plan_metadata (
                id, race_date, goal_pace_per_km, stretch_goal_pace_per_km,
                current_phase, total_weeks, plan_generated_at, plan_context_json
            ) VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(id) DO UPDATE SET
                race_date = excluded.race_date,
                goal_pace_per_km = excluded.goal_pace_per_km,
                stretch_goal_pace_per_km = excluded.stretch_goal_pace_per_km,
                current_phase = excluded.current_phase,
                total_weeks = excluded.total_weeks,
                plan_generated_at = excluded.plan_generated_at,
                plan_context_json = excluded.plan_context_json
        """, (
            meta["race_date"],
            meta["goal_pace_per_km"],
            meta.get("stretch_goal_pace_per_km"),
            meta.get("current_phase"),
            meta.get("total_weeks", 24),
            meta.get("plan_context_json"),
        ))


def get_plan_metadata() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_metadata WHERE id = 1").fetchone()
        return dict(row) if row else None


def update_plan_last_adjusted():
    with get_conn() as conn:
        conn.execute(
            "UPDATE plan_metadata SET last_adjusted_at = CURRENT_TIMESTAMP WHERE id = 1"
        )


# ── Conversations ──────────────────────────────────────────────────────────────

def add_message(role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (role, content) VALUES (?, ?)",
            (role, content),
        )


def get_recent_messages(limit: int = 15) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT role, content FROM (
                SELECT role, content, created_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT ?
            ) ORDER BY created_at ASC
        """, (limit,)).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]


def clear_old_messages(keep: int = 30):
    with get_conn() as conn:
        conn.execute("""
            DELETE FROM conversations
            WHERE id NOT IN (
                SELECT id FROM conversations ORDER BY created_at DESC LIMIT ?
            )
        """, (keep,))

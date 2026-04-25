import time
import logging
from typing import Optional

import requests

import database as db
from config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET

logger = logging.getLogger(__name__)

STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def _refresh_token_if_needed() -> Optional[str]:
    tokens = db.get_strava_tokens()
    if not tokens:
        raise RuntimeError("No Strava tokens stored. Run strava_auth.py first.")

    if tokens["expires_at"] > int(time.time()) + 60:
        return tokens["access_token"]

    logger.info("Strava token expired — refreshing...")
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }, timeout=15)

    if not resp.ok:
        raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}")

    data = resp.json()
    db.save_strava_tokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
    )
    logger.info("Strava token refreshed successfully.")
    return data["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_refresh_token_if_needed()}"}


def _get(path: str, params: dict = None) -> dict:
    resp = requests.get(f"{STRAVA_API_BASE}{path}", headers=_headers(), params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Activity fetching ──────────────────────────────────────────────────────────

def fetch_new_activities() -> list[dict]:
    """Fetch run activities newer than the most recent cached one."""
    after = db.get_most_recent_activity_date()
    params = {"per_page": 50, "type": "Run"}
    if after:
        params["after"] = after

    activities = []
    page = 1
    while True:
        params["page"] = page
        batch = _get("/athlete/activities", params)
        if not batch:
            break
        run_batch = [a for a in batch if a.get("type") == "Run"]
        activities.extend(run_batch)
        if len(batch) < 50:
            break
        page += 1

    detailed = []
    for activity in activities:
        try:
            detail = fetch_activity_detail(activity["id"])
            detailed.append(detail)
            db.upsert_activity(detail)
        except Exception as e:
            logger.warning(f"Failed to fetch detail for activity {activity['id']}: {e}")

    logger.info(f"Fetched and cached {len(detailed)} new activities.")
    return detailed


def fetch_activity_detail(activity_id: int) -> dict:
    return _get(f"/activities/{activity_id}")


def get_latest_run() -> Optional[dict]:
    """Return the most recent cached run, refreshing from Strava first."""
    try:
        fetch_new_activities()
    except Exception as e:
        logger.warning(f"Could not refresh from Strava: {e}")
    return db.get_latest_activity()


def get_athlete_profile() -> dict:
    return _get("/athlete")


# ── Pace and HR utilities ──────────────────────────────────────────────────────

def seconds_to_pace(seconds_per_km: float) -> str:
    """Convert float seconds/km to MM:SS string."""
    total = int(seconds_per_km)
    return f"{total // 60}:{total % 60:02d}"


def mps_to_pace_str(metres_per_second: float) -> str:
    """Convert Strava m/s speed to readable pace string."""
    if not metres_per_second or metres_per_second == 0:
        return "N/A"
    seconds_per_km = 1000 / metres_per_second
    return seconds_to_pace(seconds_per_km)


def format_activity_summary(activity: dict) -> str:
    """Build a human-readable activity summary for Claude context."""
    distance_km = (activity.get("distance_metres") or 0) / 1000
    moving_time = activity.get("moving_time_seconds") or 0
    pace_raw = activity.get("average_pace_per_km")

    pace_str = seconds_to_pace(pace_raw * 60) if pace_raw else "N/A"
    duration_str = f"{moving_time // 3600}h {(moving_time % 3600) // 60}m" if moving_time >= 3600 \
        else f"{moving_time // 60}m {moving_time % 60}s"

    lines = [
        f"Activity: {activity.get('name', 'Run')}",
        f"Date: {activity.get('start_date', 'unknown')}",
        f"Distance: {distance_km:.2f} km",
        f"Duration: {duration_str}",
        f"Avg pace: {pace_str}/km",
    ]

    if activity.get("average_heartrate"):
        lines.append(f"Avg HR: {activity['average_heartrate']:.0f} bpm")
    if activity.get("max_heartrate"):
        lines.append(f"Max HR: {activity['max_heartrate']:.0f} bpm")
    if activity.get("total_elevation_gain"):
        lines.append(f"Elevation: {activity['total_elevation_gain']:.0f} m")
    if activity.get("suffer_score"):
        lines.append(f"Suffer score: {activity['suffer_score']}")

    splits = None
    try:
        import json
        splits_raw = activity.get("splits_json")
        if splits_raw:
            splits = json.loads(splits_raw)
    except Exception:
        pass

    if splits:
        lines.append("\nPer-km splits:")
        for i, split in enumerate(splits[:21], 1):
            split_pace = mps_to_pace_str(split.get("average_speed", 0))
            hr_str = f" | HR {split['average_heartrate']:.0f}" if split.get("average_heartrate") else ""
            lines.append(f"  km {i}: {split_pace}/km{hr_str}")

    return "\n".join(lines)


def estimate_max_hr_from_activities() -> Optional[float]:
    """Estimate max HR from historical activities."""
    activities = db.get_activities_since("2020-01-01")
    max_hr = max((a.get("max_heartrate") or 0) for a in activities) if activities else 0
    return max_hr if max_hr > 0 else None


def classify_hr_zone(hr: float, max_hr: float) -> int:
    """Return HR zone 1-5 given current HR and max HR."""
    pct = hr / max_hr
    if pct < 0.60:
        return 1
    elif pct < 0.70:
        return 2
    elif pct < 0.80:
        return 3
    elif pct < 0.90:
        return 4
    return 5

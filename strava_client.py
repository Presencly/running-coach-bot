"""
Strava OAuth and API integration.
Handles token refresh, activity fetching, and data caching.
"""
import time
import requests
import json
from datetime import datetime
from config import (
    STRAVA_CLIENT_ID,
    STRAVA_CLIENT_SECRET,
    STRAVA_AUTH_URL,
    STRAVA_TOKEN_URL,
    STRAVA_API_BASE,
    DEBUG
)
from database import save_strava_tokens, get_strava_tokens, save_activity, get_most_recent_activity_date


def get_auth_url(redirect_uri="http://localhost:8000/auth/callback"):
    """Generate the Strava OAuth authorization URL."""
    return f"{STRAVA_AUTH_URL}?client_id={STRAVA_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=read_all,activity:read_all"


def exchange_code_for_tokens(code, redirect_uri):
    """Exchange authorization code for access and refresh tokens."""
    payload = {
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    
    response = requests.post(STRAVA_TOKEN_URL, json=payload)
    if response.status_code != 200:
        raise Exception(f"Token exchange failed: {response.text}")
    
    data = response.json()
    save_strava_tokens(data['access_token'], data['refresh_token'], data['expires_at'])
    return data


def refresh_access_token_if_needed():
    """Check if token is expired and refresh if necessary."""
    tokens = get_strava_tokens()
    if not tokens:
        raise Exception("No Strava tokens found. Run strava_auth.py first.")
    
    current_time = int(time.time())
    if current_time >= tokens['expires_at']:
        if DEBUG:
            print("Token expired. Refreshing...")
        
        payload = {
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": tokens['refresh_token']
        }
        
        response = requests.post(STRAVA_TOKEN_URL, json=payload)
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.text}")
        
        data = response.json()
        save_strava_tokens(data['access_token'], data['refresh_token'], data['expires_at'])
        return data['access_token']
    
    return tokens['access_token']


def get_authenticated_headers():
    """Get headers with current valid access token."""
    access_token = refresh_access_token_if_needed()
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


def _convert_pace(speed_ms):
    """Convert speed from m/s to min/km."""
    if speed_ms == 0:
        return None
    km_per_hour = speed_ms * 3.6
    minutes_per_km = 60 / km_per_hour
    return minutes_per_km


def _parse_activity(activity_json):
    """Parse a Strava activity JSON response into standardized format."""
    try:
        start_date_str = activity_json['start_date']
        distance_metres = activity_json.get('distance', 0)
        
        # Avoid division by zero
        if distance_metres == 0:
            return None
            
        moving_time_seconds = activity_json.get('moving_time', 0)
        average_pace_km = _convert_pace(activity_json.get('average_speed', 0))
        
        # Parse splits if available
        splits_json = None
        if 'splits_metric' in activity_json and activity_json['splits_metric']:
            splits_json = json.dumps(activity_json['splits_metric'])
        
        parsed = {
            'strava_id': activity_json['id'],
            'name': activity_json.get('name'),
            'start_date': start_date_str,
            'start_date_local': activity_json.get('start_date_local'),
            'distance_metres': distance_metres,
            'moving_time_seconds': moving_time_seconds,
            'elapsed_time_seconds': activity_json.get('elapsed_time', 0),
            'average_pace_per_km': average_pace_km,
            'average_heartrate': activity_json.get('average_heartrate'),
            'max_heartrate': activity_json.get('max_heartrate'),
            'total_elevation_gain': activity_json.get('total_elevation_gain', 0),
            'kilojoules': activity_json.get('kilojoules'),
            'suffer_score': activity_json.get('suffer_score'),
            'splits_json': splits_json,
            'raw_json': json.dumps(activity_json)
        }
        return parsed
    except Exception as e:
        if DEBUG:
            print(f"Error parsing activity: {e}")
        return None


def fetch_activities(after_date=None, per_page=30):
    """Fetch recent activities from Strava. Optionally after a specific date."""
    headers = get_authenticated_headers()
    activities = []
    page = 1
    
    while True:
        params = {
            'page': page,
            'per_page': per_page
        }
        
        # Strava expects 'after' as a Unix timestamp
        if after_date:
            # If it's a string, parse it
            if isinstance(after_date, str):
                dt = datetime.fromisoformat(after_date.replace('Z', '+00:00'))
            else:
                dt = after_date
            params['after'] = int(dt.timestamp())
        
        response = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params=params
        )
        
        if response.status_code != 200:
            raise Exception(f"Strava API error: {response.text}")
        
        page_activities = response.json()
        if not page_activities:
            break
        
        # Filter for Run type only
        for activity in page_activities:
            if activity.get('type') == 'Run':
                parsed = _parse_activity(activity)
                if parsed:
                    activities.append(parsed)
        
        page += 1
    
    return activities


def fetch_and_cache_recent_activities(limit_days=1):
    """
    Fetch recent activities from Strava and cache them.
    Only fetches activities newer than the most recent cached one.
    """
    # Find the most recent cached activity
    most_recent_date = get_most_recent_activity_date()
    
    if DEBUG:
        print(f"Most recent cached activity: {most_recent_date}")
    
    # Fetch new activities
    activities = fetch_activities(after_date=most_recent_date)
    
    if DEBUG:
        print(f"Fetched {len(activities)} new activities")
    
    # Cache them
    for activity in activities:
        save_activity(activity)
    
    return activities


def get_activity_detail(activity_id):
    """Fetch detailed information for a specific activity."""
    headers = get_authenticated_headers()
    response = requests.get(
        f"{STRAVA_API_BASE}/activities/{activity_id}",
        headers=headers
    )
    
    if response.status_code != 200:
        raise Exception(f"Activity fetch failed: {response.text}")
    
    activity_json = response.json()
    
    # Verify it's a run
    if activity_json.get('type') != 'Run':
        raise Exception("Activity is not a run")
    
    # Check for HR data
    if not activity_json.get('has_heartrate'):
        if DEBUG:
            print(f"Activity {activity_id} has no heart rate data")
    
    return activity_json

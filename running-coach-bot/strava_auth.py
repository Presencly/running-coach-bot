"""
One-time Strava OAuth helper.

Run this script once to authorise the bot with your Strava account:

    python strava_auth.py

It will:
1. Print the Strava authorisation URL — open it in your browser and approve.
2. Paste the 'code' query parameter from the redirect URL when prompted.
3. Exchange the code for tokens and store them in the SQLite database.
"""

import sys
import time
import requests
import database as db
from config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REDIRECT_URI

AUTH_URL = (
    "https://www.strava.com/oauth/authorize"
    f"?client_id={STRAVA_CLIENT_ID}"
    f"&redirect_uri={STRAVA_REDIRECT_URI}"
    "&response_type=code"
    "&approval_prompt=force"
    "&scope=read_all,activity:read_all"
)

TOKEN_URL = "https://www.strava.com/oauth/token"


def main():
    db.init_db()

    existing = db.get_strava_tokens()
    if existing:
        remaining = existing["expires_at"] - int(time.time())
        print(f"Tokens already stored (expires in {remaining}s). Re-authorising will overwrite them.")
        confirm = input("Continue? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    print("\nStep 1 — Open this URL in your browser and approve access:")
    print(f"\n  {AUTH_URL}\n")
    print("After approving, Strava will redirect to your redirect URI.")
    print("Copy the 'code' value from the URL query string.\n")

    code = input("Paste the authorisation code here: ").strip()
    if not code:
        print("No code entered. Exiting.")
        sys.exit(1)

    print("\nExchanging code for tokens...")
    resp = requests.post(TOKEN_URL, data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=15)

    if not resp.ok:
        print(f"Token exchange failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_at = data["expires_at"]
    athlete = data.get("athlete", {})

    db.save_strava_tokens(access_token, refresh_token, expires_at)

    print(f"\nAuthorised as: {athlete.get('firstname', '')} {athlete.get('lastname', '')}")
    print(f"Access token expires at: {expires_at} (auto-refreshed by the bot)")
    print("\nTokens saved to database. You can now run bot.py.")


if __name__ == "__main__":
    main()

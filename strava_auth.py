"""
Single-use Strava OAuth helper script.
Guides the user through the OAuth flow to get initial tokens.
"""
import sys
from strava_client import get_auth_url, exchange_code_for_tokens
from database import init_db


def main():
    """Run the Strava OAuth flow."""
    print("=== Strava OAuth Setup ===\n")
    
    # Initialize database first
    print("Initializing database...")
    init_db()
    print("✓ Database ready\n")
    
    redirect_uri = "http://localhost:8000/auth/callback"
    auth_url = get_auth_url(redirect_uri)
    
    print(f"1. Open this URL in your browser:\n   {auth_url}\n")
    print("2. Click 'Authorize' to grant the bot permission")
    print("3. You'll be redirected to a callback URL\n")
    
    code = input("Enter the 'code' parameter from the callback URL: ").strip()
    
    if not code:
        print("Error: No code provided")
        sys.exit(1)
    
    try:
        print("\nExchanging code for tokens...")
        tokens = exchange_code_for_tokens(code, redirect_uri)
        print("✓ Success! Tokens saved to database\n")
        print(f"Access token: {tokens['access_token'][:20]}... (expires in {tokens['expires_in']}s)")
        print(f"Refresh token: {tokens['refresh_token'][:20]}...")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

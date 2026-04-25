# Quick Start Guide

Get your Running Coach Bot up and running in 5 minutes.

## Step 1: Prerequisites

Gather these before starting:
- Python 3.11 or newer
- Telegram account
- Strava account
- Anthropic API key (from https://console.anthropic.com)
- Strava API credentials (from https://www.strava.com/settings/api)

## Step 2: Clone and Setup

```bash
# Clone/download the project
cd running-coach-bot

# Create Python virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Step 3: Configure

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials
# Required:
# - TELEGRAM_BOT_TOKEN (from @BotFather)
# - TELEGRAM_USER_ID (your ID, get from @userinfobot)
# - STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET
# - ANTHROPIC_API_KEY (from Anthropic)
```

**Where to get credentials:**

| Credential | Where | How |
|-----------|-------|-----|
| `TELEGRAM_BOT_TOKEN` | Telegram | Message [@BotFather](https://t.me/botfather), create new bot, copy token |
| `TELEGRAM_USER_ID` | Telegram | Message [@userinfobot](https://t.me/userinfobot) to get your ID |
| `STRAVA_CLIENT_ID` & `STRAVA_CLIENT_SECRET` | Strava | Go to [Settings → API](https://www.strava.com/settings/api), create app, copy credentials |
| `ANTHROPIC_API_KEY` | Anthropic | Go to [Console](https://console.anthropic.com), create API key |

## Step 4: Strava OAuth

Run the auth script to grant the bot access to your Strava data:

```bash
python strava_auth.py
```

Follow the prompts:
1. Open the printed URL in your browser
2. Click "Authorize"
3. Copy the code from the callback URL
4. Paste it into the script

You'll see: `✓ Success! Tokens saved to database`

## Step 5: Run the Bot

```bash
python bot.py
```

You should see:
```
✓ Database initialized
✓ Strava tokens available
✓ Handlers registered
🚀 Bot is running. Send messages on Telegram!
```

## Step 6: Initialize Your Plan

Open Telegram and send the bot:
```
/setup
```

The bot will generate your 24-week training plan. You'll see:
```
✅ Plan generated successfully!
📊 168 sessions across 24 weeks
🏁 Race day: 2026-10-11
⏱️ Goal pace: 6.00/km
```

## Step 7: Start Coaching!

Message your bot naturally:
- "What should I run today?"
- "How did my run go?"
- "Am I on track?"
- "What's my week looking like?"

## Troubleshooting

### Bot not responding
- Check `TELEGRAM_USER_ID` matches your Telegram ID
- Check `TELEGRAM_BOT_TOKEN` is correct
- Restart the bot

### Strava connection failing
- Run `python strava_auth.py` again to re-authenticate
- Check that `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` are correct

### Claude API errors
- Check `ANTHROPIC_API_KEY` is valid and has available credits
- Check your internet connection

## Next: Deploy to Production

Once working locally, deploy to Railway or Fly.io (see README.md for instructions).

## Useful Commands

```bash
# Show today's session
/today

# Show this week's plan
/week

# Show 4-week training progress
/progress

# Manually fetch latest Strava activities
/fetch_recent
```

---

Need help? Check README.md for more detailed information.

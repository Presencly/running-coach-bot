# Running Coach Telegram Bot

A conversational AI running coach that lives in Telegram, integrates with Strava for run data, and uses Claude to provide personalized coaching feedback and training plan management.

## Architecture

```
Telegram (user) → Python Bot → Strava API (run data + HR)
                             → SQLite (plan, activities, tokens, history)
                             → Claude API (coaching intelligence)
```

## Features

- **Conversational Coaching**: Ask your coach naturally—"How did my run go?", "What should I run today?", "Am I on track?"
- **Strava Integration**: Automatic run data fetching with heart rate analysis
- **Training Plans**: Full 24-week personalized plan to your half-marathon goal
- **Plan Adjustments**: Dynamic plan updates based on your progress and feedback
- **HR Zone Analysis**: Identifies patterns like "easy days running too hard"
- **Progress Tracking**: Weekly reviews and performance assessments

## Setup

### Prerequisites
- Python 3.11+
- Telegram account
- Strava account
- Anthropic (Claude) API key

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with:
- `TELEGRAM_BOT_TOKEN`: Get from [@BotFather](https://t.me/botfather) on Telegram
- `TELEGRAM_USER_ID`: Your Telegram user ID (send `/start` to the bot once it's running to see it, or use [@userinfobot](https://t.me/userinfobot))
- `STRAVA_CLIENT_ID` & `STRAVA_CLIENT_SECRET`: Get from [Strava Settings → API](https://www.strava.com/settings/api)
- `ANTHROPIC_API_KEY`: Get from [Anthropic Console](https://console.anthropic.com)

### 3. Strava OAuth Setup

Before running the bot, you need to complete the OAuth flow with Strava:

```bash
python strava_auth.py
```

This script will:
1. Print an authorization URL
2. Ask you to visit it and authorize the app
3. Capture the callback code
4. Exchange it for tokens and store them in the database

**Important**: Strava access tokens expire every 6 hours. The bot handles this automatically — it will refresh tokens silently before each API call.

### 4. Initialize Training Plan

Run the bot once to create the database:

```bash
python bot.py
```

Once it's running, send it the `/setup` command:
- On Telegram, message the bot: `/setup`
- It will generate your complete 24-week training plan

## Running the Bot

### Local Development

```bash
python bot.py
```

The bot will:
1. Initialize the SQLite database
2. Check for Strava tokens (remind you to run `strava_auth.py` if missing)
3. Start polling for incoming Telegram messages
4. Print logs to stdout

### Deployment to Railway or Fly.io

Both platforms support Python apps and persistent storage volumes.

#### Railway

1. Fork/push this repo to GitHub
2. Connect to Railway via the dashboard
3. Set environment variables in Railway dashboard
4. Railway will detect `requirements.txt` and run `python bot.py`

#### Fly.io

1. Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

2. Deploy with `flyctl deploy`
3. Set secrets: `flyctl secrets set TELEGRAM_BOT_TOKEN=... ANTHROPIC_API_KEY=...` etc.

For persistent SQLite storage, mount a volume in your deployment configuration.

## Usage

### Conversational Queries

Just message naturally. The bot understands:

- **Run analysis**: "How did my run go?" → Analyzes last activity against your plan
- **Today's session**: "What should I run today?" → Shows today's prescribed workout
- **Week overview**: "What does my week look like?" → Shows all sessions for the week
- **Progress**: "Am I on track?" → Compares recent performance vs goal pace
- **Plan adjustments**: "Can I swap days?" / "I'm tired, can you adjust?" → Updates plan with reasoning
- **General queries**: "What's my goal pace?" / "How should I fuel?" → Coaching advice

### Commands

- `/start` — Welcome message
- `/today` — Show today's session
- `/week [number]` — Show a week's plan (default: current week)
- `/progress` — Show 4-week training assessment
- `/fetch_recent` — Manually pull latest activities from Strava
- `/setup` — Generate the 24-week training plan

## Database Schema

### `strava_tokens`
Stores current Strava OAuth tokens with automatic refresh capability.

### `activities`
Cached Strava activities (runs only), including:
- Distance, time, pace, HR data
- Per-km splits
- Elevation gain, suffer score

### `plan_sessions`
24-week training plan with:
- Session type (easy, tempo, intervals, long run, rest)
- Target distance, pace, HR zone
- Completion status and matched activity

### `plan_metadata`
Plan context: race date, goal/stretch paces, current phase, generation timestamp.

### `conversations`
Recent chat history (last 10-15 messages) for conversational context.

## Career Development & Future Enhancements

### Phase 2 Features (Optional)
- **Strava Webhooks**: Receive automatic notifications for new activities
- **Weekly Reviews**: Run Claude analysis at end of week, regenerate next 7-14 days
- **Injury Alerts**: Flag patterns that suggest overtraining or poor recovery
- **Weather Integration**: Adjust guidance for Melbourne weather
- **Splits Analysis**: Per-km feedback on pacing consistency

### Extended Capabilities
- **Nutrition Logging**: Track fueling and recovery nutrition
- **Sleep Integration**: Correlate sleep with run performance
- **Strength Training**: Track complementary strength/cross-training
- **Multi-athlete**: Support planning for multiple users (currently single-user for security)

## Architecture Notes

### Why Claude vs Other LLMs?
- Haiku (fast, cheap) for daily queries and conversational coaching
- Sonnet (smarter) for training plan generation and complex adjustments
- Excellent context window for athlete history and detailed plans

### Why SQLite?
- Zero setup or infrastructure
- Runs anywhere (laptop, Railway, Fly.io)
- Perfect for single-athlete use case
- Easy backups (just copy the file)

### Token Management
Strava tokens are securely stored and automatically refreshed:
- Every API call checks token expiry
- Refresh happens silently if needed
- No user intervention required

### Error Handling
- **Strava API down**: Bot uses cached data + alerts user
- **Claude API down**: User gets "temporarily unavailable" message
- **Token refresh fails**: User is asked to re-run `strava_auth.py`

## Project Structure

```
running-coach-bot/
├── bot.py                    # Main Telegram bot entry point
├── config.py                 # Configuration and system prompt
├── database.py               # SQLite CRUD and schema
├── strava_client.py          # Strava OAuth, API calls, token refresh
├── ai_coach.py               # Claude API integration and prompting
├── training_plan.py          # Plan generation, parsing, matching
├── strava_auth.py            # One-time OAuth helper script
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
└── README.md                 # This file
```

## Troubleshooting

### "No Strava tokens found"
Run `python strava_auth.py` to complete the OAuth flow.

### "Unauthorized" messages
Check that `TELEGRAM_USER_ID` in `.env` matches your actual Telegram ID.

### "Activity fetch failed"
Strava API is rate-limited (100 req/15 min, 1000/day). The bot caches aggressively, so try again later.

### Large number of outdated dependencies warnings
This is expected. The main dependencies (python-telegram-bot, anthropic, requests) are current. Warnings about transitive deps are usually harmless.

## Security Notes

- The bot only responds to a single hardcoded Telegram user ID (you)
- Strava tokens and Anthropic API key should never be committed to git
- Use `.env` file locally; set via platform secrets in production
- SQLite file contains your personal training data — keep it private

## License

This project is provided as-is for personal use.

---

**Last updated**: April 2026

# Running Coach Bot

A conversational AI running coach on Telegram. Connects to Strava for run data, stores a structured training plan in SQLite, and uses Claude for coaching intelligence.

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A [Telegram bot token](https://core.telegram.org/bots/tutorial) from @BotFather
- A [Strava API application](https://www.strava.com/settings/api)
- An [Anthropic API key](https://console.anthropic.com/)

### 2. Install dependencies

```bash
cd running-coach-bot
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in all values
```

**Get your Telegram user ID:** Message @userinfobot on Telegram — it will reply with your numeric ID. Set this as `TELEGRAM_ALLOWED_USER_ID` so only you can use the bot.

**Strava redirect URI:** In your Strava app settings, add `http://localhost:8080/callback` as an authorised callback domain. The auth script doesn't run a server — just paste the code from the URL manually.

### 4. Authenticate with Strava (one-time)

```bash
python strava_auth.py
```

Follow the prompts — it prints a URL, you approve in your browser, paste back the `code` from the redirect URL.

### 5. Start the bot

```bash
python bot.py
```

On first run, message the bot on Telegram and send `/generateplan` to generate your 24-week training plan.

---

## Commands

| Command | Description |
|---|---|
| `/start` | Greeting and current week status |
| `/today` | Today's prescribed session |
| `/week` | This week's full schedule |
| `/sync` | Manually sync new activities from Strava |
| `/generateplan` | Generate the initial 24-week plan (one-time) |

**Or just message naturally:**
- "How did my run go?" — analyses your latest Strava activity
- "What should I run today?" — today's session with coaching context
- "What does my week look like?" — weekly schedule
- "I'm feeling tired, should I skip tomorrow?" — plan adjustment via Sonnet
- "Am I on track for my goal?" — 4-week progress check
- "Weekly review" — Sonnet-powered week analysis and plan adjustment

---

## Deployment (Railway)

1. Push this repo to GitHub
2. Create a new Railway project from the repo
3. Add a volume and set `DATABASE_PATH=/data/coach.db`
4. Set all environment variables in Railway's dashboard
5. Deploy — Railway uses the `Dockerfile` automatically

**Run Strava auth locally first** (before deploying), so tokens are already in the DB. Then upload the `coach.db` file to your Railway volume.

---

## Architecture

```
Telegram → bot.py → ai_coach.py → Claude API (Haiku for chat, Sonnet for plan gen)
                  → strava_client.py → Strava API (with auto token refresh)
                  → training_plan.py → database.py → SQLite (coach.db)
```

- `config.py` — env vars, Claude models, system prompt
- `database.py` — SQLite schema and all CRUD operations
- `strava_client.py` — Strava OAuth refresh, activity fetching, pace/HR utils
- `ai_coach.py` — context assembly, Claude API calls, run analysis
- `training_plan.py` — plan generation, session matching, week formatting
- `bot.py` — Telegram handlers, intent routing, startup
- `strava_auth.py` — one-time Strava OAuth helper script

# Running Coach Telegram Bot — Project Index

Complete conversational AI running coach built for Telegram, Strava, and Claude.

## 📚 Documentation

Start here based on your goal:

### 🚀 Getting Started
- **[QUICKSTART.md](QUICKSTART.md)** — 5-minute setup guide (START HERE)
  - Prerequisites checklist
  - Environment setup
  - First run
  - Troubleshooting

### 📖 Comprehensive Guides
- **[README.md](README.md)** — Full project overview
  - Features & architecture
  - Complete setup instructions
  - Usage guide
  - Database schema reference

- **[DEPLOYMENT.md](DEPLOYMENT.md)** — Production deployment
  - Railway setup (recommended)
  - Fly.io setup
  - Docker Compose for self-hosted
  - Monitoring & backups

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Technical deep dive
  - Design philosophy
  - Component descriptions
  - Data flow diagrams
  - Extension points
  - Performance notes

## 🧩 Core Source Files

| File | Purpose |
|------|---------|
| `bot.py` | Telegram bot entry point & message handlers |
| `config.py` | Configuration, environment, system prompt |
| `ai_coach.py` | Claude API integration & coaching logic |
| `strava_client.py` | Strava OAuth & activity fetching |
| `training_plan.py` | Plan generation, parsing, matching |
| `database.py` | SQLite schema & CRUD operations |
| `strava_auth.py` | One-time OAuth setup helper |

## ⚙️ Configuration Files

| File | Purpose |
|------|---------|
| `.env.example` | Template for environment variables |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image for deployment |
| `Procfile` | Deployment manifest (Railway/Heroku) |
| `.gitignore` | Git ignore rules |

## 🎯 Quick Navigation

### I want to...

**...run it locally right now**
→ See [QUICKSTART.md](QUICKSTART.md)

**...deploy to production**
→ See [DEPLOYMENT.md](DEPLOYMENT.md)

**...understand the architecture**
→ See [ARCHITECTURE.md](ARCHITECTURE.md)

**...customize athlete profile**
→ Edit `config.py` → `ATHLETE_PROFILE` dict

**...add a new Telegram command**
→ See `bot.py` examples, then [ARCHITECTURE.md#Add-a-New-Command](ARCHITECTURE.md)

**...modify Claude behavior**
→ Edit `config.py` → `SYSTEM_PROMPT`

**...fetch more data from Strava**
→ See `strava_client.py` & [ARCHITECTURE.md#Add-Strava-Data](ARCHITECTURE.md)

**...understand the database**
→ See `database.py` CRUD functions & [README.md#Database-Schema](README.md)

## 📋 Checklist: Getting Started

- [ ] Clone/download project
- [ ] Install Python 3.11+
- [ ] Create Telegram bot (@BotFather) → get `TELEGRAM_BOT_TOKEN`
- [ ] Get Telegram user ID (@userinfobot) → `TELEGRAM_USER_ID`
- [ ] Create Strava app (strava.com/settings/api) → `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`
- [ ] Get Anthropic API key (console.anthropic.com) → `ANTHROPIC_API_KEY`
- [ ] `pip install -r requirements.txt`
- [ ] Copy `.env.example` → `.env`, fill in credentials
- [ ] `python strava_auth.py` (OAuth setup)
- [ ] `python bot.py` (start bot)
- [ ] Send `/setup` in Telegram (generate plan)
- [ ] Start messaging your coach!

## 🔧 Customization Guide

### Change Athlete Profile
Edit `config.py`:
```python
ATHLETE_PROFILE = {
    "name": "Your Name",
    "race_name": "Your Race",
    "race_date": "YYYY-MM-DD",
    "goal_pace_per_km": 6.0,  # minutes
    ...
}
```

### Change Coaching Style
Edit `config.py` → `SYSTEM_PROMPT`:
```python
SYSTEM_PROMPT = """You are an experienced running coach...
Change this text to adjust tone, emphasis, philosophy.
"""
```

### Add More Run Data from Strava
Edit `strava_client.py`:
- Modify `_parse_activity()` to extract new fields
- Add fields to database schema in `database.py` → `activities` table
- Reference new data in AI prompts

### Change Training Plan Duration
Edit `config.py`:
```python
PLAN_WEEKS = 24  # Change to 16, 32, etc.
```

The plan generator will adapt automatically.

## 🚄 Architecture Overview

```
Telegram User
    ↓
[bot.py] — Handles messages, routes to handlers
    ↓
    ├─→ [strava_client.py] — Fetches run data, manages OAuth
    │       ↓
    │   SQLite Database
    │       ↑
    │   [database.py] — Schema & CRUD
    │
    ├─→ [ai_coach.py] — Claude API calls, generates coaching
    │       ↓
    │   Claude API (Haiku/Sonnet)
    │
    └─→ [training_plan.py] — Plan management & analysis

  [config.py] — Central configuration
```

## 📊 Features Included

**✅ Already Built**
- Natural language coaching via Telegram
- Strava data fetching with HR analysis
- 24-week personalized training plan generation
- Run analysis vs. prescribed sessions
- Weekly progress assessment
- Plan session matching
- Conversation history for context
- Automatic token refresh
- Secure single-user setup

**🔮 Future Enhancements** (See ARCHITECTURE.md)
- Weekly automatic reviews
- Injury/overtraining alerts
- Strava webhook notifications
- Weather-aware coaching
- Nutrition integration

## 📞 Support

- **Setup issues**: See QUICKSTART.md troubleshooting
- **Deployment questions**: See DEPLOYMENT.md
- **Code questions**: See ARCHITECTURE.md & inline code comments
- **API issues**: Check service status (Telegram, Strava, Anthropic)

---

**Ready?** Start with [QUICKSTART.md](QUICKSTART.md) and you'll be up in 5 minutes! 🏃💨

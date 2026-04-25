# Architecture & Development Notes

Technical details about the Running Coach Bot design and how to extend it.

## Design Philosophy

**Keep it simple.** The entire system is a single Python process with one SQLite file. No microservices, no complex queues, no frontend. The Telegram interface IS the application.

### Why This Architecture?

1. **Single Process**: Easier to deploy, maintain, and debug
2. **SQLite**: Zero infrastructure, runs anywhere, easy backups
3. **Claude API**: Delegates all AI work to Anthropic (no ML ops)
4. **Telegram**: Already has servers, auth, messaging — we just use the bot API

## Core Components

### `config.py`
Central configuration. Everything a deployment needs:
- API credentials (via environment vars)
- Athlete profile (hardcoded for this user)
- System prompt (the coaching instructions for Claude)
- Database path
- Constants (HR zones, plan structure, etc.)

**To customize**: Edit the `ATHLETE_PROFILE` dict to change athlete details, race date, goals, etc.

### `database.py`
SQLite abstraction layer. Features:
- Context manager for safe connections
- CRUD functions for each table
- Automatic schema creation (`init_db()`)
- Conversation history management

**Pattern**: All database access goes through this module, never raw SQL elsewhere.

### `strava_client.py`
Strava API integration:
```
OAuth → Token Storage → Token Refresh (automatic) → API Calls → Parsing → Cache
```

**Key insights**:
- `refresh_access_token_if_needed()` runs before every API call
- `_parse_activity()` converts Strava JSON to internal format
- `fetch_activities()` pages through results and filters for "Run" type only
- All activities are cached in SQLite to minimize API calls

**To extend**: Add functions for different Strava endpoints (e.g., athlete stats, gear, segments).

### `ai_coach.py`
Claude API integration. Three main methods:

1. **`chat()`**: Daily queries using Haiku (fast, cheap)
   - Include recent activities as context
   - Include upcoming week sessions
   - Store user/assistant messages for continuity

2. **`generate_training_plan()`**: Initial 24-week plan using Sonnet (smarter)
   - Parse JSON response
   - Handle extraction if Claude wraps it in text
   - Store all sessions in database

3. **`analyze_run()`**: Detailed feedback on a specific activity
   - Compare against prescribed session
   - Analyze pace, HR, effort

**To extend**: Add methods for:
- Weekly reviews with plan regeneration
- Injury warnings
- Nutrition recommendations
- Weekly summary reports

### `training_plan.py`
Plan generation and matching:

- `generate_and_store_plan()`: Claude generates JSON, parse and store
- `match_activity_to_plan()`: Smart matching of runs to prescribed sessions
- `get_week_summary()`: Format a week's plan for display
- `assess_progress()`: Compare recent vs goal pace

**Data flow**:
```
Claude (JSON) → parse_plan_from_claude() → sessions list → save_plan_sessions_bulk() → database
```

### `bot.py`
Telegram bot entry point. Uses `python-telegram-bot` library.

**Message Flow**:
```
User Message → is_authorized() → handler function → AI/Database → Telegram Response
```

**Handlers**:
- `handle_message()`: Free-text → AI coach
- `/today`: Query today's session
- `/week`: Show week plan
- `/progress`: Training assessment
- `/setup`: Generate initial plan
- `/fetch_recent`: Pull latest Strava data (manual)

**Important**: All handlers check `is_authorized()` — single-user security.

## Data Flow Examples

### "How did my run go?"
```
User Message
  ↓
handle_message() calls coach.chat()
  ↓
AiCoach._get_context_data() fetches:
  - Recent activities from DB
  - Upcoming sessions from DB
  ↓
Claude receives:
  - System prompt
  - Context (recent runs, upcoming plan)
  - Conversation history
  - User message
  ↓
Claude returns coaching feedback
  ↓
Message stored in conversations table
  ↓
Response sent to Telegram
```

### "What should I run today?"
```
get_today_session()
  ↓
Query plan_sessions WHERE session_date = TODAY
  ↓
If found: format and send description/targets
If not found: inform user no session prescribed
```

### Bot First Run
```
python bot.py
  ↓
init_db() creates schema
  ↓
get_strava_tokens() checks database
  ↓
If missing: warn user to run strava_auth.py
  ↓
If present: start polling
  ↓
User sends /setup
  ↓
generate_and_store_plan():
  - Claude generates JSON for 24 weeks
  - Parse sessions
  - Insert all into database
  - Update plan_metadata
```

## Extension Points

### Add a New Command

Example: `/splits` to show last run's per-km splits

```python
# In bot.py
async def splits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        # Get most recent activity
        activities = get_recent_activities(limit=1)
        if not activities:
            await update.message.reply_text("No recent activities")
            return
        
        activity = activities[0]
        splits = json.loads(activity['splits_json']) if activity['splits_json'] else []
        
        message = f"📊 Splits from {activity['name']}:\n\n"
        for i, split in enumerate(splits):
            km = i + 1
            pace = split.get('pace_per_km')  # or parse from moving_time/distance
            message += f"km {km}: {pace:.2f}/km\n"
        
        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# Register in main()
application.add_handler(CommandHandler("splits", splits))
```

### Add a New AI Capability

Example: Weekly review with plan regeneration

```python
# In ai_coach.py
def weekly_review_and_adjust(self):
    """Analyze past week, suggest adjustments."""
    review_prompt = f"""
    Week review for {ATHLETE_PROFILE['name']}:
    
    {self._get_context_data()}
    
    Provide:
    1. Summary of the week (what went well, what didn't)
    2. Suggested adjustments for next week
    3. Any injury/fatigue concerns
    """
    
    messages = [{"role": "user", "content": review_prompt}]
    response = self.client.messages.create(
        model=CLAUDE_MODEL_PLANNING,
        max_tokens=1200,
        system=self.system_prompt,
        messages=messages
    )
    return response.content[0].text

# Call from bot with /review command
```

### Add Database Tables

```python
# In database.py
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        # ... existing tables ...
        
        # New table: gear
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gear (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT,  -- 'shoes', 'watch', 'shirt', etc.
                purchase_date DATE,
                km_used REAL DEFAULT 0,
                notes TEXT
            )
        """)
        conn.commit()
```

### Add Strava Data

The bot currently pulls: distance, time, pace, HR, elevation, effort score, splits.

To add more (e.g., cadence, temperature, wind):
1. **Verify available in Strava API**: https://developers.strava.com/docs/reference/
2. **Add to `_parse_activity()`** in strava_client.py
3. **Add to schema** if needs persistent storage
4. **Update Claude system prompt** to reference new data

## Testing Locally

### Dry Run (No APIs)
```bash
# Check imports
python -c "import bot; import ai_coach; import strava_client"
```

### Full Setup
1. Fill `.env` with test credentials
2. Run `python strava_auth.py` (one-time)
3. Create a test Telegram bot for development
4. Run `python bot.py`
5. Send messages to your test bot
6. Check logs for errors

### Debug Mode
Set `DEBUG=True` in config.py for verbose logging.

## Performance Considerations

### Slow Areas

1. **Claude API**: 2-10 seconds per request (acceptable for Telegram)
   - Mitigation: Use Haiku for daily queries, Sonnet only for plan generation
   - Add a "thinking..." indicator before slow operations

2. **Strava API**: 500ms-2s per request
   - Mitigation: Aggressive caching (only fetch new data)
   - Done automatically via `get_most_recent_activity_date()`

3. **SQLite queries**: Generally <100ms
   - Only issue: conversation history retrieval across many rows
   - Mitigation: Keep history limit low (current: 15 messages)

### Scalability Limits

**Current design handles**:
- Single athlete (hardcoded user ID)
- 24-week plan (~170 sessions)
- 4 years of activity history (if user started at 1000 activities)
- Daily messaging (plenty of rate-limit headroom)

**To scale to multi-user**: Would need to refactor:
- Remove `TELEGRAM_USER_ID` enforcement
- Add `users` table in database
- Scope all queries to user_id
- Use Postgres instead of SQLite

Not planned for this project, but straightforward if needed.

## Monitoring & Debugging

### Check Database Health
```bash
# List all sessions
sqlite3 coach.db "SELECT id, session_date, session_type, description FROM plan_sessions LIMIT 5"

# Count activities
sqlite3 coach.db "SELECT COUNT(*) FROM activities"

# View conversation
sqlite3 coach.db "SELECT role, content FROM conversations ORDER BY created_at DESC LIMIT 3"
```

### Check API Connectivity
```python
# In Python shell
from strava_client import fetch_activities
activities = fetch_activities()
print(f"Retrieved {len(activities)} activities")
```

### Check Claude
```python
from ai_coach import AiCoach
coach = AiCoach()
response = coach.chat("Test message")
print(response)
```

## Future Enhancements

### High Priority
- Weekly automatic review + plan regeneration
- Injury/overtraining alerts (based on HR, volume, pace trends)
- Better activity matching (use ML clustering if needed)

### Medium Priority
- Nutrition logging integration
- Weather-aware coaching ("Looks like rain today, adjust pace")
- Strava webhook support (real-time activity notifications)

### Low Priority
- Strength/cross-training logging
- Sleep data integration (Apple Health/Oura)
- Multi-athlete support
- Web dashboard

---

**Philosophy**: This is a coaching tool, not a fitness platform. Stay focused on running advice backed by data.🏃

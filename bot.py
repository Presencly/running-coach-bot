"""
Main Telegram bot entry point.
Handles message routing, user context, and integration with Strava, Hevy, and Claude.
"""
import asyncio
import logging
from datetime import datetime
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_USER_ID,
    DEBUG,
    ATHLETE_PROFILE,
    HEVY_API_KEY,
    RAILWAY_URL,
)
from database import init_db, get_strava_tokens
from strava_client import fetch_and_cache_recent_activities
from ai_coach import AiCoach
from training_plan import (
    generate_and_store_plan,
    get_today_session,
    get_week_summary,
    assess_progress,
)
from gym_plan import (
    get_today_gym_session,
    get_gym_week_summary,
    create_hevy_routines_for_week,
)
from scheduler import create_scheduler
from webhook import start_webhook_server

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG if DEBUG else logging.INFO
)
logger = logging.getLogger(__name__)


def is_authorized(user_id):
    return user_id == TELEGRAM_USER_ID


async def _reply(update, text):
    """Send a reply, splitting if over Telegram's 4096 char limit."""
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000], parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML)


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    msg = (
        f"👋 Welcome back, {ATHLETE_PROFILE['name']}!\n\n"
        f"Race: {ATHLETE_PROFILE['race_name']} — {ATHLETE_PROFILE['race_date']}\n\n"
        "I'm your unified running + gym coach. Talk to me naturally:\n"
        "• 'How did my run go?'\n"
        "• 'What should I do at the gym today?'\n"
        "• 'How's my bench press progressing?'\n"
        "• 'What does my week look like?'\n"
        "• 'I'm tired, should I train today?'\n\n"
        "Commands: /today /week /gym_today /progress /fetch_recent /fetch_gym /setup"
    )
    await _reply(update, msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    user_message = update.message.text
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=constants.ChatAction.TYPING
    )

    try:
        coach = AiCoach()
        response = coach.chat(user_message)
        await _reply(update, response)
    except Exception as e:
        import anthropic
        error_type = type(e).__name__
        logger.error(f"Error processing message [{error_type}]: {e}", exc_info=True)

        if isinstance(e, anthropic.RateLimitError):
            await _reply(update, "⏳ Claude API rate limit hit — wait 30 seconds and try again.")
        elif isinstance(e, anthropic.APITimeoutError):
            await _reply(update, "⏱️ Claude took too long to respond — try again.")
        elif isinstance(e, anthropic.APIStatusError):
            await _reply(update, f"⚠️ Claude API error ({e.status_code}) — try again in a moment.")
        else:
            await _reply(update, f"❌ Error: {error_type} — {str(e)[:120]}")


async def fetch_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        activities = fetch_and_cache_recent_activities()

        if not activities:
            await _reply(update, "No new Strava activities found.")
        else:
            msg = f"✓ Fetched {len(activities)} new runs from Strava:\n\n"
            for a in activities[-5:]:
                msg += f"• {a['name']}: {a['distance_metres']/1000:.1f}km @ {a['average_pace_per_km']:.2f}/km\n"
            await _reply(update, msg)
    except Exception as e:
        logger.error(f"Error fetching Strava activities: {e}")
        await _reply(update, f"Error fetching activities: {e}")


async def fetch_gym(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    if not HEVY_API_KEY:
        await _reply(update, "Hevy API key not configured. Add HEVY_API_KEY to your environment variables.")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        from hevy_client import fetch_and_cache_recent_workouts
        workouts = fetch_and_cache_recent_workouts()

        if not workouts:
            await _reply(update, "No new Hevy workouts found.")
        else:
            msg = f"✓ Fetched {len(workouts)} new workouts from Hevy:\n\n"
            for w in workouts[-5:]:
                duration = f"{w['duration_seconds']//60}min" if w.get('duration_seconds') else "?"
                msg += f"• {w['title']}: {duration}\n"
            await _reply(update, msg)
    except Exception as e:
        logger.error(f"Error fetching Hevy workouts: {e}")
        await _reply(update, f"Error fetching gym workouts: {e}")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        sessions = get_today_session()
        if not sessions:
            msg = "No run prescribed for today."
        else:
            msg = "📅 <b>Today's Run</b>\n\n"
            for s in sessions:
                msg += f"<b>{s['session_type'].upper()}</b>\n{s['description']}\n"
                if s['target_distance_km']:
                    msg += f"Distance: {s['target_distance_km']:.1f}km\n"
                if s['target_pace_min_per_km']:
                    msg += f"Pace: {s['target_pace_min_per_km']:.2f}/km\n"
        await _reply(update, msg)
    except Exception as e:
        logger.error(f"Error getting today's session: {e}")
        await _reply(update, "Error retrieving today's session.")


async def gym_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        sessions = get_today_gym_session()
        if not sessions:
            msg = "No gym session prescribed for today."
        else:
            import json
            msg = "🏋️ <b>Today's Gym Session</b>\n\n"
            for s in sessions:
                msg += f"<b>{s['session_type'].replace('_', ' ').upper()}</b>\n{s['description']}\n"
                if s.get('exercises_json'):
                    exercises = json.loads(s['exercises_json'])
                    for ex in exercises[:6]:
                        msg += f"• {ex['name']}: {ex.get('sets', 3)}×{ex.get('reps', '8-10')}\n"
                if s.get('hevy_routine_id'):
                    msg += f"\n✓ Routine ready in Hevy app"
        await _reply(update, msg)
    except Exception as e:
        logger.error(f"Error getting gym session: {e}")
        await _reply(update, "Error retrieving gym session.")


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        week_num = 1
        if context.args and context.args[0].isdigit():
            week_num = int(context.args[0])

        run_summary = get_week_summary(week_num)
        gym_summary = get_gym_week_summary(week_num)

        msg = ""
        if run_summary:
            msg += f"🏃 {run_summary}\n\n"
        if gym_summary:
            msg += f"🏋️ {gym_summary}"
        if not msg:
            msg = f"No plan found for week {week_num}."

        await _reply(update, msg)
    except Exception as e:
        logger.error(f"Error getting week plan: {e}")
        await _reply(update, "Error retrieving week plan.")


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        assessment = assess_progress(weeks_back=4)
        await _reply(update, f"📊 <b>Training Progress</b>\n\n{assessment}")
    except Exception as e:
        logger.error(f"Error assessing progress: {e}")
        await _reply(update, "Error assessing progress.")


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        await _reply(update, "🔄 Generating your 24-week running plan... (~90 seconds)")

        coach = AiCoach()
        sessions = generate_and_store_plan()

        msg = (
            f"✅ Running plan generated — {len(sessions)} sessions across 24 weeks\n"
            f"🏁 Race day: {ATHLETE_PROFILE['race_date']}\n"
            f"⏱️ Goal pace: {ATHLETE_PROFILE['goal_pace_per_km']:.2f}/km\n\n"
        )

        # Generate gym plan if Hevy is configured
        if HEVY_API_KEY:
            await _reply(update, "🔄 Generating gym plan...")
            try:
                from gym_plan import generate_and_store_gym_plan
                gym_sessions = generate_and_store_gym_plan(coach, running_sessions=sessions)
                msg += f"🏋️ Gym plan generated — {len(gym_sessions)} sessions across 24 weeks\n\n"

                # Create Hevy routines for week 1
                try:
                    from hevy_client import fetch_and_cache_exercise_templates
                    fetch_and_cache_exercise_templates()
                    routines = create_hevy_routines_for_week(1)
                    if routines:
                        msg += f"📱 Created {len(routines)} Hevy routines for week 1\n\n"
                except Exception as e:
                    logger.warning(f"Could not create Hevy routines: {e}")
            except Exception as e:
                logger.error(f"Gym plan generation failed: {e}")
                msg += "⚠️ Gym plan generation failed — try again later\n\n"

        msg += "Use /today, /gym_today, or /week to see your plan!"
        await _reply(update, msg)

    except Exception as e:
        logger.error(f"Error generating plan: {e}")
        await _reply(update, f"Error generating plan: {e}")


async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force immediate sync of both Strava runs and Hevy workouts."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        msg = "🔄 Syncing...\n\n"

        # Strava
        try:
            runs = fetch_and_cache_recent_activities()
            if runs:
                msg += f"🏃 {len(runs)} new run(s) from Strava\n"
            else:
                msg += "🏃 Strava: up to date\n"
        except Exception as e:
            msg += f"🏃 Strava error: {e}\n"

        # Hevy
        if HEVY_API_KEY:
            try:
                from hevy_client import fetch_and_cache_recent_workouts
                workouts = fetch_and_cache_recent_workouts()
                if workouts:
                    msg += f"🏋️ {len(workouts)} new workout(s) from Hevy\n"
                else:
                    msg += "🏋️ Hevy: up to date\n"
            except Exception as e:
                msg += f"🏋️ Hevy error: {e}\n"

        await _reply(update, msg)
    except Exception as e:
        await _reply(update, f"Sync error: {e}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")


async def main():
    print("\n🏃 Running + Gym Coach Bot Starting...\n")

    init_db()
    print("✓ Database initialized")

    tokens = get_strava_tokens()
    if not tokens:
        print("⚠️  No Strava tokens found. Run: python strava_auth.py")
    else:
        print("✓ Strava tokens available")

    if HEVY_API_KEY:
        print("✓ Hevy API key configured")
        try:
            from hevy_client import fetch_and_cache_exercise_templates
            templates = fetch_and_cache_exercise_templates()
            print(f"✓ Hevy exercise templates cached ({len(templates)} exercises)")
        except Exception as e:
            print(f"⚠️  Could not fetch Hevy exercise templates: {e}")
    else:
        print("⚠️  No Hevy API key — gym features disabled")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("gym_today", gym_today))
    application.add_handler(CommandHandler("week", week))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("fetch_recent", fetch_recent))
    application.add_handler(CommandHandler("fetch_gym", fetch_gym))
    application.add_handler(CommandHandler("sync", sync))
    application.add_handler(CommandHandler("setup", setup))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    print("✓ Handlers registered")

    async with application:
        await application.start()
        await application.updater.start_polling()

        # Scheduler: daily reminders + weekly review
        scheduler = create_scheduler(application.bot)
        scheduler.start()
        print("✓ Scheduler started (daily 7am + Sunday 7pm Melbourne)")

        # Webhook server: Strava auto-sync
        webhook_runner = await start_webhook_server(application.bot)
        if RAILWAY_URL:
            print(f"✓ Webhook server on port, endpoint: {RAILWAY_URL}/webhook/strava")
        else:
            print("✓ Webhook server running locally (use ngrok to expose)")

        print("\n🚀 Bot is running!\n")

        try:
            await asyncio.Event().wait()  # run forever
        finally:
            scheduler.shutdown(wait=False)
            await webhook_runner.cleanup()
            await application.updater.stop()
            await application.stop()


if __name__ == "__main__":
    asyncio.run(main())

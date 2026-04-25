import logging
import sys
from datetime import date, timedelta

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

import database as db
import strava_client as strava
import ai_coach
import training_plan
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Security guard ─────────────────────────────────────────────────────────────

def _is_allowed(update: Update) -> bool:
    if TELEGRAM_ALLOWED_USER_ID == 0:
        return True
    return update.effective_user.id == TELEGRAM_ALLOWED_USER_ID


# ── Intent routing ─────────────────────────────────────────────────────────────

ANALYSIS_KEYWORDS = {"how did", "analyse", "analyze", "last run", "my run", "session go", "how was"}
TODAY_KEYWORDS = {"today", "what should", "schedule", "planned", "what's on", "whats on"}
WEEK_KEYWORDS = {"this week", "next week", "week look", "show me week", "weekly"}
ADJUSTMENT_KEYWORDS = {"swap", "skip", "adjust", "reschedule", "miss", "tired", "sore", "can i move"}
PROGRESS_KEYWORDS = {"on track", "progress", "how am i", "going well", "trajectory"}
REVIEW_KEYWORDS = {"weekly review", "review week", "end of week"}


def _route_intent(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ANALYSIS_KEYWORDS):
        return "analyse_run"
    if any(k in lower for k in REVIEW_KEYWORDS):
        return "weekly_review"
    if any(k in lower for k in WEEK_KEYWORDS):
        return "week_schedule"
    if any(k in lower for k in TODAY_KEYWORDS):
        return "today_session"
    if any(k in lower for k in ADJUSTMENT_KEYWORDS):
        return "plan_adjustment"
    if any(k in lower for k in PROGRESS_KEYWORDS):
        return "progress_check"
    return "general"


# ── Handlers ───────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    text = update.message.text or ""
    intent = _route_intent(text)
    logger.info(f"Message from {update.effective_user.id}: intent={intent}")

    await update.message.chat.send_action("typing")

    if intent == "analyse_run":
        try:
            activity = strava.get_latest_run()
            if not activity:
                reply = "Couldn't find any recent runs on Strava. Have you completed one lately?"
            else:
                run_date = (activity.get("start_date") or "")[:10]
                session = db.get_session_for_date(run_date)
                reply = ai_coach.analyse_run(activity, session)
        except Exception as e:
            logger.error(f"Run analysis failed: {e}")
            reply = ai_coach.ask_coach(text)

    elif intent == "today_session":
        today = date.today().isoformat()
        session = db.get_session_for_date(today)
        if session:
            week = session["week_number"]
            dist = f" {session['target_distance_km']:.0f}km" if session.get("target_distance_km") else ""
            reply = ai_coach.ask_coach(
                f"What should I run today? Here's my planned session: "
                f"Week {week}, {session['session_type']}{dist} — {session['description']}"
            )
        else:
            reply = ai_coach.ask_coach(text)

    elif intent == "week_schedule":
        week_num = training_plan.get_current_week_number()
        if "next week" in text.lower():
            week_num += 1
        schedule = training_plan.format_week_schedule(week_num)
        reply = ai_coach.ask_coach(f"Give me context on this week's plan:\n\n{schedule}")

    elif intent == "plan_adjustment":
        reply = ai_coach.check_plan_exists_and_ask_for_adjustment(text)

    elif intent == "progress_check":
        # Pull last 4 weeks of activities
        four_weeks_ago = (date.today() - timedelta(weeks=4)).isoformat()
        recent_activities = db.get_activities_since(four_weeks_ago)
        completed = db.get_recent_completed_sessions(limit=12)

        summary_lines = ["Recent activity (last 4 weeks):"]
        for a in recent_activities[:8]:
            km = (a.get("distance_metres") or 0) / 1000
            pace = strava.seconds_to_pace((a.get("average_pace_per_km") or 0) * 60)
            summary_lines.append(f"- {a['start_date'][:10]}: {km:.1f}km @ {pace}/km")

        done_count = len([s for s in completed if s.get("completed")])
        summary_lines.append(f"\nCompleted sessions in last 4 weeks: {done_count}")

        reply = ai_coach.ask_coach(
            f"Am I on track for my goal? Here's my recent data:\n\n" + "\n".join(summary_lines),
            use_sonnet=True,
        )

    elif intent == "weekly_review":
        week_num = training_plan.get_current_week_number()
        reply = ai_coach.generate_weekly_plan_adjustment(week_num)

    else:
        reply = ai_coach.ask_coach(text)

    await update.message.reply_text(reply)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    meta = db.get_plan_metadata()
    if meta:
        week = training_plan.get_current_week_number()
        phase = training_plan.get_current_phase().replace("_", " ").title()
        msg = (
            f"Hey Rohit! Your coach is ready.\n\n"
            f"You're in Week {week} — {phase} phase.\n"
            f"Race day: {meta['race_date']} 🏃\n\n"
            "Ask me anything: how your last run went, what's on today, "
            "how your week looks, or whether you're on track."
        )
    else:
        msg = (
            "Hey! Running coach bot is online. "
            "It looks like no training plan exists yet — run the setup "
            "or message me 'generate my plan' to create one."
        )
    await update.message.reply_text(msg)


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("Syncing your Strava activities...")
    try:
        new = strava.fetch_new_activities()
        if new:
            # Try to match and process each
            for activity in new:
                training_plan.process_new_activity(activity)
            await update.message.reply_text(f"Synced {len(new)} new run(s) from Strava.")
        else:
            await update.message.reply_text("No new activities found.")
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        await update.message.reply_text(f"Sync failed: {e}")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await handle_message(update, context)


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    week_num = training_plan.get_current_week_number()
    schedule = training_plan.format_week_schedule(week_num)
    await update.message.reply_text(schedule)


async def cmd_generate_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    meta = db.get_plan_metadata()
    if meta:
        await update.message.reply_text(
            "A training plan already exists. Message me if you want to adjust specific sessions."
        )
        return
    await update.message.reply_text(
        "Generating your 24-week training plan with Claude Sonnet... this may take 30-60 seconds."
    )
    success = training_plan.generate_initial_plan()
    if success:
        week_num = training_plan.get_current_week_number()
        schedule = training_plan.format_week_schedule(week_num)
        await update.message.reply_text(
            f"Plan generated! Here's your first week:\n\n{schedule}"
        )
    else:
        await update.message.reply_text(
            "Failed to generate plan. Check logs and try again."
        )


# ── Startup ────────────────────────────────────────────────────────────────────

def main():
    db.init_db()

    tokens = db.get_strava_tokens()
    if not tokens:
        logger.warning("No Strava tokens found. Run strava_auth.py to authenticate.")

    meta = db.get_plan_metadata()
    if not meta:
        logger.info("No training plan found. Bot will prompt user to generate one.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("generateplan", cmd_generate_plan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Running coach bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

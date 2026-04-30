"""
Scheduled tasks: daily training reminders and weekly review messages.
"""
import logging
from datetime import date, datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import json
from config import TELEGRAM_USER_ID, MELBOURNE_TZ, HEVY_API_KEY
from database import (
    get_plan_metadata, get_plan_week, get_gym_plan_week, get_recent_activities,
    get_exercise_pb, upsert_exercise_pb,
)
from training_plan import get_today_session
from gym_plan import get_today_gym_session

logger = logging.getLogger(__name__)
melb_tz = pytz.timezone(MELBOURNE_TZ)


def _current_week():
    from datetime import timedelta
    from config import PLAN_WEEKS
    metadata = get_plan_metadata()
    if not metadata:
        return None
    try:
        race_date = date.fromisoformat(metadata['race_date'])
        start_date = race_date - timedelta(weeks=PLAN_WEEKS)
        weeks_elapsed = (date.today() - start_date).days // 7 + 1
        return max(1, min(24, weeks_elapsed))
    except Exception:
        return None


async def send_daily_reminder(bot):
    """Send morning training reminder at 7am Melbourne time."""
    try:
        run_sessions = get_today_session()
        gym_sessions = get_today_gym_session()

        if not run_sessions and not gym_sessions:
            return  # rest day — no message

        parts = ["☀️ <b>Good morning, Rohit! Here's today:</b>\n"]

        if run_sessions:
            for s in run_sessions:
                stype = s['session_type'].replace('_', ' ').title()
                parts.append(f"🏃 <b>Run:</b> {stype}")
                if s.get('description'):
                    parts.append(f"   {s['description']}")
                if s.get('target_distance_km'):
                    parts.append(f"   Target: {s['target_distance_km']:.1f}km")

        if gym_sessions:
            import json
            for s in gym_sessions:
                stype = s['session_type'].replace('_', ' ').title()
                parts.append(f"🏋️ <b>Gym:</b> {stype}")
                if s.get('description'):
                    parts.append(f"   {s['description']}")
                if s.get('exercises_json'):
                    exercises = json.loads(s['exercises_json'])
                    ex_line = ", ".join(e['name'] for e in exercises[:3])
                    if ex_line:
                        parts.append(f"   {ex_line}...")
                if s.get('hevy_routine_id'):
                    parts.append("   ✓ Routine ready in Hevy")

        await bot.send_message(
            chat_id=TELEGRAM_USER_ID,
            text="\n".join(parts),
            parse_mode="HTML"
        )
        logger.info("Daily reminder sent")
    except Exception as e:
        logger.error(f"Error sending daily reminder: {e}")


async def send_weekly_review(bot):
    """Send Sunday evening weekly review + next week preview."""
    try:
        week_num = _current_week()
        if not week_num:
            return

        # Build a prompt for a compact weekly review
        runs = get_recent_activities(limit=7)
        run_lines = "\n".join([
            f"  {(a.get('start_date_local') or a['start_date'])[:10]}: "
            f"{a['distance_metres']/1000:.1f}km @{a['average_pace_per_km']:.2f}/km"
            for a in runs
        ]) if runs else "  No runs this week"

        next_week = week_num + 1
        run_sessions = get_plan_week(next_week)
        gym_sessions = get_gym_plan_week(next_week)

        run_preview = "\n".join([
            f"  {s['session_date']} — {s['session_type']}"
            + (f" {s['target_distance_km']:.1f}km" if s.get('target_distance_km') else "")
            for s in run_sessions
        ]) if run_sessions else "  No running sessions planned"

        gym_preview = "\n".join([
            f"  {s['session_date']} — {s['session_type'].replace('_', ' ')}"
            for s in gym_sessions
            if s['session_type'] not in ('rest', 'mobility')
        ]) if gym_sessions else "  No gym sessions planned"

        prompt = f"""Write a brief Sunday evening weekly review for Rohit (week {week_num} of 24).

This week's runs:
{run_lines}

Next week's plan (week {next_week}):
Running:
{run_preview}
Gym:
{gym_preview}

Keep it under 150 words. Cover: how this week went, one thing to focus on next week, any load management notes.
Start with "📊 Week {week_num} wrap-up:" and end with "See you Monday 💪" """

        from anthropic import Anthropic
        from config import CLAUDE_MODEL_CHAT, SYSTEM_PROMPT
        client = Anthropic()
        resp = client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        message = resp.content[0].text

        await bot.send_message(
            chat_id=TELEGRAM_USER_ID,
            text=message,
            parse_mode="HTML"
        )
        logger.info("Weekly review sent")
    except Exception as e:
        logger.error(f"Error sending weekly review: {e}")


async def sync_hevy_and_check_pbs(bot):
    """Fetch new Hevy workouts and notify if any exercise PBs were broken."""
    if not HEVY_API_KEY:
        return
    try:
        from hevy_client import fetch_and_cache_recent_workouts
        new_workouts = fetch_and_cache_recent_workouts()
        if not new_workouts:
            return

        logger.info(f"Hevy auto-sync: {len(new_workouts)} new workouts")
        pbs_hit = []

        for workout in new_workouts:
            workout_date = (workout.get('start_time') or '')[:10]
            exercises = json.loads(workout.get('exercises_json') or '[]')
            for ex in exercises:
                template_id = ex.get('template_id')
                if not template_id:
                    continue
                current_1rm = ex.get('best_1rm', 0)
                if current_1rm <= 0:
                    continue
                is_new_pb = upsert_exercise_pb(
                    template_id, ex['title'], current_1rm, workout_date
                )
                if is_new_pb:
                    old_pb = get_exercise_pb(template_id)
                    pbs_hit.append((ex['title'], current_1rm, old_pb))

        if pbs_hit:
            lines = ["🏆 <b>New personal bests!</b>\n"]
            for name, new_1rm, old_1rm in pbs_hit:
                if old_1rm and old_1rm < new_1rm:
                    lines.append(f"• {name}: {new_1rm:.1f}kg 1RM (was {old_1rm:.1f}kg ↑{new_1rm - old_1rm:.1f}kg)")
                else:
                    lines.append(f"• {name}: {new_1rm:.1f}kg 1RM (first recorded)")
            await bot.send_message(
                chat_id=TELEGRAM_USER_ID,
                text="\n".join(lines),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Error in Hevy auto-sync: {e}")


def create_scheduler(bot):
    """Create and return a configured AsyncIOScheduler."""
    scheduler = AsyncIOScheduler(timezone=melb_tz)

    # Daily reminder at 7:00am Melbourne time, every day
    scheduler.add_job(
        send_daily_reminder,
        trigger=CronTrigger(hour=7, minute=0, timezone=melb_tz),
        args=[bot],
        id="daily_reminder",
        replace_existing=True,
    )

    # Weekly review on Sunday at 7:00pm Melbourne time
    scheduler.add_job(
        send_weekly_review,
        trigger=CronTrigger(day_of_week="sun", hour=19, minute=0, timezone=melb_tz),
        args=[bot],
        id="weekly_review",
        replace_existing=True,
    )

    # Hevy auto-sync every hour
    scheduler.add_job(
        sync_hevy_and_check_pbs,
        trigger=CronTrigger(minute=0, timezone=melb_tz),
        args=[bot],
        id="hevy_sync",
        replace_existing=True,
    )

    return scheduler

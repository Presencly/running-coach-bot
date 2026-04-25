"""
Main Telegram bot entry point.
Handles message routing, user context, and integration with Strava + Claude.
"""
import logging
from datetime import datetime
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_USER_ID,
    DEBUG,
    ATHLETE_PROFILE
)
from database import init_db, get_strava_tokens
from strava_client import fetch_and_cache_recent_activities, get_most_recent_activity_date
from ai_coach import AiCoach
from training_plan import (
    generate_and_store_plan,
    get_today_session,
    match_activity_to_plan,
    get_week_summary,
    assess_progress
)


# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG if DEBUG else logging.INFO
)
logger = logging.getLogger(__name__)


def is_authorized(user_id):
    """Check if user is authorized to use this bot."""
    return user_id == TELEGRAM_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    message = f"👋 Welcome to your running coach, {ATHLETE_PROFILE['name']}!\n\n"
    message += f"I'm here to help you prepare for the {ATHLETE_PROFILE['race_name']} on {ATHLETE_PROFILE['race_date']}.\n\n"
    message += "Just message me naturally:\n"
    message += "• 'How did my run go?'\n"
    message += "• 'What should I run today?'\n"
    message += "• 'What does my week look like?'\n"
    message += "• 'Am I on track?'\n"
    message += "\nI'll use your Strava data and training plan to give you coaching feedback."
    
    await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming user messages."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    user_message = update.message.text
    
    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=constants.ChatAction.TYPING
    )
    
    try:
        coach = AiCoach()
        response = coach.chat(user_message)
        
        # Split long messages (Telegram has 4096 char limit)
        if len(response) > 4000:
            parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode=constants.ParseMode.HTML)
        else:
            await update.message.reply_text(response, parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "🤖 Coach is temporarily unavailable. Try again in a moment.",
            parse_mode=constants.ParseMode.HTML
        )


async def fetch_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fetch_recent command to pull latest Strava data."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )
        
        activities = fetch_and_cache_recent_activities()
        
        if not activities:
            await update.message.reply_text("No new activities found.", parse_mode=constants.ParseMode.HTML)
        else:
            message = f"✓ Fetched {len(activities)} new activities from Strava:\n\n"
            for activity in activities[-5:]:  # Show last 5
                pace = activity['average_pace_per_km']
                distance = activity['distance_metres'] / 1000
                message += f"• {activity['name']}: {distance:.1f}km @ {pace:.2f}/km\n"
            
            await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error fetching activities: {e}")
        await update.message.reply_text(f"Error fetching activities: {e}", parse_mode=constants.ParseMode.HTML)


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /today command."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        sessions = get_today_session()
        
        if not sessions:
            await update.message.reply_text("No session prescribed for today.", parse_mode=constants.ParseMode.HTML)
        else:
            message = "📅 <b>Today's Session</b>\n\n"
            for session in sessions:
                message += f"<b>{session['session_type'].upper()}</b>\n"
                message += f"{session['description']}\n"
                if session['target_distance_km']:
                    message += f"Distance: {session['target_distance_km']:.1f}km\n"
                if session['target_pace_min_per_km']:
                    message += f"Pace: {session['target_pace_min_per_km']:.2f}/km\n"
                if session['target_hr_zone']:
                    message += f"HR Zone: {session['target_hr_zone']}\n"
            
            await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error getting today's session: {e}")
        await update.message.reply_text("Error retrieving today's session.", parse_mode=constants.ParseMode.HTML)


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /week command to show current week's plan."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        # Get current week (could be smarter, but for now use week 1)
        week_num = 1
        if context.args and context.args[0].isdigit():
            week_num = int(context.args[0])
        
        summary = get_week_summary(week_num)
        
        if not summary:
            await update.message.reply_text(f"No plan for week {week_num}.", parse_mode=constants.ParseMode.HTML)
        else:
            await update.message.reply_text(f"📋 {summary}", parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error getting week plan: {e}")
        await update.message.reply_text("Error retrieving week plan.", parse_mode=constants.ParseMode.HTML)


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /progress command to show training assessment."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        assessment = assess_progress(weeks_back=4)
        await update.message.reply_text(f"📊 <b>Training Progress</b>\n\n{assessment}", parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error assessing progress: {e}")
        await update.message.reply_text("Error assessing progress.", parse_mode=constants.ParseMode.HTML)


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setup command for initial plan generation."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized")
        return
    
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )
        
        await update.message.reply_text("🔄 Generating your 24-week training plan...", parse_mode=constants.ParseMode.HTML)
        
        sessions = generate_and_store_plan()
        
        message = f"✅ Plan generated successfully!\n\n"
        message += f"📊 {len(sessions)} sessions across 24 weeks\n"
        message += f"🏁 Race day: {ATHLETE_PROFILE['race_date']}\n"
        message += f"⏱️ Goal pace: {ATHLETE_PROFILE['goal_pace_per_km']:.2f}/km\n\n"
        message += "Use /today or /week to see your plan, or just chat naturally!"
        
        await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Error generating plan: {e}")
        await update.message.reply_text(f"Error generating plan: {e}", parse_mode=constants.ParseMode.HTML)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Exception while handling an update: {context.error}")


def main():
    """Start the bot."""
    print("\n🏃 Running Coach Bot Starting...\n")
    
    # Initialize database
    init_db()
    print("✓ Database initialized")
    
    # Check Strava tokens
    tokens = get_strava_tokens()
    if not tokens:
        print("⚠️  No Strava tokens found. Run: python strava_auth.py")
        print("   This is required for the bot to fetch your run data.\n")
    else:
        print("✓ Strava tokens available")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("week", week))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("fetch_recent", fetch_recent))
    application.add_handler(CommandHandler("setup", setup))
    
    # Message handler for free-text conversation
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    print("✓ Handlers registered\n")
    print("🚀 Bot is running. Send messages on Telegram!\n")
    
    # Start polling
    application.run_polling()


if __name__ == "__main__":
    main()

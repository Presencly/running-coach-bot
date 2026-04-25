"""
Strava webhook HTTP server (aiohttp).
Handles GET verification challenge and POST activity events.
"""
import logging
import asyncio
from aiohttp import web
from config import STRAVA_WEBHOOK_VERIFY_TOKEN, PORT, TELEGRAM_USER_ID

logger = logging.getLogger(__name__)


async def handle_verification(request):
    """Strava sends a GET to verify the webhook endpoint."""
    mode = request.rel_url.query.get("hub.mode")
    token = request.rel_url.query.get("hub.verify_token")
    challenge = request.rel_url.query.get("hub.challenge")

    if mode == "subscribe" and token == STRAVA_WEBHOOK_VERIFY_TOKEN:
        logger.info("Strava webhook verified")
        return web.json_response({"hub.challenge": challenge})

    logger.warning(f"Webhook verification failed: mode={mode}, token={token}")
    return web.Response(status=403, text="Forbidden")


async def handle_event(request, bot, on_new_activity):
    """Strava sends a POST for each new event (activity created/updated/deleted)."""
    try:
        data = await request.json()
        logger.info(f"Strava webhook event: {data}")

        object_type = data.get("object_type")
        aspect_type = data.get("aspect_type")
        activity_id = data.get("object_id")

        if object_type == "activity" and aspect_type == "create":
            # Fire and forget — don't block the webhook response
            asyncio.create_task(on_new_activity(bot, activity_id))

        return web.Response(status=200, text="OK")
    except Exception as e:
        logger.error(f"Error handling webhook event: {e}")
        return web.Response(status=200, text="OK")  # always 200 to Strava


async def on_new_activity(bot, activity_id):
    """Fetch new activity from Strava, cache it, analyse it, and notify user."""
    try:
        from strava_client import fetch_activity_by_id, save_activity
        from ai_coach import AiCoach

        activity = fetch_activity_by_id(activity_id)
        if not activity:
            return

        save_activity(activity)
        logger.info(f"Cached new activity {activity_id}")

        coach = AiCoach()
        analysis = coach.analyze_run(activity)

        dist = activity['distance_metres'] / 1000
        pace = activity['average_pace_per_km']
        name = activity.get('name', 'Run')

        msg = (
            f"🏃 <b>New run synced: {name}</b>\n"
            f"{dist:.1f}km @ {pace:.2f}/km\n\n"
            f"{analysis}"
        )
        await bot.send_message(chat_id=TELEGRAM_USER_ID, text=msg, parse_mode="HTML")
        logger.info(f"Sent auto-analysis for activity {activity_id}")

    except Exception as e:
        logger.error(f"Error processing new activity {activity_id}: {e}")


def create_webhook_app(bot):
    """Create and return the aiohttp Application."""
    app = web.Application()
    app.router.add_get("/webhook/strava", handle_verification)
    app.router.add_post(
        "/webhook/strava",
        lambda req: handle_event(req, bot, on_new_activity)
    )
    # Health check for Railway
    app.router.add_get("/health", lambda req: web.Response(text="OK"))
    return app


async def start_webhook_server(bot):
    """Start the aiohttp server. Returns the runner so it can be cleaned up."""
    app = create_webhook_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Webhook server listening on port {PORT}")
    return runner

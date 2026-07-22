import asyncio
import hmac
import json
import traceback
import os
import signal
from aiohttp import web
import discord
from discord.ext import commands

import config

# Graceful-shutdown state lives in utils.helpers. Don't move it here: cogs
# can't `import bot` (this file runs as __main__, so importing it re-executes
# everything under a second module name with separate globals).
from utils import helpers as _shared


_web_app = web.Application()


async def run_healthcheck():
    """Healthcheck server. Returns 503 when the gateway is dead so Railway
    restarts the container. Gated on first on_ready so boot still passes."""
    async def handle(request):
        try:
            if getattr(bot, "_synced", False) and (bot.is_closed() or bot.latency > 60):
                return web.Response(text="unhealthy: gateway down", status=503)
        except Exception:
            pass
        return web.Response(text="ok")

    async def kofi_webhook(request):
        # Must be registered here: aiohttp freezes the router when the site
        # starts, and cogs load after that. Dispatches to the cog per request.
        cog = bot.get_cog("KofiCog")
        if cog is None:
            return web.Response(status=503, text="kofi cog not loaded")
        return await cog.handle_webhook(request)

    async def export_submissions(request):
        # Read-only cursor export of the submissions table, for community
        # mirrors (leaderboard sites and the like). Callers page forward by id:
        # pass the highest id already held as after_id, get the next batch in
        # insertion order, repeat until nextCursor comes back null. Rows are
        # serialized exactly like the scheduled backup (raw column dicts,
        # datetimes as naive-UTC strings), so a consumer of one can consume
        # the other. Off unless EXPORT_TOKEN is set.
        token = os.environ.get("EXPORT_TOKEN", "")
        if not token:
            return web.Response(status=503, text="export disabled")
        auth = request.headers.get("Authorization", "")
        # compare_digest, not ==: string equality short-circuits on the first
        # differing byte, which leaks the token a byte at a time to anyone who
        # can measure response times.
        if not hmac.compare_digest(auth, f"Bearer {token}"):
            return web.Response(status=403, text="forbidden")
        try:
            after_id = int(request.query.get("after_id", 0))
            limit = int(request.query.get("limit", 500))
        except ValueError:
            return web.Response(status=400, text="after_id and limit must be integers")
        if after_id < 0 or not (1 <= limit <= 1000):
            return web.Response(status=400, text="after_id must be >= 0, limit 1 to 1000")
        try:
            from utils.db import get_submissions_after
            rows = await get_submissions_after(after_id, limit)
        except RuntimeError:
            # Pool not initialised (DATABASE_URL unset or boot still in progress).
            return web.Response(status=503, text="database unavailable")
        # A full page may end exactly on the last row; the follow-up call then
        # returns an empty page and nextCursor null, which is fine.
        next_cursor = rows[-1]["id"] if len(rows) == limit else None
        return web.json_response(
            {"rows": rows, "nextCursor": next_cursor},
            dumps=lambda d: json.dumps(d, default=str, ensure_ascii=False))

    app = _web_app
    app.router.add_get("/", handle)
    app.router.add_post("/kofi", kofi_webhook)
    app.router.add_get("/export/submissions", export_submissions)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Healthcheck server running on port {port}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.registry",
    "cogs.leaderboards",
    "cogs.bounty",
    "cogs.submissions",
    "cogs.favourites",
    "cogs.personality",
    "cogs.admin",
    "cogs.kofi",
]


@bot.event
async def on_ready():
    from datetime import datetime, timezone
    # on_ready also fires on reconnects. Only sync commands (rate-limited API)
    # and stamp session_start on the FIRST ready of the process.
    if getattr(bot, "_synced", False):
        print("↻ Reconnected — skipping command re-sync.")
        return
    bot._synced = True
    bot.session_start = datetime.now(timezone.utc)
    print(f"✅ Session started at {bot.session_start.isoformat()}")
    try:
        from utils.helpers import set_bot_ref
        set_bot_ref(bot)
    except Exception as _sbe:
        print(f"[STARTUP] set_bot_ref failed: {_sbe}")
    try:
        guild = discord.Object(id=config.GUILD_ID)
        # Sync all commands to the guild only (global list already cleared)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} slash commands to guild")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")


@bot.event
async def on_error(event_method, *args, **kwargs):
    """Any unhandled error in an event handler → nerve centre, so crashes surface
    in seconds instead of going unnoticed."""
    err = traceback.format_exc()
    print(f"[ON_ERROR] {event_method}:\n{err}")
    try:
        from utils.helpers import nerve_alert
        await nerve_alert(bot, f"event:{event_method}", err)
    except Exception:
        pass


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        retry = int(error.retry_after)
        minutes, seconds = divmod(retry, 60)
        time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        await interaction.response.send_message(
            f"Easy — your card was just refreshed. Try again in {time_str}.",
            ephemeral=True,
        )
    elif isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.",
            ephemeral=True,
        )
    else:
        # Unexpected command failure — surface it to the nerve centre immediately
        # and let the user know, instead of failing silently.
        from utils.helpers import nerve_alert
        _cmd = getattr(interaction.command, "name", "?")
        try:
            await nerve_alert(interaction.client, f"/{_cmd}", error)
        except Exception:
            pass
        try:
            _msg = "Something went wrong there — the Butler has made a note of it."
            if interaction.response.is_done():
                await interaction.followup.send(_msg, ephemeral=True)
            else:
                await interaction.response.send_message(_msg, ephemeral=True)
        except Exception:
            pass
        traceback.print_exc()


async def _graceful_shutdown():
    _shared.set_shutting_down()
    print("[SHUTDOWN] SIGTERM received — draining active submissions...")
    for _ in range(60):
        if _shared.active_submissions() == 0:
            break
        await asyncio.sleep(0.5)
    print(f"[SHUTDOWN] Drained ({_shared.active_submissions()} remaining). Closing bot.")
    await bot.close()


async def main():
    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.ensure_future(_graceful_shutdown())
        )
    except NotImplementedError:
        # Windows (local dev) has no loop signal handlers — Railway/Linux does.
        print("⚠️  SIGTERM handler unavailable on this platform — skipping graceful drain.")
    await run_healthcheck()
    # Initialise Postgres pool if DATABASE_URL is configured
    if os.environ.get('DATABASE_URL'):
        from utils.db import db_init, db_close
        await db_init()
        bot._db_close = db_close
    else:
        bot._db_close = None
        print("⚠️  DATABASE_URL not set — Postgres pool skipped")
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")
                traceback.print_exc()
        try:
            await bot.start(config.TOKEN)
        except discord.HTTPException as e:
            # 429 at login means Discord/Cloudflare rate-limited the token — usually
            # from rapid redeploys/restarts. Back off hard instead of exiting fast, so
            # we don't crash-loop into a Cloudflare 1015 IP ban. The healthcheck server
            # is already running, so Railway keeps the container alive during the wait
            # rather than restarting straight into another login attempt.
            if getattr(e, "status", None) == 429:
                print("[LOGIN] 429 rate limited on login — backing off 15 min before exit "
                      "to let the rate limit / Cloudflare ban clear.")
                await asyncio.sleep(900)
            raise
        finally:
            if bot._db_close:
                await bot._db_close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import traceback
import os
import signal
from aiohttp import web
import discord
from discord.ext import commands

import config

# ---------------------------------------------------------------------------
# Graceful shutdown — shared state imported by cogs via `import bot`
# ---------------------------------------------------------------------------
_shutting_down = False
_active_submissions = 0

def is_shutting_down():
    return _shutting_down

def submission_start():
    global _active_submissions
    _active_submissions += 1

def submission_end():
    global _active_submissions
    _active_submissions = max(0, _active_submissions - 1)


_web_app = web.Application()


async def run_healthcheck():
    """Minimal HTTP server so Railway's healthcheck passes."""
    async def handle(request):
        return web.Response(text="ok")
    app = _web_app
    app.router.add_get("/", handle)
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
    bot.session_start = datetime.now(timezone.utc)
    print(f"✅ Session started at {bot.session_start.isoformat()}")
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
    global _shutting_down
    _shutting_down = True
    print("[SHUTDOWN] SIGTERM received — draining active submissions...")
    for _ in range(60):
        if _active_submissions == 0:
            break
        await asyncio.sleep(0.5)
    print(f"[SHUTDOWN] Drained ({_active_submissions} remaining). Closing bot.")
    await bot.close()


async def main():
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.ensure_future(_graceful_shutdown())
    )
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

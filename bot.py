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


async def run_healthcheck():
    """Minimal HTTP server so Railway's healthcheck passes."""
    async def handle(request):
        return web.Response(text="ok")
    app = web.Application()
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
        raise error


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
        finally:
            if bot._db_close:
                await bot._db_close()


if __name__ == "__main__":
    asyncio.run(main())

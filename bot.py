import asyncio
import traceback
import os
from aiohttp import web
import discord
from discord.ext import commands

import config


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
    try:
        guild = discord.Object(id=config.GUILD_ID)
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


async def main():
    await run_healthcheck()
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")
                traceback.print_exc()
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

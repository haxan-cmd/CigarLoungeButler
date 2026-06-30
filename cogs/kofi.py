import os
import json
import logging
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

import config
from utils.db import (
    kofi_init, add_kofi_donation,
    get_kofi_total, get_kofi_dashboard_message, set_kofi_dashboard_message
)

log = logging.getLogger(__name__)

GOAL = config.KOFI_MONTHLY_GOAL
KOFI_URL = config.KOFI_URL


def _build_embed(total: float) -> discord.Embed:
    pct = min(total / GOAL, 1.0)
    filled = int(pct * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    over = total > GOAL

    embed = discord.Embed(
        title="☕ Support the Cigar Lounge Butler",
        description=(
            f"The Butler runs on [Ko-fi]({KOFI_URL}) donations.\n"
            f"Running costs are **${GOAL:.0f}/month**.\n\n"
            f"**Raised so far:** ${total:.2f}\n"
            f"`{bar}` ${total:.2f} / ${GOAL:.0f}"
            + (" ✅" if over else "")
        ),
        color=0xFF5E5B,
    )
    embed.set_footer(text="Every bit helps keep the lights on.")
    return embed


class KofiCog(commands.Cog, name="KofiCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await kofi_init()

    async def update_dashboard(self):
        result = await get_kofi_dashboard_message()
        if not result:
            return
        channel_id, message_id = result
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(message_id)
            total = await get_kofi_total()
            await msg.edit(embed=_build_embed(total))
        except Exception as e:
            log.warning(f"[KOFI] Failed to update dashboard: {e}")

    async def handle_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.post()
            raw = data.get("data")
            if not raw:
                return web.Response(status=400, text="no data")

            payload = json.loads(raw)

            # Verify token
            expected = os.environ.get("KOFI_TOKEN", "")
            if expected and payload.get("verification_token") != expected:
                log.warning("[KOFI] Invalid verification token")
                return web.Response(status=403, text="forbidden")

            # Only handle donations (not shop orders etc.)
            if payload.get("type") not in ("Donation", "Subscription"):
                return web.Response(text="ok")

            transaction_id = payload.get("kofi_transaction_id", "")
            donor_name = payload.get("from_name", "Anonymous")
            amount = float(payload.get("amount", 0))
            currency = payload.get("currency", "USD")

            inserted = await add_kofi_donation(transaction_id, donor_name, amount, currency)
            if inserted:
                log.info(f"[KOFI] New donation: {donor_name} ${amount} {currency}")
                await self.update_dashboard()

            return web.Response(text="ok")
        except Exception as e:
            log.error(f"[KOFI] Webhook error: {e}")
            return web.Response(status=500, text="error")

    @app_commands.command(name="post_kofi_dashboard", description="Post the Ko-fi support dashboard in this channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_kofi_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        total = await get_kofi_total()
        msg = await interaction.channel.send(embed=_build_embed(total))
        await set_kofi_dashboard_message(interaction.channel_id, msg.id)
        await interaction.followup.send("Dashboard posted.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = KofiCog(bot)
    await bot.add_cog(cog)
    # Register the webhook route on the existing aiohttp app
    import bot as bot_module
    if hasattr(bot_module, '_web_app'):
        bot_module._web_app.router.add_post("/kofi", cog.handle_webhook)
        log.info("[KOFI] Webhook route registered at /kofi")
    else:
        log.warning("[KOFI] No _web_app found — webhook route not registered")

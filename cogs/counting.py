"""Opt-in counting referee. Shares Butler's Postgres layer and is_mod policy."""
import asyncio
import logging
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils.db as db
from utils.counting import MAX_COUNT
from utils.counting_card import user_card,server_card,bean_counter_badge

log = logging.getLogger(__name__)
NO_PINGS = discord.AllowedMentions.none()
_DANGEROUS = ('administrator','manage_roles','manage_guild','manage_channels',
              'manage_webhooks','moderate_members','ban_members','kick_members','manage_messages')


def mod_only():
    async def check(interaction):
        from utils.helpers import is_mod
        if interaction.guild_id != config.GUILD_ID or not is_mod(interaction):
            raise app_commands.CheckFailure('Only Butler moderators can change counting settings.')
        return True
    return app_commands.check(check)


class CountingCog(commands.GroupCog, group_name='count', group_description='Counting game and three-day penalties'):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = config.COUNTING_GAME_CHANNEL_ID
        self.lock = asyncio.Lock()
        self.ready = False

    async def cog_load(self):
        if not self.channel_id or not config.COUNTING_PENALTY_ROLE_ID:
            raise ValueError('Set COUNTING_GAME_CHANNEL_ID and COUNTING_PENALTY_ROLE_ID before enabling counting.')
        await db.counting_game_init(self.channel_id,config.GUILD_ID)
        await db.counting_penalty_recheck(config.GUILD_ID)
        self.maintenance.start()

    async def cog_unload(self):
        self.maintenance.cancel()
        task = self.maintenance.get_task()
        if task:
            await asyncio.gather(task,return_exceptions=True)

    async def interaction_check(self, interaction):
        if interaction.guild_id != config.GUILD_ID:
            await interaction.response.send_message('Use these commands in Cigar Lounge.',ephemeral=True)
            return False
        return True

    async def cog_app_command_error(self, interaction, error):
        interaction.extras['counting_error_handled'] = True
        original = getattr(error,'original',error)
        if isinstance(original,(ValueError,app_commands.CheckFailure)):
            text = str(original)
        elif isinstance(original,discord.Forbidden):
            text = 'Discord denied access. Check channel permissions and the penalty role hierarchy.'
        else:
            log.error('Counting command failed',exc_info=(type(original),original,original.__traceback__))
            text = 'Counting command failed. Check service logs and /count penalties before retrying.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(text[:1900],ephemeral=True,allowed_mentions=NO_PINGS)

    async def get_channel(self):
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not isinstance(channel,discord.TextChannel) or channel.guild.id != config.GUILD_ID:
            raise ValueError('Configure a counting text channel in Cigar Lounge.')
        return channel

    def get_role(self, guild, role_id):
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError(f'Penalty role {role_id} is missing or managed by Discord.')
        if not guild.me or not guild.me.guild_permissions.manage_roles or role >= guild.me.top_role:
            raise ValueError('Butler needs Manage Roles and a role above the penalty role.')
        if role.id == config.MOD_ROLE_ID or any(getattr(role.permissions,p) for p in _DANGEROUS):
            raise ValueError('The penalty role cannot grant staff privileges.')
        return role

    async def validate(self):
        channel = await self.get_channel()
        self.get_role(channel.guild,config.COUNTING_PENALTY_ROLE_ID)
        permissions = channel.permissions_for(channel.guild.me)
        required = ('view_channel','send_messages','read_message_history','add_reactions','embed_links')
        missing = [p for p in required if not getattr(permissions,p)]
        if missing:
            raise ValueError('Missing counting-channel permissions: '+', '.join(missing))
        if not self.bot.intents.message_content or not self.bot.intents.members:
            raise ValueError('Enable Message Content and Server Members intents in code and the Developer Portal.')
        return channel

    @commands.Cog.listener()
    async def on_disconnect(self):
        self.ready = False

    @commands.Cog.listener()
    async def on_ready(self):
        await self.recover()

    @commands.Cog.listener()
    async def on_resumed(self):
        await self.recover()

    async def recover(self):
        async with self.lock:
            self.ready = False
            channel = await self.validate()
            state = await db.counting_game_status(self.channel_id)
            if state['paused'] or not state['last_message']:
                return  # First activation and large outages require an explicit seed.
            last = await db.counting_game_latest(self.channel_id)
            if last:
                try:
                    message = await channel.fetch_message(last['message_id'])
                    if message.content != (last['expression'] or str(last['number'])):
                        await db.counting_game_disrupt(self.channel_id,[last['message_id']])
                except discord.NotFound:
                    await db.counting_game_disrupt(self.channel_id,[last['message_id']])
            missed = [m async for m in channel.history(limit=config.COUNTING_RECOVERY_LIMIT+1,
                      after=discord.Object(id=state['last_message']),oldest_first=True)]
            if len(missed)>config.COUNTING_RECOVERY_LIMIT:
                await db.counting_game_pause(self.channel_id,None,'Recovery limit exceeded; inspect and reseed.')
                await channel.send('Counting paused after a long outage. A moderator must inspect the count and use /count seed.',allowed_mentions=NO_PINGS)
                return
            changed = False
            for message in missed:
                if message.author.bot or message.webhook_id:
                    continue
                verdict = await db.counting_game_attempt(self.channel_id,message.id,message.author.id,
                    message.author.display_name,message.content,config.COUNTING_PENALTY_ROLE_ID,recovering=True)
                changed |= verdict is not None and verdict.kind != 'ignore'
            self.ready = True
            if changed:
                state = await db.counting_game_status(self.channel_id)
                await channel.send(f'Counting recovered. Next: **{state["current"]+1}**. '
                                   'Invalid downtime attempts were skipped without penalties.',allowed_mentions=NO_PINGS)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.guild.id != config.GUILD_ID or message.channel.id != self.channel_id:
            return
        if message.author.bot or message.webhook_id:
            return
        async with self.lock:
            if not self.ready:
                return
            try:
                verdict = await db.counting_game_attempt(self.channel_id,message.id,message.author.id,
                    message.author.display_name,message.content,config.COUNTING_PENALTY_ROLE_ID)
            except Exception:
                self.ready = False  # Recover from the durable cursor before handling newer messages.
                log.exception('Counting state update failed; enforcement suspended pending recovery')
                return
            if verdict is None or verdict.kind == 'ignore':
                return
            try:
                if verdict.kind == 'accepted':
                    await message.add_reaction('✅')
                elif verdict.kind == 'failed':
                    await message.add_reaction('❌')
                    await message.reply(f'{verdict.reason}. Count reset; next: **1**. '
                                        'The three-day penalty role is queued.',mention_author=False,allowed_mentions=NO_PINGS)
                else:
                    await message.reply(f'⚠️ {verdict.reason} Next: **{verdict.next_number}**.',mention_author=False,allowed_mentions=NO_PINGS)
            except discord.HTTPException:
                log.exception('Count saved, but Discord feedback failed')

    async def disrupted(self, channel_id, message_ids):
        if channel_id != self.channel_id:
            return
        async with self.lock:
            number = await db.counting_game_disrupt(self.channel_id,message_ids)
            if number is not None:
                channel = await self.get_channel()
                await channel.send(f'⚠️ A counted message was deleted or edited. The saved count stays **{number-1}**; '
                                   f'next is **{number}**. The next mistaken attempt gets a warning instead of a reset.',allowed_mentions=NO_PINGS)

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        await self.disrupted(payload.channel_id,[payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        await self.disrupted(payload.channel_id,payload.message_ids)

    @commands.Cog.listener()
    async def on_raw_message_edit(self,payload):
        if payload.channel_id == self.channel_id and 'content' in payload.data:
            previous = await db.counting_game_message(self.channel_id,payload.message_id)
            if previous is not None and payload.data['content'] != str(previous):
                await self.disrupted(payload.channel_id,[payload.message_id])

    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.guild.id == config.GUILD_ID:
            await db.counting_penalty_recheck(config.GUILD_ID,member.id)

    async def apply_penalty(self,penalty,expired):
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            raise ValueError('Cigar Lounge is unavailable.')
        role = self.get_role(guild,penalty['role_id'])
        try:
            member = await guild.fetch_member(int(penalty['discord_id']))
        except discord.NotFound:
            return 'done' if expired else 'pending'
        if expired:
            if role in member.roles:
                await member.remove_roles(role,reason='Counting penalty expired',atomic=True)
            return 'done'
        if role not in member.roles:
            await member.add_roles(role,reason='Counting mistake: three-day penalty',atomic=True)
        return 'active'

    @tasks.loop(seconds=30)
    async def maintenance(self):
        # Isolate recovery errors so an invalid channel cannot stop role expirations.
        try:
            if not self.ready:
                await self.recover()
        except Exception:
            log.exception('Counting recovery failed; will retry')
        try:
            await db.counting_penalty_sweep(config.GUILD_ID,self.apply_penalty)
        except Exception:
            log.exception('Counting role worker failed; will retry')

    @maintenance.before_loop
    async def before_maintenance(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='check',description='Check counting channel and penalty-role permissions (mod only).')
    @mod_only()
    async def check(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel=await self.validate()
        if config.COUNTING_BEAN_ROLE_ID:
            self.get_role(channel.guild,config.COUNTING_BEAN_ROLE_ID)
        await interaction.followup.send('Counting channel: OK\nManage Roles: OK\nPenalty and configured Bean Counter roles: OK',ephemeral=True)

    @app_commands.command(name='status',description='Show the current count, next number and recovery status.')
    async def status(self,interaction:discord.Interaction):
        await interaction.response.defer()
        _,server=await db.counting_user_stats(self.channel_id,interaction.user.id)
        await interaction.followup.send(embed=server_card(interaction.guild,server,self.ready),allowed_mentions=NO_PINGS)

    async def bean_change(self,member,desired):
        if member.bot or not config.COUNTING_BEAN_ROLE_ID or desired is None:
            return None
        role=self.get_role(member.guild,config.COUNTING_BEAN_ROLE_ID)
        current=await member.guild.fetch_member(member.id)
        if desired and role not in current.roles:
            await current.add_roles(role,reason='Bean Counter: 50 attempts and 98.5% accuracy',atomic=True)
            return 'earned'
        if not desired and role in current.roles:
            await current.remove_roles(role,reason='Bean Counter: accuracy below 98.5% or moderator reset',atomic=True)
            return 'lost'
        return None

    @app_commands.command(name='user',description='Show local counting stats, rank, Bean Counter and the server count.')
    async def user(self,interaction:discord.Interaction,member:discord.Member=None):
        await interaction.response.defer()
        selected=member or interaction.user
        change=None
        error=None
        async with self.lock:
            try:
                change=await db.counting_member_action(self.channel_id,selected.id,interaction.user.id,
                    lambda desired:self.bean_change(selected,desired))
            except (discord.HTTPException,ValueError,TimeoutError):
                log.exception('Bean Counter update failed')
                error='Bean Counter could not be updated. Check Manage Roles and the role hierarchy, then retry.'
            player,server=await db.counting_user_stats(self.channel_id,selected.id)
            card=user_card(selected,interaction.guild,player,server,self.ready)
            role=interaction.guild.get_role(config.COUNTING_BEAN_ROLE_ID)
            if role and (change=='earned' or change!='lost' and role in selected.roles):
                bean_counter_badge(card,role)
        announcement=None
        if change=='earned':
            announcement=f'<@{selected.id}> earned **Bean Counter**! At least 50 attempts and 98.5% accuracy. The beans are in capable hands.'
        elif change=='lost':
            announcement=f'<@{selected.id}>: **Bean Counter revoked.** Apparently the beans were doing the counting. Accuracy fell below 98.5%.'
        await interaction.followup.send(content=announcement,embed=card,allowed_mentions=NO_PINGS)
        if error:
            await interaction.followup.send(error,ephemeral=True)

    @app_commands.command(name='reset-user',description='Clear personal counting stats and Bean Counter, preserving the server count (mod only).')
    @mod_only()
    async def reset_user(self,interaction:discord.Interaction,member:discord.Member,reason:app_commands.Range[str,1,200]):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            await db.counting_member_action(self.channel_id,member.id,interaction.user.id,
                lambda desired:self.bean_change(member,desired),reset=True,reason=reason)
        await interaction.followup.send('Personal counting stats reset and Bean Counter removed if held. '
            'Server count, record, turn order and active Idiot penalty expiry are unchanged.',ephemeral=True)

    @app_commands.command(name='seed',description='Set the last valid number; zero starts at one (mod only).')
    @mod_only()
    async def seed(self,interaction:discord.Interaction,current:app_commands.Range[int,0,MAX_COUNT-1],last_counter:discord.Member=None):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            channel = await self.validate()
            latest = [m async for m in channel.history(limit=1)]
            cursor = latest[0].id if latest else discord.utils.time_snowflake(discord.utils.utcnow())
            await db.counting_game_seed(self.channel_id,interaction.user.id,current,last_counter.id if last_counter else None,cursor)
            self.ready = True
        await channel.send(f'Counting is active. Next: **{current+1}**. Alternate players; mistakes reset to 1 and earn the penalty role for three days.',allowed_mentions=NO_PINGS)
        await interaction.followup.send('Count saved. Keep the other counting bot disabled in this channel.',ephemeral=True)

    @app_commands.command(name='pause',description='Pause counting enforcement; penalty timers still expire (mod only).')
    @mod_only()
    async def pause(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            await db.counting_game_pause(self.channel_id,interaction.user.id,'Paused by moderator')
            self.ready = False
        await interaction.followup.send('Counting paused. Existing penalty timers remain active.',ephemeral=True)

    @app_commands.command(name='forgive',description='End a counting penalty early for a correction or test cleanup (mod only).')
    @mod_only()
    async def forgive(self,interaction:discord.Interaction,member:discord.Member):
        await interaction.response.defer(ephemeral=True)
        await db.counting_penalty_forgive(config.GUILD_ID,member.id,interaction.user.id,self.channel_id)
        await interaction.followup.send('Early removal queued. Check /count penalties after the next worker cycle.',ephemeral=True)

    @app_commands.command(name='penalties',description='Show pending penalty deadlines and role-operation errors (mod only).')
    @mod_only()
    async def penalties(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await db.counting_penalties_list(config.GUILD_ID)
        lines = []
        for row in rows:
            ts = int(row['expires_at'].replace(tzinfo=timezone.utc).timestamp())
            lines.append(f'<@{row["discord_id"]}>: <t:{ts}:R> ({row["state"]})'
                         +(f' | {row["error"][:100]}' if row['error'] else ''))
        await interaction.followup.send(('\n'.join(lines) or 'No active penalties.')[:1900],ephemeral=True,allowed_mentions=NO_PINGS)

    @app_commands.command(name='board',description='Top ten counters by correct counts minus mistakes.')
    async def board(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await db.counting_game_top(self.channel_id)
        await interaction.followup.send('\n'.join(f'#{row["place"]}. <@{row["discord_id"]}>: {row["score"]} points'
            for i,row in enumerate(rows,1)) or 'No accepted numbers here yet.',ephemeral=True,allowed_mentions=NO_PINGS)

    @app_commands.command(name='reset-server',description='Zero the server record and total correct counts (mod only).')
    @mod_only()
    async def reset_server(self,interaction:discord.Interaction,confirm:bool=False):
        await interaction.response.defer(ephemeral=True)
        status=await db.counting_game_status(self.channel_id)
        if not confirm:
            await interaction.followup.send(
                f"This will zero the server **record** ({status.get('record',0)}) and **total correct counts** "
                f"({status.get('total_counts',0)}). The current count, turn order and per-player stats are kept. "
                "Re-run with `confirm:True` to apply.",ephemeral=True)
            return
        async with self.lock:
            await db.counting_game_reset_totals(self.channel_id,interaction.user.id)
        await interaction.followup.send('Server record and total correct counts reset to zero.',ephemeral=True)


async def setup(bot):
    await bot.add_cog(CountingCog(bot))

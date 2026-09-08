import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from discord.ext import commands
import pytest
import config
import utils.db as db
from cogs.counting import CountingCog,mod_only

def run(coro):
    return asyncio.run(coro)

def test_count_group_loads_without_changing_other_commands(monkeypatch):
    async def check():
        monkeypatch.setattr(config,'COUNTING_GAME_CHANNEL_ID',123)
        monkeypatch.setattr(config,'COUNTING_PENALTY_ROLE_ID',456)
        monkeypatch.setattr(db,'counting_game_init',AsyncMock())
        monkeypatch.setattr(db,'counting_penalty_recheck',AsyncMock())
        bot = commands.Bot(command_prefix='!',intents=discord.Intents.none())
        async with bot:
            await bot.load_extension('cogs.counting')
            groups = bot.tree.get_commands()
            assert [g.name for g in groups]==['count']
            payload = groups[0].to_dict(bot.tree)
            assert {c['name'] for c in payload['options']} == {'check','status','seed','pause','forgive','penalties','board','user','reset-user'}
            other_guild = SimpleNamespace(guild_id=0,response=SimpleNamespace(send_message=AsyncMock()))
            # discord.py invokes the cog/binding check through each command,
            # not through the generated Group's default interaction_check.
            assert not await groups[0].get_command('status')._check_can_run(other_guild)
            other_guild.response.send_message.assert_awaited_once()
    # check,status,seed,pause,forgive,penalties,board: seven commands.
    run(check())

def test_moderator_policy_and_guild_gate(monkeypatch):
    from utils.helpers import is_mod
    import utils.helpers as helpers
    policy = MagicMock(return_value=True)
    monkeypatch.setattr(helpers,'is_mod',policy)
    async def check():
        async def dummy(interaction):
            pass
        fn = mod_only()(dummy)
        predicate = fn.__discord_app_commands_checks__[0]
        interaction=SimpleNamespace(guild_id=config.GUILD_ID,user=object())
        assert await predicate(interaction)
        policy.return_value=False
        with pytest.raises(discord.app_commands.CheckFailure):
            await predicate(interaction)
        policy.return_value=True
        interaction.guild_id=0
        with pytest.raises(discord.app_commands.CheckFailure):
            await predicate(interaction)
    run(check())

def test_penalty_apply_and_remove_and_privileged_role_rejection():
    async def check():
        role=MagicMock(spec=discord.Role)
        role.id=555
        role.managed=False
        role.is_default.return_value=False
        role.__ge__.return_value=False
        role.permissions=discord.Permissions.none()
        member=SimpleNamespace(roles=[],add_roles=AsyncMock(),remove_roles=AsyncMock())
        guild=SimpleNamespace(get_role=lambda _:role,fetch_member=AsyncMock(return_value=member),
            me=SimpleNamespace(top_role=object(),guild_permissions=discord.Permissions(manage_roles=True)))
        cog=CountingCog(SimpleNamespace(get_guild=lambda _:guild))
        penalty={'role_id':555,'discord_id':'42'}
        assert await cog.apply_penalty(penalty,False)=='active'
        member.add_roles.assert_awaited_once()
        member.roles=[role]
        assert await cog.apply_penalty(penalty,True)=='done'
        member.remove_roles.assert_awaited_once()
        role.permissions=discord.Permissions(administrator=True)
        with pytest.raises(ValueError):
            await cog.apply_penalty(penalty,False)
    run(check())


def test_bean_role_changes_once_and_updates_card(monkeypatch):
    async def check():
        monkeypatch.setattr(config,'COUNTING_BEAN_ROLE_ID',555)
        role=MagicMock(spec=discord.Role)
        role.id=555
        role.managed=False
        role.is_default.return_value=False
        role.__ge__.return_value=False
        role.permissions=discord.Permissions.none()
        role.unicode_emoji='🫘'
        role.icon=None
        member=SimpleNamespace(id=42,bot=False,roles=[],add_roles=AsyncMock(),remove_roles=AsyncMock())
        guild=SimpleNamespace(get_role=lambda _:role,fetch_member=AsyncMock(return_value=member),
            me=SimpleNamespace(top_role=object(),guild_permissions=discord.Permissions(manage_roles=True)))
        member.guild=guild
        cog=CountingCog(SimpleNamespace())
        assert await cog.bean_change(member,None) is None
        assert await cog.bean_change(member,True)=='earned'
        member.roles=[role]
        assert await cog.bean_change(member,True) is None
        assert await cog.bean_change(member,False)=='lost'
        member.roles=[]
        assert await cog.bean_change(member,False) is None
        member.add_roles.assert_awaited_once()
        member.remove_roles.assert_awaited_once()
        from utils.counting_card import bean_counter_badge
        card=bean_counter_badge(discord.Embed(),role)
        assert card.description=='🫘 **Bean Counter**'
    run(check())

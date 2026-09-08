"""Cigar Lounge counting cards. No global rankings or save mechanics."""
import discord

COLOR = 0xB89957

def bean_counter_badge(embed,role):
    """Show the actual role emoji, or its uploaded icon as a thumbnail."""
    emoji = role.unicode_emoji
    embed.description = f'{emoji + " " if emoji else ""}**Bean Counter**'
    if role.icon:
        embed.set_thumbnail(url=role.icon.url)
    return embed

def ago(message_id):
    return f'<t:{int(discord.utils.snowflake_time(int(message_id)).timestamp())}:R>' if message_id else 'Not recorded'

def server_lines(server,active):
    last = f'<@{server["last_user"]}>' if server['last_user'] else 'Nobody yet'
    record = f'**{server["high_score"]:,}**'
    if server.get('record_message_id'):
        record += f' · {ago(server["record_message_id"])}'
    return (f'Current number: **{server["current"]:,}**\n'
            f'Next number: **{server["current"]+1:,}**\n'
            f'Server record: {record}\n'
            f'Total correct counts: **{server["total_counts"]:,}**\n'
            f'Last counted by: {last}\n'
            f'Counting: **{"Active" if active and not server["paused"] else "Paused / reconnecting"}**\n'
            'Math: **Enabled**')

def user_card(member,guild,player,server,active):
    correct,mistakes=player['successes'],player['mistakes']
    attempts=correct+mistakes
    rate=f'{100*correct/attempts:.3f}%' if attempts else 'No attempts yet'
    rank=f'#{player["place"]} of {server["players"]}' if player['place'] else 'Unranked'
    best=f'**{player["highest_valid"]:,}**' if player['highest_message_id'] else 'Not recorded'
    if player['highest_message_id']:
        best += f' · {ago(player["highest_message_id"])}'
    embed=discord.Embed(color=COLOR)
    embed.set_author(name=member.display_name,icon_url=member.display_avatar.url)
    embed.add_field(name='Counting stats',value=(
        f'Correct rate: **{rate}**\n'
        f'✅ Correct counts: **{correct:,}**\n'
        f'❌ Mistakes: **{mistakes:,}**\n'
        f'Score: **{player["score"]:,}**\n'
        f'Cigar Lounge rank: **{rank}**\n'
        f'Idiot penalties: **{player["idiot_penalties"]:,}**\n'
        f'Highest valid count: {best}\n'
        f'Last active: {ago(player["last_active_id"])}'),inline=True)
    embed.add_field(name=guild.name,value=server_lines(server,active),inline=True)
    embed.set_footer(text='Score = correct counts minus mistakes. Warnings excluded. Idiot penalties include renewals recorded by this bot.')
    return embed

def server_card(guild,server,active):
    embed=discord.Embed(title=f'{guild.name} · Counting',description=server_lines(server,active),color=COLOR)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text='Math is always enabled. Use /count user for your counting rank and stats.')
    return embed

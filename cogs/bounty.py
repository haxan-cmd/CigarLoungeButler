"""
cogs/bounty.py — Bounty system: helpers, progress boards, and bounty slash commands.
"""
import json
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import config
from utils.parsing import is_vip
import utils.db as _db
import utils.challenges as _ch

MOD_ROLE_ID             = config.MOD_ROLE_ID
BOUNTY_FORUM_CHANNEL_ID = config.BOUNTY_FORUM_CHANNEL_ID
DECORATION_TOP          = config.DECORATION_TOP
DECORATION_BOTTOM       = config.DECORATION_BOTTOM
BULLETIN_BOARD_CATEGORY_ID = config.BULLETIN_BOARD_CATEGORY_ID
LEDGER_CATEGORY_ID         = config.LEDGER_CATEGORY_ID


async def get_active_bounty():
    """Return the active bounty as a dict, or None."""
    rows = await _db.get_all_bounties()
    for row in rows:
        if len(row) >= 9 and row[8] == 'TRUE':
            return {
                'id': int(row[15]),
                'title': row[0],
                'channel_id': int(row[1]) if row[1] else None,
                'message_id': int(row[2]) if row[2] else None,
                'theme_emoji': row[3],
                'weapons': json.loads(row[4]) if row[4] else {},
                'special_challenge': row[5],
                'special_done': row[6] == '1',
                'completions': json.loads(row[7]) if row[7] else [],
                'role_id': int(row[9]) if len(row) > 9 and row[9] else None,
                'forum_channel_id': int(row[10]) if len(row) > 10 and row[10] else None,
                'completions_msg_id': int(row[11]) if len(row) > 11 and row[11] else None,
                'bonus_msg_id': int(row[12]) if len(row) > 12 and row[12] else None,
                'progress_msg_id': int(row[13]) if len(row) > 13 and row[13] else None,
                'bonus_completions': json.loads(row[16]) if len(row) > 16 and row[16] else [],
                'start_date': row[14] if len(row) > 14 and row[14] else None,
            }
    return None


async def ensure_bounty_boards(guild, bounty):
    """Post any of the three channel boards that are missing, and record their ids.

    bounty_create leaves all three unset, and the on_message hook that used to
    create them only fires when a human happens to post an image in the bounty
    channel. Relying on that meant a fresh bounty could sit with an empty channel.
    Returns the list of boards created.
    """
    channel = guild.get_channel(bounty.get('channel_id'))
    if not channel and bounty.get('channel_id'):
        try:
            channel = await guild.fetch_channel(bounty['channel_id'])
        except Exception:
            channel = None
    if not channel:
        return []

    async def _alive(mid):
        """A stored id is not proof the message still exists: mods delete these by
        hand. Confirm before skipping, or a deleted board can never come back."""
        if not mid:
            return False
        try:
            await channel.fetch_message(int(mid))
            return True
        except discord.NotFound:
            return False
        except Exception as _fe:
            # Transient API/permission failure. Assume the board is still there:
            # a false "missing" would post a duplicate and orphan the original.
            print(f"[BOUNTY] board liveness check failed for {mid}: {_fe}")
            return True

    _e = bounty.get('theme_emoji') or ''

    def _placeholder(heading, empty):
        return (f"```\n\u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e\n"
                f"  {_e} {heading} {_e}\n"
                f"\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\n"
                f"{empty}\n```")

    made = []
    if not await _alive(bounty.get('completions_msg_id')):
        m = await channel.send(_placeholder('COMPLETIONS', 'No completions yet.'))
        await _db.update_bounty_field(bounty['id'], 'completions_msg_id', str(m.id))
        bounty['completions_msg_id'] = m.id
        made.append('completions')
    if not await _alive(bounty.get('bonus_msg_id')):
        try:
            _txt = _build_bonus_board_text(bounty)
        except Exception:
            _txt = _placeholder('BONUS COMPLETIONS', 'No bonus completions yet.')
        m = await channel.send(_txt)
        await _db.update_bounty_field(bounty['id'], 'bonus_msg_id', str(m.id))
        bounty['bonus_msg_id'] = m.id
        made.append('bonus')
    if not await _alive(bounty.get('progress_msg_id')):
        try:
            _txt = await build_progress_board(bounty, top_n=10)
        except Exception:
            _txt = _placeholder('TOP HUNTERS', 'No submissions yet.')
        m = await channel.send(_txt)
        await _db.update_bounty_field(bounty['id'], 'progress_msg_id', str(m.id))
        bounty['progress_msg_id'] = m.id
        made.append('progress')
    return made


def _is_mod(interaction):
    """True if the user may run mod bounty tooling: holds the mod role, OR is a guild
    administrator, OR is the configured manager. Role-only gates were locking the owner
    (admin but no mod role) out of their own commands like /bounty_credit."""
    u = interaction.user
    if any(r.id == MOD_ROLE_ID for r in getattr(u, 'roles', []) or []):
        return True
    _perms = getattr(u, 'guild_permissions', None)
    if _perms is not None and _perms.administrator:
        return True
    return u.id == getattr(config, 'MANAGER_ID', 0)


def _community_now():
    """Current time in the community display timezone (config.COMMUNITY_TZ). Used for
    user-facing dates like bounty completions so an evening finish isn't stamped with
    tomorrow's UTC date (an 8:30pm ET completion was landing on the next day). Falls
    back to UTC if the zone is unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(getattr(config, 'COMMUNITY_TZ', 'America/New_York')))
    except Exception:
        return datetime.now(timezone.utc)


def build_bounty_card(title, theme_emoji, weapons, special_challenge, special_done, completions):
    """
    Completions list only — used to be the full community card (weapon progress
    bars + special challenge box + completions), but the weapon/special-challenge
    breakdown was just maxed-out aggregate counts that weren't useful to an
    individual player checking their own status, and got cut entirely per
    feedback (2026-06-30). weapons/theme_emoji/special_challenge/special_done
    are accepted but unused now — kept so the one call site in /bounty_status
    doesn't need to change its signature if this gets reused later.

    completions: list of {"name": str, "date": str}
    """
    if not completions:
        return ""
    card = "🏆 **Completions**"
    for idx, c in enumerate(completions, 1):
        card += f"\n{idx}. {c['name']} — {c['date']}"
    return card


async def save_bounty_state(bounty_id, weapons, special_done, completions, message_id=None):
    await _db.update_bounty_field(bounty_id, 'weapons', json.dumps(weapons))
    await _db.update_bounty_field(bounty_id, 'special_done', bool(special_done))
    await _db.update_bounty_field(bounty_id, 'completions', json.dumps(completions))
    if message_id:
        await _db.update_bounty_field(bounty_id, 'message_id', str(message_id))


async def check_bounty_completion(guild, bounty, player_name, player_id):
    """Check if player just completed the full bounty. Returns True if newly completed."""
    player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
    if not player_row:
        return False
    player_progress = player_row['progress']
    weapons = bounty['weapons']
    for weapon, data in weapons.items():
        target = data['total']
        raw = player_progress.get(weapon, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        if cur < target:
            return False
    completions = bounty['completions']
    already = any(str(c.get('id')) == str(player_id) for c in completions)
    if already:
        return False
    return True


async def build_progress_board(bounty, top_n=10):
    """Build a top-N hunters board from BountyPlayers, excluding completed players."""
    completed_ids = {str(c['id']) for c in bounty['completions']}
    rows = await _db.get_all_bounty_players()

    total_target = sum(
        v.get('total', 0) if isinstance(v, dict) else 0
        for v in bounty['weapons'].values()
    )

    entries = []
    for row in rows:
        if len(row) < 5 or row[0] != bounty['title']:
            continue
        discord_id = row[1]
        if discord_id in completed_ids:
            continue
        player_name = row[2]
        progress = json.loads(row[4]) if row[4] else {}
        weapons = bounty.get('weapons', {})
        total_submissions = sum(
            min(
                (v['current'] if isinstance(v, dict) else int(v)),
                weapons.get(k, {}).get('total', 9999) if isinstance(weapons.get(k), dict) else 9999
            )
            for k, v in progress.items() if k != '__special__'
        )
        if total_submissions > 0:
            entries.append((player_name, total_submissions))
    entries.sort(key=lambda x: x[1], reverse=True)
    top = entries[:top_n]

    emoji = bounty['theme_emoji']
    lines = [f"```"]
    lines.append(f"╭────────────────────────────────╮")
    lines.append(f"  {emoji} LIVE SCOREBOARD {emoji}")
    lines.append(f"╰────────────────────────────────╯")
    if top:
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, count) in enumerate(top):
            if i < 3:
                medal = medals[i]
            else:
                medal = f"{i+1}. "
            suffix = f"/ {total_target}" if total_target else ""
            lines.append(f"{medal} {name:<20} {count} {suffix}")
    else:
        lines.append("  No active hunters yet.")
    lines.append("```")

    # Always append a blank card under the standings, so the per-weapon targets
    # and the bonus instructions stay visible no matter who is on the board.
    return "\n".join(lines) + "\n" + build_player_bounty_card(bounty, {})


async def update_progress_board(bounty, bounty_channel):
    """Edit the TOP HUNTERS message in the bounty channel."""
    if not bounty.get('progress_msg_id'):
        print(f"[PROGRESS_BOARD] Skipped — no progress_msg_id in bounty row")
        return
    if not bounty_channel:
        print(f"[PROGRESS_BOARD] bounty_channel was None — skipped")
        return
    try:
        content = await build_progress_board(bounty)
        msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
        await msg.edit(content=content)
        print(f"[PROGRESS_BOARD] Updated successfully")
    except Exception as e:
        print(f"[PROGRESS_BOARD] Update error: {e}")


async def refresh_bounty_boards(guild, bounty):
    """Re-render the bounty channel's completions, bonus, and progress boards from
    the CURRENT bounty state. Used after a manual data edit (e.g. correcting a
    completion date via SQL) so the boards reflect it immediately instead of waiting
    for the next completion event. Best-effort per board; returns the list refreshed."""
    ch = guild.get_channel(bounty['channel_id'])
    if not ch and bounty.get('channel_id'):
        try:
            ch = await guild.fetch_channel(bounty['channel_id'])
        except Exception:
            ch = None
    if not ch:
        return []
    done = []
    if bounty.get('completions_msg_id'):
        try:
            _comps = bounty['completions']
            _em = bounty['theme_emoji']
            if _comps:
                _lines = ["```", "╭──────────────────────────────╮",
                          f"  {_em} COMPLETIONS {_em}",
                          "╰──────────────────────────────╯"]
                for _idx, _c in enumerate(_comps, 1):
                    _lines.append(f"{_idx}. {_c['name']}  {_c['date']}")
                _lines.append("```")
                _comp_text = "\n".join(_lines)
            else:
                _comp_text = ("```\n╭──────────────────────────────╮\n"
                              f"  {_em} COMPLETIONS {_em}\n"
                              "╰──────────────────────────────╯\n"
                              "No completions yet.\n```")
            _cm = await ch.fetch_message(bounty['completions_msg_id'])
            await _cm.edit(content=_comp_text)
            done.append("completions")
        except Exception as _ce:
            print(f"[REFRESH] completions board: {_ce}")
    if bounty.get('bonus_msg_id'):
        try:
            _bm = await ch.fetch_message(bounty['bonus_msg_id'])
            await _bm.edit(content=_build_bonus_board_text(bounty))
            done.append("bonus")
        except Exception as _be:
            print(f"[REFRESH] bonus board: {_be}")
    try:
        await update_progress_board(bounty, ch)
        done.append("progress")
    except Exception as _pe:
        print(f"[REFRESH] progress board: {_pe}")
    return done


async def get_player_bounty_progress(bounty_title, discord_id):
    """Get a player's bounty progress from DB, or None."""
    rows = await _db.get_all_bounty_players()
    discord_id_str = str(discord_id)
    for row in rows:
        if len(row) >= 2 and row[0] == bounty_title and row[1] == discord_id_str:
            return {
                'player_name': row[2] if len(row) > 2 else '',
                'forum_post_id': int(row[3]) if len(row) > 3 and row[3] else None,
                'progress': json.loads(row[4]) if len(row) > 4 and row[4] else {}
            }
    return None


async def save_player_bounty_progress(bounty_title, discord_id, player_name, forum_post_id, progress):
    await _db.upsert_bounty_player(
        bounty_title, str(discord_id), player_name,
        str(forum_post_id) if forum_post_id else '',
        json.dumps(progress)
    )


async def _bounty_title_ac(interaction: discord.Interaction, current: str):
    try:
        rows = await _db.get_all_bounties()
        titles = [r[0].strip() for r in rows if r and r[0] and r[0].strip()]
    except Exception:
        titles = []
    cur = current.lower()
    seen, out = set(), []
    for t in reversed(titles):  # newest first
        if t.lower() in seen or cur not in t.lower():
            continue
        seen.add(t.lower())
        out.append(app_commands.Choice(name=t, value=t))
    return out[:25]


def build_player_bounty_card(bounty, player_progress):
    """Build a personal bounty card. Uses plain text so Discord strikethrough renders."""
    weapons = bounty['weapons']
    lines = []
    lines.append(f"```")
    lines.append(f"  {bounty['theme_emoji']} {bounty['title']}")
    lines.append(f"```")

    for weapon, data in weapons.items():
        tot = data['total']
        raw = player_progress.get(weapon, 0)
        cur = min(raw['current'] if isinstance(raw, dict) else int(raw), tot)
        progress = f"{cur}/{tot}"
        if cur >= tot:
            lines.append(f"~~`▸ {weapon:<22} {progress:>4}`~~")
        else:
            lines.append(f"`▸ {weapon:<22} {progress:>4}`")

    _spec = _parse_special(bounty)
    _need = _spec['need'] if _spec else 1
    sc_cur = min(player_progress.get('__special__', 0), _need)
    sc_progress = f"{sc_cur}/{_need}"
    lines.append(f"```")
    lines.append(f"  {bounty['theme_emoji']} SPECIAL CHALLENGE")
    lines.append(f"```")
    _sc_label = _describe_special(_spec) or bounty['special_challenge']
    if sc_cur >= _need:
        lines.append(f"~~`▸ {_sc_label:<22} {sc_progress:>4}`~~")
    else:
        lines.append(f"`▸ {_sc_label:<22} {sc_progress:>4}`")

    return "\n".join(lines)


# Pure parsing lives in utils/challenges.py so it can be unit tested without
# pulling in discord/db. These aliases keep the existing call sites unchanged.
_parse_ts = _ch.parse_ts
_parse_special = _ch.parse_special
_special_weapon_ok = _ch.special_weapon_ok
_describe_special = _ch.describe


async def _bounty_window_start(bounty):
    """The moment the current bounty/season opened, as a naive UTC datetime.

    bounties.start_date is a DATE, so it floors to midnight and would count runs
    submitted earlier that day, before the bounty existed. The season row opens at
    the same moment via start_season() and is a TIMESTAMPTZ, so it gives the real
    cutoff. Fall back to the date only if there is no season.
    """
    start = None
    try:
        _season = await _db.get_current_season()
        _sa = _season.get('started_at') if _season else None
        if _sa is not None:
            start = _sa.replace(tzinfo=None) if getattr(_sa, 'tzinfo', None) else _sa
    except Exception as _we:
        print(f"[BOUNTY] season window lookup failed: {_we}")
    if start is None:
        start = _parse_ts(bounty.get('start_date'))
    return start


async def count_player_weapon_runs(bounty, player_id):
    """{matched_weapon_key: qualifying_run_count} for a player's history.

    A run counts toward regular bounty weapon progress when it is on a bounty
    weapon, 100+ TD, and not a Resubmit. VIP DOES count here (weapon progress
    includes VIP, unlike the boards' records and unlike the lethality bonus);
    Unlisted also still counts for the bounty. This is the idempotent truth the
    edit path reconciles against, so a misread or lagged run can be topped up
    without the risk of double-counting an incrementing counter.
    """
    out = {}
    try:
        subs = await _db.get_submissions_by_player(str(player_id))
    except Exception:
        return out
    start = await _bounty_window_start(bounty)
    keys = {str(k).strip().lower(): k for k in (bounty.get('weapons') or {})}
    for r in subs:
        if len(r) < 12:
            continue
        feats = (r[11] or '')
        if 'resubmit' in feats.lower():
            continue
        if start is not None:
            ts = _parse_ts(r[0])
            if ts is None or ts < start:
                continue
        mk = keys.get((r[3] or '').strip().lower())
        if not mk:
            continue
        try:
            td = int(r[7]) if r[7] else 0
        except (ValueError, TypeError):
            continue
        if td < 100:
            continue
        out[mk] = out.get(mk, 0) + 1
    return out


async def _count_special_runs(bounty, player_id):
    """Count the player's runs INSIDE the bounty window that satisfy the challenge.

    Reads submission rows straight from the DB, so deaths (index 9) are available
    here without threading them through the submission pipeline. Resubmits are
    excluded, matching how they are excluded from bounty progress elsewhere.
    """
    spec = _parse_special(bounty)
    if not spec:
        return 0
    try:
        subs = await _db.get_submissions_by_player(str(player_id))
    except Exception:
        return 0
    start = await _bounty_window_start(bounty)
    n = 0
    for r in subs:
        if len(r) < 10:
            continue
        # VIP runs never hit the weapon boards, so keep them out of the bonus too.
        if len(r) > 10 and is_vip(r[10]):
            continue
        feats = (r[11] or '') if len(r) > 11 else ''
        if start is not None:
            ts = _parse_ts(r[0])
            if ts is None or ts < start:
                continue
        if _ch.run_qualifies(bounty, spec, r[3] or '', r[7], r[9], feats, r[8]):
            n += 1
    return n


async def _special_satisfied(bounty, player_id):
    """True once the player has enough qualifying runs for the challenge."""
    spec = _parse_special(bounty)
    if not spec:
        return False
    return (await _count_special_runs(bounty, player_id)) >= spec['need']


async def _commit_bonus(guild, bounty, player_name, player_id):
    """Add the player to the bonus completion board (dedup) + ping + refresh the board.
    Caller guarantees the player has finished the bounty AND done the special run."""
    bonus = bounty.get('bonus_completions', [])
    if any(str(e.get('id') if isinstance(e, dict) else '') == str(player_id) for e in bonus):
        return False
    bonus.append({'id': str(player_id), 'name': player_name})
    bounty['bonus_completions'] = bonus
    bounty['special_done'] = True
    await _db.update_bounty_field(bounty['id'], 'bonus_completions', json.dumps(bonus))
    await _db.update_bounty_field(bounty['id'], 'special_done', True)
    print(f"[BOUNTY] Bonus awarded to {player_name}")
    bounty_channel = guild.get_channel(bounty['channel_id'])
    if not bounty_channel and bounty.get('channel_id'):
        try:
            bounty_channel = await guild.fetch_channel(bounty['channel_id'])
        except Exception:
            bounty_channel = None
    if bounty_channel:
        try:
            role = guild.get_role(bounty.get('role_id')) if bounty.get('role_id') else None
            mention = role.mention if role else ''
            await bounty_channel.send(
                f"{mention} \u2b50 **{player_name}** completed the bonus challenge: "
                f"**{bounty['special_challenge']}**!"
            )
        except Exception as e:
            print(f"[BOUNTY] Bonus ping error: {e}")
        if bounty.get('bonus_msg_id'):
            try:
                msg = await bounty_channel.fetch_message(bounty['bonus_msg_id'])
                await msg.edit(content=_build_bonus_board_text(bounty))
            except Exception as e:
                print(f"[BOUNTY] Bonus board update error: {e}")
    return True


async def _try_award_bonus(guild, bounty, weapon, takedowns, player_name, player_id):
    """Run-path: called on every submission. If THIS run is the special challenge and the
    player has already finished the main bounty, credit the bonus. If they haven't finished
    yet, do nothing now -- the completion path will credit this run once they do (either
    order). No-ops unless the run is the special challenge."""
    spec = _parse_special(bounty)
    if not spec:
        return
    # Challenges can require N qualifying runs, so a single submission is never
    # enough on its own: re-count the player's history instead of judging this run.
    if not any(str(c.get('id')) == str(player_id) for c in bounty.get('completions', [])):
        return
    _done = await _count_special_runs(bounty, player_id)
    if _done < spec['need']:
        return
    await _commit_bonus(guild, bounty, player_name, player_id)


async def reconcile_bounty_progress(guild, bounty, player_id, player_name=None):
    """Idempotently TOP UP one player's stored bounty progress to match ground truth
    (their own submissions), with NO side effects. Built for the startup reconcile so a
    submission whose background bounty-credit was killed by a mid-flight deploy is
    healed on the next boot — the run row is already in the DB (it is written before
    the blurb posts), only the derived credit was lost.

    Safety contract — this function must never make things worse:
      * TOP-UP ONLY. For each weapon it takes max(stored, recount) and never lowers a
        stored count. count_player_weapon_runs() returns {} on a transient DB error, so
        a failed read simply tops nothing up; a value already correct is left untouched.
      * The community participation counter (weapons[k]['current']) moves ONLY by the
        positive delta actually applied to the player, so it stays in step and can never
        be driven down.
      * NO completions, GP awards, role grants, pings, reactions, bonus commits, or
        community-board edits. It re-renders only THIS player's own forum card, in place,
        and only if that card already exists — it never creates a new thread.
      * Completed players are skipped entirely; their progress is final.
    Completion ceremony (GP + ping) is deliberately left to the player's next real
    submission or a mod: the reconcile fixes DATA, it does not spend GP or ping a channel.

    Returns True if it changed anything, else False.
    """
    if not bounty or not player_id:
        return False
    pid = str(player_id)
    if any(str(c.get('id')) == pid for c in bounty.get('completions', []) or []):
        return False

    try:
        recount = await count_player_weapon_runs(bounty, pid)
    except Exception as _ce:
        print(f"[RECONCILE] weapon recount failed for {pid}: {_ce}")
        return False

    row = await get_player_bounty_progress(bounty['title'], pid)
    progress = dict(row['progress']) if row and row.get('progress') else {}
    forum_post_id = row['forum_post_id'] if row else None
    name = player_name or (row.get('player_name') if row else '') or ''

    weapons = bounty.get('weapons') or {}
    changed = False

    for wk, truth in recount.items():
        if wk not in weapons:
            continue
        raw = progress.get(wk, 0)
        stored = raw['current'] if isinstance(raw, dict) else int(raw or 0)
        if truth > stored:                       # TOP-UP ONLY — never reduce
            delta = truth - stored
            progress[wk] = truth
            wd = weapons[wk]
            if isinstance(wd, dict):
                wd['current'] = max(0, int(wd.get('current', 0)) + delta)
                weapons[wk] = wd
            changed = True

    # Special-challenge display progress: top-up only, display-only (no bonus fired here).
    try:
        truth_special = await _count_special_runs(bounty, pid)
        stored_special = int(progress.get('__special__', 0) or 0)
        if truth_special > stored_special:
            progress['__special__'] = truth_special
            changed = True
    except Exception as _se:
        print(f"[RECONCILE] special recount failed for {pid}: {_se}")

    if not changed:
        return False

    await save_player_bounty_progress(bounty['title'], pid, name, forum_post_id, progress)
    await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])

    # Re-render only THIS player's forum card, in place, and only if it already exists.
    if forum_post_id:
        try:
            forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
            forum_channel = guild.get_channel(forum_channel_id) if guild else None
            if forum_channel and isinstance(forum_channel, discord.ForumChannel):
                thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                bot_msgs = [m async for m in thread.history(limit=5, oldest_first=True) if m.author.bot]
                if bot_msgs:
                    await bot_msgs[-1].edit(content=build_player_bounty_card(bounty, progress))
        except Exception as _fe:
            print(f"[RECONCILE] forum card re-render failed for {pid}: {_fe}")

    print(f"[RECONCILE] topped up bounty progress for {name or pid}")
    return True


async def correct_player_bounty_overcount(guild, player_id, player_name=None):
    """After an EDIT, lower any stored bounty weapon/special progress that now EXCEEDS the
    player's true qualifying-run count. The edit path's update_bounty top-up handles the
    UPWARD case (a weapon that gained a run); this is its mirror for the DOWNWARD case — a
    run edited OFF a bounty weapon (e.g. "Spear" corrected to "Poleaxe") leaves the old
    weapon over-counted (Spear stuck at 2/3 when only 1 real Spear run remains).

    An edit is authoritative: recounting from submissions gives the EXACT number of real
    qualifying runs, so setting a weapon DOWN to it never claws back other valid runs — it
    just removes the phantom hit the moved run left behind. Adjusts the community counter by
    the negative delta. Fires NO side effects (no completion reversal, GP, roles, pings); it
    re-renders only this player's own forum card in place. Never touches a COMPLETED player
    (their progress is frozen — an edit shouldn't un-complete a finished bounty).

    Fetches its own fresh bounty so it can't overwrite a counter the top-up just saved.
    Returns True if it lowered anything.
    """
    if not player_id:
        return False
    pid = str(player_id)
    bounty = await get_active_bounty()
    if not bounty:
        return False
    if any(str(c.get('id')) == pid for c in bounty.get('completions', []) or []):
        return False
    try:
        recount = await count_player_weapon_runs(bounty, pid)
    except Exception as _ce:
        print(f"[EDIT] bounty down-correct recount failed for {pid}: {_ce}")
        return False
    row = await get_player_bounty_progress(bounty['title'], pid)
    if not row or not row.get('progress'):
        return False
    progress = dict(row['progress'])
    forum_post_id = row.get('forum_post_id')
    name = player_name or row.get('player_name') or ''
    weapons = bounty.get('weapons') or {}
    changed = False

    for wk in list(progress.keys()):
        if wk == '__special__' or wk not in weapons:
            continue
        raw = progress.get(wk, 0)
        stored = raw['current'] if isinstance(raw, dict) else int(raw or 0)
        truth = recount.get(wk, 0)
        if truth < stored:                        # LOWER to the real count (edit is authoritative)
            delta = stored - truth
            progress[wk] = truth
            wd = weapons[wk]
            if isinstance(wd, dict):
                wd['current'] = max(0, int(wd.get('current', 0)) - delta)
                weapons[wk] = wd
            changed = True

    # Special challenge: correct downward too if a run left the qualifying set.
    try:
        truth_special = await _count_special_runs(bounty, pid)
        stored_special = int(progress.get('__special__', 0) or 0)
        if truth_special < stored_special:
            progress['__special__'] = truth_special
            changed = True
    except Exception as _se:
        print(f"[EDIT] bounty down-correct special recount failed for {pid}: {_se}")

    if not changed:
        return False

    await save_player_bounty_progress(bounty['title'], pid, name, forum_post_id, progress)
    await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])

    if forum_post_id:
        try:
            fcid = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
            fch = guild.get_channel(fcid) if guild else None
            if fch and isinstance(fch, discord.ForumChannel):
                th = fch.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                bmsgs = [m async for m in th.history(limit=5, oldest_first=True) if m.author.bot]
                if bmsgs:
                    await bmsgs[-1].edit(content=build_player_bounty_card(bounty, progress))
        except Exception as _fe:
            print(f"[EDIT] bounty down-correct card re-render failed for {pid}: {_fe}")

    print(f"[EDIT] corrected bounty over-count for {name or pid}")
    return True


async def update_bounty(guild, weapon, player_name, player_id, takedowns):
    """Called from finalise_submission. Updates bounty progress if weapon qualifies. Returns True if weapon matched.

    VIP runs DO count toward regular bounty weapon progress (a bounty is about
    participation, not board records). They are only excluded from the special
    challenge / bonus, gated in _count_special_runs.
    """
    bounty = await get_active_bounty()
    if not bounty:
        print(f"[BOUNTY] No active bounty found — skipping for {player_name} weapon={weapon}")
        return False

    if not weapon:
        return False

    # Bonus/special challenge (e.g. "Katar 100 Takedowns") is evaluated first: it can
    # carry its own TD threshold and applies whether or not the weapon is a main bounty
    # weapon. Strict order: _try_award_bonus only credits players who have ALREADY
    # completed the main bounty; a bonus run done beforehand is not retro-credited.
    await _try_award_bonus(guild, bounty, weapon, takedowns, player_name, player_id)

    # Main-bounty progress requires a 100-TD run.
    if takedowns < 100:
        return False

    weapons = bounty['weapons']

    matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
    if not matched_key:
        print(f"[BOUNTY] Weapon '{weapon}' not in bounty '{bounty['title']}' — keys: {list(weapons.keys())}")
        return False

    # Player already completed this bounty — don't re-credit their progress or fire the
    # bounty (cat) reaction again. They're done; extra challenge-weapon runs shouldn't track.
    if any(str(c.get('id')) == str(player_id) for c in bounty['completions']):
        return False

    # Increment global participation counter
    w = weapons[matched_key]
    w['current'] += 1
    weapons[matched_key] = w

    bounty_channel = guild.get_channel(bounty['channel_id'])
    if not bounty_channel and bounty['channel_id']:
        try:
            bounty_channel = await guild.fetch_channel(bounty['channel_id'])
        except Exception as e:
            print(f"[BOUNTY] Could not fetch bounty channel: {e}")
    bounty_role = guild.get_role(bounty['role_id']) if bounty['role_id'] else None
    member = guild.get_member(player_id)
    if member and bounty_role and bounty_role not in member.roles:
        try:
            await member.add_roles(bounty_role, reason="Bounty participant")
        except Exception as e:
            print(f"Bounty role assign error: {e}")

    # ── PLAYER PROGRESS ───────────────────────────────────────────────────────
    player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
    if player_row:
        player_progress = player_row['progress']
        forum_post_id = player_row['forum_post_id']
    else:
        player_progress = {}
        forum_post_id = None

    raw = player_progress.get(matched_key, 0)
    cur = raw['current'] if isinstance(raw, dict) else int(raw)
    player_progress[matched_key] = cur + 1

    # Recount the special challenge and store it, so the player's card can show
    # real progress (2/3) instead of sitting at 0/1 until a mod credits them.
    # Must happen before the card is rendered below.
    try:
        player_progress['__special__'] = await _count_special_runs(bounty, player_id)
    except Exception as _se:
        print(f"[BOUNTY] special recount failed for {player_name}: {_se}")

    forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
    forum_channel = guild.get_channel(forum_channel_id)
    if forum_channel and isinstance(forum_channel, discord.ForumChannel):
        if forum_post_id:
            try:
                forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                messages = []
                async for msg in forum_thread.history(limit=5, oldest_first=True):
                    messages.append(msg)
                bot_messages = [m for m in messages if m.author.bot]
                card_text = build_player_bounty_card(bounty, player_progress)
                if bot_messages:
                    await bot_messages[-1].edit(content=card_text)
                else:
                    await forum_thread.send(card_text)
            except Exception as e:
                print(f"Forum post update error: {e}")
                forum_post_id = None

        if not forum_post_id:
            try:
                new_thread, first_msg = await forum_channel.create_thread(
                    name=player_name,
                    content=bounty['theme_emoji']
                )
                card_text = build_player_bounty_card(bounty, player_progress)
                await new_thread.send(card_text)
                forum_post_id = new_thread.id
            except Exception as e:
                print(f"Forum post create error: {e}")

    # Save player progress (upsert handles both new and existing)
    await save_player_bounty_progress(bounty['title'], str(player_id), player_name, forum_post_id, player_progress)

    # ── COMPLETIONS & BONUS BOARDS ───────────────────────────────────────────
    completions = bounty['completions']
    newly_completed = await check_bounty_completion(guild, bounty, player_name, player_id)
    if newly_completed:
        date_str = _community_now().strftime('%b %d')
        completions.append({"id": str(player_id), "name": player_name, "date": date_str})
        # Season championship GP: completion is a RACE. First to finish gets the
        # full bonus, second 4, third 3, everyone after 2 — placement is this
        # player's position in the completions list (they were just appended).
        # Awarded HERE, the moment completion is recorded, because the caller's
        # later check_bounty_completion() returns False for this player now.
        # Idempotent per season/player/reason.
        placement = len(completions)
        race_points = {1: config.BOUNTY_COMPLETION_BONUS, 2: 4, 3: 3}.get(placement, 2)
        try:
            _bseason = await _db.get_current_season()
            if _bseason:
                await _db.award_season_bonus(_bseason['id'], player_name,
                                             race_points, "Bounty completion",
                                             discord_id=str(player_id))
        except Exception as _sbe:
            print(f"[SEASON] bounty bonus error: {_sbe}")
        if bounty_channel and bounty_role:
            _ord = {1: '1st', 2: '2nd', 3: '3rd'}.get(placement, f'{placement}th')
            try:
                await bounty_channel.send(
                    f"{bounty_role.mention} 🏆 **{player_name}** has completed the "
                    f"**{bounty['title']}**! ({_ord} to finish"
                    + (f" — +{race_points} GP)" if getattr(config, 'SEASON_GP_CHAMPION', True) else ")")
                )
            except Exception as e:
                print(f"Bounty completion ping error: {e}")

        # Either-order bonus: credit a special run they already did, now the bounty is done.
        if await _special_satisfied(bounty, player_id):
            await _commit_bonus(guild, bounty, player_name, player_id)

    # Save updated state
    await save_bounty_state(bounty['id'], weapons, bounty['special_done'], completions)

    # Update completions board
    if bounty_channel and bounty.get('completions_msg_id'):
        try:
            if completions:
                lines = [f"```"]
                lines.append(f"╭──────────────────────────────╮")
                lines.append(f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}")
                lines.append(f"╰──────────────────────────────╯")
                for idx, c in enumerate(completions, 1):
                    lines.append(f"{idx}. {c['name']}  {c['date']}")
                lines.append("```")
                comp_text = "\n".join(lines)
            else:
                comp_text = (
                    f"```\n╭──────────────────────────────╮\n"
                    f"  {bounty['theme_emoji']} COMPLETIONS {bounty['theme_emoji']}\n"
                    f"╰──────────────────────────────╯\n"
                    f"No completions yet.\n```"
                )
            comp_msg = await bounty_channel.fetch_message(bounty['completions_msg_id'])
            await comp_msg.edit(content=comp_text)
        except Exception as e:
            print(f"Completions board update error: {e}")

    # Update bonus completions board if special just got done
    if bounty['special_done'] and bounty_channel and bounty.get('bonus_msg_id'):
        try:
            bonus_text = _build_bonus_board_text(bounty)
            bonus_msg = await bounty_channel.fetch_message(bounty['bonus_msg_id'])
            await bonus_msg.edit(content=bonus_text)
        except Exception as e:
            print(f"Bonus board update error: {e}")

    await update_progress_board(bounty, bounty_channel)

    return True


def _build_bonus_board_text(bounty):
    """Build the BONUS COMPLETIONS board text from bounty['bonus_completions'] list."""
    completers = bounty.get('bonus_completions', [])
    lines = [
        "```",
        "╭──────────────────────────────╮",
        f"  {bounty['theme_emoji']} BONUS COMPLETIONS {bounty['theme_emoji']}",
        "╰──────────────────────────────╯",
    ]
    if completers:
        for idx, entry in enumerate(completers, 1):
            name = entry['name'] if isinstance(entry, dict) else entry
            lines.append(f"{idx}. {name}")
    else:
        lines.append("No bonus completions yet.")
    lines.append("```")
    return "\n".join(lines)


class BountyCog(commands.Cog):
    bounty_group = app_commands.Group(name="bounty", description="Active bounty status and hunters")

    def __init__(self, bot):
        self.bot = bot
        self._grace_sweep.start()

    def cog_unload(self):
        self._grace_sweep.cancel()

    @tasks.loop(minutes=30)
    async def _grace_sweep(self):
        """Delete the channel/role of any ended bounty whose 24h grace period has
        elapsed. Replaces an in-handler asyncio.sleep(24h) that a restart would lose,
        orphaning the channel forever. Persistent + idempotent: clears the pointers
        only after a clean pass, never touches the bounties row itself."""
        try:
            due = await _db.get_bounties_pending_deletion()
        except Exception as e:
            print(f"[BOUNTY SWEEP] query error: {e}")
            return
        if not due:
            return
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        for b in due:
            hard_error = False
            try:
                _cid = b.get('channel_id')
                if _cid:
                    ch = guild.get_channel(int(_cid))
                    if ch is None:
                        try:
                            ch = await guild.fetch_channel(int(_cid))
                        except discord.NotFound:
                            ch = None            # already gone -> treat as done
                        except Exception as _fe:
                            hard_error = True; print(f"[BOUNTY SWEEP] channel fetch error: {_fe}")
                    if ch:
                        await ch.delete(reason=f"Bounty ended: {b['title']}")
                _rid = b.get('role_id')
                if _rid:
                    role = guild.get_role(int(_rid))
                    if role:
                        await role.delete(reason=f"Bounty ended: {b['title']}")
            except discord.NotFound:
                pass                             # channel/role already gone -> done
            except Exception as e:
                hard_error = True
                print(f"[BOUNTY SWEEP] cleanup error for {b.get('title')}: {e}")
            if not hard_error:
                try:
                    await _db.clear_bounty_grace(b['id'])
                    print(f"[BOUNTY SWEEP] cleaned up channel/role for {b.get('title')}")
                except Exception as _ce:
                    print(f"[BOUNTY SWEEP] clear-grace error: {_ce}")

    @_grace_sweep.before_loop
    async def _before_grace_sweep(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="bounty_create", description="Create a new monthly bounty (mod only)")
    @app_commands.describe(
        title="Bounty title e.g. Meowy's Birthday Bounty",
        channel_name="Channel name e.g. meowys-birthday-bounty",
        theme_emoji="Emoji pair for special challenge header e.g. 🐾",
        weapon1="Weapon slot 1 — e.g. Messer or Messer:9 for custom total (default 3)",
        weapon2="Weapon slot 2 — e.g. Dane Axe or Dane Axe:6",
        weapon3="Weapon slot 3", weapon4="Weapon slot 4",
        weapon5="Weapon slot 5", weapon6="Weapon slot 6",
        weapon7="Weapon slot 7 (optional)",
        weapon8="Weapon slot 8 (optional)",
        special_challenge="Special challenge description e.g. 100 Takedowns on Cat Claws (Katars)",
        image="Bounty picture to post in the new bounty channel (optional)"
    )
    async def bounty_create(
        self, interaction: discord.Interaction,
        title: str,
        channel_name: str,
        theme_emoji: str,
        weapon1: str, weapon2: str, weapon3: str,
        weapon4: str, weapon5: str, weapon6: str,
        special_challenge: str,
        weapon7: str = None,
        weapon8: str = None,
        image: discord.Attachment = None,
    ):
        if not _is_mod(interaction):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.send_message("Working on it.", ephemeral=True)

        # Deactivate any existing active bounty
        existing_bounties = await _db.get_all_bounties()
        for row in existing_bounties:
            if len(row) >= 9 and row[8] == 'TRUE':
                bounty_id = int(row[15])
                await _db.update_bounty_field(bounty_id, 'active', False)

        def parse_weapon(raw):
            if raw is None:
                return None
            raw = raw.strip()
            if ':' in raw:
                parts = raw.rsplit(':', 1)
                name = parts[0].strip()
                try:
                    total = int(parts[1].strip())
                except ValueError:
                    total = 3
            else:
                name = raw
                total = 3
            return name, total

        raw_weapons = [weapon1, weapon2, weapon3, weapon4, weapon5, weapon6]
        if weapon7:
            raw_weapons.append(weapon7)
        if weapon8:
            raw_weapons.append(weapon8)

        weapons = {}
        for raw in raw_weapons:
            parsed = parse_weapon(raw)
            if parsed:
                name, total = parsed
                weapons[name] = {"current": 0, "total": total}

        guild = interaction.guild

        formatted_channel_name = f"{theme_emoji}┃{channel_name}"

        bulletin_board = guild.get_channel(BULLETIN_BOARD_CATEGORY_ID)
        channel = await guild.create_text_channel(formatted_channel_name, category=bulletin_board)
        if image is not None:
            try:
                await channel.send(file=await image.to_file())
            except Exception as _ie:
                print(f"Bounty image post error: {_ie}")

        ledger = guild.get_channel(LEDGER_CATEGORY_ID)
        forum_channel = None
        forum_error = None
        if not ledger:
            forum_error = f"Ledger category not found (ID: {LEDGER_CATEGORY_ID})"
        else:
            try:
                forum_channel = await guild.create_forum(formatted_channel_name, category=ledger)
            except Exception as e:
                forum_error = str(e)
                print(f"Forum channel create error: {e}")

        lavender = discord.Colour(0xB57EDC)
        bounty_role = await guild.create_role(
            name=title,
            colour=lavender,
            mentionable=True,
            reason=f"Bounty role for: {title}"
        )
        try:
            await bounty_role.edit(unicode_emoji=theme_emoji)
        except Exception:
            pass

        await _db.add_bounty(
            title=title,
            channel_id=str(channel.id),
            message_id='',
            theme_emoji=theme_emoji,
            weapons=json.dumps(weapons),
            special_challenge=special_challenge,
            active=True,
            role_id=str(bounty_role.id),
            forum_channel_id=str(forum_channel.id) if forum_channel else '',
            start_date=datetime.now(timezone.utc).date()
        )

        forum_mention = forum_channel.mention if forum_channel else f"*(forum creation failed: {forum_error})*"
        msg = (
            f"✅ Bounty **{title}** created!\n"
            f"📋 Bulletin Board: {channel.mention}\n"
            f"📖 Ledger: {forum_mention}\n"
            f"🎭 Role: {bounty_role.mention}"
        )

        # Echo how the special challenge actually PARSED. It is matched by regex
        # over free text, so a reworded challenge can silently never qualify —
        # far better to see that here than at the end of the month.
        _spec = _parse_special({'special_challenge': special_challenge})
        if _spec:
            _bits = []
            if _spec.get('min_lethality') is not None:
                _bits.append(f"{_spec['min_lethality']}%+ lethality")
            if _spec['min_td']:
                _bits.append(f"{_spec['min_td']}+ TD")
            if _spec['max_deaths'] is not None:
                _bits.append(f"under {_spec['max_deaths']} deaths")
            if not _bits:
                _bits.append(f"{_spec['min_td']}+ TD")
            _bits.append(f"x{_spec['need']}")
            _bits.append("any bounty weapon" if _spec['any_weapon'] else "weapon named in the text")
            msg += f"\n\n🧪 Special challenge parsed as: **{', '.join(_bits)}**"
            if not _spec['any_weapon']:
                _named = [w for w in weapons if w.lower() in _spec['text']]
                if _named:
                    msg += f"\nMatches: {', '.join(_named)}"
                else:
                    msg += ("\n⚠️ **No weapon matches this challenge.** Nothing will ever "
                            "qualify. Either name a weapon in the text or use the phrase "
                            "'any bounty weapon'.")
        try:
            _fresh = await get_active_bounty()
            if _fresh:
                _made = await ensure_bounty_boards(guild, _fresh)
                print(f"[BOUNTY] posted boards on create: {_made}")
        except Exception as _be:
            print(f"[BOUNTY] board post error: {_be}")
        try:
            _sid = await _db.start_season(title)
            from cogs.favourites import roll_featured
            await roll_featured(_sid)
        except Exception as _se:
            print(f"[SEASON] start error: {_se}")
        await interaction.edit_original_response(content=msg)

    @app_commands.command(name="bounty_end", description="End the active bounty with a 24hr grace period (mod only)")
    async def bounty_end(self, interaction: discord.Interaction):
        if not _is_mod(interaction):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"⏳ Grace period started for **{bounty['title']}**. Channel will be deleted in 24 hours.",
            ephemeral=False
        )

        # Mark inactive immediately
        await _db.update_bounty_field(bounty['id'], 'active', False)

        guild = interaction.guild

        # Close the season tied to this bounty: post the Hall of Fame entry, then end it.
        try:
            from cogs.favourites import finalize_season, _hof_index_refresh
            from cogs.leaderboards import snapshot_monthly_to_hof
            _season = await _db.get_current_season()
            if _season:
                await finalize_season(guild, _season)
                # Snapshot this month's Lethality/Warlord boards to the Hall of Fame
                # while the season is still active — the snapshot derives its window
                # from the current season, so it must run before end_current_season().
                try:
                    await snapshot_monthly_to_hof(guild)
                except Exception as _me:
                    print(f"[MONTHLY HOF] snapshot error: {_me}")
                await _db.end_current_season()
                # finalize_season refreshed the index while this season was still
                # open, so its line read "(in progress)". Re-render now that
                # ended_at is set.
                try:
                    await _hof_index_refresh(guild)
                except Exception as _ie:
                    print(f"[HOF] index re-refresh error: {_ie}")
        except Exception as _se:
            print(f"[SEASON] finalize error: {_se}")
        closed_date = _community_now().strftime('%Y-%m-%d')
        completed_ids = {str(c['id']) for c in bounty['completions']}

        # ── STAMP FORUM CARD THREADS AS CLOSED ───────────────────────────────
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        try:
            forum_channel = guild.get_channel(forum_channel_id)
            if not forum_channel:
                forum_channel = await guild.fetch_channel(forum_channel_id)
            if forum_channel:
                threads = list(forum_channel.threads)
                async for t in forum_channel.archived_threads(limit=None):
                    threads.append(t)
                for thread in threads:
                    try:
                        msgs = []
                        async for msg in thread.history(limit=1, oldest_first=True):
                            msgs.append(msg)
                        if msgs:
                            original = msgs[0].content or ''
                            if '🔒 CLOSED' not in original:
                                stamp = f"🔒 **CLOSED — {bounty['title']}**"
                                new_content = f"{stamp}\n\n{original}".strip()
                                await msgs[0].edit(content=new_content)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        print(f"Bounty card stamp error ({thread.name}): {e}")
            print(f"Bounty cards stamped CLOSED for {bounty['title']}")
        except Exception as e:
            print(f"Bounty card stamp error: {e}")

        # ── REFRESH FINISHERS' REGISTRY CARDS ────────────────────────────────
        # Card completions are derived live from bounty_players.progress, but a card
        # is only re-rendered when something calls create_or_update_registry_card.
        # Nothing did that on bounty end, so finishers kept a stale card (and a stale
        # title, which is keyed off the completion count) until their next run.
        try:
            from cogs.registry import create_or_update_registry_card
            _comp_names = {
                str(c['id']): (c.get('name') if isinstance(c, dict) else None)
                for c in bounty['completions']
            }
            for _cid, _cname in _comp_names.items():
                try:
                    _m = guild.get_member(int(_cid))
                    await create_or_update_registry_card(
                        guild, int(_cid), _cname or (_m.display_name if _m else str(_cid))
                    )
                    await asyncio.sleep(0.5)
                except Exception as _ce:
                    print(f"[BOUNTY END] card refresh failed for {_cid}: {_ce}")
            print(f"[BOUNTY END] refreshed {len(_comp_names)} finisher cards")
        except Exception as _ce:
            print(f"[BOUNTY END] card refresh sweep error: {_ce}")

        # Persist the deletion time instead of sleeping 24h in the handler — a
        # restart (Railway redeploy, SIGTERM, crash) would have lost the sleep and
        # orphaned the channel/role forever. The _grace_sweep loop deletes them once
        # the grace period elapses, and survives restarts.
        try:
            _grace_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=24)
            await _db.set_bounty_grace_delete(bounty['id'], _grace_at)
        except Exception as _ge:
            print(f"[BOUNTY END] grace-delete schedule failed: {_ge}")

    @app_commands.command(name="bounty_post_progress", description="Post or repost the live TOP HUNTERS board in the bounty channel (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def bounty_post_progress(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            bounty = await get_active_bounty()
            if not bounty:
                await interaction.followup.send("No bounty is running.", ephemeral=True)
                return

            bounty_channel = interaction.guild.get_channel(bounty['channel_id'])
            if not bounty_channel:
                await interaction.followup.send("Bounty channel not found.", ephemeral=True)
                return

            made = await ensure_bounty_boards(interaction.guild, bounty)
            if 'progress' in made:
                await interaction.followup.send(
                    f"Posted missing boards: {', '.join(made)}.", ephemeral=True)
                return

            if bounty.get('progress_msg_id'):
                try:
                    old_msg = await bounty_channel.fetch_message(bounty['progress_msg_id'])
                    await old_msg.delete()
                except Exception:
                    pass

            content = await build_progress_board(bounty, top_n=10)
            msg = await bounty_channel.send(content)

            await _db.update_bounty_field(bounty['id'], 'progress_msg_id', str(msg.id))
            await interaction.followup.send("Done.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_refresh_boards", description="Re-render the bounty channel boards (completions/bonus/progress) from current data (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def bounty_refresh_boards(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            bounty = await get_active_bounty()
            if not bounty:
                await interaction.followup.send("No bounty is running.", ephemeral=True)
                return
            done = await refresh_bounty_boards(interaction.guild, bounty)
            await interaction.followup.send(
                f"Refreshed: {', '.join(done) if done else 'nothing (boards missing?)'}.", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @bounty_group.command(name="status", description="Show the active bounty card and your personal progress")
    async def bounty_status(self, interaction: discord.Interaction):
        # Merged with the old standalone /my_bounty command (removed 2026-06-30) —
        # this now shows the server-wide aggregate card plus the command runner's
        # own progress in one response, instead of requiring a second command.
        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        completions_block = build_bounty_card(
            bounty['title'], bounty['theme_emoji'], bounty['weapons'],
            bounty['special_challenge'], bounty['special_done'], bounty['completions']
        )
        player_row = await get_player_bounty_progress(bounty['title'], str(interaction.user.id))
        if player_row:
            personal_block = f"**Your progress:**\n{build_player_bounty_card(bounty, player_row['progress'])}"
        else:
            personal_block = "*No submissions recorded for this bounty yet.*"
        card = "\n\n".join(b for b in (completions_block, personal_block) if b)
        await interaction.response.send_message(card, ephemeral=True)

    @bounty_group.command(name="hunt", description="Show the top hunters for the active bounty")
    async def bounty_hunt(self, interaction: discord.Interaction):
        bounty = await get_active_bounty()
        if not bounty:
            await interaction.response.send_message("No bounty is running.", ephemeral=True)
            return
        board = await build_progress_board(bounty, top_n=10)
        await interaction.response.send_message(board)

    @app_commands.command(name="bounty_add_card", description="Manually create a bounty forum card for a player (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player to create a card for")
    async def bounty_add_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)
        if not forum_channel:
            await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
            return

        player_name = member.nick if member.nick else member.display_name
        player_id = member.id

        player_row = await get_player_bounty_progress(bounty['title'], str(player_id))
        if player_row and player_row.get('forum_post_id'):
            await interaction.followup.send(f"⚠️ {player_name} already has a forum card.", ephemeral=True)
            return

        if player_row:
            player_progress = player_row['progress']
        else:
            player_progress = {w: {"current": 0, "total": bounty['weapons'][w]['total']} for w in bounty['weapons']}

        try:
            new_thread, _ = await forum_channel.create_thread(
                name=player_name,
                content=bounty['theme_emoji']
            )
            card_text = build_player_bounty_card(bounty, player_progress)
            await new_thread.send(card_text)
            forum_post_id = new_thread.id

            await save_player_bounty_progress(bounty['title'], str(player_id), player_name, forum_post_id, player_progress)

            await interaction.followup.send(f"Bounty card created for {player_name}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_refresh_card", description="Refresh a player's bounty forum card (mod only)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The player whose card to refresh")
    async def bounty_refresh_card(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        player_row = await get_player_bounty_progress(bounty['title'], player_id)
        if not player_row:
            await interaction.followup.send(f"❌ No bounty data found for {player_name}.", ephemeral=True)
            return

        forum_post_id = player_row.get('forum_post_id')
        if not forum_post_id:
            await interaction.followup.send(f"❌ No forum card found for {player_name}. Use /bounty_add_card instead.", ephemeral=True)
            return

        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)
        if not forum_channel:
            await interaction.followup.send("❌ Ledger forum channel not found.", ephemeral=True)
            return

        try:
            forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
            player_progress = player_row['progress']
            card_text = build_player_bounty_card(bounty, player_progress)
            messages = []
            async for msg in forum_thread.history(limit=5, oldest_first=True):
                messages.append(msg)
            bot_messages = [m for m in messages if m.author.bot]
            if bot_messages:
                await bot_messages[-1].edit(content=card_text)
            else:
                await forum_thread.send(card_text)
            await interaction.followup.send(f"✅ Refreshed bounty card for **{player_name}**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)

    @app_commands.command(name="bounty_set_bonus", description="Mark a player's bounty special challenge as complete (mod only).")
    @app_commands.describe(member="The player to mark bonus complete for")
    async def bounty_set_bonus(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_mod(interaction):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        player_row = await get_player_bounty_progress(bounty['title'], player_id)
        # Allow even if player has no prior bounty data — create fresh progress
        player_progress = player_row['progress'] if player_row else {}
        forum_post_id = player_row.get('forum_post_id') if player_row else None

        _cspec = _parse_special(bounty)
        _cneed = _cspec['need'] if _cspec else 1
        already_done = player_progress.get('__special__', 0) >= _cneed

        player_progress['__special__'] = _cneed

        # Update global bounty special_done flag
        bounty['special_done'] = True

        # Append to bonus_completions list (same pattern as completions)
        bonus_completions = bounty.get('bonus_completions', [])
        already_in_list = any(str(e.get('id') if isinstance(e, dict) else '') == str(player_id) for e in bonus_completions)
        if already_done and already_in_list:
            await interaction.followup.send(f"**{player_name}** has already completed the bonus.", ephemeral=True)
            return
        if not already_in_list:
            bonus_completions.append({'id': str(player_id), 'name': player_name})
        bounty['bonus_completions'] = bonus_completions
        await save_bounty_state(bounty['id'], bounty['weapons'], True, bounty['completions'])
        await _db.update_bounty_field(bounty['id'], 'bonus_completions', json.dumps(bonus_completions))

        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)

        if forum_channel and forum_post_id:
            try:
                forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                card_text = build_player_bounty_card(bounty, player_progress)
                messages = []
                async for msg in forum_thread.history(limit=5, oldest_first=True):
                    messages.append(msg)
                bot_messages = [m for m in messages if m.author.bot]
                if bot_messages:
                    await bot_messages[-1].edit(content=card_text)
                else:
                    await forum_thread.send(card_text)
            except Exception as e:
                print(f"bounty_set_bonus card update error: {e}")

        await save_player_bounty_progress(bounty['title'], player_id, player_name, forum_post_id, player_progress)

        # Update the bonus completions board message
        bounty_channel = guild.get_channel(bounty['channel_id']) if bounty.get('channel_id') else None
        if not bounty_channel and bounty.get('channel_id'):
            try:
                bounty_channel = await guild.fetch_channel(bounty['channel_id'])
            except Exception as e:
                print(f"bounty_set_bonus channel fetch error: {e}")
                bounty_channel = None
        print(f"[BOUNTY_SET_BONUS] channel={bounty_channel} bonus_msg_id={bounty.get('bonus_msg_id')}")
        if bounty_channel and bounty.get('bonus_msg_id'):
            try:
                bonus_text = _build_bonus_board_text(bounty)
                bonus_msg = await bounty_channel.fetch_message(bounty['bonus_msg_id'])
                await bonus_msg.edit(content=bonus_text)
                print(f"[BOUNTY_SET_BONUS] Board updated with {len(bonus_completions)} completers")
            except Exception as e:
                print(f"bounty_set_bonus board update error: {e}")

        await interaction.followup.send(f"⚜️ Bonus marked complete for **{player_name}**.", ephemeral=True)

    @app_commands.command(name="bounty_credit", description="Add or remove a player's bounty weapon hits (mod only).")
    @app_commands.describe(member="The player", weapon="The bounty weapon",
                           amount="How many hits to add — use a NEGATIVE number to remove (default +1).")
    async def bounty_credit(self, interaction: discord.Interaction, member: discord.Member, weapon: str, amount: int = 1):
        if not _is_mod(interaction):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bounty = await get_active_bounty()
        if not bounty:
            await interaction.followup.send("No bounty is running.", ephemeral=True)
            return

        weapons = bounty['weapons']
        matched_key = next((k for k in weapons if k.lower() == weapon.lower()), None)
        if not matched_key:
            valid = ", ".join(weapons.keys())
            await interaction.followup.send(
                f"❌ `{weapon}` is not in the current bounty.\nValid weapons: {valid}", ephemeral=True)
            return

        guild = interaction.guild
        player_name = member.nick if member.nick else member.display_name
        player_id = str(member.id)

        if amount == 0:
            await interaction.followup.send("Amount is 0 — nothing to do.", ephemeral=True)
            return
        # Adjust global weapon counter (clamped at 0)
        w = weapons[matched_key]
        w['current'] = max(0, int(w.get('current', 0)) + amount)
        weapons[matched_key] = w

        # Update player progress
        player_row = await get_player_bounty_progress(bounty['title'], player_id)
        if player_row:
            player_progress = player_row['progress']
            forum_post_id = player_row['forum_post_id']
        else:
            player_progress = {}
            forum_post_id = None

        raw = player_progress.get(matched_key, 0)
        cur = raw['current'] if isinstance(raw, dict) else int(raw)
        new_total = max(0, cur + amount)
        player_progress[matched_key] = new_total

        # Assign bounty role if not already
        bounty_role = guild.get_role(bounty['role_id']) if bounty['role_id'] else None
        if amount > 0 and bounty_role and bounty_role not in member.roles:
            try:
                await member.add_roles(bounty_role, reason="Bounty credit (manual)")
            except Exception as e:
                print(f"[BOUNTY_CREDIT] Role assign error: {e}")

        # Update forum card
        forum_channel_id = bounty.get('forum_channel_id') or BOUNTY_FORUM_CHANNEL_ID
        forum_channel = guild.get_channel(forum_channel_id)
        if forum_channel and isinstance(forum_channel, discord.ForumChannel):
            if forum_post_id:
                try:
                    forum_thread = forum_channel.get_thread(forum_post_id) or await guild.fetch_channel(forum_post_id)
                    card_text = build_player_bounty_card(bounty, player_progress)
                    messages = []
                    async for msg in forum_thread.history(limit=5, oldest_first=True):
                        messages.append(msg)
                    bot_messages = [m for m in messages if m.author.bot]
                    if bot_messages:
                        await bot_messages[-1].edit(content=card_text)
                    else:
                        await forum_thread.send(card_text)
                except Exception as e:
                    print(f"[BOUNTY_CREDIT] Forum card update error: {e}")
                    forum_post_id = None
            if not forum_post_id:
                try:
                    new_thread, first_msg = await forum_channel.create_thread(
                        name=player_name,
                        content=bounty['theme_emoji']
                    )
                    card_text = build_player_bounty_card(bounty, player_progress)
                    await new_thread.send(card_text)
                    forum_post_id = new_thread.id
                except Exception as e:
                    print(f"[BOUNTY_CREDIT] Forum post create error: {e}")

        await save_player_bounty_progress(bounty['title'], str(member.id), player_name, forum_post_id, player_progress)
        await save_bounty_state(bounty['id'], weapons, bounty['special_done'], bounty['completions'])

        _verb = "Credited" if amount > 0 else "Removed"
        _n = abs(amount)
        await interaction.followup.send(
            f"\u2705 {_verb} **{player_name}** {_n} hit{'s' if _n != 1 else ''} on **{matched_key}** — now {new_total}/{w['total']}.",
            ephemeral=True
        )


    @app_commands.command(name="bounty_complete", description="Manually mark a player as having completed a bounty, past or present (mod only).")
    @app_commands.describe(member="The player", bounty="Bounty title (past or present)")
    @app_commands.autocomplete(bounty=_bounty_title_ac)
    async def bounty_complete(self, interaction: discord.Interaction, member: discord.Member, bounty: str):
        if not _is_mod(interaction):
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        rows = await _db.get_all_bounties()
        brow = next((r for r in rows if r and r[0].strip().lower() == bounty.strip().lower()), None)
        if not brow:
            valid = ", ".join(sorted({r[0].strip() for r in rows if r and r[0].strip()}))
            await interaction.followup.send(f"\u274c No bounty titled `{bounty}`.\nKnown: {valid}", ephemeral=True)
            return
        title = brow[0].strip()
        try:
            weapons = json.loads(brow[4]) if brow[4] else {}
        except Exception:
            weapons = {}
        player_id = str(member.id)
        # Use the player's REGISTERED name so the card's legacy-bounty lookup matches.
        _reg = await _db.get_player(player_id)
        player_name = ((_reg[1].strip() if _reg and len(_reg) > 1 and _reg[1] else None)
                       or member.nick or member.display_name)

        # If the bounty has weapon requirements, satisfy them + record the completion
        # in its list (keeps the in-app state correct). Bounties with none (e.g. Plague)
        # simply skip this and rely on the retroactive credit below.
        if weapons:
            prow = await get_player_bounty_progress(title, player_id)
            progress = prow['progress'] if prow else {}
            forum_post_id = prow['forum_post_id'] if prow else None
            for w, t in weapons.items():
                progress[w] = t['total'] if isinstance(t, dict) else int(t)
            await save_player_bounty_progress(title, player_id, player_name, forum_post_id, progress)
            try:
                completions = json.loads(brow[7]) if brow[7] else []
            except Exception:
                completions = []
            already = any((isinstance(e, dict) and str(e.get('id')) == player_id) or str(e) == player_id
                          for e in completions)
            if not already:
                completions.append({"id": player_id, "name": player_name,
                                    "date": _community_now().strftime('%b %d')})
                await save_bounty_state(brow[15], weapons, brow[6] == '1', completions)

        # Retroactive credit — a legacy-bounties record shows on the card directly,
        # no matter the weapon requirements. This is what makes Plague work.
        try:
            await _db.add_legacy_bounty(player_name, title, None, discord_id=player_id)
        except Exception as e:
            print(f"[BOUNTY_COMPLETE] legacy credit error: {e}")

        # Refresh the player's registry card.
        try:
            from cogs.registry import create_or_update_registry_card
            await create_or_update_registry_card(interaction.guild, member.id, player_name)
        except Exception as e:
            print(f"[BOUNTY_COMPLETE] card refresh error: {e}")

        await interaction.followup.send(
            f"\u2705 Credited **{player_name}** with completing **{title}**. Card refreshed.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(BountyCog(bot))

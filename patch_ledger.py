"""
One-time patch: redesign ledger entrance to mirror Discord sidebar structure.
Run from the repo root: python patch_ledger.py
"""
import re

path = 'cogs/leaderboards.py'
content = open(path, encoding='utf-8').read()

# Find and replace the entire build_ledger_entrance function body up to the embed= line
old = '''async def build_ledger_entrance(guild):
    """
    Post or refresh the 6-section ledger entrance in LEDGER_ENTRANCE_CHANNEL_ID.
    Each section is one message; Butler edits it in-place on subsequent calls.
    """
    try:
        channel = guild.get_channel(LEDGER_ENTRANCE_CHANNEL_ID)
        if not channel:
            channel = await guild.fetch_channel(LEDGER_ENTRANCE_CHANNEL_ID)

        try:
            all_lb_rows = await _get_lb_records()
        except Exception as e:
            print(f"Ledger entrance DB read error: {e}")
            return

        def board_links(names_and_ids, guild_id, max_chars=1600):
            """Turn a list of (display_name, thread_id) into inline bullet links, capped to fit."""
            links = []
            for name, tid in names_and_ids:
                links.append(f"[{name}](https://discord.com/channels/{guild_id}/{tid})")
            result = \' • \'.join(links)
            if len(result) <= max_chars:
                return result
            kept = []
            for link in links:
                candidate = \' • \'.join(kept + [link])
                if len(candidate) > max_chars - 30:
                    remaining = len(links) - len(kept)
                    kept.append(f"*+{remaining} more*")
                    break
                kept.append(link)
            return \' • \'.join(kept)

        guild_id = guild.id

        weapon_1h_boards = sorted(
            [(r[\'Leaderboard Name\'], int(r[\'Thread ID\']))
             for r in all_lb_rows
             if r.get(\'Type\', \'\').strip().lower() == \'weapon\'
             and r[\'Leaderboard Name\'] in _WEAPONS_1H],
            key=lambda x: x[0]
        )
        weapon_2h_boards = sorted(
            [(r[\'Leaderboard Name\'], int(r[\'Thread ID\']))
             for r in all_lb_rows
             if r.get(\'Type\', \'\').strip().lower() == \'weapon\'
             and r[\'Leaderboard Name\'] in _WEAPONS_2H],
            key=lambda x: x[0]
        )
        map_boards_raw = [
            r for r in all_lb_rows
            if r.get(\'Type\', \'\').strip().lower() == \'map\'
        ]
        seen_maps = {}
        for r in sorted(map_boards_raw, key=lambda x: x[\'Leaderboard Name\']):
            base = r[\'Leaderboard Name\'].split(\' - \')[0].strip()
            if base not in seen_maps:
                seen_maps[base] = int(r[\'Thread ID\'])
        map_boards = sorted(seen_maps.items(), key=lambda x: x[0])

        feat_boards = sorted(
            [(r[\'Leaderboard Name\'], int(r[\'Thread ID\']))
             for r in all_lb_rows
             if r.get(\'Type\', \'\').strip().lower() == \'feat\'],
            key=lambda x: x[0]
        )

        _t = lambda tid: type(\'T\', (), {\'id\': tid})()
        idx_1h     = _t(INDEX_THREAD_1H)
        idx_2h     = _t(INDEX_THREAD_2H)
        idx_maps   = await _find_index_thread(guild, MAP_RECORDS_FORUM_ID,  "Map Records")
        idx_feats  = _t(INDEX_THREAD_FEATS)
        idx_bounty = await _find_index_thread(guild, BOUNTY_CARDS_FORUM_ID, "Bounty Cards")
        idx_reg    = _t(REGISTRY_INDEX_THREAD_ID)

        def index_link(thread, label):
            if thread:
                return f"[→ Full {label} Index](https://discord.com/channels/{guild_id}/{thread.id})"
            return f"*{label} index not yet built*"

        def section_link(label, thread, full_label):
            """Return a bold markdown hyperlink for a section, or plain label if no thread."""
            if thread:
                url = f"https://discord.com/channels/{guild_id}/{thread.id}"
                return f"**[{label}]({url})**"
            return f"**{label}**"

        embed = discord.Embed(color=0x8b6914)

        sections = [
            section_link("<:cigar:1444893851427803298>  BUTLER\'S ARCHIVE", idx_reg, \'Registry\'),
            section_link("🐱  BOUNTY CARDS",                               idx_bounty, \'Bounty Cards\'),
            section_link("<a:campaignmaster:1520497947115262083>  MAP RECORDS", idx_maps, \'Maps\'),
            section_link("⚔️  TWO-HANDED WEAPONS",                         idx_2h, \'2H\'),
            section_link("🗡️  ONE-HANDED WEAPONS",                         idx_1h, \'1H\'),
            section_link("🏛️  FEATS",                                      idx_feats, \'Feats\'),
        ]

        for value in sections:
            embed.add_field(name="​", value=value, inline=False)
            embed.add_field(name="​", value="​", inline=False)'''

new = '''async def build_ledger_entrance(guild):
    """
    Post or refresh the ledger entrance in LEDGER_ENTRANCE_CHANNEL_ID.
    Mirrors the Discord sidebar structure top-to-bottom with bold hyperlinks.
    """
    try:
        channel = guild.get_channel(LEDGER_ENTRANCE_CHANNEL_ID)
        if not channel:
            channel = await guild.fetch_channel(LEDGER_ENTRANCE_CHANNEL_ID)

        guild_id = guild.id

        def ch_url(channel_id):
            return f"https://discord.com/channels/{guild_id}/{channel_id}"

        def row(emoji, label, url):
            if url:
                return f"**[{emoji}┃{label}]({url})**"
            return f"**{emoji}┃{label}**"

        # Fixed channels
        rules_url      = ch_url(1460713024082935930)
        favourites_url = ch_url(1518822798116524092)

        # Index threads
        _t = lambda tid: type('T', (), {'id': tid})()
        idx_1h    = _t(INDEX_THREAD_1H)
        idx_2h    = _t(INDEX_THREAD_2H)
        idx_maps  = await _find_index_thread(guild, MAP_RECORDS_FORUM_ID, "Map Records")
        idx_feats = _t(INDEX_THREAD_FEATS)
        idx_reg   = _t(REGISTRY_INDEX_THREAD_ID)

        # Active bounty from DB
        bounty_emoji = "🎯"
        bounty_label = "Active Bounty"
        bounty_url   = None
        try:
            all_bounties = await _db.get_all_bounties()
            # row format: [title, channel_id, message_id, theme_emoji, ..., active(idx8), ...]
            for b in all_bounties:
                if b[8] == 'TRUE':
                    bounty_emoji = b[3] or "🎯"
                    bounty_label = b[0] or "Active Bounty"
                    if b[1]:
                        bounty_url = ch_url(int(b[1]))
                    break
        except Exception as be:
            print(f"[LEDGER] bounty lookup error: {be}")

        lines = [
            row("⚖️",        "challenge-rules",   rules_url),
            row("📋",        "butlers-favorites",  favourites_url),
            row(bounty_emoji, bounty_label,        bounty_url),
            row("🗂️",        "butlers-archive",   ch_url(idx_reg.id)   if idx_reg   else None),
            row("🏆",        "map-records",        ch_url(idx_maps.id)  if idx_maps  else None),
            row("⚔️",        "2h-weapons",         ch_url(idx_2h.id)    if idx_2h    else None),
            row("🗡️",        "1h-weapons",         ch_url(idx_1h.id)    if idx_1h    else None),
            row("🏛️",        "feats-of-war",       ch_url(idx_feats.id) if idx_feats else None),
        ]

        embed = discord.Embed(description="\n".join(lines), color=0x8b6914)'''

if old in content:
    content = content.replace(old, new)
    open(path, 'w', encoding='utf-8').write(content)
    print('✅ Patch applied successfully.')
else:
    print('❌ Pattern not found — file may have already been patched or differs from expected.')
    # Diagnostic: show lines around build_ledger_entrance
    for i, line in enumerate(content.splitlines(), 1):
        if 'build_ledger_entrance' in line:
            print(f'  Line {i}: {line}')

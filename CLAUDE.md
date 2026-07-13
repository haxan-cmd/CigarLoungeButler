# CLAUDE.md — orientation for AI assistants (and new humans)

The Butler is a Discord bot for a competitive Chivalry 2 community. Players post
scorecard screenshots; the bot reads them with vision AI, logs runs to Postgres,
and maintains leaderboards, per-player registry cards, monthly bounties, seasonal
titles, and a sardonic AI personality. Hosted on Railway, auto-deploys from
`main` on GitHub.

## File map

| File | Owns |
|---|---|
| `bot.py` | Startup, healthcheck HTTP server (+ `/kofi` webhook route), command sync, graceful shutdown, global error handlers. Runs as `__main__`. |
| `config.py` | ALL constants: channel/role IDs, weapon/class/map tables, alias maps, emoji tokens, rank thresholds. No imports from project modules. |
| `utils/db.py` | The only file that talks to Postgres. Pool, TTL cache, targeted queries, schema/index bootstrap (`_ensure_schema` / `_ensure_indexes`). |
| `utils/helpers.py` | AI clients (Anthropic + Gemini vision), vision scorecard parser, nerve-centre logging/alerts, milestone detection, **shared shutdown state**. |
| `utils/parsing.py` | Pure caption → (weapon, subclass) parser. Unit-tested. |
| `utils/ranks.py` | Pure rank/title/Hundred-Handed math. Unit-tested. |
| `cogs/submissions.py` | The submission pipeline: on_message trigger → vision → confirm UI views → finalise worker → reactions/blurb → background updates. Also the edit flow. |
| `cogs/leaderboards.py` | Board rendering/updating, ledger entrance, forum indexes, monthly/all-time boards, ratings, `/rank`, `/refresh*`, `/remove_board_score`. |
| `cogs/registry.py` | Registry cards (per-player forum threads), mark calculation, `/stats`, `/refresh_card`, legacy imports. |
| `cogs/bounty.py` | Monthly bounty: progress tracking, forum cards, completion, `/bounty_*` commands. |
| `cogs/favourites.py` | Season board (`calculate_butler_stats`), title roles, seasons/Hall of Fame, `/butlers_report`. |
| `cogs/personality.py` | Butler AI chat (on_message), task loops (polls, digest, dry-spell, daily cycle), bounty channel placeholders. |
| `cogs/admin.py` | Mod tooling: `/remove_submission`, `/unlist_submission`, backups, rules posts, `/award_marks`, `/set_feat_count`. |
| `cogs/kofi.py` | Ko-fi donations: webhook handler (route lives in bot.py), dashboard embed. |
| `schema.sql` | Canonical table definitions. Post-launch columns/tables are added by `_ensure_schema` in db.py. |
| `tests/` | Pure-logic tests (`pytest -q`): parsing, ranks, config integrity. |

## What happens on a submission (the hot path)

1. `SubmissionsCog.on_message` — image in the submissions channel → "Scorecard detected" prompt with Submit button.
2. Button → Gemini vision reads the screenshot (`vision_parse_scorecard` in helpers, run in a thread). Caption keywords fill gaps. Player confirms/fixes via select views.
3. `finalise_submission` → per-guild asyncio queue → `_do_finalise_submission`:
   - instant reactions (cigar first), stickers, dedup check, DB insert (`log_submission`),
   - summary blurb reply with Edit button,
   - then a detached `_bg_tasks` (120s cap): board updates (under `_BOARD_LOCK`), Hundred-Handed tracking, bounty progress, butler personality hooks, registry card refresh, archive row, milestones, season board + title roles.
4. Edits (`_apply_edit`) rewrite the DB row, wipe + rebuild the affected boards, refresh the card, and rebuild the blurb.

## Row shapes (legacy Sheets format — lists of strings)

`utils/db.py` returns rows as **lists of strings** (a holdover from the Google
Sheets era). Cogs index into them positionally. Key maps:

- **submissions**: 0 submitted_at · 1 player_name · 2 discord_id · 3 weapon · 4 subclass · 5 map · 6 faction · 7 takedowns · 8 kills · 9 deaths · 10 vip("Yes"/"No") · 11 feats · 12 message_link · 13 lobby_rank · 14 lobby_size · 15 kills_rank · 16 team_rank · 17 team_size · 18 total_lobby_kills · 19 team_td_ratio · 20 team_kill_share · 21 team_td_share · 22 second_place_td · 23 id · 24 score
- **leaderboard_data**: 0 board_name · 1 player_name · 2 discord_id · 3 score · 4 message_link · 5 weapon
- **players**: 0 discord_id · 1 player_name · 2 forum_thread_id · 3 total_marks · 4 submission_count · 5 last_submission · 6 weapon_marks · 7 class_marks · 8–10 manual feat-count overrides (None = auto)

## Conventions and gotchas (learned the hard way)

- **Never `import bot` from a cog.** bot.py runs as `__main__`; importing it
  re-executes the file under a second module name (second Bot instance, separate
  globals). Shared state lives in `utils/helpers.py`; web routes must be
  registered in bot.py **before** the aiohttp site starts (the router freezes).
- **Timestamps are naive UTC.** DB columns are `TIMESTAMP` (no tz); asyncpg
  rejects tz-aware datetimes. Use `datetime.now(timezone.utc).replace(tzinfo=None)`.
- **The `feats` column is also a tag bag.** Besides real feats (100 Kills,
  200 Takedowns, Triple, Flawless, Predator, High Score…) it can carry:
  - `Resubmit` — an old run re-uploaded; excluded from weekly stats, bounty, ratings.
  - `Unlisted` — mod-toggled via `/unlist_submission`; excluded from ALL boards,
    records, rebuilds, backfills, and ratings, but still counts for marks + bounty.
- **Board names**: weapon boards are the weapon name; map boards are
  `"{Map} - {Faction}"`; feat boards are `100 Kills`, `200 Takedowns`, `Triple`,
  `TUFF`, `Flawless`, `Mallet`, `Knife`, `Healing Horn`, `Pacifist`.
  Feat boards are per-run ("unlimited") except Flawless/Mallet/Knife/Healing Horn
  (personal-best). Weapon/map boards are top-10, VIP runs excluded from weapon boards.
- **Hot paths use targeted queries** (`get_leaderboard_by_board`,
  `get_submissions_by_player`, SQL MAX/COUNT). Don't "simplify" them into
  `get_all_*` scans. The TTL cache in db.py (5s) collapses bursts; cached lists
  are shared references — treat as read-only.
- **`_BOARD_LOCK`** (submissions.py) serialises all board read-modify-writes.
  Any new code that mutates `leaderboard_data` + re-renders should hold it.
- **All DDL lives in `_ensure_schema`/`_ensure_indexes`** (db.py), run once at
  startup. Never put ALTER/CREATE in per-call functions.
- **Command sync** happens once, on the first `on_ready` (guild-scoped).
  New/changed slash commands appear after deploy; clients may need Ctrl+R.
- **Pacifist runs** (0 kills, ≤10 TD) earn no weapon marks and only land on the
  Pacifist board (ranked by scoreboard score, one row per player).
- **Vision name hints**: stored IGNs (players.igns) + Discord display name are
  passed to Gemini; new IGNs are auto-learned unless they belong to another player.
- **Mount/registry cards** are edited in place, never recreated — thread IDs are
  referenced from blurbs and indexes.

## Environment variables

`DISCORD_TOKEN` (required) · `DATABASE_URL` (Postgres; bot runs without it but
most features need it) · `ANTHROPIC_API_KEY` (Butler chat; optional, quips fall
back) · `GOOGLE_AI_API_KEY` (vision; optional, manual entry fallback) ·
`KOFI_TOKEN` (webhook verification; optional) · `PORT` (healthcheck, default 8080).

## Deploy & ops

- Railway auto-deploys `main`. Healthcheck `GET /` returns 503 once the gateway
  is dead (post-first-ready), so Railway restarts a zombied bot.
- SIGTERM → drain in-flight submissions (counter in utils/helpers) → close.
- Login 429 → 15-minute backoff to avoid Cloudflare bans on crash-loops.
- Daily gzip DB backup to the nerve-centre channel (`/backup_now` to force).
- Errors surface to the nerve-centre channel via `nerve_alert` (10-min dedup).

## Where to look when something's wrong

See `docs/TROUBLESHOOTING.md` for the symptom → fix table, and
`ADMIN_COMMANDS.md` for the full mod command list.

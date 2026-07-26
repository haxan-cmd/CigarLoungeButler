# CLAUDE.md: orientation for AI assistants (and new humans)

The Butler is a Discord bot for a competitive Chivalry 2 community. Players post
scorecard screenshots; the bot reads them with vision AI, logs runs to Postgres,
and maintains leaderboards, per-player registry cards, monthly bounties, seasonal
titles, and a sardonic AI personality. Hosted on Railway, auto-deploys from
`main` on GitHub.

## File map

| File | Owns |
|---|---|
| `bot.py` | Startup, healthcheck HTTP server (+ `/kofi` webhook and `/export/submissions` routes), command sync, graceful shutdown, global error handlers. Runs as `__main__`. |
| `config.py` | ALL constants: channel/role IDs, weapon/class/map tables, alias maps, emoji tokens, rank thresholds. No imports from project modules. |
| `utils/db.py` | The only file that talks to Postgres. Pool, TTL cache, targeted queries, schema/index bootstrap (`_ensure_schema` / `_ensure_indexes`). |
| `utils/helpers.py` | AI clients (OpenAI chat + Gemini vision), `butler_complete` (the single Butler chat call path), vision scorecard parser, nerve-centre logging/alerts, milestone detection, shared shutdown state. |
| `utils/parsing.py` | Pure caption to (weapon, subclass) parser. Unit-tested. |
| `utils/ranks.py` | Pure rank/title/Hundred-Handed math. Unit-tested. |
| `utils/tilt.py` | Pure lobby-difficulty ladder: raw kill gap to band to tiered valor marks. Single source for the difficulty label and the mark payout, so they cannot drift. Unit-tested. |
| `utils/challenges.py` | Pure parser for bounty special-challenge strings. Unit-tested. |
| `utils/charts.py` | Themed matplotlib charts, rendered off the event loop via `render_async`: tilt ladder, weapon-lethality charge, `/explore` breakdown and trend lines, macro season graphs. |
| `cogs/submissions.py` | The submission pipeline: on_message trigger, vision, confirm UI views, finalise worker, reactions/blurb (incl. the lethality percentile and lobby-difficulty marker), background updates. Also the edit flow and the isolated Peasant Run flow. |
| `cogs/leaderboards.py` | Board rendering/updating, ledger entrance, forum indexes, monthly/all-time boards, ratings, the Peasant board, `/top`, `/refresh*`, `/remove_board_score`. |
| `cogs/registry.py` | Registry cards (per-player forum threads), mark calculation (incl. difficulty valor marks), `/playerstats`, `/refreshcard`, legacy imports. |
| `cogs/bounty.py` | Monthly bounty: progress tracking, forum cards, completion, `/bounty_*` commands. |
| `cogs/favourites.py` | Season board (`calculate_butler_stats`), title roles, seasons/Hall of Fame, the combined All-Time Titles board (`/setup_titles_board`, `refresh_all_time_titles_board`), `/report`, `/standings`, `/season`, `/titles`. |
| `cogs/personality.py` | Butler AI chat (on_message, with lore injection), task loops (polls, digest, dry-spell, daily cycle), `/explore`, `/tilt_stats`, `/serverstats`, `/help`, bounty channel placeholders. |
| `cogs/admin.py` | Mod tooling: `/remove_submission`, `/unlist_submission`, backups, rules posts, `/award_marks`, `/set_feat_count`. |
| `cogs/kofi.py` | Ko-fi donations: webhook handler (route lives in bot.py), dashboard embed. |
| `schema.sql` | Canonical table definitions. Post-launch columns/tables are added by `_ensure_schema` in db.py. |
| `tests/` | Pure-logic tests (`pytest -q`): parsing, ranks, config integrity. |

## What happens on a submission (the hot path)

1. `SubmissionsCog.on_message`: image in the submissions channel produces a "Scorecard detected" prompt with a Submit button.
2. Button click: Gemini vision reads the screenshot (`vision_parse_scorecard` in helpers, run in a thread). Caption keywords fill gaps. Player confirms/fixes via select views.
3. `finalise_submission` puts the run on a per-guild asyncio queue; `_do_finalise_submission` then does:
   instant reactions (cigar first), stickers, dedup check, DB insert (`log_submission`),
   the summary blurb reply with an Edit button,
   then a detached `_bg_tasks` (120s cap): board updates (under `_BOARD_LOCK`), Hundred-Handed tracking, bounty progress, butler personality hooks, registry card refresh, archive row, milestones, season board + title roles.
4. Edits (`_apply_edit`) rewrite the DB row, wipe and rebuild the affected boards, refresh the card, and rebuild the blurb.

## Row shapes (legacy Sheets format, lists of strings)

`utils/db.py` returns rows as lists of strings (a holdover from the Google
Sheets era). Cogs index into them positionally. Key maps:

- submissions: 0 submitted_at · 1 player_name · 2 discord_id · 3 weapon · 4 subclass · 5 map · 6 faction · 7 takedowns · 8 kills · 9 deaths · 10 vip("Yes"/"No") · 11 feats · 12 message_link · 13 lobby_rank · 14 lobby_size · 15 kills_rank · 16 team_rank · 17 team_size · 18 total_lobby_kills · 19 team_td_ratio · 20 team_kill_share · 21 team_td_share · 22 second_place_td · 23 id · 24 score · 25 team_total_kills · 26 enemy_total_kills
- leaderboard_data: 0 board_name · 1 player_name · 2 discord_id · 3 score · 4 message_link · 5 weapon
- players: 0 discord_id · 1 player_name · 2 forum_thread_id · 3 total_marks · 4 submission_count · 5 last_submission · 6 weapon_marks · 7 class_marks · 8-10 manual feat-count overrides (None = auto)
- peasant_runs (own table, not leaderboard_data): player_name, discord_id, map, faction, score, takedowns, kills, deaths, message_link. One highscore row per player per map.
- peasant_board (pointer, single row id=1): channel_id, message_id for the posted board message.
- titles_board (pointer, single row id=1): channel_id, message_id for the combined All-Time Titles board (Grand Marshal / Weapons Master / Campaign Master rankings). Refreshed on `/refresh_report` or `/refresh_titles_board`; no longer shown in the monthly report.

## Conventions and gotchas

- Never `import bot` from a cog. bot.py runs as `__main__`; importing it
  re-executes the file under a second module name (second Bot instance, separate
  globals). Shared state lives in `utils/helpers.py`. Web routes must be
  registered in bot.py before the aiohttp site starts (the router freezes).
- Timestamps are naive UTC. DB columns are `TIMESTAMP` (no tz); asyncpg
  rejects tz-aware datetimes. Use `datetime.now(timezone.utc).replace(tzinfo=None)`.
- The `feats` column is also a tag bag. Besides real feats (100 Kills,
  200 Takedowns, Triple, Flawless, Predator, High Score, etc.) it can carry:
  - `Resubmit`: an old run re-uploaded. Excluded from weekly stats, bounty, ratings.
  - `Unlisted`: mod-toggled via `/unlist_submission`. Excluded from ALL boards,
    records, rebuilds, backfills, and ratings, but still counts for marks + bounty.
- Board names: weapon boards are the weapon name; map boards are
  `"{Map} - {Faction}"`; feat boards are `100 Kills`, `200 Takedowns`, `Triple`,
  `TUFF`, `Flawless`, `Mallet`, `Knife`, `Healing Horn`, `Healing Banner`, `Pacifist`.
  Feat boards are per-run ("unlimited") except Mallet/Knife/Healing Horn/Healing Banner
  (personal-best). Flawless is unlimited (every no-death run stacks, ranked by TD); the
  player card counts it ×N like 100 Kills. Healing Horn and Healing Banner also accept manual submissions:
  a HEALING-popup screenshot captioned "horn"/"banner" opens a score modal
  (submissions.py HealingScoreView, leaderboards.py submit_manual_pb_score).
  Weapon/map boards are top-10. VIP runs are excluded from weapon boards.
- Hot paths use targeted queries (`get_leaderboard_by_board`,
  `get_submissions_by_player`, SQL MAX/COUNT). Don't "simplify" them into
  `get_all_*` scans. The TTL cache in db.py (5s) collapses bursts; cached lists
  are shared references, treat them as read-only.
- `_BOARD_LOCK` (submissions.py) serialises all board read-modify-writes.
  Any new code that mutates `leaderboard_data` and re-renders should hold it.
- All DDL lives in `_ensure_schema`/`_ensure_indexes` (db.py), run once at
  startup. Never put ALTER/CREATE in per-call functions.
- Command sync happens once, on the first `on_ready` (guild-scoped).
  New/changed slash commands appear after deploy; clients may need Ctrl+R.
- Pacifist runs (0 kills, 10 or fewer TD) earn no weapon marks and only land on
  the Pacifist board (ranked by scoreboard score, one row per player).
- Vision name hints: stored IGNs (players.igns) plus the Discord display name are
  passed to Gemini; new IGNs are auto-learned unless they belong to another player.
- Registry cards are edited in place, never recreated. Thread IDs are
  referenced from blurbs and indexes.
- Lobby difficulty: `utils/tilt.py` grades the raw kill gap (submissions
  columns 25/26, `team_total_kills` vs `enemy_total_kills`, signed from the
  player's OWN side, positive = your team outkilled them) into 7 bands. Graded
  the same for attack and defence, no role correction: Chiv is imbalanced by
  design, so we show the honest gap. The hard tail (your team outkilled) pays
  tiered valor marks, Slightly Uphill +1 / Outmatched +2 / Brutal +3, written as
  a tag (`Uphill`/`Outmatched`/`Brutal`) on the feats column so the mark math and
  edits see it. `adjusted()` is a 0-baseline pass-through kept for option value.
  `/tilt_stats` and `/explore` surface the distribution.
- Peasant board: an isolated highscore board for the Coxwell / Bridgetown Agatha
  peasant stage. It has its OWN tables (`peasant_runs` + the `peasant_board`
  pointer) and its own submit flow, and is deliberately NOT a `leaderboard_data`
  record, so generic board machinery never touches it. It bypasses weapon/class
  marks entirely. `/setup_peasant_board` posts it in the current thread.
- Weapon lethality: the blurb shows a green weapon-silhouette charge and a
  "top X% on {weapon}" percentile (`get_weapon_lethality_percentile`). The
  thumbnail PNG is uploaded to `LETHALITY_STASH_CHANNEL_ID` and referenced by its
  URL, because attachment:// thumbnails detach into standalone images on an
  edited blurb. Do NOT bulk-delete stash-channel images: it breaks old thumbnails.
- Butler lore: `lore/chiv2_lore.md` holds the Chiv 2 faction and world lore; it is
  injected into the Butler chat context on relevant keywords (`personality.py`
  `_lore_context`), not held permanently in the system prompt.

## Environment variables

`DISCORD_TOKEN` (required) · `DATABASE_URL` (Postgres; bot runs without it but
most features need it) · `OPENAI_API_KEY` (Butler chat, GPT-5.6 Luna; optional,
quips fall back) · `GOOGLE_AI_API_KEY` (vision; optional, manual entry fallback) ·
`KOFI_TOKEN` (webhook verification; optional) · `EXPORT_TOKEN` (bearer token for
the read-only `GET /export/submissions` cursor export; endpoint off when unset) ·
`LETHALITY_STASH_CHANNEL_ID` (channel that hosts the blurb lethality thumbnails;
falls back to a hardcoded default) · `PORT` (healthcheck, default 8080).

## Deploy & ops

- Railway auto-deploys `main`. Healthcheck `GET /` returns 503 once the gateway
  is dead (post-first-ready), so Railway restarts a zombied bot.
- SIGTERM: drain in-flight submissions (counter in utils/helpers), then close.
- Login 429: 15-minute backoff to avoid Cloudflare bans on crash-loops.
- Daily gzip DB backup to the nerve-centre channel (`/backup_now` to force).
- Errors surface to the nerve-centre channel via `nerve_alert` (10-min dedup).

## Where to look when something's wrong

See `docs/TROUBLESHOOTING.md` for the symptom-to-fix table, and
`ADMIN_COMMANDS.md` for the full mod command list.

## Writing style

House rule, straight from the Butler's own system prompt: no em dashes in the
Butler's own generated output (chat replies, blurbs, quips). Use a comma, colon,
or period. This rule is about the Butler's voice; existing code comments and
docs are not held to it, so do not churn the codebase to strip them.

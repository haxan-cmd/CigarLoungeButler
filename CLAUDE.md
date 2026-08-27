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
| `utils/parsing.py` | Pure caption to (weapon, subclass) parser, plus `md_safe()` — strips `[`/`]` from a user-controlled name before it goes into a markdown `[text](url)` link, so a crafted display name can't inject its own hyperlink into a board/card/blurb. Unit-tested. |
| `utils/grounding.py` | Pure anti-fabrication check: `ungrounded_numbers(reply, context)` flags material numbers the Butler cites that aren't in the context it was given (year-shaped values excluded). Log-only — never rewrites a reply; feeds the fabrication signal in the event log + weekly rollup. Unit-tested. |
| `utils/ranks.py` | Pure rank/title/Hundred-Handed math. Unit-tested. |
| `utils/tilt.py` | Pure lobby-difficulty ladder: raw kill gap to band to tiered valor marks. Single source for the difficulty label and the mark payout, so they cannot drift. Unit-tested. |
| `utils/challenges.py` | Pure parser for bounty special-challenge strings. Unit-tested. |
| `utils/feats.py` | Pure feat/mark derivation (triple, stat feats, tilt valor mark). Shared by the finalise and edit paths. Unit-tested. |
| `utils/boards.py` | Pure board classification — THE single source of truth for which boards are feat/weapon/map/kills, which count toward the board titles (`non_weapon_feat_boards()`), and each board's score unit (`board_unit()`). Route new board-name checks through here, not hand-typed sets. Unit-tested. |
| `utils/goals.py` | Pure "what's next" goal picker across next weapon rank / mastery / Hundred-Handed. Feeds `/next` and the Butler's in-passing goal nudge. Unit-tested. |
| `utils/aggregates.py` | Pure server-wide RANKING engine — THE home for any Butler "who has the most / highest / best X" question. One canonical-identity resolver (`Identity`: IGN variants collapse to one player, displayed under the registry name) + a registry of `AggSpec` records (metric over submissions/players/boards → grouped → ranked → formatted line). Adding a new answerable ranking = ONE `AggSpec` entry; its keywords are exported by `gate_keywords()` and auto-unlock the Butler's data-question gate, so a metric can never be answerable-but-gated (the bug that made "most 100 kill games" deflect). `personality._build_player_stats_ctx` calls `context_block()` once — do NOT add new per-metric injection blocks there; add a spec here. Unit-tested. |
| `utils/archetype.py` | Pure descriptive-playstyle labels from a player's marks distribution: `derive_archetype` (class/weapon → "Knight Main", "Generalist", "Messer Specialist") and `derive_damage_style` (damage type via `config.WEAPON_DAMAGE_TYPES` → "Blunt specialist", "Chop-leaning", "Mixed damage"). Neutral tone. Shown on the registry card (`registry.archetype_label` / `damage_style_label`) and injected into the Butler on data questions (`registry.get_player_descriptors`). Unit-tested. |
| `utils/rivalries.py` | Pure shared-lobby aggregation via a time-window FINGERPRINT (same map + tight time + matching banner totals). NOW THE FALLBACK for legacy rows with no stored roster; the roster engine below is preferred. nemesis/ally, `head_to_head`, pair awards. NO per-game win/loss. Unit-tested. |
| `utils/roster.py` | Pure ROSTER-based rivalry engine — the accurate successor. Every scoreboard lists everyone in the lobby; the vision parser now keeps those NAMES per side. Matches them to registered players (`normalize_name` + OCR-confusable-fold + fuzzy, unregistered = anonymous), then derives nemesis (enemy side) / ally (team side) / `head_to_head` / pair awards from ground-truth membership — one screenshot, no time window, and a rival shows up even if they never submit. Unit-tested. |
| `utils/rivalry_service.py` | Async orchestration: prefers `utils.roster` when ANY submission has a stored roster (`has_roster_coverage`), else falls back to `utils.rivalries`. Fetches submissions + rosters + name→id map, runs the pure engines off the event loop. All rivalry callers (wrapped, statscape, `/versus`, Butler, superlatives) go through here — do NOT call the pure engines directly. |
| `utils/wrapped.py` | Pure season-recap + superlatives aggregation (`/wrapped`, `/superlatives`). Unit-tested. |
| `utils/validation.py` | Pure impossible-submission guard — rejects contradictory data (e.g. Agatha on Askandir) while passing incomplete data. Unit-tested. |
| `utils/charts.py` | Themed matplotlib charts, rendered off the event loop via `render_async`: tilt ladder, weapon-lethality charge, `/explore` breakdown and trend lines, macro season graphs. |
| `cogs/submissions.py` | The submission pipeline: on_message trigger, vision, confirm UI views, finalise worker, reactions/blurb (incl. the lethality percentile and lobby-difficulty marker), background updates. Also the edit flow and the isolated Peasant Run flow. |
| `cogs/leaderboards.py` | Board rendering/updating, ledger entrance, forum indexes, monthly/all-time boards, ratings, the Peasant board, the **Score** board (highest match points, one row/player, top-50, `/setup_score_board`), `/top`, `/refresh*`, `/rebuild_boards`, `/remove_board_score`. Imports `_FEAT_BOARD_NAMES` from `utils/boards`. |
| `cogs/registry.py` | Registry cards (per-player forum threads), mark calculation (incl. difficulty valor + High Score + Score marks), `/playerstats`, `/refreshcard`, `/versus` (head-to-head), `/next` (goal nudge), legacy imports. |
| `cogs/bounty.py` | Monthly bounty: progress tracking, forum cards, completion, `/bounty_*` commands. |
| `cogs/favourites.py` | Season board (`calculate_butler_stats`), title roles (Most Dominant / Warlord), seasons + Hall of Fame (GP champion or per-category winners, per `config.SEASON_GP_CHAMPION`), the combined All-Time Titles board (`/setup_titles_board`, `refresh_all_time_titles_board`), `/report`, `/standings`, `/season`, `/titles`. |
| `cogs/personality.py` | Butler AI chat (on_message, with lore injection), task loops (polls, digest, dry-spell, daily cycle), `/explore`, `/tilt_stats`, `/serverstats`, `/help`, bounty channel placeholders. |
| `cogs/admin.py` | Mod tooling: `/remove_submission`, `/unlist_submission`, backups, rules posts, `/award_marks`, `/set_feat_count`. |
| `cogs/kofi.py` | Ko-fi donations: webhook handler (route lives in bot.py), dashboard embed. |
| `schema.sql` | Canonical table definitions. Post-launch columns/tables are added by `_ensure_schema` in db.py. |
| `tests/` | Pure-logic tests (`pytest -q`): parsing, ranks, tilt, feats, challenges, config integrity, boards, goals, rivalries, wrapped, validation, archetype, aggregates, plus `test_regressions.py` (bugs that shipped — Score-as-TD, kills-companion, feat/archer classification), `test_grounding.py` (anti-fabrication) and `test_md_safe.py` (link-injection). Tests import only `utils/*` + `config` (never cogs — CI installs just pytest+dotenv). Eval methodology + the LLM-behavioural layer live in `docs/EVALS.md`. |
| `tests/integration/` | Cog-level tests (19) that drive real cog logic against an in-memory `FakeDB` (`conftest.py` monkeypatches `utils.db` reads; `make_sub` builds legacy submission rows; sync tests via `asyncio.run`). These reach the mark/board/context logic the pure tests can't. The whole package `importorskip`s discord + asyncpg, so the pure-unit CI skips it and `pytest -q` stays green there; a full env runs all 124. `test_marks_integration` locks mark calc (base/feat-stack/Score-vs-High-Score/valor/canonical/pacifist/VIP); `test_titles_integration` locks the title/board-count math (`_calculate_butler_stats_uncached`) — Kills companions not double-counted (the "81 boards" regression), map vs weapon vs feat bucketing, Weapons Master min-9 threshold; `test_butler_ctx_integration` locks the Butler context bound (`_build_player_stats_ctx`) — standings pinned at 20 entries however many boards a player holds, so the ~8k-char balloon that made the model deflect cannot return. |

## What happens on a submission (the hot path)

1. `SubmissionsCog.on_message`: image in the submissions channel produces a "Scorecard detected" prompt with a Submit button.
2. Button click: Gemini vision reads the screenshot (`vision_parse_scorecard` in helpers, run in a thread). Caption keywords fill gaps. Player confirms/fixes via select views.
3. `finalise_submission` puts the run on a per-guild asyncio queue; `_do_finalise_submission` then does:
   instant reactions (cigar first), stickers, dedup check, DB insert (`log_submission`),
   the summary blurb reply with an Edit button,
   then a detached `_bg_tasks` (120s cap): board updates (under `_BOARD_LOCK`), Hundred-Handed tracking, bounty progress, butler personality hooks, registry card refresh, archive row, milestones, season board + title roles.
4. Edits (`_apply_edit`) rewrite the DB row, wipe and rebuild the affected boards, refresh the card, and rebuild the blurb.

## Startup reconcile (self-heal after an interrupted deploy)

The DB insert (`log_submission`) happens BEFORE the blurb posts, and the derived
work (bounty credit, board placement) runs AFTER it in a detached `_bg_tasks`. So a
deploy/restart that lands mid-submission leaves the run ROW saved but its derived
credit half-done. On every boot, `personality.on_ready` fires two one-shot,
detached reconcilers (guarded by `_startup_reconcile_done` / `_startup_board_reconcile_done`)
that heal exactly that window over the last ~20 minutes of submissions:

- `bounty.reconcile_bounty_progress(guild, bounty, did, name)` — TOP-UP ONLY. Recounts
  weapon + special progress from submissions (`count_player_weapon_runs`) and raises the
  stored value to match; it never lowers a count, so a transient empty read changes
  nothing. Bumps the community participation counter by only the applied delta. Fires NO
  side effects (no completions, GP, roles, pings, reactions, bonus, or community-board
  edits); re-renders only that player's own forum card, in place, and only if it exists.
  Skips already-completed players. Completion ceremony is deliberately left to the
  player's next run or a mod.
- `_startup_board_reconcile` — reruns the interaction-free, additive `rebuild_score_boards`
  (the `/rebuild_boards` engine, keep-higher merge so legacy entries survive and correct
  boards are skipped) on ONLY the boards recent runs touched, then `reseed_feat_boards_for_run`
  (dedup by message link) for the unlimited feat boards. Held under `_board_lock()`. Covers
  weapon / map / weapon-kills + 100 Kills / 200 Takedowns / Triple / Flawless. Does NOT
  cover the niche boards (Score, TUFF, Hybrid, Pacifist, Mallet, Knife, Healing) — a
  resubmit or manual `/rebuild_boards` still heals those.

Both are top-up/additive only and idempotent: re-running over already-correct data is a
no-op, so they can never overwrite or double-count. Real heals log a `reconcile` event
(visible in `/logs`) and print `[RECONCILE] ...` lines. Recent-row fetches:
`db.get_recent_submitter_ids` / `db.get_recent_submissions`.

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
- Board classification is single-sourced in `utils/boards.py` (feat set, weapon vs
  map vs kills, which count toward titles, score units). NEVER re-type a feat-board
  set inline — a stale copy is exactly how the Score board nearly got wiped on season
  reset and inflated the Weapons Master title. Route new checks through `utils/boards`.
- A weapon's Highest-Kills companion board (`"{Weapon} Kills"`) does NOT count as a
  separate weapon board for the titles (Weapons Master / Grand Marshal) — one board
  per weapon. `is_kills_board()` gates this everywhere (board, card, playerstats, butler).
- Archer/ranged weapons (Bow, War Bow, Crossbow, Siege Crossbow, Javelin, Throwing Axe)
  are excluded BY POLICY from the melee titles (Weapons Master / Grand Marshal) —
  `utils.boards.is_archer_weapon()` (derived from `REGISTRY_CLASS_MAP['Archer']`), gated
  in `favourites._calculate_butler_stats_uncached`. The ranged boards still rank on their
  own; they just don't count toward those titles or their board denominators.
- Map kills are NOT a separate board — they render as a section INSIDE the map embed,
  right under the takedowns list and before Kill Share/Warlord. `_map_kills_ranking`
  computes top-10 by best kills per player for that `"{Map} - {Faction}"` live from
  submissions (VIP included, unlisted excluded), threaded through `_rated_embeds` →
  `format_leaderboard_embeds` → `_append_rating_fields` as `kills_rows`. Because those
  sections are LIVE-computed on render, but `update_leaderboards`'s per-board loop only
  re-renders the map board when a run's TAKEDOWNS move the TD ranking, a kills-only record
  used to leave the Kills/Kill Share/Warlord sections stale ("map kill record didn't
  update", recurring). Fixed by a forced `_render_board(map_lb_name)` after the loop
  whenever the loop didn't already render it (`_map_rendered` flag) — do NOT remove it. (An earlier
  separate-board approach was reverted; `/remove_map_kills_boards` cleans up any stray
  `map_kills` boards a prior `/setup_map_kills_boards` run created. `_classify_board`
  still recognises `map_kills` so those strays are found and stay out of the Campaign
  Master count.)
- The **Score** board (`Score`) ranks the highest scoreboard POINTS in a single match,
  one row per player, capped at top-50, +1 mark on board movement (like High Score).
  It is a feat board; its value is POINTS, never takedowns.
- Season display is switched by `config.SEASON_GP_CHAMPION` (default True), read everywhere
  via `getattr(config, 'SEASON_GP_CHAMPION', True)`. ON = the aggregate Grand-Prix points
  champion + standings show across `/standings`, `/season` (with the rendered card), the
  monthly report, the Hall of Fame season embed + index, the registry card season line, and
  the Butler's season context; GP = top-5 per category (5/4/3/2/1) + featured picks (3/1) +
  bounty race, summed in `favourites.season_total` / `compute_season_standings`. OFF = no
  overall champion; each of the five categories (Kill Share, Warlord, Total Tally, Most
  Kills, Highest Takedowns) stands alone and the Hall of Fame records the category champions
  (`/standings` = category leaders, `/season` = your per-category placements). Every season
  display site carries BOTH branches — keep them both working when you touch season display,
  and never delete the GP engine, it feeds the ON path. The **Most Dominant** / **Warlord**
  ROLES are separate season titles (Dominance = harmonic mean of Kill Share + Warlord;
  Warlord = TD ÷ team kills) and exist in either mode.
- Board names: weapon boards are the weapon name; map boards are
  `"{Map} - {Faction}"`; feat boards are `100 Kills`, `200 Takedowns`, `Triple`,
  `TUFF`, `Flawless`, `Mallet`, `Knife`, `Healing Horn`, `Healing Banner`, `Pacifist`,
  `Hybrid`, `Score`.
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
- Rivalries (nemesis/ally/`/versus`/pair awards) are ROSTER-based: the vision parser
  reads every scoreboard row and now returns `team_names`/`enemy_names` alongside the
  stat arrays it already extracted; the finalise path stores them in `submission_rosters`
  (side='team'=ally / 'enemy'=opponent). `utils.roster` matches names to registered
  players and derives exact rivalries; `utils.rivalry_service` picks it over the legacy
  time-window `utils.rivalries` whenever a roster exists. Route new rivalry reads through
  `rivalry_service`, never the pure engine, so the fallback stays automatic. Names are the
  ONE field where OCR noise matters, so the matcher folds look-alikes (1/l, 0/O, 5/S) and
  fuzzy-matches; an unregistered name stays anonymous and is skipped (never a false rival).
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
- Butler chat context (`player_stats_ctx`) must stay BOUNDED. The model runs at
  `reasoning_effort='none'` with a small budget; a heavy player's data (e.g. 77
  boards, 40 weapons) once ballooned the prompt to ~8k chars and the model deflected
  ("I don't have your data") even though everything was present. Any per-weapon or
  per-board list injected here must be CAPPED (standings top-20) and/or GATED to the
  relevant question (per-weapon TDs → TD questions; per-weapon ratings → rating
  questions). Match a player's board rows on EITHER discord_id OR name (a stale
  non-blank id or a name variant will otherwise miss their own boards).

## Environment variables

`DISCORD_TOKEN` (required) · `DATABASE_URL` (Postgres; bot runs without it but
most features need it) · `OPENAI_API_KEY` (Butler chat, GPT-5.6 Luna; optional,
quips fall back) · `GOOGLE_AI_API_KEY` (vision; optional, manual entry fallback) ·
`KOFI_TOKEN` (webhook verification; optional) · `EXPORT_TOKEN` (bearer token for
the read-only `GET /export/submissions` cursor export; endpoint off when unset) ·
`ANALYTICS_TOKEN` (URL token gating the private `/traffic` dashboard AND the consolidated
`/dev` developer dashboard — AI usage/cost, traffic, bot health — plus their `/data`
endpoints; all off when unset. The `_traffic_logger` middleware still counts page views
into `page_views` and AI calls are still logged into `ai_usage` regardless) · `ANALYTICS_SALT`
(optional; salts the daily-rotating visitor hash, falls back to `LAB_ID_SALT` then a constant) ·
`LETHALITY_STASH_CHANNEL_ID` (channel that hosts the blurb lethality thumbnails;
falls back to a hardcoded default) · `PORT` (healthcheck, default 8080) ·
`LAB_BASE_URL` (public base URL of the bot's web server, e.g. the Railway domain;
needed for the Stats Lab / Hall of Fame links — the `/correlate` "Open in Stats Lab"
button and `/setup_hall_of_fame` only build a link when this is set). `LAB_SECRET`
is retired from the serving path: the web pages (`/lab`, `/hof`) are PUBLIC now
(read-only community stats already visible on the boards), one model for both. The
signed-token module (`utils/lab_auth.py`) and its tests are kept in case a surface
ever needs re-gating, but nothing live verifies a token.

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

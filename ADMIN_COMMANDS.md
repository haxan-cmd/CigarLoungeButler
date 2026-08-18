# 🗂️ Cigar Lounge Butler — Admin & Mod Commands

`[Admin]` = server administrator · `[Mod]` = mod role · everything else below is usable by anyone.

**Renamed this update (Source-server style):** `/stats`→`/playerstats` · `/my_season`→`/season` · `/rank`→`/top` · `/season_standings`→`/standings` · `/title_standings`→`/titles` · `/activity`→`/serverstats` · `/commands`→`/help` · `/butlers_report`→`/report` · `/refresh_card`→`/refreshcard`. Old names no longer work — use `/help` to see the current list.

**Also new:** `/explore` (any metric grouped any way, filtered by feat or season, as a chart). Player titles are now the lounge ladder: Lounger → Insider → Regular → Made Man → High Roller → Kingpin → Legend, by total bounties completed.

**Currently unregistered** (code kept, uncomment the `@app_commands.command` decorator to re-enable — these sit out to stay under Discord's 100-command guild cap): `/statslab`, `/statslab_panel`, `/statslab_usage` (Lab is public now, linked from `/setup_lounge`), `/refresh_manual` (butlers-manual retired), `/refresh_monthly` · `/season_reset` · `/force_finalize_season` (Monthly Report + forum Hall of Fame retired), and the one-time board builders `/setup_titles_board` · `/setup_score_board` · `/setup_healing_banner_board` · `/setup_hybrid_board` · `/setup_kills_boards` · `/create_missing_boards` · `/remove_map_kills_boards`.

---

## Season & Bounty
- `/bounty_create` **[Mod]** — Create a new monthly bounty (also opens the season).
- `/bounty_end` **[Mod]** — End the active bounty (24h grace); finalizes the season + snapshots the month to the Hall of Fame.
- `/bounty_post_progress` **[Admin]** — Post/repost the live TOP HUNTERS board.
- `/bounty_add_card` **[Mod]** — Manually create a bounty forum card for a player.
- `/bounty_refresh_card` **[Mod]** — Refresh a player's bounty forum card.
- `/bounty_set_bonus` **[Mod]** — Mark a player's bounty special challenge complete.
- `/bounty_credit` **[Mod]** — Add or remove a player's bounty weapon hits.
- `/bounty_complete` **[Mod]** — Manually mark a player as having completed a bounty.
- `/season_start` **[Mod]** — Open a season now for the current bounty.
- `/season_set_start` **[Mod]** — Backdate the current season's start date.
- `/season_reset` **[Admin]** — Snapshot this month's Lethality/Warlord to the Hall of Fame (non-destructive).
- `/roll_features` **[Mod]** — Roll this season's Special Features.
- `/force_finalize_season` **[Mod]** — Refresh the current season's Hall of Fame data. (With `HALL_OF_FAME_WEB` on, this no longer posts a forum thread — the champions render live on the public `/hof` page.)
- `/setup_lounge` **[Mod]** — Pin one card in the current channel with BOTH public web links: 🏆 Hall of Fame (`<domain>/hof`, season champions) and 📊 Stats Lab (`<domain>/lab`, run explorer). Two separate pages that share a "Cigar Lounge" top nav; needs `LAB_BASE_URL` set. (Boards, submissions, reactions stay native Discord — only the read-only archive/analytics surfaces live on the web.)

## Leaderboards & Boards
**Which render command? →** `/rebuild_boards` is THE one: it recomputes a board's entries from full submission history AND repaints it correctly (maps, weapons, kills sections, ratings). Reach for it whenever a board is wrong or a render change needs to land. `/refresh_all` only reframes threads whose *structure* changed — it skips threads that already look right, so it will NOT apply a content-only change (e.g. a new embed section). `/refresh` repaints a single board in place.

- `/refresh` **[Mod]** — Repaint the board in this thread (or by name) from current data.
- `/refresh_all` **[Mod]** — Reframe every thread whose structure drifted from the template (skips unchanged ones). Not for content-only changes — use `/rebuild_boards` for those.
- `/refresh_monthly` **[Admin]** — Rebuild all Monthly Report boards + pinned index.
- `/setup` **[Mod]** — Set up a bot-owned leaderboard in this thread.
- `/setup_score_board` **[Mod]** — Create the Score board (highest match points, one row/player, top-50) in the feats forum.
- `/remove_map_kills_boards` **[Mod]** — Remove the old SEPARATE map Kills boards. Map kills now render as a section INSIDE each map embed (top 10 by kills, VIP included), so no separate board is needed. Deletes the stray board embeds/records only — never the map thread. Run `/rebuild_boards` afterwards to repaint the map boards with the inline Kills section.
- `/backfill_feat_boards` also seeds the Score board from submission history.
- `/create_missing_boards` **[Admin]** — Create board threads for primary weapons that lack one.
- `/rebuild_boards` **[Mod]** — THE rebuild. Recompute a board (or all, if no name) from full submission history AND repaint it correctly — maps, weapons, kills sections, ratings. Force-renders, so it applies content changes `/refresh_all` skips. (Retired: `/refresh_maps`, `/migrate_boards`, `/reframe_thread` — all covered by this + `/refresh_all`.)
- `/cleanup_boards` **[Mod]** — Remove junk board entries with missing map/weapon names.
- `/add_board_score` **[Mod]** — Manually add/restore a single board entry.
- `/remove_board_score` **[Mod]** — Remove a player's entry from a board.
- `/dedupe_board` **[Mod]** — Remove exact duplicate entries from an unlimited board.
- `/backfill_feat_boards` **[Mod]** — Add missing 100 Kills / 200 Takedowns entries from submissions.
- `/board_audit` **[Mod]** — Read-only: list submission scores missing from boards.
- `/repair_marks` **[Mod]** — Backfill missing High Score marks from board entries.
- `/backfill_hundred_handed` **[Mod]** — Seed Hundred-Handed from submissions + legacy list.
- `/consolidate_hundred_handed` **[Mod]** — Merge duplicate Hundred-Handed identities per player.
- `/ledger_refresh` **[Mod]** — Rebuild the ledger entrance + all forum indexes. (Indexes also auto-refresh daily and whenever a new board thread is created, so they no longer drift between manual runs.)
- `/refresh_entrance` **[Mod]** — Refresh just the ledger entrance links.
- `/clear_forum_tags` **[Admin]** — Remove the class/feat filter tags from the board forums (weapon indexes list alphabetically, so class tags were dropped). Needs Manage Channels.
- `/alltime_refresh` **[Admin]** — Refresh the all-time archive (legacy).

## Registry Cards
- `/create_card` **[Admin]** — Create or refresh a specific player's card.
- `/bulk_refresh_cards` **[Admin]** — Refresh all player cards in place.
- `/purge_blank_cards` **[Admin]** — Delete cards for players with no marks (cleanup for blank cards).
- `/update_index` **[Admin]** — Rebuild a forum index thread.
- `/import_single` **[Admin]** — Import one player's legacy registry data by name.
- `/import_registry` **[Admin]** — Import old registry cards into butlers-archive.

## Marks & Data Fixes
- `/award_marks` **[Mod]** — Manually award marks on a weapon to a player.
- `/set_feat_count` **[Mod]** — Set a player's 100 Kills / 200 Takedowns / Triple count.
- `/remove_submission` **[Admin]** — Remove a fake/erroneous submission and roll back all tables.
- `/purge_low_td_runs` **[Admin]** — Remove ALL of one player's runs under the takedown minimum (`config.MIN_SUBMISSION_TAKEDOWNS`, default 100; Pacifist 0-kill runs exempt), strip them from boards, rebuild affected boards, and refresh their card. Marks recompute from remaining runs; bounty progress is not auto-adjusted. (New submissions under the minimum are now blocked at submit time.)
- `/backfill_players` **[Admin]** — Create a `players` row for anyone who submitted but has no row (fixes Butler "unregistered" / missing stats).

## Player Commands (everyone)
- `/help` — List the commands you can use, grouped by what they do.
- `/playerstats` — Your all-time profile: title, weapon ranks and marks.
- `/season` — Your season GP: rank, where each point came from, and how far off the next scoring place.
- `/serverstats` — Server activity dashboard over a window (24h / 7d / 30d): totals, top players and weapons, as a chart.
- `/explore` — Any metric (runs, lethality, kill share, warlord, totals, best run, lobby difficulty, valor marks) grouped any way (weapon, player, map, subclass, faction, side, week/month trend, feat), filtered by feat, season, or side, and optionally scoped to one `player` (their own weapon distribution, maps, etc.) — as a chart.
- `/top` — Show the top 10 for a weapon or class board.
- `/standings` — Live standings for the current season.
- `/titles` — Board count + average placement for the all-time titles.
- `/report` — Summon the Butler Monthly report.
- `/refreshcard` — Refresh your own registry card.
- `/versus` — Your head-to-head history with another player: shared lobbies, teammate/opponent split, comparative averages (no win/loss).
- `/next` — Your nearest goal on each track: next weapon rank, mastery, and Hundred-Handed.
- `/wrapped` — Your season recap (signature weapon, best game, streaks). `/superlatives` — the season's tongue-in-cheek awards.
- `/rules` — Show the challenge rules.
- `/aliases` — Who has the most in-game names (the witness-protection board).

## Butler Monthly & Titles (mod)
- `/refresh_titles` **[Mod]** — Recalculate Butler Monthly titles + reassign roles.
- `/title_guide` **[Admin]** — Post the Butler Monthly title guide.

## Rules & Announcements
- `/rules` — Show the challenge rules.
- `/post_challenge_rules` **[Admin]** — Post the challenge rules to the rules channel.
- `/update_challenge_rules` **[Admin]** — Update the rules channel with current info.
- `/patch_notes` **[Admin]** — Post patch notes to the current channel.
- `/force_poll` **[Admin]** — Post a dry Butler question in main now.

## Ko-fi
- `/post_kofi_dashboard` **[Admin]** — Post the Ko-fi support dashboard.
- `/refresh_kofi` **[Admin]** — Recompute the Ko-fi total + update the dashboard.
- `/add_kofi` **[Admin]** — Manually record a Ko-fi donation the webhook missed.

## Maintenance & Backups
- `/backup_now` **[Mod]** — Force an immediate DB backup to the nerve centre.
- `/purge_forum` **[Admin]** — Delete ALL threads in a forum channel. ⚠️ Irreversible — run with `confirm: False` first for a dry-run count.
- `/seed_players` **[Admin]** — Seed the Players table from a Discord role.
- `/populate_butlers_archive` **[Mod]** — Pre-populate the ButlersArchive sheet.

## Observability
- `/logs` **[Mod]** — Review the persistent event log. Filter by category (Errors / Fabrication flags / Deploys / Butler Q&A / Vision failures) and a lookback window (default 7 days). Survives Railway's log truncation; a weekly rollup is also auto-posted to the nerve centre.
- `/health` **[Mod]** — Butler self-check across subsystems; posts to the nerve centre only when something is wrong.
- `/statslab_usage` **[Mod]** — How often the web Stats Lab deep-link is opened.

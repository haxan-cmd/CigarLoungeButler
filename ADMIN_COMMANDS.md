# 🗂️ Cigar Lounge Butler — Admin & Mod Commands

`[Admin]` = server administrator · `[Mod]` = mod role · everything else below is usable by anyone.

**Changed this update:** `/season_reset` is now **non-destructive** (snapshots the month's Lethality/Warlord to the Hall of Fame, boards stay permanent) · **new** `/refresh_monthly` and `/purge_forum` · removed `/force_snapshot` and `/purge_archive`.

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
- `/force_finalize_season` **[Mod]** — Post/refresh the current season's Hall of Fame entry.

## Leaderboards & Boards
- `/refresh` **[Mod]** — Refresh the board in this thread (or by name).
- `/refresh_all` **[Mod]** — Refresh every leaderboard at once.
- `/refresh_monthly` **[Admin]** — Rebuild all Monthly Report boards + pinned index.
- `/setup` **[Mod]** — Set up a bot-owned leaderboard in this thread.
- `/create_missing_boards` **[Admin]** — Create board threads for primary weapons that lack one.
- `/rebuild_boards` **[Mod]** — Rebuild weapon + map boards from full submission history.
- `/cleanup_boards` **[Mod]** — Remove junk board entries with missing map/weapon names.
- `/add_board_score` **[Mod]** — Manually add/restore a single board entry.
- `/remove_board_score` **[Mod]** — Remove a player's entry from a board.
- `/dedupe_board` **[Mod]** — Remove exact duplicate entries from an unlimited board.
- `/backfill_feat_boards` **[Mod]** — Add missing 100 Kills / 200 Takedowns entries from submissions.
- `/board_audit` **[Mod]** — Read-only: list submission scores missing from boards.
- `/repair_marks` **[Mod]** — Backfill missing High Score marks from board entries.
- `/backfill_hundred_handed` **[Mod]** — Seed Hundred-Handed from submissions + legacy list.
- `/consolidate_hundred_handed` **[Mod]** — Merge duplicate Hundred-Handed identities per player.
- `/ledger_refresh` **[Mod]** — Rebuild the ledger entrance + all forum indexes.
- `/refresh_entrance` **[Mod]** — Refresh just the ledger entrance links.
- `/alltime_refresh` **[Admin]** — Refresh the all-time archive (legacy).

## Registry Cards
- `/refresh_card` — Refresh your own registry card.
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

## Butler Monthly, Reports & Titles
- `/butlers_report` — Summon the Butler Monthly report.
- `/season_standings` — Live standings for the current season.
- `/title_standings` — Board count + average placement for the all-time titles.
- `/stats` — Show a player's title standings and weapon ranks.
- `/rank` — Show the top 10 for a weapon or class board.
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

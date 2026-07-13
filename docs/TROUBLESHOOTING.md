# Troubleshooting

Symptom to fix, grouped by area. Full command list: [ADMIN_COMMANDS.md](../ADMIN_COMMANDS.md).

## Boards & leaderboards

| Symptom | Likely cause | Fix |
|---|---|---|
| A board shows wrong/stale entries | Missed render after an edit/removal | `/refresh` in the board's thread (or `/refresh name:<board>`) |
| Every board needs a refresh | Bulk change (reset, migration) | `/refresh_all` (mod). Slow and rate-limited on purpose. |
| A score shouldn't be there (bad add, wrong player) | Manual add gone wrong | `/remove_board_score board:<name> player:<name>`. Add `message_link:` to remove only ONE entry when the player has several (TUFF, 100 Kills, etc.) |
| A legit-but-unfair run is polluting boards | Lopsided lobby, farm game | `/unlist_submission message_link:<scorecard link>`. Takes the run off ALL boards/records, keeps marks + bounty. Run again to re-list. |
| A run is outright fake/wrong | Fraud or bad entry | `/remove_submission message_link:<link>` for a full rollback (record, boards, bounty, card) |
| Feat boards missing old runs | Entries predate the board | `/backfill_feat_boards`, then `/refresh` each board |
| Board index thread looks wrong | Rebuild raced or crashed | `/update_index` (registry forums). Board-forum indexes self-heal on the next submission. |
| "None - Agatha"-style junk boards | Old bug, junk rows | Junk rows are blocked at insert now; `delete_junk_leaderboard_rows` in db.py cleans up leftovers |

## Player cards & stats

| Symptom | Fix |
|---|---|
| A player's card is stale | `/refresh_card` (player) or `/create_card player:<name>` (mod) |
| ALL cards need a refresh (formula change) | `/bulk_refresh_cards`, slow by design |
| Marks look wrong after mod changes | `/award_marks` to adjust; card refresh happens automatically |
| Feat counts undercounted (legacy) | `/set_feat_count` sets a manual floor; auto-detection continues on top |
| Player renamed and stats split | Names are matched via `players.igns` and `LEADERBOARD_NAME_OVERRIDES` in config.py |

## Bounty

| Symptom | Fix |
|---|---|
| Player's bounty card wrong | `/bounty_refresh_card` |
| Progress miscounted | `/bounty_credit` (add or remove hits) |
| Bonus not registering | `/bounty_set_bonus` |
| Completion missed | `/bounty_complete` |
| Top Hunters board missing/stale | `/bounty_post_progress` |

## Titles & season

| Symptom | Fix |
|---|---|
| Title roles on the wrong people | `/refresh_titles` |
| Season board stale | `/refresh_report` |
| Season needs finalizing | `/force_finalize_season` |

## The bot itself

| Symptom | Where to look |
|---|---|
| Bot offline / silent | Railway logs. The healthcheck returns 503 when the gateway dies, so Railway should auto-restart. If it's crash-looping on login with 429s, it backs off 15 min on purpose; don't spam redeploys. |
| Slash command missing an option | Commands sync on the FIRST ready after deploy. Check logs for `✅ Synced N slash commands`, then Ctrl+R in Discord (client caches definitions). |
| Errors happening somewhere | The nerve-centre channel gets ⚠️ alerts (deduped, 10-min cooldown per error) plus an hourly digest. |
| Vision misreading scorecards | `[VISION]` lines in Railway logs show what Gemini returned. Corrections players make are logged to the nerve centre (`✏️ Vision corrections`). |
| Ko-fi donation didn't record | Check the webhook URL is `https://<railway-domain>/kofi` and `KOFI_TOKEN` matches. Backstop: `/add_kofi` records it manually, `/refresh_kofi` recomputes the dashboard. |
| Database emergency | Daily gzip backups are posted in the nerve centre (`/backup_now` for a fresh one). They contain every table as JSON. |

## Development

- Tests: `pytest -q` (pure logic only: parsing, ranks, config integrity; no Discord/DB needed).
- Local run: copy `.env` with `DISCORD_TOKEN` (plus optionally `DATABASE_URL` and AI keys). Without `DATABASE_URL` the bot boots but most features are inert.
- The `[DB] schema ensured.` / `[DB] indexes ensured.` boot lines are where all schema migrations happen. If a new column is missing, look at `_SCHEMA_STATEMENTS` in `utils/db.py`.

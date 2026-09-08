# Cigar Lounge counting: handoff to Bald Female

Base: CigarLoungeButler commit `1e69454f3eb4d7166331fc94ae63d7648ae95670`.
This is a native discord.py cog using Butler's existing PostgreSQL pool and moderator policy.
It is disabled by default. No Discord token, credentials, production database or player snapshot is bundled.
The patch has not been deployed to Butler or pushed to GitHub. Main auto-deploys to Railway: review on a branch first.

## Agreed production settings

```dotenv
COUNTING_REFEREE_ENABLED=true
COUNTING_GAME_CHANNEL_ID=1510068548775579868
COUNTING_PENALTY_ROLE_ID=1510070252044554390
COUNTING_BEAN_ROLE_ID=1517244986251411586
```

Guild: `1324379304544567356`. Counting only runs in the configured channel, currently 🔢｜00.
Keep Butler's existing DISCORD_TOKEN and DATABASE_URL. Do not copy Sommelier's token.
Enable Server Members and Message Content in Developer Portal. Channel permissions:
View Channel, Send Messages, Read Message History, Add Reactions, Embed Links.
Butler needs Manage Roles and its top role above both Idiot and Bean Counter.
`/count check` verifies the configuration. Administrator is not required for the bot.

## Features

- Alternate successful players; start at 1. Incorrect results or consecutive turns reset to 1.
- Idiot role lasts 72 hours. Repeat failures renew the deadline. Persistent worker retries role operations.
- Arithmetic always enabled: +, -, *, /, //, %, parentheses, powers ** or ^, × and ÷. Exact decimal arithmetic is supported when the result is a whole number. Bounded parsing uses no eval, names or function calls.
- Invalid math, division by zero and invisible characters warn without advancing, resetting or penalizing. Ordinary spaces in expressions are allowed. Chatter is ignored.
- Editing/deleting an accepted number preserves the saved count and gives the next mistaken attempt one warning. A correct attempt consumes protection too. Previous runs cannot renew protection after a reset/seed.
- `/count user [member]`: two-column public card, local correct rate, counts, mistakes, net score, rank, highest count, last activity, Idiot penalties and server progress. No global stats or game saves. Warnings excluded; ties share rank. Idiot penalties include renewals recorded by this referee, not unrelated manual grants.
- Bean Counter: 50 personal attempts (correct + mistakes), at least 98.5% accuracy. Checked only on `/count user`. At 50+ attempts falling below the rate removes it; below 50, existing roles remain until enough local history exists. Role emoji/icon appears on holders' cards. New awards/losses get a fixed announcement with the card, once per change, with no pings. No AI calls are used by this feature.
- `/count reset-user member reason`: moderator-only personal reset, removes Bean Counter, preserves server progress, record, total counts, turn order, accepted message history and current penalty deadlines. Audit stores previous stats and reason.
- Discord cannot expose blocked-bot status. No exemption for blocking is implemented.

## Commands and permissions

| Command | Access |
|---|---|
| `/count user`, `/count status`, `/count board` | Cigar Lounge members |
| `/count check`, `/count seed`, `/count pause`, `/count forgive`, `/count penalties`, `/count reset-user` | Butler's existing is_mod policy: configured mod role, administrator or manager |

Stats/status cards are public; board and moderator replies are private. Reset access is checked server-side, even if Discord shows the command to a normal member. Butler's moderator policy is deliberately reused rather than changing permissions on its other features.

## Apply and test

1. Back up Butler's PostgreSQL database. Apply the patch on a clean review branch using `git apply --check` then `git apply`. For a newer main that conflicts, merge the changes deliberately; never overwrite newer files from changed-files blindly.
2. Keep COUNTING_REFEREE_ENABLED=false during code review. The new additive schema is in utils/db.py `_COUNTING_SCHEMA`; its reference is docs/counting-schema.sql and root schema.sql. Normal startup applies it; do not replay the full root schema on an existing database.
3. Test in an isolated channel with test roles if desired. Original test IDs: channel 1546965748604477510, idiot-test 1546965379207798825. Use a separate Bean Counter test role (or COUNTING_BEAN_ROLE_ID=0) to avoid changing production awards.
4. Run tests with Python 3.12: `python -m pytest -q`. For database tests set TEST_DATABASE_URL to a disposable PostgreSQL 16 instance. Each test creates/drops its own random schema. The included GitHub workflow runs counting tests with a disposable service. Never use a production database for tests.
5. Live acceptance: `/count check`, seed zero, alternate 1 and 2; verify fail/forgive; test deletion, invisible space, expressions, user cards, Bean award/loss, moderator reset and a rejected ordinary-member reset. Restart and verify current count plus role deadlines.

## Production handover with Sommelier stats and timers

Sommelier is currently running separately on the owner's PC. Do not leave it and Butler enforcing the same channel.
Do not hard-code the current number from this document; people are still counting.

1. Arrange a short no-posting window. Run Sommelier `/count pause`. Capture `/count status` (current and last player).
2. On the owner's PC, export its paused database using the included script:
   `python tools/export_sommelier_counting.py PATH_TO_SOMMELIER/data/lounge.sqlite3 counting-cutover.json`
   The script reads only, rejects an unpaused game and refuses to overwrite a file. Transfer that fresh JSON privately to Bald Female. It contains counting stats/IDs and active deadlines, not tokens or messages. Keep a full SQLite backup separately.
3. Stop Sommelier after export. Disable/remove the old third-party counting bot too. Stop Butler during import; use one instance for cutover.
4. With the production variables above, import into a never-seeded Butler referee:
   `python tools/import_sommelier_counting.py counting-cutover.json`
   This previews without writing. Then run the same command with `--apply` against Butler's DATABASE_URL.
   The importer replaces only the target referee's counting users and the corresponding legacy counting statistics. This intentionally carries over Sommelier's user resets instead of resurrecting old third-party scores. It preserves other Butler features. It imports active penalty deadlines, including any remaining idiot-test deadlines, without extending them; role operations resume on startup.
   Import is atomic and allowed only once, before the target referee is ever seeded. If production was already seeded during testing, stop and review a database migration rather than deleting rows to bypass the guard.
5. Enable COUNTING_REFEREE_ENABLED and start Butler. Run `/count check`. It remains paused until `/count seed current:NUMBER last_counter:@LAST_PLAYER` using the fresh exported number (for zero omit last_counter). Seed never clears imported scores or timers.
6. Reopen counting and verify one alternating count, `/count user`, record, and `/count penalties`. Keep Sommelier stopped. Store the snapshot securely as a cutover backup.

Import includes personal stats and server totals, not old message history, so deletion detection starts with Butler's newly accepted messages. Existing legacy-only data cannot reconstruct unknown last-active timestamps or historical Idiot assignments: those display as unknown/zero until recorded. Without the Sommelier import, initialization copies Butler's existing lifetime counting totals once; this is an alternative, not a way to merge both histories.

## Operations and rollback

PostgreSQL row locks serialize counts, Bean checks and resets. Timed penalties use bounded Discord operations and row locks; retries preserve deadlines. Avoid multiple active gateway instances even though database writes are deduplicated. Discord changes and database commits cannot be one distributed transaction; inspect an error after a role change before retrying a reset.

Recovery replays at most 1000 newer messages; invalid downtime attempts are skipped without retroactive penalties. A long outage pauses enforcement for review. Missing history cannot be reconstructed. Penalty removal waits for the bot to reconnect.

Butler's full database backups include the new tables automatically. Rollback: pause/stop Butler first, export/record new progress and outstanding penalties, then explicitly reconcile before re-enabling Sommelier or the old bot. Never restore a stale snapshot blindly or run both role workers. Turning the feature flag off also stops its penalty worker; outstanding deadlines still need an active owner.

The standalone Sommelier core, math, stats and reset were exercised in Discord. Bean Counter badge rendering was verified; natural threshold award/loss announcements were still awaiting the owner's live counting test at packaging time. The integrated Butler code passes automated tests but still needs its own Discord acceptance test.

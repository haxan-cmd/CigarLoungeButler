import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1aT7MbBa3qZxx9ZyaFvlgmbjvCDe2kkQMt5Qsnq_6lzY"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)

submissions_ws = sh.worksheet("Submissions")
players_ws = sh.worksheet("Players")
leaderboard_ws = sh.worksheet("LeaderboardData")

# ── Step 1: Build Players sheet from Submissions ──────────────────────────────
print("Step 1: Reading Submissions...")
sub_rows = submissions_ws.get_all_values()
sub_headers = sub_rows[0]
name_col = sub_headers.index("Discord Name")
id_col   = sub_headers.index("Discord ID")

# Keyed by Discord ID — later rows overwrite earlier ones (most recent name wins)
players = {}  # discord_id -> discord_name
for row in sub_rows[1:]:
    if len(row) <= max(name_col, id_col):
        continue
    disc_id   = row[id_col].strip()
    disc_name = row[name_col].strip()
    if disc_id and disc_name:
        players[disc_id] = disc_name

print(f"  Found {len(players)} unique players.")

# Write to Players sheet (clear existing data rows first, keep header)
print("  Writing Players sheet...")
existing = players_ws.get_all_values()
if len(existing) > 1:
    players_ws.delete_rows(2, len(existing))

player_rows = [[disc_id, disc_name, ""] for disc_id, disc_name in sorted(players.items(), key=lambda x: x[1].lower())]
if player_rows:
    players_ws.update(f"A2:C{1 + len(player_rows)}", player_rows)

print(f"  ✅ Players sheet populated with {len(player_rows)} players.")

# ── Step 2: Build name -> ID lookup from Players ──────────────────────────────
# Also build a lowercase version for case-insensitive matching
name_to_id = {name.lower(): disc_id for disc_id, name in players.items()}

# ── Step 3: Backfill LeaderboardData ─────────────────────────────────────────
print("\nStep 2: Backfilling LeaderboardData...")
lb_rows = leaderboard_ws.get_all_values()

updates = []
unmatched = []

for i, row in enumerate(lb_rows[1:], start=2):
    if len(row) < 2:
        continue
    player_name = row[1].strip()
    discord_id  = row[2].strip() if len(row) > 2 else ""

    if discord_id:
        continue  # already has an ID, skip

    match = name_to_id.get(player_name.lower())
    if match:
        updates.append({
            "range": f"C{i}",
            "values": [[match]]
        })
    else:
        unmatched.append((i, player_name))

if updates:
    print(f"  Writing {len(updates)} Discord IDs...")
    leaderboard_ws.batch_update(updates)
    print("  ✅ Done.")
else:
    print("  Nothing to update.")

print(f"\n✅ Matched: {len(updates)}")
print(f"❌ Unmatched ({len(unmatched)}) — these need manual review:")
for row_num, name in unmatched:
    print(f"  Row {row_num}: {name}")
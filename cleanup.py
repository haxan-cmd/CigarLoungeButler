import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = '1aT7MbBa3qZxx9ZyaFvlgmbjvCDe2kkQMt5Qsnq_6lzY'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)
ws = sheet.worksheet('LeaderboardData')

# Boards with top 10 limit
TOP_10_BOARDS = [
    "Mallet", "Knife",
]
# These are weapon/map boards — identified by not being in any named feat list
FEAT_BOARDS_UNLIMITED_PERSONAL_BEST = ["Flawless", "Healing Horn"]
FEAT_BOARDS_UNLIMITED_ALL = ["100 Kills", "200 Takedowns"]

all_values = ws.get_all_values()
header = all_values[0]
rows = all_values[1:]  # data rows, 0-indexed here = sheet row index + 2

print(f"Total data rows: {len(rows)}")

# Group rows by leaderboard name
from collections import defaultdict
boards = defaultdict(list)
for i, row in enumerate(rows):
    lb_name = row[0]
    player = row[1]
    score = int(row[2]) if row[2] else 0
    link = row[3] if len(row) > 3 else ''
    sheet_row = i + 2  # 1-based, +1 for header
    boards[lb_name].append({
        'player': player,
        'score': score,
        'link': link,
        'sheet_row': sheet_row
    })

rows_to_delete = set()

for lb_name, entries in boards.items():
    is_unlimited_all = lb_name in FEAT_BOARDS_UNLIMITED_ALL

    if is_unlimited_all:
        # No deduplication needed — all entries are valid
        print(f"[SKIP] {lb_name} — unlimited all entries, no cleanup needed")
        continue

    # For all other boards: keep personal best per player
    best_per_player = {}
    for e in entries:
        player = e['player']
        if player not in best_per_player or e['score'] > best_per_player[player]['score']:
            best_per_player[player] = e

    # Mark duplicates for deletion
    for e in entries:
        if e['sheet_row'] != best_per_player[e['player']]['sheet_row']:
            rows_to_delete.add(e['sheet_row'])
            print(f"[DUPLICATE] {lb_name} | {e['player']} score {e['score']} at row {e['sheet_row']} (keeping row {best_per_player[e['player']]['sheet_row']} with score {best_per_player[e['player']]['score']})")

    # For top 10 boards, trim to top 10 after deduplication
    is_top_10 = lb_name in TOP_10_BOARDS or lb_name not in FEAT_BOARDS_UNLIMITED_PERSONAL_BEST and lb_name not in FEAT_BOARDS_UNLIMITED_ALL
    if is_top_10:
        survivors = [e for e in entries if e['sheet_row'] not in rows_to_delete]
        survivors_sorted = sorted(survivors, key=lambda x: x['score'], reverse=True)
        if len(survivors_sorted) > 10:
            for e in survivors_sorted[10:]:
                rows_to_delete.add(e['sheet_row'])
                print(f"[TRIM TOP10] {lb_name} | {e['player']} score {e['score']} at row {e['sheet_row']} — outside top 10")

print(f"\nTotal rows to delete: {len(rows_to_delete)}")

if rows_to_delete:
    # Delete rows in reverse order so indices don't shift
    for row_num in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(row_num)
        print(f"Deleted row {row_num}")
    print("Cleanup complete!")
else:
    print("No cleanup needed.")

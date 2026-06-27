# Google Sheets connection, cache, and worksheet objects.
# Everything that touches the spreadsheet goes through here so other modules
# don't have to care about auth, retries, or rate limits.
import os
import json
import time
import asyncio
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()
import config


def gspread_retry(func, *args, retries=5, **kwargs):
    # Sheets will 429 us hard if the bot restarts repeatedly or hits burst limits.
    # Exponential backoff starting at 10s gives it room to breathe.
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            err_str = str(e)
            if ('429' in err_str or '503' in err_str) and attempt < retries - 1:
                wait = 10 * (2 ** attempt)
                print(f"Sheets error ({err_str[:10]}), retrying in {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
            else:
                raise


class SheetCache:
    # Simple in-memory TTL cache so we're not hammering the Sheets API on
    # every command. Writes should call invalidate() so the next read is fresh.
    def __init__(self, ttl=60):
        self._ttl = ttl
        self._cache = {}  # ws_name -> {'data': [...], 'ts': float}

    def get(self, ws, fetch_fn):
        name = ws.title
        entry = self._cache.get(name)
        now = time.time()
        if entry and (now - entry['ts']) < self._ttl:
            return entry['data']
        data = fetch_fn()
        self._cache[name] = {'data': data, 'ts': now}
        return data

    def invalidate(self, ws):
        self._cache.pop(ws.title, None)

    def invalidate_all(self):
        self._cache.clear()


_sheet_cache = SheetCache(ttl=60)


# Local .env has GOOGLE_CREDENTIALS=credentials.json (a file path).
# Railway has the actual JSON content as the env var value.
# Handle both so local dev and prod work without changing anything.
google_creds_raw = os.getenv('GOOGLE_CREDENTIALS')
if google_creds_raw and google_creds_raw.strip().endswith('.json'):
    with open(google_creds_raw.strip()) as _f:
        _creds_info = json.load(_f)
else:
    _creds_info = json.loads(google_creds_raw)
_creds = Credentials.from_service_account_info(_creds_info, scopes=config.SCOPES)
gc    = gspread.authorize(_creds)
sheet = gspread_retry(gc.open_by_key, config.SHEET_ID)


def _init_worksheet(name):
    # Same backoff logic as gspread_retry but for individual tab opens —
    # startup hits the quota fast when opening 8+ worksheets in quick succession.
    for attempt in range(5):
        try:
            return sheet.worksheet(name)
        except Exception as e:
            if attempt < 4:
                wait = 5 * (2 ** attempt)
                print(f"Sheet '{name}' init error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


submissions_ws      = _init_worksheet('Submissions')
players_ws          = _init_worksheet('Players')
leaderboards_ws     = _init_worksheet('Leaderboards')
leaderboard_data_ws = _init_worksheet('LeaderboardData')

try:
    special_ops_ws = sheet.worksheet('SpecialOps')
except Exception:
    try:
        special_ops_ws = sheet.add_worksheet(title='SpecialOps', rows=500, cols=3)
        special_ops_ws.append_row(['DiscordID', 'PlayerName', 'Achievement'])
    except Exception as e:
        print(f"SpecialOps sheet init error: {e}")
        special_ops_ws = None

try:
    registry_ws = sheet.worksheet('RegistryCards')
except gspread.exceptions.WorksheetNotFound:
    registry_ws = sheet.add_worksheet(title='RegistryCards', rows=500, cols=5)
    registry_ws.append_row(['DiscordID', 'PlayerName', 'ForumThreadID'])

try:
    bounty_players_ws = sheet.worksheet('BountyPlayers')
except gspread.exceptions.WorksheetNotFound:
    bounty_players_ws = sheet.add_worksheet(title='BountyPlayers', rows=500, cols=10)
    bounty_players_ws.append_row(['BountyTitle', 'DiscordID', 'PlayerName', 'ForumPostID', 'Progress'])

try:
    bounty_ws = sheet.worksheet('Bounty')
except gspread.exceptions.WorksheetNotFound:
    bounty_ws = sheet.add_worksheet(title='Bounty', rows=100, cols=20)
    bounty_ws.append_row(['Title', 'ChannelID', 'MessageID', 'ThemeEmoji', 'Weapons',
                          'SpecialChallenge', 'SpecialDone', 'Completions', 'Active', 'RoleID',
                          'ForumChannelID', 'CompletionsMsgID', 'BonusMsgID', 'ProgressMsgID', 'StartDate'])

try:
    snapshots_ws = sheet.worksheet('Snapshots')
except Exception:
    try:
        snapshots_ws = sheet.add_worksheet(title='Snapshots', rows=1000, cols=20)
        snapshots_ws.append_row([
            'Date', 'TotalSubmissions', 'WeeklySubmissions', 'ActivePlayers',
            'TopWeapon1', 'TopWeapon2', 'TopWeapon3', 'TopWeapon4', 'TopWeapon5',
            'TopMap1', 'TopMap2', 'TopMap3', 'AvgTD', 'AvgKills',
            'HighScoresSet', 'BoardsUpdated', 'WeaponTrend1', 'WeaponTrend2', 'WeaponTrend3',
        ])
    except Exception as e:
        print(f"Snapshots sheet init error: {e}")
        snapshots_ws = None

try:
    index_posts_ws = sheet.worksheet('IndexPosts')
except Exception:
    try:
        index_posts_ws = sheet.add_worksheet(title='IndexPosts', rows=50, cols=3)
        index_posts_ws.append_row(['ForumName', 'ChannelID', 'MessageID'])
    except Exception as e:
        print(f"IndexPosts sheet init error: {e}")
        index_posts_ws = None

# ButlersArchive data lives in cols D-H of the Players sheet, not its own tab
butlers_archive_ws = players_ws


def cached_submissions():
    return _sheet_cache.get(submissions_ws, lambda: submissions_ws.get_all_values()[1:])

def cached_players():
    return _sheet_cache.get(players_ws, lambda: players_ws.get_all_values()[1:])

def cached_leaderboard_data():
    return _sheet_cache.get(leaderboard_data_ws, lambda: leaderboard_data_ws.get_all_values()[1:])

def cached_bounty_ws():
    if not bounty_ws:
        return []
    return _sheet_cache.get(bounty_ws, lambda: bounty_ws.get_all_values()[1:])

def cached_bounty_players():
    return _sheet_cache.get(bounty_players_ws, lambda: bounty_players_ws.get_all_values()[1:])


# Submission queue per guild — serialises concurrent submissions so two people
# submitting at the same time don't race and corrupt each other's registry card.
_submission_queues  = {}
_submission_workers = {}
_registry_lock      = asyncio.Lock()

def get_submission_queue(guild_id):
    if guild_id not in _submission_queues:
        _submission_queues[guild_id] = asyncio.Queue()
    return _submission_queues[guild_id]

# Legacy lock accessor kept for anything still using it
_submission_locks = {}
def get_submission_lock(guild_id):
    if guild_id not in _submission_locks:
        _submission_locks[guild_id] = asyncio.Lock()
    return _submission_locks[guild_id]

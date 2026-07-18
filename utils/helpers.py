import os
import random
import asyncio
from datetime import datetime, timezone

import config


def swallow(exc, context=""):
    """Log a caught-and-continued exception instead of silently dropping it.

    The `except Exception: pass` pattern is how the two worst bugs this codebase
    has shipped stayed invisible for months (a wrong-arity unpack that blanked
    Warlord/Kill Share, and a dropped column that blanked TUFF). This turns those
    silent swallows into one greppable line that names WHERE the error was raised,
    so 'the bot is quietly dumber than it should be' becomes a log search.

    Use in place of `pass` in a handler whose failure shouldn't crash the caller
    but also shouldn't vanish: `except Exception as e: swallow(e, "context")`."""
    loc = ""
    tb = getattr(exc, "__traceback__", None)
    if tb is not None:
        last = tb
        while last.tb_next:  # walk to the frame where it was actually raised
            last = last.tb_next
        fname = last.tb_frame.f_code.co_filename.replace("\\", "/").split("/")[-1]
        loc = f"{fname}:{last.tb_lineno} "
    tag = f"[{context}] " if context else ""
    print(f"[SWALLOW] {tag}{loc}{type(exc).__name__}: {exc}")

# Shared OpenAI client - initialised once, used by any cog that needs a Butler line.
# The Butler's conversational voice runs on GPT-5.6 Luna (the cheap, high-volume
# tier). Vision stays on Gemini, below — these are separate concerns.
_openai_client = None
try:
    import openai as _openai
    _openai_client = _openai.AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
except Exception:
    pass

BUTLER_MODEL = 'gpt-5.6-luna'


async def butler_complete(system: str, prompt: str, max_tokens: int) -> str:
    """One Butler completion. Returns '' on any failure — callers supply their
    own fallback line.

    reasoning_effort='none' is REQUIRED, not a tuning knob: GPT-5.6 is a
    reasoning model, and with budgets this small (50-350) reasoning tokens
    would consume the entire allowance and return empty content."""
    if not _openai_client:
        return ''
    # One retry: a transient refusal (or a blip) otherwise costs the player a
    # silent non-answer, which reads as the Butler ignoring them.
    last_err = None
    for _attempt in range(2):
        try:
            r = await _openai_client.chat.completions.create(
                model=BUTLER_MODEL,
                max_completion_tokens=max_tokens,
                reasoning_effort='none',
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': prompt},
                ],
            )
            return (r.choices[0].message.content or '').strip()
        except Exception as e:
            last_err = e
            if _attempt == 0:
                await asyncio.sleep(1.5)
    print(f"[BUTLER] completion failed after retry (model={BUTLER_MODEL}): {last_err}")
    return ''

# Gemini client for vision (scorecard parsing)
_gemini_client = None
try:
    from google import genai as _genai
    _gemini_client = _genai.Client(api_key=os.environ['GOOGLE_AI_API_KEY'])
except Exception:
    pass


_BUTLER_SYSTEM_BRIEF = (
    "You are the Butler - dry, sardonic, one or two sentences max. "
    "Never say 'great', 'awesome', or use exclamation marks. Never break character."
)

async def butler_quip(prompt: str, fallback: str = '') -> str:
    """Short Butler line. Returns fallback if unavailable."""
    try:
        return (await butler_complete(_BUTLER_SYSTEM_BRIEF, prompt, 60)) or fallback
    except Exception:
        return fallback


_SCORECARD_PROMPT = """You are reading a Chivalry 2 end-of-round scoreboard screenshot.

The scoreboard columns are: RANK | NAME | SCORE | T | K | D | PING
- RANK: leftmost column, a rank number (e.g. 1,000 or 74) - do NOT use this as score or takedowns
- NAME: player name
- SCORE: large point value (often 1,000–20,000) - do NOT use this as takedowns
- T: Takedowns - the number of kills+assists, typically the largest combat stat (50–400 for top players)
- K: Kills - always less than or equal to T
- D: Deaths - typically 0–50
- PING: last column, network latency in ms - ignore this

DIGIT ACCURACY (CRITICAL): T/K/D digits are small and easily misread. Read each digit precisely and re-check before answering. Watch especially for 3 vs 8, 8 vs 6, 5 vs 6, 0 vs 8, and 1 vs 7. If a digit is ambiguous, prefer the shape that best matches the pixels rather than guessing.

CRITICAL: The submitting player's row is visually highlighted - it has a noticeably brighter background (often gold/yellow/tan), different colour tint, or a star/crown/icon marker next to their name. The highlighted row can be ANYWHERE - top, middle, or bottom of the scoreboard. NOTE: more than one row may look highlighted — the submitter's OWN row is GOLD/YELLOW/TAN, while a GREEN tint or green person-icon marks a friend/party member (NOT the submitter). When a player name hint is provided, the row whose NAME matches the hint wins over any highlight colour.

LARGE LOBBIES: The scoreboard may have up to 32 players per team (64 total). In large lobbies the text is small - read carefully. Do not skip rows.

STEAM DECK / CONTROLLER UI: Some screenshots show "PRESS A TO INTERACT", "PRESS B", "PRESS X", or similar controller button prompts at the bottom of the screen. These are UI overlays - ignore them completely, they are not part of the scoreboard.

SCREEN OVERLAYS TO IGNORE - these are NOT scoreboard rows:
- Discord/streaming voice overlays on the left or right edges (small cards showing player names with icons like arrows, diamonds, or letters like "E")
- A "SPECTATORS" panel that may appear on the right side listing players who are spectating
- Any name that appears outside the main two-column scoreboard table
Only read names and stats from inside the RANK | NAME | SCORE | T | K | D | PING table columns.

FINDING THE PLAYER:
Method 1 (PRIMARY) — the submitter's OWN row is highlighted GOLD/YELLOW/TAN (brighter background, sometimes a crown/marker icon). This is the MOST reliable signal: the submitter is always their own gold-highlighted row. A GREEN tint or green person-icon marks a FRIEND / party member — that is NOT the submitter; never read the green row.
Method 2 (DISAMBIGUATE + CONFIRM) — a name hint may be provided. Use it ONLY to (a) pick the correct row when more than one row looks highlighted (gold vs green), and (b) sanity-check the gold row. Match loosely: case-insensitive, ignore clan tags/decorators.
CRITICAL: a player's in-game name OFTEN does NOT match the hint. If no row's name matches the hint, DO NOT force it onto another row — just use the GOLD/YELLOW/TAN self-highlighted row. Never invent, bend, or combine names to fit the hint; read the name EXACTLY as printed on the chosen row.

Step 1: Using both methods above, identify the submitting player's row.
Step 2: Read the T, K, D values ONLY from that exact row - do not read from any row above or below it.
Step 3: That same player must NOT appear in team_scores or team_kills - those arrays are for all OTHER teammates only.

Extract ONLY from that highlighted row:
- weapon (exact weapon name if shown - may appear as an icon tooltip or text; null if not visible)
- subclass (class name e.g. Ambusher, Officer, Devastator, Poleman, Man-at-Arms, Longbowman; null if not visible)
- map (full map name shown at the TOP of the screen above the scoreboard, e.g. "The Siege of Rudhelm", "The Battle of Darkforest" — NOT from the leaderboard rows)
NOTE: The two large numbers at the TOP of the screen, one on each side (one per faction, e.g. "AGATHA 531" on the left and "MASON 678" on the right), are each team's TOTAL KILL count for the whole match. Read them into team_total_kills (the submitting player's OWN faction) and enemy_total_kills (the OTHER faction). These are team totals, NOT individual stats — never use them for the highlighted player's kills or takedowns.
- faction: the highlighted player's team. Determine it from the large faction banner at the TOP of the screen (the same "AGATHA .../ MASON ..." labels noted above — one faction name on the LEFT side, the other on the RIGHT side). The scoreboard is split into two side-by-side halves; work out which half (left or right) the highlighted row sits in, then read the faction from the banner label directly ABOVE that half. That banner name is the source of truth — do NOT guess the faction from row colours or icons. (Agatha, Mason, or Tenosia.)
- takedowns (integer from T column of highlighted row)
- kills (integer from K column of highlighted row)
- deaths (integer from D column of highlighted row)
- score: the number under the column header literally reading "SCORE" for the highlighted row. It is a 4-5 digit points total, almost always shown WITH a comma (e.g. "9,260", "11,653") -- strip the comma and return it as an integer (9260, 11653). SCORE is the THIRD column (RANK | NAME | SCORE | T | K | D | PING) and is far LARGER than the T/K/D numbers to its right. This column is ALWAYS present and legible for every listed player, so you MUST read the highlighted row's SCORE value; only return null if that row is entirely unreadable. Never confuse SCORE with T (takedowns).

The scoreboard shows TWO teams side by side. For ALL other rows (excluding the highlighted player), split by team:
- team_scores: T column integers for players on the SAME team as the highlighted player
- team_kills: K column integers for players on the SAME team as the highlighted player
- enemy_scores: T column integers for players on the ENEMY team
- enemy_kills: K column integers for players on the ENEMY team

COLUMN READING EXAMPLES - study these carefully before reading the image:

Example 1 (highlighted row is rank 2, not rank 1):
  Row data visible: RANK=1,000  NAME=mlowy  SCORE=11,653  T=124  K=54  D=6  PING=8
  Correct output: takedowns=124, kills=54, deaths=6
  WRONG output would be: takedowns=11653 (that is SCORE, not T), or takedowns=1000 (that is RANK)

Example 2 (highlighted row is mid-table):
  Row data visible: RANK=266  NAME=SauceCode  SCORE=9,029  T=79  K=29  D=21  PING=12
  Correct output: takedowns=79, kills=29, deaths=21
  WRONG output would be: takedowns=266 (RANK) or takedowns=9029 (SCORE)

Example 3 (highlighted row is near bottom):
  Row data visible: RANK=88  NAME=ColdestQmurray  SCORE=2,947  T=31  K=9  D=14  PING=60
  Correct output: takedowns=31, kills=9, deaths=14

The T column (takedowns) is always a small integer, typically 10–400. The SCORE column is always a large number (thousands). Never confuse them.

Your response must be ONLY the JSON object below - no explanation, no preamble, no markdown fences. Start your response with `{` and end with `}`. Use null for any field you cannot confidently read.

Also read match_result: the huge VICTORY or DEFEAT text in the center of the screen (often faint behind the scoreboard). This is the SUBMITTER's result. "victory", "defeat", or null if not visible.

{"weapon":null,"subclass":null,"map":null,"faction":null,"name":null,"takedowns":null,"kills":null,"deaths":null,"score":null,"team_scores":[],"team_kills":[],"enemy_scores":[],"enemy_kills":[],"team_total_kills":null,"enemy_total_kills":null,"match_result":null}"""


_HALF_ROSTER_PROMPT = """This image is ONE team's half of a Chivalry 2 end-of-round
scoreboard (the columns RANK | NAME | SCORE | T | K | D | PING). Read EVERY row, top to
bottom, skipping none. For each row return its T (takedowns) and K (kills) integers.
T is the takedowns column (typically 10-400), K is kills (<= T), both far smaller than
the SCORE column. Ignore RANK, SCORE, D, PING, and any Discord/voice overlay cards on
the screen edges. Return ONLY this JSON: {"scores":[T,T,...],"kills":[K,K,...]} with one
entry per row in top-to-bottom order. Start with { and end with }."""


def _read_half_roster(pil_img, gtypes, gemini_client):
    """Read one cropped team-column's T/K values. Returns (scores, kills) lists.
    Cropping to a single team doubles the effective text size and removes the other
    half, which is what lets vision read every row on a dense 60-player board that it
    skips when shown the whole thing at once."""
    import io as _io, json as _json
    buf = _io.BytesIO()
    pil_img.save(buf, format='JPEG', quality=95)
    part = gtypes.Part.from_bytes(data=buf.getvalue(), mime_type='image/jpeg')
    r = gemini_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[_HALF_ROSTER_PROMPT, part],
        config=gtypes.GenerateContentConfig(
            temperature=0, response_mime_type='application/json',
            max_output_tokens=2048,
            thinking_config=gtypes.ThinkingConfig(thinking_budget=256)))
    raw = (r.text or '').strip()
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:].strip()
    s = raw.find('{')
    if s == -1:
        return [], []
    d, _ = _json.JSONDecoder().raw_decode(raw[s:])
    def _ints(x):
        return [v for v in (x or []) if isinstance(v, int) and 0 < v <= 600]
    return _ints(d.get('scores')), _ints(d.get('kills'))


def vision_parse_scorecard(image_url: str, player_name: str = None, other_names=None) -> dict:
    """
    Pass a Discord image URL to Gemini vision and extract scorecard fields.
    player_name: Discord display name of the submitting player - used as a hint to find their row.
    Returns a dict with keys: weapon, subclass, map, faction, takedowns, kills, deaths, other_scores.
    Any field that couldn't be read confidently is None.
    """
    empty = {
        'weapon': None, 'subclass': None, 'map': None, 'faction': None, 'name': None,
        'takedowns': None, 'kills': None, 'deaths': None, 'score': None,
        'team_scores': [], 'team_kills': [], 'enemy_scores': [], 'enemy_kills': [],
        'team_total_kills': None, 'enemy_total_kills': None, 'match_result': None,
    }
    print(f"[VISION] Attempting parse for URL: {image_url[:80]}...")
    if not _gemini_client:
        print("[VISION] No Gemini client - skipping")
        return empty
    try:
        import json as _json
        import urllib.request
        import io

        # Fetch image bytes - Discord CDN URLs with expiry tokens must be fetched immediately
        try:
            req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                image_bytes = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/png').split(';')[0].strip()
            print(f"[VISION] Fetched {len(image_bytes)} bytes, type={content_type}")
        except Exception as fetch_err:
            print(f"[VISION] Image fetch failed: {fetch_err}")
            return empty

        # Pre-process image: upscale small images and sharpen for better OCR accuracy
        _iw = _ih = 0  # image dims, filled in below — referenced by the roster-retry log
        _pp_img = None  # the preprocessed PIL image, kept for the half-crop roster pass
        try:
            from PIL import Image as _PImage, ImageEnhance as _PIEnhance, ImageFilter as _PIFilter
            import io as _io
            img = _PImage.open(_io.BytesIO(image_bytes)).convert('RGB')
            w, h = img.size
            # Normalize by HEIGHT, not width. Scoreboard rows are horizontal, so the
            # readable size of each row's T/K/D digits scales with image HEIGHT. The
            # old width-normalization (fix width to 2560) crushed ultrawide monitors:
            # a 3440x1440 board became 2560x1071, dropping row height ~26% until a
            # dense 64-player roster was too small to read and the model skipped rows.
            # Height-normalizing keeps every aspect ratio's rows the same legible size
            # (a 16:9 board still lands at 2560x1440, unchanged). Width is capped only
            # for super-ultrawide so uploads stay sane; Gemini tiles the rest.
            TARGET_H = 1440
            MAX_W = 3840
            if h > 0:
                scale = TARGET_H / h
                if w * scale > MAX_W:
                    scale = MAX_W / w
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                if (new_w, new_h) != (w, h):
                    img = img.resize((new_w, new_h), _PImage.LANCZOS)
            # Sharpen and boost contrast slightly (after resize, to recover edges)
            img = img.filter(_PIFilter.SHARPEN)
            img = _PIEnhance.Contrast(img).enhance(1.3)
            img = _PIEnhance.Sharpness(img).enhance(2.0)
            buf = _io.BytesIO()
            img.save(buf, format='JPEG', quality=95)
            image_bytes = buf.getvalue()
            content_type = 'image/jpeg'
            _iw, _ih = img.size
            _pp_img = img  # keep for the half-crop roster recovery pass
            print(f"[VISION] Pre-processed to {_iw}x{_ih} JPEG ({len(image_bytes)} bytes)")
        except Exception as pp_err:
            print(f"[VISION] Pre-process skipped: {pp_err}")

        from google.genai import types as _gtypes
        image_part = _gtypes.Part.from_bytes(data=image_bytes, mime_type=content_type)
        name_hint = (
            f"\n\nPLAYER NAME HINT: The submitting player may appear as one of these names: {player_name}. "
            f"Their in-game name OFTEN differs from these, so treat this as a SOFT hint, not a target to force. "
            f"PRIMARY: read every stat (SCORE, T, K, D, faction, weapon, subclass) from the submitter's OWN row — the one tinted GOLD/YELLOW/TAN (their self-highlight). "
            f"A GREEN tint or green person-icon is a FRIEND/party member, NOT the submitter — never read the green row. "
            f"Use the hint ONLY to disambiguate when more than one row looks highlighted (gold vs green). "
            f"If NO row's name matches the hint, do NOT force a match — the player's in-game name simply differs; use the GOLD/YELLOW/TAN self-highlighted row and read its REAL printed name. "
            f"Never invent, bend, or combine names to fit the hint. NEVER read stats from Discord voice-overlay cards on the screen edges. "
            f"Return the exact NAME text you read from the chosen row in the 'name' field."
        ) if player_name else ""
        prompt = _SCORECARD_PROMPT + name_hint

        import time as _time
        raw = None
        for _attempt in range(3):
            try:
                r = _gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[prompt, image_part],
                    config=_gtypes.GenerateContentConfig(
                        temperature=0,
                        response_mime_type='application/json',
                        # Cap output so a runaway response (a real 65k-char blob was
                        # seen) gets cut off fast instead of hanging ~100s. A full
                        # 64-player lobby's four roster arrays plus fields can approach
                        # ~1k tokens, and the 512-token thinking budget also draws from
                        # this pool — 2048 risked truncating the roster on big lobbies,
                        # so 4096 gives real headroom without inviting a runaway.
                        max_output_tokens=4096,
                        thinking_config=_gtypes.ThinkingConfig(thinking_budget=512),
                    )
                )
                raw = r.text.strip()
                break
            except Exception as _e:
                _es = str(_e)
                if '503' in _es or 'UNAVAILABLE' in _es:
                    print(f"[VISION] 503 on attempt {_attempt+1}, retrying in {5 * (_attempt+1)}s...")
                    _time.sleep(5 * (_attempt + 1))
                else:
                    raise
        if raw is None:
            print("[VISION] All retries failed (503)")
            return empty
        raw = raw.strip()
        print(f"[VISION] Raw response ({len(raw)} chars): {raw[:200]}")
        if not raw:
            print("[VISION] Empty response from Gemini")
            return empty
        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:].strip()
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            # Gemini sometimes trails/wraps the JSON with extra text, which plain json.loads
            # rejects ("Extra data"). Extract the first complete JSON object and ignore the rest.
            _start = raw.find('{')
            if _start == -1:
                print("[VISION] No JSON object found in response")
                return empty
            try:
                data, _ = _json.JSONDecoder().raw_decode(raw[_start:])
            except _json.JSONDecodeError as _je:
                print(f"[VISION] JSON parse failed after extract: {_je}")
                return empty
        # --- Safety net: make sure the model read the SUBMITTER's row, not a
        # party member's. Gemini sometimes locks onto a green-highlighted friend
        # row. If the name it returned doesn't match the submitter's known name(s),
        # re-read the correct row by name in one corrective pass.
        if player_name:
            import re as _rex
            def _n(s):
                return _rex.sub(r'[^a-z0-9]', '', (s or '').lower())
            _hints = [h.strip() for h in str(player_name).split(',') if h.strip()]
            def _match(got):
                g = _n(got)
                return bool(g) and any(_n(h) and (_n(h) == g or _n(h) in g or g in _n(h)) for h in _hints)
            # Only correct a GENUINE wrong-row: the read name matches a DIFFERENT registered
            # player. A name matching nobody is just an unregistered in-game name on the
            # (usually correct) gold self-highlighted row — leave it alone rather than risk
            # a hallucinated corrective re-read.
            _other_norm = {_n(o) for o in (other_names or []) if _n(o)}
            _nr = _n(data.get('name'))
            if (bool(_nr) and _nr in _other_norm) and not _match(data.get('name')):
                _corr = (
                    f"\n\nCORRECTION REQUIRED: You returned the row named '{data.get('name')}', which is NOT the "
                    f"submitting player. The submitter's row is named one of: {player_name} (match case-insensitively, "
                    f"ignore clan tags/decorators). Find THAT row and return its score, takedowns (T), kills (K), "
                    f"deaths (D), faction, weapon, subclass and name — ignore highlight colour entirely."
                )
                try:
                    _r2 = _gemini_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[prompt + _corr, image_part],
                        config=_gtypes.GenerateContentConfig(
                            temperature=0, response_mime_type='application/json',
                            max_output_tokens=2048,
                            thinking_config=_gtypes.ThinkingConfig(thinking_budget=512),
                        ),
                    )
                    _raw2 = (_r2.text or '').strip()
                    if _raw2.startswith('```'):
                        _raw2 = _raw2.split('```')[1]
                        if _raw2.startswith('json'):
                            _raw2 = _raw2[4:].strip()
                    _s2 = _raw2.find('{')
                    if _s2 != -1:
                        _data2, _ = _json.JSONDecoder().raw_decode(_raw2[_s2:])
                        if _match(_data2.get('name')):
                            print(f"[VISION] Corrected wrong-row read: '{data.get('name')}' -> '{_data2.get('name')}'")
                            data = _data2
                        else:
                            print(f"[VISION] Correction pass still no name match (got '{_data2.get('name')}'); keeping original")
                except Exception as _ce:
                    print(f"[VISION] Correction pass error: {_ce}")

        # Roster-completeness retry: the highlighted player read fine, but the
        # team/enemy roster arrays came back empty or thin. That blanks TUFF, the
        # lobbymate fingerprint, team ratings AND cross-verification. If the faction
        # banner totals were read (proof a full scoreboard IS in the image, not a
        # crop), take ONE more pass that asks specifically for every roster row.
        def _roster_len(d):
            return sum(len(d.get(k) or []) for k in
                       ('team_scores', 'team_kills', 'enemy_scores', 'enemy_kills'))
        _has_totals = isinstance(data.get('team_total_kills'), int) or isinstance(data.get('enemy_total_kills'), int)
        if _roster_len(data) < 4 and _has_totals:
            print(f"[VISION] Roster thin ({_roster_len(data)} cells) but totals present "
                  f"— retrying for full roster (img {_iw}x{_ih})")
            _roster_req = (
                "\n\nROSTER PASS: Your previous read captured the highlighted player but "
                "SKIPPED most or all of the other rows. Read EVERY OTHER row in the "
                "RANK|NAME|SCORE|T|K|D|PING table, both teams, top to bottom, skipping none. "
                "Fill team_scores/team_kills (same team as the highlighted player) and "
                "enemy_scores/enemy_kills (other team) completely. Keep the highlighted "
                "player's own stats exactly as before. Return the full JSON object.")
            try:
                _rr = _gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[prompt + _roster_req, image_part],
                    config=_gtypes.GenerateContentConfig(
                        temperature=0, response_mime_type='application/json',
                        max_output_tokens=4096,
                        thinking_config=_gtypes.ThinkingConfig(thinking_budget=512)))
                _rraw = (_rr.text or '').strip()
                if _rraw.startswith('```'):
                    _rraw = _rraw.split('```')[1]
                    if _rraw.startswith('json'):
                        _rraw = _rraw[4:].strip()
                _rs = _rraw.find('{')
                if _rs != -1:
                    _rdata, _ = _json.JSONDecoder().raw_decode(_rraw[_rs:])
                    if _roster_len(_rdata) > _roster_len(data):
                        print(f"[VISION] Roster pass recovered {_roster_len(_rdata)} cells "
                              f"(was {_roster_len(data)})")
                        # Keep the original player fields; adopt the fuller roster.
                        for _rk in ('team_scores', 'team_kills', 'enemy_scores', 'enemy_kills'):
                            if _rdata.get(_rk):
                                data[_rk] = _rdata[_rk]
                    else:
                        print(f"[VISION] Roster pass no better ({_roster_len(_rdata)} cells) "
                              f"— trying half-crop")
            except Exception as _rre:
                print(f"[VISION] Roster pass error: {_rre}")

        # Half-crop roster recovery: dense boards (50-64 players) stay unreadable even
        # on the full-image retry — the rows are simply too small. Crop to each team
        # COLUMN (half the width) so the text roughly doubles and vision faces one team
        # at a time, then assign the half that contains the submitter's own T/K as their
        # team. This is what finally reads TUFF-eligible rosters on packed lobbies.
        if _roster_len(data) < 4 and _has_totals and _pp_img is not None:
            try:
                _pw, _ph = _pp_img.size
                _mid = _pw // 2
                _ov = int(_pw * 0.04)  # slight overlap so a centre gutter can't clip edge digits
                _left = _pp_img.crop((0, 0, _mid + _ov, _ph))
                _right = _pp_img.crop((max(0, _mid - _ov), 0, _pw, _ph))
                _ls, _lk = _read_half_roster(_left, _gtypes, _gemini_client)
                _rs, _rk = _read_half_roster(_right, _gtypes, _gemini_client)
                print(f"[VISION] Half-crop rosters: left {len(_ls)} rows, right {len(_rs)} rows")
                _std, _sk = data.get('takedowns'), data.get('kills')

                def _strip_self(scores, kills):
                    # drop one instance of the submitter's own row from their team half
                    if isinstance(_std, int) and _std in scores:
                        i = scores.index(_std)
                        scores = scores[:i] + scores[i + 1:]
                        if i < len(kills):
                            kills = kills[:i] + kills[i + 1:]
                    return scores, kills

                _ts = _tk = _es = _ek = None
                if isinstance(_std, int) and _std in _ls:
                    _ts, _tk = _strip_self(_ls, _lk); _es, _ek = _rs, _rk
                elif isinstance(_std, int) and _std in _rs:
                    _ts, _tk = _strip_self(_rs, _rk); _es, _ek = _ls, _lk
                else:
                    print("[VISION] Half-crop: submitter's own row not found in either half; skipping")

                _merged = {'team_scores': _ts or [], 'team_kills': _tk or [],
                           'enemy_scores': _es or [], 'enemy_kills': _ek or []}
                if _ts and _roster_len(_merged) > _roster_len(data):
                    data.update(_merged)
                    print(f"[VISION] Half-crop recovered roster: team {len(_ts)} / enemy {len(_es or [])}")
            except Exception as _hce:
                print(f"[VISION] Half-crop pass error: {_hce}")

        # Coerce numeric fields to int, ignore bad values
        for field in ('takedowns', 'kills', 'deaths', 'team_total_kills', 'enemy_total_kills'):
            try:
                if data.get(field) is not None:
                    data[field] = int(data[field])
            except (ValueError, TypeError):
                data[field] = None
        try:
            if data.get('score') is not None:
                data['score'] = int(str(data['score']).replace(',', '').strip())
        except (ValueError, TypeError):
            data['score'] = None
        for list_field in ('team_scores', 'team_kills', 'enemy_scores', 'enemy_kills'):
            if not isinstance(data.get(list_field), list):
                data[list_field] = []
        return {**empty, **data}
    except Exception as e:
        err = str(e)
        if '429' in err or 'RESOURCE_EXHAUSTED' in err:
            print(f"[VISION] Gemini quota exhausted - user will need to enter stats manually")
        else:
            print(f"[VISION] Error: {e}")
        return empty


def build_favourites_explainer_embed():
    """Explainer embed posted in the Butler's Favourites channel."""
    import discord as _discord

    embed = _discord.Embed(
        title="📋  The Butler's Favourites",
        description="The Butler's Report tracks server-wide performance stats across all submissions. Updated automatically after every submission.",
        colour=_discord.Colour.from_str("#8b6914"),
    )
    embed.add_field(
        name="📅 Weekly stats  *(resets Monday 12:00 UTC)*",
        value=(
            "`Most Lethal` — highest kills ÷ takedowns % across the week\n"
            "`Warlord` — highest takedown share of team % across the week\n"
            "`Apex` — highest average kills on 100+ kill runs this week\n"
            "`Frenzied` — highest average takedowns on 200+ takedown runs this week\n"
            "`Most Kills` — best single-game kill score this week\n"
            "`Highest Takedowns` — best single-game takedown score this week\n"
            "`Busiest` — most total submissions this week\n"
            "`Top Weapons` — most submitted weapons this week\n"
            "`Top Maps` — most played maps this week"
        ),
        inline=False,
    )
    embed.add_field(
        name="🏆 All-time titles  *(permanent leaderboard holders)*",
        value=(
            "`Grand Marshal` — #1 across the most leaderboards overall\n"
            "`Weapons Master` — #1 across the most weapon boards\n"
            "`Campaign Master` — #1 across the most map boards"
        ),
        inline=False,
    )
    embed.set_footer(text="Use /butlers_report to summon the latest report.")
    return embed


def build_manual_embed():
    """Build the butler's-manual embed listing all player-facing slash commands."""
    import discord as _discord

    embed = _discord.Embed(
        title="🎩  Butler's Manual",
        description="*Slash commands available to all players.*",
        colour=_discord.Colour.from_str("#2b2d31"),
    )

    embed.add_field(
        name="📊 Stats & Rankings",
        value=(
            "`/stats` — Your title standings and weapon rank progress. Use `/stats [name]` for any player.\n"
            "`/rank` — Top 10 for any weapon board. e.g. `/rank Messer`\n"
            "`/title_standings` — Who leads each all-time title (Grand Marshal, Weapons Master, Campaign Master), with the board-count + average-placement tiebreak shown.\n"
            "`/butlers_report` — Your current-standings snapshot (season champions, records, all-time titles)."
        ),
        inline=False,
    )
    embed.add_field(
        name="🏹 Bounty",
        value=(
            "`/bounty status` — The active bounty card and your personal progress.\n"
            "`/bounty hunt` — Top 5 hunters for the active bounty.\n"
            "`/season_standings` — Live standings for the current season (this bounty cycle)."
        ),
        inline=False,
    )
    embed.add_field(
        name="📋 Registry",
        value=(
            "`/refresh_card` — Refresh your registry card in Butler's Archive."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚖️ Rules",
        value="`/rules` — Show the Cigar Lounge challenge rules.",
        inline=False,
    )
    embed.set_footer(text="Use the bot's slash commands anywhere.")
    return embed


def build_manual_content():
    """Legacy plain-text fallback — use build_manual_embed() instead."""
    return "See pinned embed above."


# parse_submission_text extracted to utils/parsing.py (pure + unit-tested).
from utils.parsing import parse_submission_text  # noqa: F401


def format_weapon_marks(marks):
    # Formatting tiers map to rank thresholds - bold at Gold (12), italic+bold at
    # Crimson (60), plus prestige multiplier suffix past Iridescent (150).
    if marks >= 150:
        prestige = sum(1 for t in config.PRESTIGE_THRESHOLDS if marks >= t)
        prestige_str = f" ×**{prestige}**" if prestige > 0 else ""
        return f"***{marks}***{prestige_str}"
    elif marks >= 60:
        return f"***{marks}***"
    elif marks >= 12:
        return f"**{marks}**"
    else:
        return str(marks)


# Only these thresholds get milestone announcements - not every rank crossing,
# just the ones that actually mean something: first mark, Crimson, Prestige, Iridescent.
_MILESTONE_THRESHOLDS = {1, 60, 80, 150}

def detect_weapon_milestones(old_flat, new_flat):
    # old_flat / new_flat: dict of weapon_name -> int marks
    milestones = []
    for weapon in set(old_flat) | set(new_flat):
        old = old_flat.get(weapon, 0)
        new = new_flat.get(weapon, 0)
        if new <= old:
            continue
        for threshold, rank_name in config.WEAPON_RANK_THRESHOLDS:
            if threshold in _MILESTONE_THRESHOLDS and old < threshold <= new:
                milestones.append((weapon, threshold, rank_name))
        # Prestige multiplier - fire each time they cross another prestige threshold past 150
        if old >= 150:
            old_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if old >= t)
            new_x = sum(1 for t in config.PRESTIGE_THRESHOLDS if new >= t)
            if new_x > old_x:
                milestones.append((weapon, new, f"Iridescent ×{new_x}"))
    return milestones


def build_milestone_message(player_name, weapon, threshold, rank_name):
    if rank_name.startswith("Iridescent ×"):
        n = int(rank_name.split("×")[1].strip())
        mark_count = (config.PRESTIGE_THRESHOLDS[n - 1]
                      if n <= len(config.PRESTIGE_THRESHOLDS)
                      else config.PRESTIGE_THRESHOLDS[-1])
        return f"**{player_name}** - **{weapon}** ×{n}. {mark_count} marks. The bald woman would be proud."
    messages = {
        1:   f"*Noted.* **{player_name}** has drawn first blood with the **{weapon}**.",
        60:  f"**{player_name}** has reached Crimson rank on the **{weapon}**. 60 marks. I approve. Quietly.",
        80:  f"**{player_name}** has entered Prestige with the **{weapon}**. 80 marks. I'll say nothing. That is the compliment.",
        150: f"**{player_name}** has gone Iridescent on the **{weapon}**. 150 marks. I'm pouring a drink.",
    }
    return messages.get(threshold)


# Shared mutable state between submissions and personality cogs.
# Using a dict so both modules mutate the same object after import.
submission_state = {'last_submission_time': None, 'dry_spell_posted': False}

# ── Graceful-shutdown shared state ───────────────────────────────────────────
# Lives here, not bot.py: bot.py runs as __main__, so a cog importing it gets
# a second module instance with its own copy of these counters.
_shutting_down = False
_active_submissions = 0

def set_shutting_down():
    global _shutting_down
    _shutting_down = True

def is_shutting_down() -> bool:
    return _shutting_down

def submission_start():
    global _active_submissions
    _active_submissions += 1

def submission_end():
    global _active_submissions
    _active_submissions = max(0, _active_submissions - 1)

def active_submissions() -> int:
    return _active_submissions

# In-memory log for the hourly digest posted to nerve center.
# Nothing persists across restarts - intentional, digest is ephemeral.
_nerve_events = {
    'submissions':         [],  # (timestamp, player, weapon)
    'butler_interactions': [],  # (trigger[:60], response[:60])
    'errors':              [],  # (timestamp, error_str)
    'milestones':          [],  # (player, weapon, rank)
}


def nerve_log_submission(player, weapon):
    _nerve_events['submissions'].append((datetime.now(timezone.utc).strftime('%H:%M'), player, weapon))


def nerve_log_butler(trigger, response):
    _nerve_events['butler_interactions'].append((trigger[:60], response[:60]))


def nerve_log_error(context, error):
    _nerve_events['errors'].append((datetime.now(timezone.utc).strftime('%H:%M'), f"{context}: {str(error)[:80]}"))


def nerve_log_milestone(player, weapon, rank):
    _nerve_events['milestones'].append((player, weapon, rank))


_nerve_alert_sent = {}          # signature -> last-sent timestamp
_NERVE_ALERT_COOLDOWN = 600     # sec — same error won't re-post within 10 min


async def nerve_alert(bot_instance, context, error):
    # Fire-and-forget critical error to nerve center - don't let this crash anything else
    try:
        import time as _t
        _lines = [l for l in str(error).splitlines() if l.strip()]
        _sig = f"{context}::{(_lines[-1] if _lines else '')[:120]}"
        _now = _t.time()
        if _now - _nerve_alert_sent.get(_sig, 0) < _NERVE_ALERT_COOLDOWN:
            return  # suppress duplicate spam — same error already reported recently
        _nerve_alert_sent[_sig] = _now
        if len(_nerve_alert_sent) > 200:
            for _k in sorted(_nerve_alert_sent, key=_nerve_alert_sent.get)[:100]:
                _nerve_alert_sent.pop(_k, None)
    except Exception:
        pass
    try:
        guild = bot_instance.get_guild(config.GUILD_ID)
        if not guild:
            return
        ch = (guild.get_channel(config.NERVE_CENTER_CHANNEL_ID)
              or await guild.fetch_channel(config.NERVE_CENTER_CHANNEL_ID))
        if ch:
            import discord as _discord
            if isinstance(ch, _discord.Thread) and ch.archived:
                await ch.edit(archived=False)
            await ch.send(f"⚠️ **Critical Error** - {context}\n```{str(error)[:300]}```")
    except Exception:
        pass


def nerve_flush():
    # Drain the buffer and return a formatted digest string.
    # Called by the hourly task loop in personality.py.
    subs       = _nerve_events['submissions']
    errors     = _nerve_events['errors']
    milestones = _nerve_events['milestones']

    parts = []

    if errors:
        parts.append(f"⚠️ **Errors — {len(errors)}**")
        for ts, err in errors:
            parts.append(f"  `{ts}` {err}")

    if subs:
        parts.append(f"📋 **Submissions — {len(subs)}**")
        for ts, player, weapon in subs:
            parts.append(f"  `{ts}` **{player}** — {weapon}")
    else:
        parts.append("📋 **Submissions — 0**")

    if milestones:
        parts.append(f"🏆 **Milestones — {len(milestones)}**")
        for player, weapon, rank in milestones:
            parts.append(f"  **{player}** — {weapon} → {rank}")

    _nerve_events['submissions'].clear()
    _nerve_events['butler_interactions'].clear()
    _nerve_events['errors'].clear()
    _nerve_events['milestones'].clear()

    return "\n".join(parts) if parts else ""
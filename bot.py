import asyncio
import hashlib
import hmac
import json
import traceback
import os
import signal
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands

import config

# --- public-facing ID anonymizer ---------------------------------------------
# The public web payloads (Stats Lab, player cards) must NEVER leak a raw Discord
# snowflake — that would publish a name->Discord-ID map to the open web. The client
# only needs a STABLE per-player key to group a player's runs, so we emit a salted
# hash instead of the real id. The salt makes the public value un-linkable to the
# real snowflake; set LAB_ID_SALT in the environment to rotate it.
_ID_SALT = os.environ.get('LAB_ID_SALT', 'cigar-lounge-public-v1').encode()

def _anon_id(did):
    s = (str(did) if did is not None else '').strip()
    if not s:
        return ''
    return 'p' + hashlib.blake2s(s.encode(), key=_ID_SALT, digest_size=6).hexdigest()

def _scrub_ids(obj):
    """Recursively replace any 'did' value in a nested dict/list with its anon hash."""
    if isinstance(obj, dict):
        return {k: (_anon_id(v) if k == 'did' else _scrub_ids(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_ids(x) for x in obj]
    return obj

# Graceful-shutdown state lives in utils.helpers. Don't move it here: cogs
# can't `import bot` (this file runs as __main__, so importing it re-executes
# everything under a second module name with separate globals).
from utils import helpers as _shared


_web_app = web.Application()


async def run_healthcheck():
    """Healthcheck server. Returns 503 when the gateway is dead so Railway
    restarts the container. Gated on first on_ready so boot still passes."""
    async def handle(request):
        try:
            if getattr(bot, "_synced", False) and (bot.is_closed() or bot.latency > 60):
                return web.Response(text="unhealthy: gateway down", status=503)
        except Exception:
            pass
        # A real browser hitting the bare domain should land on the site, not read "ok".
        # Railway's healthcheck probe doesn't ask for HTML, so it still gets the plain
        # 200 below and the restart-on-503 behaviour is preserved.
        if "text/html" in (request.headers.get("Accept") or ""):
            try:
                _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "home.html")
                with open(_p, encoding="utf-8") as f:
                    html = f.read()
                return web.Response(text=html, content_type="text/html",
                                    headers={"Cache-Control": "no-cache, must-revalidate"})
            except Exception:
                # Landing page missing? Fall back to the Stats Lab so the domain still works.
                raise web.HTTPFound("/lab")
        return web.Response(text="ok")

    async def kofi_webhook(request):
        # Must be registered here: aiohttp freezes the router when the site
        # starts, and cogs load after that. Dispatches to the cog per request.
        cog = bot.get_cog("KofiCog")
        if cog is None:
            return web.Response(status=503, text="kofi cog not loaded")
        return await cog.handle_webhook(request)

    async def export_submissions(request):
        # Read-only cursor export of the submissions table, for community
        # mirrors (leaderboard sites and the like). Callers page forward by id:
        # pass the highest id already held as after_id, get the next batch in
        # insertion order, repeat until nextCursor comes back null. Rows are
        # serialized exactly like the scheduled backup (raw column dicts,
        # datetimes as naive-UTC strings), so a consumer of one can consume
        # the other. Off unless EXPORT_TOKEN is set.
        token = os.environ.get("EXPORT_TOKEN", "")
        if not token:
            return web.Response(status=503, text="export disabled")
        auth = request.headers.get("Authorization", "")
        # compare_digest, not ==: string equality short-circuits on the first
        # differing byte, which leaks the token a byte at a time to anyone who
        # can measure response times.
        if not hmac.compare_digest(auth, f"Bearer {token}"):
            return web.Response(status=403, text="forbidden")
        try:
            after_id = int(request.query.get("after_id", 0))
            limit = int(request.query.get("limit", 500))
        except ValueError:
            return web.Response(status=400, text="after_id and limit must be integers")
        if after_id < 0 or not (1 <= limit <= 1000):
            return web.Response(status=400, text="after_id must be >= 0, limit 1 to 1000")
        try:
            from utils.db import get_submissions_after
            rows = await get_submissions_after(after_id, limit)
        except RuntimeError:
            # Pool not initialised (DATABASE_URL unset or boot still in progress).
            return web.Response(status=503, text="database unavailable")
        # A full page may end exactly on the last row; the follow-up call then
        # returns an empty page and nextCursor null, which is fine.
        next_cursor = rows[-1]["id"] if len(rows) == limit else None
        return web.json_response(
            {"rows": rows, "nextCursor": next_cursor},
            dumps=lambda d: json.dumps(d, default=str, ensure_ascii=False))

    async def lab_page(request):
        # The interactive web Stats Lab. PUBLIC read-only — it shows the same community
        # game stats already visible on the Discord boards, so it needs no gate. (Was
        # token-gated via a /correlate-minted link; now one model with the Hall of Fame.)
        # Record an anonymous open for the usage counter; a public URL has no per-user id.
        try:
            from utils.db import record_lab_open
            await record_lab_open(None, None)
        except Exception:
            pass
        try:
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "lab.html")
            with open(_p, encoding="utf-8") as f:
                html = f.read()
        except Exception:
            return web.Response(status=500, text="lab page missing")
        # no-cache so a deploy's page changes reach everyone without a hard refresh
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    _lab_data_cache = {"body": None, "ts": 0.0}

    async def lab_data(request):
        # Per-run numeric+categorical records for the Lab to filter and correlate
        # client-side. PUBLIC (same as the page). The serialized payload is cached ~30s
        # so reloads can't hammer the DB/CPU, and every visitor's first paint is cheap.
        import time as _t
        now = _t.time()
        if _lab_data_cache["body"] is not None and (now - _lab_data_cache["ts"]) < 30:
            return web.Response(text=_lab_data_cache["body"], content_type="application/json")
        try:
            from utils.db import get_all_submissions, get_all_players, get_name_to_id_map
            rows = await get_all_submissions()
        except RuntimeError:
            return web.Response(status=503, text="database unavailable")
        # Condense IGN variants: resolve every run to the player's canonical registry
        # name (by discord_id, or by IGN for legacy blank-id runs), so name changes
        # and "Name, Title" variants collapse into one entry across the whole Lab.
        _did2canon, _name2did, _pmarks = {}, {}, []
        try:
            for _pr in await get_all_players():
                if not _pr or len(_pr) < 2:
                    continue
                _d, _n = (_pr[0] or '').strip(), (_pr[1] or '').strip()
                if _d and _n:
                    _did2canon[_d] = _n
                # players.total_marks (index 3) — the stored all-time career marks tally,
                # for the Lab's Career-marks ranking. Keyed by id + name so the client
                # can match either a did-backed run or a name-keyed legacy one.
                try:
                    _mk = int(_pr[3]) if len(_pr) > 3 and _pr[3] not in (None, '') else 0
                except (ValueError, TypeError):
                    _mk = 0
                if _mk > 0 and (_d or _n):
                    _pmarks.append([_anon_id(_d), _n, _mk])
            _name2did = await get_name_to_id_map()
        except Exception as _ce:
            print(f"[LAB] canonical-name map failed: {_ce}")
        import utils.stats_engine as _SE
        fields = _SE.RECORD_FIELDS
        recs = _SE.records(rows)
        for _rec in recs:
            _d = _rec.get('did') or _name2did.get((_rec.get('name') or '').strip().lower())
            _canon = _did2canon.get(_d)
            if _canon:
                _rec['name'] = _canon
                if _d:
                    _rec['did'] = _d   # backfill id so galaxy/filter merge legacy runs too
        # Emit the anon hash for did (never the raw snowflake); every other field verbatim.
        data = [[(_anon_id(_rec.get(f)) if f == 'did' else _rec.get(f)) for f in fields] for _rec in recs]
        # Leaderboard boards (weapon/map/feat) for the web Boards tab — a 1:1 mirror of the
        # Discord boards: stored Takedowns entries + the same live Kills / Lethality /
        # Warlord sections, computed by the board cog's own functions.
        import config as _cfg
        _boards = {}
        try:
            from cogs.leaderboards import build_boards_payload
            _boards = await build_boards_payload()
        except Exception as _be:
            print(f"[LAB] boards build failed: {_be}")
        try:
            _emoji = {"factions": _cfg.FACTION_EMOJIS,
                      "titles": {"Lethality": _cfg.TITLE_EMOJIS.get("Lethality", ""),
                                 "Warlord": _cfg.TITLE_EMOJIS.get("Warlord", "")}}
        except Exception:
            _emoji = {}
        body = json.dumps({"fields": fields, "rows": data, "player_marks": _pmarks,
                           "stat_labels": {k: v[1] for k, v in _SE.STAT_EXTRACTORS.items()},
                           "boards": _scrub_ids(_boards), "emoji": _emoji},
                          default=str, ensure_ascii=False)
        _lab_data_cache["body"], _lab_data_cache["ts"] = body, now
        return web.Response(text=body, content_type="application/json")

    _hof_cache = {"body": None, "ts": 0.0}

    async def hof_data(request):
        # Public Hall of Fame JSON: every season's champions/standings/category winners.
        # Read-only, cached ~60s. Numbers come from the SAME season_total path as the
        # bot embeds, so the page and Discord can never disagree.
        import time as _t
        now = _t.time()
        if _hof_cache["body"] is not None and (now - _hof_cache["ts"]) < 60:
            return web.Response(text=_hof_cache["body"], content_type="application/json")
        try:
            from cogs.favourites import build_hof_payload
            payload = await build_hof_payload()
        except RuntimeError:
            return web.Response(status=503, text="database unavailable")
        except Exception as _e:
            print(f"[HOF] data build error: {_e}")
            return web.Response(status=500, text="hall of fame unavailable")
        body = json.dumps(payload, default=str, ensure_ascii=False)
        _hof_cache["body"], _hof_cache["ts"] = body, now
        return web.Response(text=body, content_type="application/json")

    _card_cache = {}   # player-name (lower) -> (body, ts)

    async def card_data(request):
        # One player's registry card as markdown — the SAME content build_registry_messages
        # produces for Discord, so the web card mirrors the Discord card. Cached ~60s/player.
        p = (request.query.get("p") or "").strip()
        if not p:
            return web.Response(status=400, text="?p= (player name) required")
        import time as _t
        now = _t.time()
        _hit = _card_cache.get(p.lower())
        if _hit and (now - _hit[1]) < 60:
            return web.Response(text=_hit[0], content_type="application/json")
        try:
            from utils.db import get_name_to_id_map, get_all_players
            from cogs.registry import build_registry_messages
            n2i = await get_name_to_id_map()
            did = n2i.get(p.lower(), "")
            name = p
            # Known-player set from data we already have to hand. Fast-404 an unknown
            # name BEFORE the expensive registry build, so an attacker can't bust the
            # per-name cache with junk ?p= values and force a build on every request.
            known = set(n2i.keys())
            for _pr in await get_all_players():
                if not _pr or len(_pr) < 2:
                    continue
                _pn = (_pr[1] or "").strip()
                if _pn:
                    known.add(_pn.lower())
                if (_pr[0] or "").strip() == did and did and _pn:
                    name = _pn
            if p.lower() not in known:
                return web.Response(status=404, text="no such player")
            guild = bot.get_guild(config.GUILD_ID)
            msgs = await build_registry_messages(name, did, guild=guild)
        except RuntimeError:
            return web.Response(status=503, text="database unavailable")
        except Exception as _e:
            print(f"[CARD] web card error for {p!r}: {_e}")
            return web.Response(status=500, text="card unavailable")
        # did is anonymized (hash) — the public card never carries a raw snowflake.
        body = json.dumps({"name": name, "did": _anon_id(did), "messages": msgs},
                          default=str, ensure_ascii=False)
        if len(_card_cache) > 200:
            _card_cache.clear()
        _card_cache[p.lower()] = (body, now)
        return web.Response(text=body, content_type="application/json")

    async def hof_page(request):
        # Public Hall of Fame page. No token — it's a showcase of season champions.
        try:
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "hof.html")
            with open(_p, encoding="utf-8") as f:
                html = f.read()
        except Exception:
            return web.Response(status=500, text="hall of fame page missing")
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    _bounty_cache = {"body": None, "ts": 0.0}

    async def bounty_data(request):
        # Slim public snapshot of the active monthly bounty for the landing page.
        # Completion names are already public in Discord; we return just a count.
        # Cached ~60s so the landing page can't hammer the DB.
        import time as _t
        now = _t.time()
        if _bounty_cache["body"] is not None and (now - _bounty_cache["ts"]) < 60:
            return web.Response(text=_bounty_cache["body"], content_type="application/json")
        try:
            from cogs.bounty import get_active_bounty
            b = await get_active_bounty()
        except RuntimeError:
            return web.Response(status=503, text="database unavailable")
        except Exception as _e:
            print(f"[BOUNTY] web data error: {_e}")
            return web.Response(status=500, text="bounty unavailable")
        if not b:
            payload = {"active": False}
        else:
            _w = b.get("weapons") or {}
            payload = {
                "active": True,
                "title": b.get("title") or "",
                "theme_emoji": b.get("theme_emoji") or "",
                # Just the objective target per weapon — no internal tracking fields.
                "weapons": {k: (v.get("total") if isinstance(v, dict) else v) for k, v in _w.items()},
                "special_challenge": b.get("special_challenge") or "",
                "completions": len(b.get("completions") or []),
                "start_date": b.get("start_date"),
            }
        body = json.dumps(payload, default=str, ensure_ascii=False)
        _bounty_cache["body"], _bounty_cache["ts"] = body, now
        return web.Response(text=body, content_type="application/json")

    # "Apply to join": public form -> pending request posted to the admin channel for
    # mod accept/deny -> applicant's status page reveals a single-use invite on accept.
    _join_rl = {"t": [], "ip": {}}   # global bucket + per-IP last-apply time
    _oauth_sessions = {}             # sid -> {did, uname, handle, avatar, ts}

    def _oauth_conf():
        cid = getattr(config, "DISCORD_CLIENT_ID", 0)
        sec = os.environ.get("DISCORD_CLIENT_SECRET", "")
        redir = os.environ.get("OAUTH_REDIRECT_URI", "") or getattr(config, "OAUTH_REDIRECT_URI", "")
        return (str(cid) if cid else ""), sec, redir

    def _oauth_ready():
        cid, sec, redir = _oauth_conf()
        return bool(cid and sec and redir)

    def _current_oauth(request):
        import time as _t
        s = _oauth_sessions.get(request.cookies.get("join_sid", ""))
        if not s:
            return None
        if _t.time() - s["ts"] > 3600:
            return None
        return s

    async def join_page(request):
        # Serves both the application form and (with ?id=&t=) the status view — one file.
        try:
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "join.html")
            with open(_p, encoding="utf-8") as f:
                html = f.read()
        except Exception:
            return web.Response(status=500, text="join page missing")
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    async def join_login(request):
        import secrets as _secrets
        from urllib.parse import quote as _q
        cid, sec, redir = _oauth_conf()
        if not (cid and sec and redir):
            raise web.HTTPFound("/join")
        state = _secrets.token_urlsafe(16)
        url = ("https://discord.com/oauth2/authorize?response_type=code&scope=identify"
               f"&client_id={cid}&redirect_uri={_q(redir, safe='')}&state={state}")
        resp = web.HTTPFound(url)
        resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="Lax")
        raise resp

    async def join_callback(request):
        import secrets as _secrets, time as _t
        cid, sec, redir = _oauth_conf()
        if not (cid and sec and redir):
            raise web.HTTPFound("/join")
        code = request.query.get("code", "")
        state = request.query.get("state", "")
        if not code or not state or state != request.cookies.get("oauth_state", ""):
            raise web.HTTPFound("/join?e=oauth")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post("https://discord.com/api/oauth2/token", data={
                        "client_id": cid, "client_secret": sec, "grant_type": "authorization_code",
                        "code": code, "redirect_uri": redir}) as tr:
                    if tr.status != 200:
                        raise web.HTTPFound("/join?e=oauth")
                    access = (await tr.json()).get("access_token")
                async with sess.get("https://discord.com/api/users/@me",
                                    headers={"Authorization": f"Bearer {access}"}) as ur:
                    if ur.status != 200:
                        raise web.HTTPFound("/join?e=oauth")
                    u = await ur.json()
        except web.HTTPException:
            raise
        except Exception as _e:
            print(f"[OAUTH] callback error: {_e}")
            raise web.HTTPFound("/join?e=oauth")
        _now = _t.time()
        for _k in [k for k, v in _oauth_sessions.items() if _now - v["ts"] > 3600]:
            _oauth_sessions.pop(_k, None)
        sid = _secrets.token_urlsafe(24)
        _oauth_sessions[sid] = {
            "did": str(u.get("id") or ""),
            "uname": (u.get("global_name") or u.get("username") or "")[:100],
            "handle": (u.get("username") or "")[:100],
            "avatar": (u.get("avatar") or ""),
            "ts": _now}
        resp = web.HTTPFound("/join")
        resp.del_cookie("oauth_state")
        resp.set_cookie("join_sid", sid, max_age=3600, httponly=True, samesite="Lax")
        raise resp

    async def join_me(request):
        if not _oauth_ready():
            return web.json_response({"oauth": False})
        s = _current_oauth(request)
        if not s:
            return web.json_response({"oauth": True, "signed_in": False})
        av = (f"https://cdn.discordapp.com/avatars/{s['did']}/{s['avatar']}.png"
              if s.get("avatar") else "")
        return web.json_response({"oauth": True, "signed_in": True,
                                  "username": s["uname"], "avatar": av})

    async def join_apply(request):
        import time as _t, secrets as _secrets
        now = _t.time()
        ip = (request.headers.get("X-Forwarded-For", "") or request.remote or "").split(",")[0].strip()
        _join_rl["ip"] = {k: v for k, v in _join_rl["ip"].items() if now - v < 3600}
        if ip and now - _join_rl["ip"].get(ip, 0) < 30:
            return web.json_response({"error": "Please wait a moment before applying again."}, status=429)
        _join_rl["t"] = [x for x in _join_rl["t"] if now - x < 600]
        if len(_join_rl["t"]) >= 30:
            return web.json_response({"error": "Too many applications right now — try again shortly."}, status=429)
        try:
            data = await request.post()
        except Exception:
            return web.json_response({"error": "bad form"}, status=400)
        ign = (data.get("ign") or "").strip()[:80]
        note = (data.get("note") or "").strip()[:500]
        if not ign:
            return web.json_response({"error": "Please enter a name or in-game name."}, status=400)
        # When OAuth is configured, the applicant must be signed in with Discord; the
        # verified identity comes from the server-side session, never from the client.
        did = uname = avatar = None
        if _oauth_ready():
            s = _current_oauth(request)
            if not s:
                return web.json_response({"error": "Please sign in with Discord first.", "signin": True}, status=401)
            did, uname, avatar = s["did"], s["uname"], s.get("avatar")
        token = _secrets.token_urlsafe(16)
        try:
            from utils.db import create_join_request
            req_id = await create_join_request(token, ign, note,
                                               discord_id=did, discord_username=uname, avatar=avatar)
        except RuntimeError:
            return web.json_response({"error": "database unavailable — try again shortly"}, status=503)
        except Exception as _e:
            print(f"[JOIN] apply failed: {_e}")
            return web.json_response({"error": "couldn't file your request"}, status=500)
        cog = bot.get_cog("JoinCog")
        if cog is not None:
            try:
                await cog.post_request(req_id, ign, note, discord_id=did, discord_username=uname)
            except Exception as _pe:
                print(f"[JOIN] post_request error: {_pe}")
        _join_rl["t"].append(now)
        if ip:
            _join_rl["ip"][ip] = now
        return web.json_response({"id": req_id, "token": token})

    async def join_state(request):
        try:
            rid = int(request.query.get("id", 0))
        except ValueError:
            return web.json_response({"error": "bad id"}, status=400)
        tok = request.query.get("t", "")
        try:
            from utils.db import get_join_request
            req = await get_join_request(rid)
        except Exception:
            return web.json_response({"error": "unavailable"}, status=503)
        if not req or req["token"] != tok:
            return web.json_response({"status": "unknown"}, status=404)
        out = {"status": req["status"]}
        if req["status"] == "accepted" and req.get("invite_url"):
            out["invite"] = req["invite_url"]
        return web.json_response(out)

    @web.middleware
    async def _security_headers(request, handler):
        # Baseline hardening on every response. (No CSP: the pages use inline scripts,
        # so a strict policy would need nonces for little gain on a read-only stats site.)
        resp = await handler(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return resp

    app = _web_app
    app.middlewares.append(_security_headers)
    app.router.add_get("/", handle)
    app.router.add_post("/kofi", kofi_webhook)
    app.router.add_get("/export/submissions", export_submissions)
    app.router.add_get("/lab", lab_page)
    app.router.add_get("/lab/data", lab_data)
    app.router.add_get("/hof", hof_page)
    app.router.add_get("/hof/data", hof_data)
    app.router.add_get("/lab/card", card_data)
    app.router.add_get("/bounty/data", bounty_data)
    app.router.add_get("/join", join_page)
    app.router.add_get("/join/status", join_page)
    app.router.add_get("/join/login", join_login)
    app.router.add_get("/join/callback", join_callback)
    app.router.add_get("/join/me", join_me)
    app.router.add_post("/join/apply", join_apply)
    app.router.add_get("/join/state", join_state)
    # Static assets (weapon PNGs, decorative board borders) for the web Boards tab.
    try:
        _assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        if os.path.isdir(_assets_dir):
            app.router.add_static("/assets", _assets_dir, show_index=False)
    except Exception as _ae:
        print(f"[WEB] static assets route failed: {_ae}")
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Healthcheck server running on port {port}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# Safe mention default: the Butler's AI replies echo user-influenced text, so a
# prompt-injected "@everyone" must never actually ping. everyone/roles OFF blocks
# the mass-ping vector; users ON keeps legitimate <@id> references working.
bot = commands.Bot(
    command_prefix="!", intents=intents,
    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
)

COGS = [
    "cogs.registry",
    "cogs.leaderboards",
    "cogs.bounty",
    "cogs.submissions",
    "cogs.favourites",
    "cogs.personality",
    "cogs.admin",
    "cogs.kofi",
    "cogs.join",
    "cogs.suggestions",
]


@bot.event
async def on_ready():
    from datetime import datetime, timezone
    # on_ready also fires on reconnects. Only sync commands (rate-limited API)
    # and stamp session_start on the FIRST ready of the process.
    if getattr(bot, "_synced", False):
        print("↻ Reconnected — skipping command re-sync.")
        return
    bot._synced = True
    bot.session_start = datetime.now(timezone.utc)
    print(f"✅ Session started at {bot.session_start.isoformat()}")
    try:
        from utils.helpers import set_bot_ref
        set_bot_ref(bot)
    except Exception as _sbe:
        print(f"[STARTUP] set_bot_ref failed: {_sbe}")
    try:
        guild = discord.Object(id=config.GUILD_ID)
        # Sync all commands to the guild only (global list already cleared)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} slash commands to guild")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")


@bot.event
async def on_error(event_method, *args, **kwargs):
    """Any unhandled error in an event handler → nerve centre, so crashes surface
    in seconds instead of going unnoticed."""
    err = traceback.format_exc()
    print(f"[ON_ERROR] {event_method}:\n{err}")
    try:
        from utils.helpers import nerve_alert
        await nerve_alert(bot, f"event:{event_method}", err)
    except Exception:
        pass


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    if isinstance(error, discord.app_commands.CommandNotFound):
        # Benign and self-resolving: a client invoked a command the running instance
        # hasn't synced yet — normal right after a deploy while clients hold a stale
        # command cache (Ctrl+R fixes it). Do NOT nerve-alert or log an error for it,
        # or every deploy spams a fake failure into the nerve centre + event log.
        print(f"[CMD] ignored stale/unknown command invocation: {error}")
        return
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        retry = int(error.retry_after)
        minutes, seconds = divmod(retry, 60)
        time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        await interaction.response.send_message(
            f"Easy — your card was just refreshed. Try again in {time_str}.",
            ephemeral=True,
        )
    elif isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.",
            ephemeral=True,
        )
    else:
        # Unexpected command failure — surface it to the nerve centre immediately
        # and let the user know, instead of failing silently.
        from utils.helpers import nerve_alert
        _cmd = getattr(interaction.command, "name", "?")
        try:
            await nerve_alert(interaction.client, f"/{_cmd}", error)
        except Exception:
            pass
        try:
            _msg = "Something went wrong there — the Butler has made a note of it."
            if interaction.response.is_done():
                await interaction.followup.send(_msg, ephemeral=True)
            else:
                await interaction.response.send_message(_msg, ephemeral=True)
        except Exception:
            pass
        traceback.print_exc()


async def _graceful_shutdown():
    _shared.set_shutting_down()
    print("[SHUTDOWN] SIGTERM received — draining active submissions...")
    for _ in range(60):
        if _shared.active_submissions() == 0:
            break
        await asyncio.sleep(0.5)
    print(f"[SHUTDOWN] Drained ({_shared.active_submissions()} remaining). Closing bot.")
    await bot.close()


async def main():
    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.ensure_future(_graceful_shutdown())
        )
    except NotImplementedError:
        # Windows (local dev) has no loop signal handlers — Railway/Linux does.
        print("⚠️  SIGTERM handler unavailable on this platform — skipping graceful drain.")
    await run_healthcheck()
    # Initialise Postgres pool if DATABASE_URL is configured
    if os.environ.get('DATABASE_URL'):
        from utils.db import db_init, db_close
        await db_init()
        bot._db_close = db_close
    else:
        bot._db_close = None
        print("⚠️  DATABASE_URL not set — Postgres pool skipped")
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")
                traceback.print_exc()
        try:
            await bot.start(config.TOKEN)
        except discord.HTTPException as e:
            # 429 at login means Discord/Cloudflare rate-limited the token — usually
            # from rapid redeploys/restarts. Back off hard instead of exiting fast, so
            # we don't crash-loop into a Cloudflare 1015 IP ban. The healthcheck server
            # is already running, so Railway keeps the container alive during the wait
            # rather than restarting straight into another login attempt.
            if getattr(e, "status", None) == 429:
                print("[LOGIN] 429 rate limited on login — backing off 15 min before exit "
                      "to let the rate limit / Cloudflare ban clear.")
                await asyncio.sleep(900)
            raise
        finally:
            if bot._db_close:
                await bot._db_close()


if __name__ == "__main__":
    asyncio.run(main())

# 🎩 The Butler

> *The lounge does not run itself.*

A full-stack project for the **Cigar Lounge**, a competitive [Chivalry 2](https://www.chivalry2.com/) community: a Discord bot **and** the public web app it serves, from a single process. Players post in-game scorecards, vision AI reads them, and everything flows into live leaderboards, seasons, player cards, and a public stats site.

🌐 **Live site — [thecigarlounge.app](https://thecigarlounge.app)**

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![aiohttp](https://img.shields.io/badge/web-aiohttp-2C5BB4?logo=aiohttp&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/data-PostgreSQL-336791?logo=postgresql&logoColor=white)
![Railway](https://img.shields.io/badge/hosted-Railway-0B0D0E?logo=railway&logoColor=white)
![OpenAI](https://img.shields.io/badge/AI-GPT--5.6_Luna-10A37F?logo=openai&logoColor=white)
![Gemini](https://img.shields.io/badge/AI-Gemini_Flash-4285F4?logo=google&logoColor=white)

> 📐 System design & data-flow diagrams: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**
> 🧭 Codebase map & conventions (start here if you're new): **[CLAUDE.md](CLAUDE.md)**
> 🔧 Symptom → fix cheat sheet: **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**
> 🛡️ Mod command reference: **[ADMIN_COMMANDS.md](ADMIN_COMMANDS.md)**

---

## Features

### 📋 Submission Flow
Players post a screenshot of their in-game scorecard. Vision AI (Gemini) reads the stats automatically. Players confirm class and weapon, then the Butler logs the run to the database. Includes VIP detection, triple-kill verification, emoji reactions, and a formatted confirmation reply with an edit button. Vision failures fall back to a manual entry form.

The submission blurb includes live team context parsed from the scoreboard image: warlord emoji + TD share percentage, kill share percentage with lethality emoji, and feat reactions for notable runs.

```mermaid
flowchart TD
    A([Player posts screenshot]) --> B[Gemini Vision reads scoreboard]
    B --> C{Stats detected?}
    C -->|Yes| D[Confirm screen\nclass · weapon · map · faction · stats]
    C -->|No| E[Manual entry form\nclass → weapon → map → faction → stats]
    D --> F{Player confirms}
    E --> F
    F -->|Change| G[Edit fields] --> F
    F -->|Confirm| H[Write to PostgreSQL]

    H --> I[Post summary reply\nwarlord · TD share · kill share]
    H --> J[React to screenshot]
    H --> K[Update leaderboards]
    H --> L[Update registry card]
    H --> M[Bounty check]

    J --> J0[cigar — always]
    J --> J1{Stat feats?}
    J1 -->|0 deaths| J2[flawless]
    J1 -->|100+ kills| J3[100 kills]
    J1 -->|200+ TDs| J4[200 TDs]
    J1 -->|150 TD · 0 deaths| J5[predator]
    J1 -->|150 TD · 100K · 20k score| J6[triple]
    J1 -->|30+ deaths| J7[lounger]
    J1 -->|Kills > next teammate TDs| J8[TUFF]

    J --> J9{Personal best\non weapon board?}
    J9 -->|Yes — not VIP · not ranged| J10[weapon HS]

    K --> K1{Leaderboard\nupdated?}
    K1 -->|Yes| K2[high score react\nPlacement added to summary]

    M --> M1{Bounty weapon hit?}
    M1 -->|Yes| M2[bounty react]
    M2 --> M3{All weapons\ncomplete?}
    M3 -->|Yes| M4[Bounty completion\nannounced in main]

    classDef default fill:#1e1e2e,stroke:#89b4fa,color:#cdd6f4
    classDef decision fill:#313244,stroke:#cba6f7,color:#cdd6f4
    classDef action fill:#1e3a5f,stroke:#89b4fa,color:#cdd6f4
    classDef db fill:#1a3a2a,stroke:#a6e3a1,color:#a6e3a1
    classDef summary fill:#3a2a1a,stroke:#fab387,color:#fab387
    classDef feat fill:#2a1a3a,stroke:#cba6f7,color:#cba6f7
    classDef start fill:#313244,stroke:#f38ba8,color:#f38ba8

    class A start
    class C,F,J1,K1,M1 decision
    class D,E,G action
    class H db
    class I,K,L,M,K2,M2 summary
    class J2,J3,J4,J5,J6,J7,J8 feat
```

### 🏆 Leaderboards
Live weapon leaderboards for all 1H and 2H weapons, plus map boards and feat boards. Multi-message chunking handles large boards. Shared weapons across subclasses are deduplicated by `(weapon, subclass)` key.

### 📇 Registry Cards
Per-player forum threads in the Butler's Archive. Weapon marks are merged from live submissions, leaderboard data, and legacy records. Includes class rank progression, personal bests (with best **lethality vs the lounge average on that weapon**), Best Placements sorted by dominance gap (gap between 1st and 2nd place), a **Feats of Legend** ladder, and a **Legendary Games** trophy cabinet — a capped, variety-balanced set of your most impressive feat games, best-of-each-type first, each linking to the actual match. `/repair_marks` backfills missing High Score marks in bulk.

Ask the Butler to **"show me my stats"** for a live emoji **dossier** embed of the same profile — title/rank, marks, signature arms with rank badges, best game, lethality-vs-lounge, feats, archetype, Hundred-Handed, and a per-player *Curio* (career totals plus the map they're most over-indexed on versus the lounge).

### 🎖️ Butler's Report
Weekly stats and all-time prestige titles posted as a Discord embed. Titles recalculated after every submission — one holder per title at a time, with a stability margin so a title only changes hands when a challenger clearly beats the current holder. Weekly stats reset each Monday.

| Title | Criteria |
|---|---|
| **Grand Marshal** | Most leaderboard breadth — 15+ boards across all categories, ranked by average placement |
| **Weapons Master** | 9+ weapon leaderboards, ranked by average placement |
| **Campaign Master** | 6+ map leaderboards, ranked by average placement |

Weekly stats include **Lethality** (kills per takedown), **Warlord** (your share of your team's takedowns), Busiest player, Top Weapons, and Top Maps. The Lethality and Warlord ratings use a recency-weighted, volume-adjusted (Bayesian) average, so a handful of lucky games can't top the board — 3-run minimum.

### 🌐 Public Website — [`thecigarlounge.app`](https://thecigarlounge.app)
The bot **co-hosts a public, read-only web app** (aiohttp, no framework) from the same process, on a custom domain with automatic HTTPS. Every surface is drawn live from the same database the Discord boards use, so the two can never disagree.

- **Stats Lab** — an interactive, client-side explorer over every run: weapon / map / feat leaderboards that mirror Discord 1:1 (Discord CDN emoji + local weapon art), **player cards** with recent-form sparklines, records, per-player rankings, and deep-dive views — correlation matrix, scatter, "galaxy" clustering, trends, and head-to-head compare — all filtered in the browser with no page reloads.
- **Hall of Fame** — season champions, Grand-Prix standings, per-category top 5s, and the all-time title holders.
- **Landing page** — headline stats (live count-ups), the month's active bounty, and how the community works.

Built with vanilla JS + inline SVG (no build step) and an auto-escaping `` html`` `` templating helper for XSS safety. Hardened for public exposure: anonymized player IDs, per-IP and global rate limits, and baseline security headers.

In-Discord, `/explore` and `/correlate` render the same analyses as themed charts for players who never leave chat.

### 🎟️ Apply to Join — Discord OAuth
A public **"Apply to join"** flow. Applicants **sign in with Discord** (OAuth2, `identify` scope) so their real account is verified on the request, fill a short form, and it posts to a mod channel with **Accept / Deny** buttons. On approval the bot mints a **single-use invite** the applicant retrieves from a status page. New arrivals get a **Guest** role, auto-promoted to **Lounger** on their first submission.

### 💡 Bounty Suggestion Box
`/suggest_bounty` posts community bounty ideas to a public board with 👍 upvotes, **auto-threaded** for discussion and ranked on a **live pinned leaderboard**. Mods shortlist / use / dismiss from the card; using one fires a Butler shout-out crediting the suggester.

### 🎯 Bounty System
Monthly bounty cards with per-player progress tracking, a live Top Hunters board, and archival on completion. Supports per-weapon custom targets. Player commands: `/bounty_hunt`, `/my_bounty`, `/bounty_status`.

### 🗂 Ledger Entrance
A master index channel linking to every forum section in sidebar order: challenge rules, Butler's favourites, active bounty, archive, map records, 2H weapons, 1H weapons, and feats of war. Bounty emoji rotates with the active bounty. Rebuilt automatically after leaderboard updates and on demand via `/ledger_refresh`.

### 🧠 Nerve Center Digest
Hourly summary posted to a private channel covering submissions, milestones, Butler interactions, and keyword mentions. Cross-container dedup prevents double-posts on rolling deploys. Silent when there is nothing to report.

### ⚠️ Anomaly Detection
Flags suspicious runs to a private notes channel when stats exceed 2x the server record or a leaderboard gap exceeds 80%. `/remove_submission` rolls back fraudulent entries; `/unlist_submission` toggles a legit-but-unfair run (lopsided lobby, farm game) off all boards and records while keeping its marks and bounty progress.

### 🔎 Observability & Evals
A persistent `bot_events` log (Postgres, 30-day retention) captures errors, deploys, vision misses, Butler Q&A, and **suspected stat fabrications** — a grounding check that flags any number the Butler cites in a data answer that isn't present in the context it was given. Reviewed with `/logs`, delivered as a **weekly rollup** to the nerve centre, and it survives Railway's ~1000-line log truncation. A growing regression **eval suite** (`tests/test_regressions.py`, `tests/integration/`, `docs/EVALS.md`) pins every fixed bug so it can't silently return.

### 🃏 Butler Personality
Dry, sardonic responses to pings and unprompted one-liners in the main channel every few hours. Dry-spell warnings after 48 hours of inactivity. Answers player questions about stats, leaderboard standings, weapon **kill vs takedown records**, the current **bounty/season timeline** ("when does the bounty end"), stats about **@mentioned players**, and Hundred-Handed progress using live database context. Reply *structure* varies (he doesn't always end on a quip), and attempts to reprogram his voice or persona ("talk in uwu", "ignore your instructions") are refused flatly rather than obeyed. Powered by OpenAI GPT-5.6 Luna.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.13 |
| Bot framework | discord.py 2.x |
| Web server | aiohttp (co-hosted in the bot process) |
| Web frontend | Vanilla JS + inline SVG, no build step |
| Auth | Discord OAuth2 (`identify`) |
| Data | PostgreSQL (asyncpg) |
| AI — Butler chat | OpenAI GPT-5.6 Luna |
| AI — Scoreboard vision | Google Gemini Flash |
| Hosting / TLS | Railway + custom domain (auto-HTTPS) |
| Tests | pytest (pure-logic + integration) |
| Version control | GitHub |

---

## Running It / Development

```bash
git clone <this repo>
cd CigarLoungeButler
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

Environment variables (via `.env` locally, Railway variables in production):

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Bot token |
| `DATABASE_URL` | for real use | Postgres connection string. The bot boots without it, but nearly everything needs it. Apply `schema.sql` once; later migrations run automatically at startup. |
| `OPENAI_API_KEY` | optional | Butler chat/quips (falls back to canned lines) |
| `GOOGLE_AI_API_KEY` | optional | Scorecard vision (falls back to manual entry) |
| `KOFI_TOKEN` | optional | Ko-fi webhook verification (`POST /kofi`) |
| `EXPORT_TOKEN` | optional | Enables `GET /export/submissions`, a bearer-token, read-only cursor export of the submissions table for community mirrors. Off when unset. Also the default signing secret for the Stats Lab. |
| `LAB_BASE_URL` | optional | Public base URL of the web app (e.g. `https://thecigarlounge.app`). Powers the absolute links the bot posts (Hall of Fame, Stats Lab, `/setup_lounge`). |
| `DISCORD_CLIENT_ID` · `DISCORD_CLIENT_SECRET` | optional | Discord OAuth for the "Apply to join" flow. Without them the apply form still works anonymously; the secret comes from the environment and is never committed. |
| `OAUTH_REDIRECT_URI` | optional | Must exactly match the redirect registered in the Discord Developer Portal (e.g. `https://thecigarlounge.app/join/callback`). |
| `PORT` | optional | Web / healthcheck server port (default 8080) |

All server-specific IDs (guild, channels, roles, emojis) live in `config.py`; a
fork pointed at a different server needs those replaced. Tests are pure-logic
and need no Discord or DB: `pytest -q`.

Before writing code, read **[CLAUDE.md](CLAUDE.md)**. It covers the row
shapes, the hot-path query rules, and known gotchas.

---

## Architecture Notes

- **Submission queue** serialises concurrent submissions per guild to prevent race conditions
- **PostgreSQL via asyncpg** replaced Google Sheets as the data layer; all reads/writes go through `utils/db.py`
- **Registry cards** edited in-place (never deleted or recreated) for stable thread ID references
- **Shared weapons** keyed as `(weapon, subclass)` tuples to prevent double-counting across subclasses
- **Discord cache** falls back to `fetch_channel()` / `fetch_thread()` after restarts
- **Bulk imports** suppress per-card updates and milestone announcements; index rebuilt once at completion
- **Manual feat count floors** allow mods to correct historical undercounts via `/set_feat_count` without suppressing future auto-detection
- **Player names are sanitized** (`utils.parsing.md_safe`) before going into markdown links, so a crafted display name can't inject its own hyperlink into a board or card
- **Butler answers are grounded** — a check flags any stat he cites that isn't in the context he was given (anti-fabrication), logged for review rather than shown to players
- **Persistent event log** (`bot_events`) survives restarts and log truncation; reviewed via `/logs` and an auto-posted weekly rollup
- **The web app runs in the bot process** — aiohttp routes are registered before the site starts (the router freezes on boot), and the same healthcheck endpoint lets Railway restart a zombied gateway
- **Public payloads anonymize Discord IDs** — a salted hash replaces the raw snowflake so the open web never leaks a name→account map, while the client keeps a stable key for grouping
- **Web player cards preload shared tables once** and reuse them across ~20 registry helpers, turning a cold build's ~30 full-table scans into a handful — cards render in well under a second

---

*Designed, built, and maintained solo for a live competitive community — Discord bot, database, and public web app end to end. Poking around? Start with [CLAUDE.md](CLAUDE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).*

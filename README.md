# 🎩 The Butler

> *The lounge does not run itself.*

A Discord bot for the **Cigar Lounge** — a competitive [Chivalry 2](https://www.chivalry2.com/) community. The Butler automates the full submission and tracking workflow: players post in-game scorecards, and the bot handles the rest.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![Railway](https://img.shields.io/badge/hosted-Railway-0B0D0E?logo=railway&logoColor=white)
![Google Sheets](https://img.shields.io/badge/data-Google_Sheets-34A853?logo=googlesheets&logoColor=white)
![Claude](https://img.shields.io/badge/AI-Claude_Haiku-D97706)

---

## Features

### 📋 Submission Flow
Players submit a screenshot of their in-game scorecard. The Butler walks them through a 5-step ephemeral form (class → subclass → weapon → map → faction → stats) and logs the run to Google Sheets. Includes VIP detection, triple kill checks, feat detection, emoji reactions, and a confirmation post.

### 🏆 Leaderboards
Live weapon leaderboards across all 1H and 2H weapons, plus map boards and feat boards. Chunked multi-message support for large boards. Deduplicates shared weapons across subclasses.

### 📇 Registry Cards
Per-player forum threads in the Butler's Archive. Weapon marks merged from live submissions, leaderboard data, and legacy records — keyed by `(weapon, subclass)` to prevent double-counting. Includes subclass/class rank progression and Best Placements sorted by dominance gap.

### 🎖️ Butler's Favourites
Weekly prestige report. Tracks five titles with auto role assignment:

| Title | Criteria |
|---|---|
| **Grand Marshal** | Most kills |
| **Weapons Master** | Most weapon marks |
| **Campaign Master** | Best TD/kill ratio (Warlord) |
| **Headhunter** | Best kill rate % (Lethality) |
| **Butcher** | Most team damage dealt |

### 🎯 Bounty System
Active bounty cards with per-player progress tracking, a live Top Hunters board, and archival on bounty end. Supports per-weapon custom targets. Public commands: `/bounty_hunt`, `/my_bounty`, `/bounty_status`.

### 🧠 Nerve Center Digest
Hourly summary posted to a private channel — submissions, milestones, Butler interactions, and errors. Quiet when nothing happened; dry when something did.

### ⚠️ Anomaly Detection
Flags suspicious runs to a private notes channel when kills or team damage exceed 2× the server record, or when a leaderboard gap exceeds 80%. `/remove_submission` rolls back fraudulent entries.

### 🃏 Butler Personality
Dry, first-person responses to pings. Unprompted one-liners in the main channel every few hours. Dry-spell warnings after 48 hours of silence. Powered by Claude Haiku.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11 |
| Bot framework | discord.py 2.x |
| Data | Google Sheets (gspread) |
| AI | Anthropic Claude Haiku |
| Hosting | Railway (auto-deploy on push) |
| Version control | GitHub |

---

## Architecture Notes

- **Submission queue** serialises concurrent submissions per guild to prevent race conditions
- **SheetCache** TTL class reduces Sheets API calls; invalidated on writes
- **Registry cards** edit-in-place (never delete/recreate) for stable thread ID references
- **Shared weapons** keyed as `(weapon, subclass)` tuples to prevent double-counting across classes
- **Discord cache** always falls back to `fetch_channel()` / `fetch_thread()` after restarts
- **Bulk imports** suppress per-card updates and milestone announcements; index rebuilt once at completion
- **Google Sheets IDs** stored as plain text to prevent 18-digit snowflake corruption

---

*Private repository. Not open for contributions.*

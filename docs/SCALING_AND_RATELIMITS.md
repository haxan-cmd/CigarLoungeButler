# Scaling, Rate Limits & "What Can We Get Away With"

Written August 2026. Grounded in Discord's published rate-limit rules; exact
per-route numbers come from response headers and shouldn't be hardcoded.

## Bottom line first

Discord rate limits are **not** your constraint at current scale. One bot has
enormous headroom for a single-guild community your size. The only place you feel
a limit today is the **bulk board rebuild**, and most of that slowness is
*self-imposed* pacing, not Discord's hard ceiling. A second bot is a real option
but it's rarely the right first move — there are cheaper, safer levers. And the
thing that actually costs money as you grow is **AI (OpenAI + Gemini), not
Discord**, which is free.

---

## The limits that actually apply to you

- **Global REST limit: ~50 requests/second per bot token.** Your steady state
  (a handful of submissions an hour, some Butler chats) is well under 1% of this.
- **Per-route buckets** (e.g. "edit this message", "send to this channel"): each
  endpoint + major-param has its own small bucket, and the numbers arrive in
  `X-RateLimit-*` headers. `discord.py` reads these and paces itself automatically.
- **The dangerous one — invalid-request ban:** ~10,000 invalid responses
  (HTTP 401/403/429) per 10 minutes **per IP** gets you a Cloudflare ban (up to
  24h). This is the crash-loop failure mode. You already guard the worst case
  (the 15-min login-429 backoff in `bot.py`). It's per **IP**, so it's shared by
  everything running on that Railway container.
- **Sharding: irrelevant to you.** It's mandatory only at 2,500+ guilds. You have
  one guild.
- **Webhooks: separate rate limits** (roughly 30/min per webhook, plus per-channel
  webhook caps) that **do not consume the bot's global 50/s**. This is a lever (below).
- **Gateway:** one connection, 120 gateway commands / 60s. Not close to a concern.

At real scale you can ask Discord support to raise your global limit, but you're
nowhere near needing that.

---

## Where you actually feel it today: board rebuilds

`/rebuild_boards full:True` edits hundreds of forum messages, serialized under
`_BOARD_LOCK` with a manual `await asyncio.sleep(0.3)` between edits. That's why it
runs 15+ minutes and why it once outran the interaction token. **Most of that time
is your own conservative throttle, not Discord saying no.** `discord.py` already
handles 429s (it waits on the bucket and retries), so the manual serial sleeps are
belt-and-suspenders on top of a rate-limiter that would pace you correctly anyway.

### The single highest-leverage change (no new bot)
Rebuild in **bounded parallel batches** and let the library pace it, instead of a
strictly serial 0.3s-per-edit loop:

- Group boards by thread, fire e.g. 5–10 edits concurrently with
  `asyncio.gather`, `discord.py` respects each channel's bucket for you.
- Drop or shorten the blanket 0.3s sleeps; keep a small concurrency cap so you
  don't generate a burst of 429s (that's what feeds the Cloudflare invalid-request
  ban). A `Semaphore(8)` is a sane starting point.
- Expected result: a 15-minute rebuild drops to roughly 2–4 minutes, on **one**
  bot, with the same safety, because 429s are handled, not avoided by hand.

The reason to keep *some* cap: the invalid-request ban counts 429s. Uncapped
parallelism could spike 429s and trip the 10k/10min IP ban. Bounded parallelism is
the sweet spot.

---

## Does a second bot help?

Sometimes — but understand what you actually get:

**What a second token buys you**
- Its own independent global 50/s bucket and its own per-route buckets. Two bots
  can edit *different* threads truly in parallel, roughly doubling render throughput.

**What it does NOT buy you**
- **The Cloudflare invalid-request ban is per-IP.** Both bots on the same Railway
  container share it — a buggy second bot can get *both* banned.
- Discord may view multiple bots whose only purpose is dodging rate limits as
  abuse. Multiple bots for genuinely different *roles/features* is completely
  normal; multiple bots as a pure throughput hack is riskier.
- Coordination cost: `_BOARD_LOCK` is in-process. Two bots writing boards need a
  **Postgres advisory lock** (`pg_advisory_lock`) so they don't race the same board.
  Your DB is already the natural coordination point.

**When a second bot is genuinely worth it**
- A dedicated **worker bot** for heavy rendering (rebuilds, backfills) so the main
  bot stays snappy for live submissions and chat. Split boards by a hash of the
  board name; coordinate via advisory locks.
- A separate **feature/persona bot** (a rival character, a stats-site poster, a
  different channel's game) — value is product, not throughput.

You can run multiple bot clients in **one process** (two `commands.Bot` instances,
two gateway connections) if you just want separate tokens without a second Railway
service, though separate services isolate failures better.

---

## Cheaper, higher-leverage levers than "more bots"

1. **Parallelize rebuilds within one bot** (above). Biggest win for least risk.
2. **Webhooks for board posts.** Webhook execution has its own buckets and doesn't
   touch the bot's global 50/s. One webhook per thread = massively parallel posting
   and editing. Your board nav uses **link buttons**, which work fine on webhook
   messages (link buttons need no interaction listener). Caveat: it's a real
   refactor (author becomes the webhook; the baked-frame/attachment and edit-in-place
   logic would need rework), so it's a "later, if rebuild speed still hurts" move.
3. **Only render what changed.** You already added skip-unchanged to
   `rebuild_score_boards`, lean into it — most rebuilds touch a few boards, not all.
4. **Do full rebuilds off-peak / chunked**, and never inside a live interaction's
   15-minute token (you already made the status reply best-effort).
5. **Offload rich UI to a web app.** You already expose `/export/submissions`. A
   read-only static site (or a small service) that renders live leaderboards,
   player pages, and season history from Postgres is *unlimited* by Discord rate
   limits, looks far better than embeds, and costs pennies. This is the biggest
   "insane shit" idea relative to cost: keep Discord for interaction, move the
   heavy visual stuff to the web.

---

## The real cost driver: AI, not Discord

Discord is free. Your marginal cost per submission/chat is:
- **Gemini vision** on every scorecard (plus the retry/half-crop passes on hard boards),
- **OpenAI (Butler)** on every chat reply, digest, poll, blurb quip.

A second *Discord* bot adds ~one Railway service and $0 to Discord. It only adds AI
cost if it does AI work. So "what can we get away with" is really an **AI-spend**
question:
- Cache/skip vision on obvious re-submits; you already tag `Resubmit`.
- Keep the Butler on the cheap/low-reasoning path for banter (you do), reserve the
  bigger budget for data answers.
- If AI spend ever dominates, a self-hosted vision/text model on a GPU box becomes
  cheaper than per-call API costs, that's the point where "insane" becomes "worth it."

---

## "Insane shit" menu, ranked by leverage vs. cost/risk

| Idea | Leverage | Cost | Risk | Verdict |
|---|---|---|---|---|
| Parallel/bounded rebuilds on one bot | High | ~0 | Low | **Do this first** |
| Companion web dashboard off the export API | High | Low | Low | **Do this** |
| Webhook-posted boards | Med-High | Dev time | Med | Later, if rebuild still hurts |
| Worker bot for heavy rendering (advisory locks) | Med | 1 service | Med | If one bot's rebuilds still block live traffic |
| Persona / rival second bot | Low (fun) | 1 service | Low | Pure product play |
| Ask Discord for a higher global limit | — | — | — | Not needed at your scale |
| Self-host AI models | High (at scale) | GPU $ | Med | Only if AI spend dominates |

---

## Concrete recommendations

1. **Rework the rebuild loop to bounded-parallel** (`Semaphore(~8)`, drop the blanket
   0.3s sleeps, let `discord.py` pace). Keep `_BOARD_LOCK` per thread. Biggest, safest win.
2. **Prototype a read-only web dashboard** off `/export/submissions` — it sidesteps
   Discord limits entirely and is where "impressive" lives.
3. **Hold off on a second bot** until the rebuild parallelization and web offload
   don't cover you. If you do add one, make it a role-specific worker with Postgres
   advisory locks, and watch the shared per-IP Cloudflare ceiling.
4. **Track AI spend, not Discord** — that's the real budget lever.

## Sources
- [Discord Developer Docs — Rate Limits](https://docs.discord.com/developers/topics/rate-limits)
- [Discord Developer Support — My Bot is Being Rate Limited](https://support-dev.discord.com/hc/en-us/articles/6223003921559-My-Bot-is-Being-Rate-Limited)
- [Discord Webhook Rate Limits Explained](https://discord-webhook.com/en/blog/discord-webhook-rate-limits/)

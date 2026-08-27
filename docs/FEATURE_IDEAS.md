# Butler — Feature & Direction Ideas

A living menu, tailored to what already exists in this codebase. Not a to-do list —
a buffet. Each idea notes **why it fits** (the infra it reuses), a rough **effort**
(🟢 small / 🟡 medium / 🔴 large), and a **risk** flag where relevant.

Skip to [My top 5 picks](#my-top-5-if-i-had-to-choose) if you just want a shortlist.

---

## 1. Keep reducing your own toil (extends today's self-healing work)

The through-line of everything you fix by hand is *derived state drifting from the
submissions table*. Today's reconcile healed the deploy window. These push it further.

- **Persistent Edit buttons** 🟢 — `EditSubmissionView` dies on every restart, which is
  half of "too late to hit edit." Register it as a persistent view (`bot.add_view` with a
  stable `custom_id`) and reconstruct its state from the message/DB on click, exactly like
  `StatsLabEntry` already does. Buttons then survive deploys. *Reuses: the persistent-view
  pattern you already run for the Stats Lab panel.*
- **Scheduled drift report** 🟡 — you already have `/board_audit`, `board_card_audit`, and
  the bounty recount. Run all three on a daily loop and post a one-line "drift report" to the
  nerve centre ("3 board entries missing, 1 card unbuilt, 0 bounty gaps — /rebuild to fix").
  Turns "a player noticed a bug" into "you saw it first." *Reuses: existing audits +
  `nerve_alert` + a `tasks.loop`.*
- **One-button heal** 🟢 — a `/reconcile_now` mod command that runs the startup reconcilers
  on demand (bounty top-up + board rebuild for a time window), so you don't have to redeploy
  to trigger a heal. *Reuses: the functions you just wrote.*
- **Vision correction memory** 🟡🔴 — when a player fixes a misread (weapon, name, a number),
  log the (before → after) to a table. Feed the most common corrections back into the Gemini
  prompt as few-shot examples, and auto-apply safe name corrections. The parser gets better
  the more it's used instead of you re-teaching it. *Reuses: you already log vision corrections
  to the nerve centre; this persists and closes the loop.* **Risk:** guard against learning a
  bad correction — require N confirmations before a rule sticks.

## 2. Speed & cost

- **Vision de-dupe by image hash** 🟢 — hash each scorecard; if the same image is submitted
  again (resubmits, double-clicks, someone re-posting a friend's shot), skip the Gemini call
  and reuse the parse. Cuts vision cost and latency on the exact case that already causes
  duplicate-submission confusion. *Reuses: your dedup check already runs on message link;
  add an image-hash column.*
- **Downscale before vision** 🟢 — scoreboards read fine at ~1280px wide. Resizing before the
  Gemini call trims tokens/latency with no accuracy loss on the numbers that matter. *Cheap,
  measurable on the `/dev` cost line you already track.*
- **Materialized season/titles snapshot** 🟡 — `/standings`, `/wrapped`, the titles board, and
  the web Hall of Fame all recompute heavy aggregates live. Compute them once on a cadence into
  a `season_snapshot` table and read that; recompute on submission or a timer. Speeds the web
  pages and the slash commands. *Reuses: `favourites` season engine; just cache its output.*
- **Butler answer cache** 🟢 — identical stat questions ("who has the most hundos") asked
  minutes apart re-run the whole aggregate + model call. A short TTL cache keyed on the
  normalized question collapses bursts, like the db cache already does for rows.

## 3. Player delight — personal, low-toxicity

You (rightly) killed the "best player" ranking because it breeds ego. These give people
something to chase that's about **their own** progress, not beating a named rival.

- **Opt-in weekly "your week" DM** 🟡 — a private recap: your PBs this week, mastery/HH
  progress, your next goal (you already compute `/next`), a Butler one-liner. Private means no
  public shaming and no leaderboard war. *Reuses: `/wrapped`, `/next`, goals engine, Butler
  voice.* **Risk:** opt-in only; a surprise DM reads as spam.
- **Personal quest chains** 🟡 — beyond the monthly bounty: evergreen personal milestones
  ("finish Hundred-Handed", "10 Flawless runs", "a hundo on 5 different weapons") that award a
  cosmetic badge on the registry card. Progress is yours, not a ranking. *Reuses: marks/feats
  data + the card renderer.*
- **"On this day"** 🟢 — the Butler occasionally resurfaces a player's standout run from N
  months back. Nostalgia, zero competition. *Reuses: submissions history + Butler.*
- **Form line on the card** 🟢 — a tiny "recent form vs career" indicator (last 10 runs'
  average TD vs lifetime) — a sparkline or an arrow. Personal signal, not a rank. *Reuses:
  card renderer + submissions.*
- **Duo / ally stats** 🟡 — you already capture full rosters. Surface collaborative framing:
  "you and X have shared 30 lobbies, won 18 together." Nemesis/ally exists; lean into the
  *ally* (wholesome) side to balance the rivalry side. *Reuses: `roster.py` / `rivalry_service`.*

## 4. Feedback loops with the community (your stated priority)

The goal: make ideas surface **passively** so you're not guessing, and close the loop so people
see their feedback ship (which produces more feedback).

- **Suggestion box with vote reactions** 🟡 — a `/suggest` command drops the idea into a forum
  thread; 👍 reactions are votes; a `/dev`-side view lists top-voted. You mentioned a bounty
  suggestions upvote board — generalize it to all features. This *is* your roadmap, ranked by
  the people who use it. *Reuses: forum + reaction infra + `/dev` dashboard.*
- **Auto-changelog on deploy** 🟡 — when `main` deploys, post a short, human "what changed for
  players" note (you've written these by hand before — e.g. the PB-line change). Parse the
  commit subjects, let the Butler translate them to player-facing language, post to an
  announcements channel. Players see their suggestions land. *Reuses: the `deploy` event you
  already record on `on_ready`; add the git subject.* **Risk:** filter internal/refactor
  commits so it only announces player-visible changes.
- **Weekly feedback digest** 🟢 — the Butler skims recent reactions / a #feedback channel and
  summarizes "what people asked for this week" into the nerve centre. Turns scattered chatter
  into a triaged list. *Reuses: event log + AI summarization you already do for digests.*
- **Butler-run micro-polls tied to decisions** 🟢 — you have poll infra. Point it at real
  choices ("next bounty weapon?", "which map board to add?"). The answer directly feeds what you
  build next. *Reuses: `butler_poll_post`.*
- **Beta role** 🟢 — a small opt-in "test kitchen" role that gets new features first with a
  dedicated thread. Gives you a safe rollout group and your most-engaged players a voice.

## 5. Web / shareable / growth

The web app is public — these turn stats into things people *share*, which pulls new players in.

- **Per-match pages** 🔴 — you store both rosters + both teams' kill totals + difficulty. That's
  enough to reconstruct a shareable "match page": who was there, the tilt band, the outcome. A
  link people paste back into Discord to relive a game. Genuinely novel for a Chiv community.
  *Reuses: `roster` + tilt + submissions.* **Effort is real** — new web surface.
- **Rich link previews (OpenGraph)** 🟢 — when someone shares a Stats Lab or Hall of Fame link,
  render an OG image/description so it unfurls with the player's headline stats instead of a bare
  URL. Cheap virality. *Reuses: existing web server; add meta tags + a small render.*
- **"Compare two players" on the Lab** 🟡 — side-by-side stat columns. Framed as comparison, not
  a ladder, so it stays fun. *Reuses: Stats Lab + aggregates.* **Risk:** it *is* adjacent to
  ranking — keep it head-to-head-for-fun, not a global leaderboard.
- **Weapon recommender** 🟡 — you derive a damage-style archetype already. "Players with your
  style tend to over-perform on: Messer, Maul." A fun nudge, not a verdict. *Reuses:
  `archetype.py` + weapon lethality percentiles.*

## 6. The Butler as a narrator (novel, mostly reuses the AI you have)

Your best differentiator is the voice. These spend it on *color*, not stats deflection.

- **Nightly "last call" recap** 🟡 — at end of day, the Butler writes a short sardonic recap of
  the day's runs: the biggest hundo, the most brutal uphill win, the funniest death count, a
  quiet nod to a first-timer. Community texture without a single ranking. *Reuses: daily cycle +
  Butler + the day's submissions.* **Risk:** keep it kind; the death-count joke should never
  punch down at a struggling new player.
- **Season chronicle** 🟡 — the Butler maintains a running, in-character "chronicle" of the
  season (a pinned, appended narrative) — rivalries that formed, records that fell. A story the
  community is inside of. *Reuses: season engine + rivalry_service + Butler.*
- **Butler voice eval harness** 🟢🟡 — you have `docs/EVALS.md`. Add a small behavioral suite that
  checks the Butler stays in voice, never fabricates numbers (you already have the grounding
  check), and doesn't over-reference the same weapon/player — so voice tuning doesn't regress the
  way it did mid-build. *Reuses: grounding check + EVALS methodology.*

## 7. Structural bets (only if you want to invest in the foundation)

- **Typed submission model** 🔴 — the list-of-strings rows are a recurring bug source (Score-as-TD,
  kills-companion, the index juggling all over the cogs). A thin `Submission` dataclass with named
  fields, built once in `db.py`, would kill a whole class of positional bugs without a schema
  change. High effort (touches every cog), high long-term payoff. **Do it incrementally**, one read
  path at a time.
- **Feature flags** 🟢 — you already have a chaos-mode flag. A tiny `config.FLAGS` dict (or a DB
  table) to gate new features on/off per-guild lets you ship dark and flip on when ready — pairs
  perfectly with the beta role.

---

## My top 5 if I had to choose

Balancing impact, effort, and your "rely on community feedback / don't add ego" stance:

1. **Suggestion box with vote reactions** (§4) — directly solves "I'm out of ideas": the roadmap
   comes from the people who use it, ranked. 🟡
2. **Auto-changelog on deploy** (§4) — closes the loop so players see their feedback ship. Pairs
   with #1 to create a real feedback flywheel. 🟡
3. **Persistent Edit buttons** (§1) — kills the other half of "too late to edit," pure toil
   reduction, small. 🟢
4. **Vision de-dupe + downscale** (§2) — measurable cost/latency win on the exact flow that already
   confuses people, low effort. 🟢
5. **Opt-in "your week" DM** (§3) — the highest-delight, lowest-toxicity engagement lever, and it
   reuses `/wrapped` + `/next` you already built. 🟡

If you want a single theme for the next stretch: **the feedback flywheel** (#1 + #2). It's the
most on-point answer to "where do I go next" — instead of you generating ideas, you build the
machine that surfaces and closes them, then let the community drive.

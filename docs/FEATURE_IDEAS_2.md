# Butler — Feature Ideas, Batch 2 (bolder / more novel)

Batch 1 was the sensible stuff. This one leans into what makes *this* bot unique: you
capture **every lobby's full roster**, **both teams' kill totals**, a **per-lobby
difficulty read**, weapon **damage-type archetypes**, and **lethality percentiles** —
data no generic community bot has. Most ideas here are only possible *because* of that.

Effort: 🟢 small / 🟡 medium / 🔴 large. Risk noted where it matters.

---

## 1. Use the data nobody else has

Your roster + tilt + both-team-totals capture is the moat. Almost nobody else can build these.

- **The in-house balancer (hidden rating)** 🔴 — *the big one.* You avoided public rankings
  because they breed ego. So don't show a number — use one. Maintain a **private, never-displayed**
  skill estimate per player (from TD share, lethality percentile, tilt-adjusted performance) and
  expose ONE command: `/balance` — "here's a fair 6v6 from who reacted 👍." It solves a real pain
  (stacked lobbies ruin games) that your data uniquely enables, and sidesteps the ego problem
  entirely because the rating never surfaces — only balanced teams do. Genuinely novel for Chiv.
  *Reuses: roster + lethality + tilt.* **Risk:** keep the rating opaque forever; the moment it
  leaks it becomes a ladder.
- **Lobby fairness score / anti-stack signal** 🟡 — you store both teams' totals and the roster.
  Compute a per-lobby balance number and, over time, surface "the lounge's lobbies are getting
  lopsided" without naming-and-shaming. Optional gentle nudge: the Butler notes when a submitted
  game was a blowout stack. *Reuses: `tilt.py` gap + rosters.* **Risk:** never accuse a player of
  stacking; frame as lobby-level, not person-level.
- **Community meta report** 🟡 — a monthly "State of the Meta": which weapons are rising/falling in
  usage AND lethality across the whole community, which maps play hardest, which damage types are
  over-performing. Chiv players *live* for meta debate — nobody can produce a data-backed community
  meta report but you. Post it, watch the arguments (the good kind). *Reuses: submissions + damage
  types + lethality percentiles.*
- **Activity heatmap ("when's the lounge hot")** 🟢 — a simple by-hour/by-day chart of when games
  actually happen, so people know when to show up to find a lobby. Practical, drives more play,
  which drives more submissions. *Reuses: submission timestamps + your charts module.*
- **Map/faction difficulty atlas** 🟡 — using the tilt data, a ranked "sweatiest lobbies" view per
  map+faction. Flavorful and useful for matchmaking expectations. *Reuses: tilt bands.*

## 2. Cooperative mechanics — anti-ego *by design*

The cleanest answer to "rankings bring out shitty egos": make the whole server pull the same rope.

- **Community raid-boss meter** 🟡 — a big server-wide collective goal with a fat progress bar:
  "As a lounge, land **1,000 hundos** this season" or "collectively survive 100 Brutal-tier
  lobbies." Everyone's runs feed one bar; hitting it unlocks a server reward (a Butler event, a
  special bounty, a cosmetic). Zero individual ranking — you win *together* or not at all. This is
  the single most on-brand feature for a community that's tired of egos. *Reuses: feats/marks
  aggregation + a progress renderer you already have for bounties.*
- **Mentor / first-hundo program** 🟡 — pair a newcomer with a vet; the bot watches for the
  rookie's first 100-kill game and throws a little ceremony (and credits the mentor). Onboarding +
  wholesome + sticky. *Reuses: milestone detection + roles.* **Risk:** opt-in on both sides.
- **Seasonal collective streak** 🟢 — "the lounge has submitted every day for 12 days." A shared
  streak the community protects together. Ties into your existing dry-spell detection, inverted.

## 3. Spontaneous engagement (ephemeral, exciting, low-stakes)

- **Flash challenges** 🟡 — the Butler spontaneously drops a 2-hour bounty: "First to a hundo on
  the Falchion before 10pm gets a mark and bragging rights." Ephemeral, no season weight, pure
  fun. Scarcity + surprise drive activity. *Reuses: bounty progress tracking + a short timer +
  Butler voice.*
- **Pick'em / prediction** 🟡 — before a scrim or event, players predict outcomes; the Butler
  scores everyone after. Communal, needles the loudmouths in good fun. *Reuses: poll infra.*
- **Moment detection & distinct celebrations** 🟢 — you already catch milestones; expand the
  *vocabulary* of moments: a **comeback** (won a Brutal uphill), a **rivalry escalation** (you and
  your nemesis both went off in the same lobby), a **first hundo**, a **clutch** (low deaths, high
  TD in a losing lobby). Each gets its own distinct Butler reaction instead of a generic one. Makes
  the feed feel alive. *Reuses: tilt + roster + feats.*

## 4. Competitive infrastructure (it *is* a competitive community)

- **Tournament / scrim manager** 🔴 — sign-ups, brackets, results, and — the part only you can do —
  **stat-seeded** brackets so the bracket isn't random. A real tournament tool that knows the
  players. Big lift, big payoff for a competitive lounge. *Reuses: stats for seeding + forum/embeds.*
- **Teams / clans** 🟡 — register a team, get a team board and team-vs-team head-to-head. Your
  rosters already know who plays with whom, so team detection can even be *suggested* automatically.
  *Reuses: roster engine + board machinery.*
- **Draft captains tool** 🟡 — for organized in-houses: two captains, snake draft, and an optional
  "auto-balance suggestion" from the hidden rating (§1). Solves the "captains accidentally stack it"
  problem. *Reuses: the balancer.*

## 5. Identity & cosmetics — earned, never ranked

- **A richer vocabulary of earned titles** 🟢 — you have title roles; expand the *lore*: "The
  Unkillable" (most Flawless), "Peasant King," "The Anvil" (Blunt specialist with X hundos), "Ghost"
  (highest kill-share in losses). Identity people *earn* and wear, not a leaderboard slot. *Reuses:
  archetype + feats + your title system.*
- **Registry card customization** 🟡 — let players unlock a card accent color / banner / frame via
  milestones. Cosmetic progression is the least-toxic retention lever there is. *Reuses: card
  renderer.*
- **Clip attachment** 🟢 — `/clip <link>` pins a Medal/YouTube highlight to a run on the card. Chiv
  is a clip culture; give the clips a home. *Reuses: card + submissions.*

## 6. Integrity & trust

- **Outlier / impossible-run review queue** 🟡 — you already reject *impossible* data. Add a soft
  layer: statistically implausible runs (way outside a player's distribution, or physically
  improbable TD/time) get quietly flagged to a mod review queue — not auto-removed. Protects board
  integrity in a competitive setting without false accusations. *Reuses: validation.py + a stats
  distribution.* **Risk:** review-only, never auto-punish; false positives erode trust fast.
- **Public status page** 🟢 — a tiny public uptime/health page (you already have `/dev` internals).
  Signals the project is maintained and serious. *Reuses: healthcheck + web server.*

## 7. The Butler, spent on the things it's uniquely good at

- **In-character season chronicle & "last call" nightly recap** 🟡 — (carried from batch 1 because
  it's underrated) a running narrative the community lives inside. Your voice is the differentiator;
  spend it on color, not stat-deflection.
- **"Butler's read" on a lobby** 🟢 — react to a submission with a one-line *qualitative* take
  driven by the real numbers ("A Brutal lobby and you still out-shared the team. The Butler is,
  reluctantly, impressed."). Personality that's *earned* by the data, not generic quips. *Reuses:
  tilt + kill-share + Butler.*

---

## Boldest bets (my picks from this batch)

1. **Community raid-boss meter** (§2) — the definitive anti-ego feature: the whole lounge pulls one
   rope. Nothing else you could build says "this community over these egos" as clearly. 🟡
2. **The in-house balancer with a hidden rating** (§1) — solves a real, felt pain (stacked lobbies),
   uses data only you have, and threads the ego needle by never showing the number. The most novel
   thing on either list. 🔴 but stageable.
3. **Community meta report** (§1) — turns your data into the thing Chiv players argue about most,
   monthly. Pure differentiator, moderate effort. 🟡
4. **Moment detection vocabulary** (§3) — cheap, high-texture; makes the whole submission feed feel
   alive and personal without any ranking. 🟢
5. **Flash challenges** (§3) — spontaneity is the one thing your (excellent but scheduled) systems
   don't have yet. 🟡

If batch 1's theme was *the feedback flywheel*, batch 2's theme is **"lean on the moat"**: build the
handful of things that are only possible because you capture the whole lobby, and make them
cooperative so they strengthen the community instead of fracturing it.

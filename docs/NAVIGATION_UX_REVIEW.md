# Cigar Lounge — Navigation & Organization UX Review

A benchmark of how the lounge's navigation (forums, index posts, hyperlinking, nav
buttons, bot commands) compares to current Discord community best practice, plus a
prioritized list of what's worth adding. Researched July 2026.

## The short version

The lounge is already **ahead of most communities** on navigation. The things the
best-practice literature obsesses over — a clean structure, jump links, a "way back
out," directory posts that keep evergreen content findable — you've engineered
deliberately, and in a couple of places you've solved problems most servers never
even notice. The real gaps are in Discord's *native* discovery features (forum tags,
Onboarding, Server Guide), which complement what you've built rather than replace it.

## What the research says (best practice, synthesized)

**Structure is a path, not a pile.** The single most repeated idea: a new member
should understand where to go in under 30 seconds, and channels should be *ordered*
so the list reads like a journey (start here → rules → main chat → topics →
resources). Most "messy" servers don't have too many channels; they have channels in
the wrong order.

**Fewer, busier beats many and quiet.** Consolidate overlapping channels. Two
half-dead channels usually make one healthy one. Descriptive names with emoji
prefixes help scanning (`#share-your-art`, not `#art`).

**Forums are for structured, hop-in/hop-out content** — exactly the "give structure
to the chaos" use case. But they have real limitations: a forum shows only **one**
pinned post, and the default sort is **latest activity**, so static/evergreen posts
sink and "forums die when only latest matters." The recommended mitigations are
pinning an evergreen guide and pointing to standout posts from elsewhere.

**Tags are the native filter.** Forum channels support tags for filtering and
sorting. Guidance: keep to ~5–15 well-named tags (some say ≤5 so the filter bar
doesn't crowd), use emojis to make them scannable, and consider a required tag so
skimming works. A pinned "Read Me First" that explains tags + post format is the
standard pattern.

**Onboarding + Server Guide are the front door.** Discord's native Onboarding routes
new members to relevant channels and opt-in roles via a few questions, then shows
them a personalized channel list and a "Channels & Roles" tab. The Server Guide is a
dedicated first-thing-you-see welcome surface. Both are Community-server features and
are the recommended way to hit the "30-second" bar.

**Jump links and pointers reduce disorientation.** Linking directly to a message or
post, and giving people a way back, is praised throughout — it's the antidote to
"forum content vanishing" and to members getting lost after a deep link.

## How the lounge compares

### Where you're ahead of the field

- **Auto-generated index posts are a genuine strength.** The per-forum index
  (`📋 Feats of War Index`, etc.) that scans every thread and lists them as
  alphabetized hyperlinks is a direct fix for the #1 forum weakness in the research:
  posts sinking under "latest activity." You've built a stable, sorted directory that
  doesn't care about forum sort order. Most communities never solve this; they just
  let old boards disappear.
- **Deep linking + hyperlinking is exactly the recommended pattern.** Registry cards
  linking to boards and to individual submission games, the `channels/guild/thread/
  message` jump links, `/top` → board — this is "jump links / point to standout
  topics," done thoroughly.
- **Nav buttons give the 'way back out.'** The Ledger / Main / 💯 link buttons at the
  bottom of boards and cards address the exact disorientation problem the guides warn
  about after a deep link drops someone somewhere unfamiliar.
- **Forums instead of channels sidesteps the 'too many channels' trap.** By making
  each board a forum *post* rather than a *channel*, the sidebar stays clean no matter
  how many weapons and maps exist. This is the consolidation principle achieved
  structurally.
- **Command-driven navigation is a whole extra layer.** `/help` (tiered by
  permission), `/top`, `/explore`, `/playerstats`, `/titles` let people *query* their
  way to information instead of clicking. The best-practice guides don't even
  contemplate this — it's above and beyond typical server design.

### Where the native features could add lift

1. **Forum tags (biggest gap).** If the board forums don't use tags, adding a small,
   emoji'd tag set would give members a *native* filter that works on mobile and
   doesn't depend on the index being fresh. Examples: on the Feats forum — `100 Kills`,
   `200 TD`, `Triple`, `Flawless`, `TUFF`, `Peasant`, `Titles`; on weapon forums —
   `Knight`, `Vanguard`, `Footman`, `Archer`. Keep it under ~15 and let people filter
   the pile without scrolling.
2. **Onboarding + Server Guide.** If these aren't set up, new members lean entirely on
   the Ledger and the Butler to orient. A short Onboarding flow (route to submissions,
   rules, boards; opt-in notification roles) plus a Server Guide would hit the
   30-second bar for first-timers, which is the one audience your current tools serve
   least directly.
3. **A pinned "Read Me First" per forum.** The index is pinned (good — that's your one
   allowed pin), but a short "how to read these boards / how to submit" is the standard
   companion. Could be folded into the index post itself so you don't spend the single
   pin twice.
4. **Index freshness.** The index is only as current as the last `/ledger_refresh`
   (you flagged this yourself). Worth either a scheduled refresh (daily/weekly) or a
   refresh hook when a *new board thread* is created, so it can't silently drift.
5. **Surface the bot's navigation.** `/explore`, `/top`, and `/playerstats` are
   powerful but only useful if people know they exist. A one-line "try `/explore`"
   pointer in the Ledger or Server Guide turns a hidden feature into a navigation aid.

## Recommended priority order

1. **Add forum tags** to the board forums — highest lift, native, mobile-friendly,
   and it complements (doesn't replace) the index.
2. **Set up Onboarding + a Server Guide** — closes the new-member gap, the one place
   your otherwise-strong tooling is quietest.
3. **Automate index refresh** (schedule or on-thread-create) so the directory can't go
   stale.
4. **Fold a short "how to read/submit" + a `/explore` pointer** into the pinned index
   posts and the Ledger.

Everything else — the hyperlinking, deep links, nav buttons, command layer — is
already best-practice or beyond, and worth keeping exactly as is.

## Sources

- [Discord — Community Server Cleanup Report (Aug 2025)](https://discord.com/blog/introducing-the-community-server-cleanup-report-for-august-2025)
- [Discord — Server Guide FAQ](https://support.discord.com/hc/en-us/articles/13497665141655-Server-Guide-FAQ)
- [Discord — Community Onboarding FAQ](https://support.discord.com/hc/en-us/articles/11074987197975-Community-Onboarding-FAQ)
- [Discord — Community Onboarding announcement](https://discord.com/blog/community-onboarding-welcome-your-new-members)
- [Discord — Forum Channels FAQ](https://support.discord.com/hc/en-us/articles/6208479917079-Forum-Channels-FAQ)
- [Discord — Forum Channel Improvements: searching, tagging, filtering, sorting](https://support.discord.com/hc/en-us/community/posts/20758113122455-Forum-Channel-Improvements-Searching-Tagging-Filtering-Sorting)
- [BuildMyDiscord — Channel Organization Guide](https://buildmydiscord.com/en/blog/discord-channel-organization-guide-best-channel-structure-for-active-communities)
- [BuildMyDiscord — Server Categories Guide](https://buildmydiscord.com/en/blog/discord-server-categories-guide-how-to-organize-channels-for-maximum-engagement-)
- [BuildMyDiscord — Forum Channels Complete Guide (2026)](https://buildmydiscord.com/en/blog/discord-forum-channels-complete-guide-to-community-discussion-features-in-2026)
- [PeakBot — How to Organize Discord Channels and Categories](https://peakbot.pro/blog/how-to-organize-discord-channels-and-categories)
- [Space-Node — Discord Forum Channels 2026: Setup, Tags and Moderation](https://space-node.net/blog/discord-forum-channels-setup-guide-2026)
- [Mava — Discord Server Best Practices: 15 Tips](https://www.mava.app/blog/discord-server-best-practices)
- [GeeksforGeeks — How to Organize Your Discord Channels](https://www.geeksforgeeks.org/websites-apps/how-to-organize-discord-channels-for-better-navigation/)

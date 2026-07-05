# Architecture

A high-level map of how the Butler works. These diagrams are deliberately structural — they only change if the system is re-architected, not when a threshold or title is tweaked — so they should stay accurate with little upkeep. For per-value detail (rank thresholds, feat rules, titles) see the challenge rules and `config.py`.

## How a run becomes a leaderboard entry

The bot runs on two clocks: a **monthly cycle** (a bounty and season open together and run about a month) and a **per-run pipeline** that fires every time a player posts a scorecard. Marks, boards, and ratings from each run feed the progression and recognition systems; weapon ranks, marks, and all-time titles carry over between months, while season titles reset.

```mermaid
flowchart TD
    subgraph MACRO["Monthly cycle (macro)"]
        M1["Open bounty and season"] --> M2["Players grind all month"]
        M2 --> M3["Month ends, bounty closes"]
        M3 --> M4["Champions to Hall of Fame,<br/>season titles reset"]
        M4 -.->|next month| M1
    end

    subgraph MICRO["Every run (micro)"]
        S1(["Scorecard screenshot"]) --> S2["Vision AI reads stats"]
        S2 --> S3["Weapon and subclass<br/>from caption or menu"]
        S3 --> S4[("Saved to database")]
        S4 --> S5["Marks awarded"]
        S5 --> B1["Boards updated"]
        S5 --> B2["Ratings updated"]
        S5 --> B3["Card and blurb posted"]
        B1 --> S6["Bounty, titles, indexes refreshed"]
        B2 --> S6
        B3 --> S6
    end

    subgraph BUILD["What the totals build"]
        R1["Weapon ranks"] --> R2["Subclass ranks"] --> R3["Class ranks"]
        MA["Mastery (100 / 250)"]
        FE["Feats + Hundred-Handed (46)"]
        T1["Boards"] --> T2["All-time titles"]
        T3["Ratings"] --> T4["Season titles"]
        T5["Bounties"] --> T6["Player titles"]
    end

    subgraph BG["Always on"]
        BUT["Butler AI"]
        NRV["Hourly nerve digest"]
        BKP["Daily backup + reminders"]
    end

    M2 --> S1
    S5 --> R1
    B1 --> T1
    B2 --> T3
    M4 --> T5

    classDef node fill:#1e3a5f,stroke:#89b4fa,color:#e8eff8
    classDef start fill:#2b4f77,stroke:#a9c9f0,color:#eef4fc
    classDef db fill:#1b4a4a,stroke:#7fd0c4,color:#e7f8f4
    class M1,M2,M3,M4,S2,S3,S5,B1,B2,B3,S6,R1,R2,R3,MA,FE,T1,T2,T3,T4,T5,T6,BUT,NRV,BKP node
    class S1 start
    class S4 db
    style MACRO fill:#111c2b,stroke:#34527b,color:#9dc0ec
    style MICRO fill:#111c2b,stroke:#34527b,color:#9dc0ec
    style BUILD fill:#111c2b,stroke:#34527b,color:#9dc0ec
    style BG fill:#111c2b,stroke:#34527b,color:#9dc0ec
```

## Where the load is (and why the queries look the way they do)

Not all paths run equally often. The **hot** paths run on *every* submission and *every* chat message; the **warm** paths run periodically; the **cold** paths run occasionally, usually triggered by a mod on purpose. In the diagram below, deeper blue means a busier path.

Everything ultimately reads and writes Postgres, so the busier a path is, the more it matters that the database does the filtering, sorting, and counting rather than the bot loading whole tables into Python. The hot paths use **index-backed, targeted queries** (e.g. `get_leaderboard_by_board`, `get_submissions_by_player`) and SQL aggregates (`MAX`, `COUNT`). The cold paths still do full-table scans — that's fine, because they run rarely.

> **Note to future maintainers:** the targeted queries and SQL aggregates on the hot paths are intentional. Please don't "simplify" them back into `get_all_*` full-table scans — that reintroduces an O(rows) cost on the busiest paths. See the `_INDEXES` list in `utils/db.py`.

```mermaid
flowchart LR
    subgraph HOT["Hot — every event"]
        H1(["Scorecard posted"]) --> H1W["Submission pipeline"]
        H2(["Chat message"]) --> H2W["Butler AI"]
    end
    subgraph WARM["Warm — periodic"]
        W1(["Reaction added"]) --> W1W["Feedback log"]
        W2(["Hourly timer"]) --> W2W["Nerve digest"]
    end
    subgraph COLD["Cold — occasional"]
        C1(["Admin command"]) --> C1W["Backfills and refresh"]
        C2(["Month rollover"]) --> C2W["Season and bounty reset"]
    end
    H1W -->|indexed| DB[("Postgres")]
    H2W -->|indexed| DB
    W1W --> DB
    W2W --> DB
    C1W -->|full scan| DB
    C2W --> DB

    classDef hot fill:#1e3a5f,stroke:#8ab6ee,color:#eaf2fb
    classDef warm fill:#1b3149,stroke:#6a93c4,color:#dce7f4
    classDef cold fill:#1a2432,stroke:#5c7092,color:#c6d2e2
    classDef db fill:#1b4a4a,stroke:#7fd0c4,color:#e7f8f4
    class H1,H1W,H2,H2W hot
    class W1,W1W,W2,W2W warm
    class C1,C1W,C2,C2W cold
    class DB db
    style HOT fill:#0f1a27,stroke:#34527b,color:#9dc0ec
    style WARM fill:#0f1722,stroke:#34527b,color:#9dc0ec
    style COLD fill:#0e131c,stroke:#34527b,color:#9dc0ec
```

## Pure logic and tests

Rank / title / Hundred-Handed math lives in `utils/ranks.py` (no Discord or DB dependencies) so it can be imported and unit-tested in isolation. `tests/test_ranks.py` locks the tier boundaries, the Apex/Ascended/Legend caps, mastery vs virtuoso thresholds, and `HH_TOTAL == 46`. Run the suite with `pytest -q`.

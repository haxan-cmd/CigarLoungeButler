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
```

## Where the load is (and why the queries look the way they do)

Not all paths run equally often. The **hot** paths run on *every* submission and *every* chat message; the **warm** paths run periodically; the **cold** paths run occasionally, usually triggered by a mod on purpose.

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

    classDef hot fill:#3a1a1a,stroke:#f38ba8,color:#f2cdcd
    classDef warm fill:#3a2f1a,stroke:#f9e2af,color:#f9e2af
    classDef cold fill:#232634,stroke:#9399b2,color:#cdd6f4
    classDef db fill:#1a3a2a,stroke:#a6e3a1,color:#a6e3a1
    class H1,H1W,H2,H2W hot
    class W1,W1W,W2,W2W warm
    class C1,C1W,C2,C2W cold
    class DB db
```

## Pure logic and tests

Rank / title / Hundred-Handed math lives in `utils/ranks.py` (no Discord or DB dependencies) so it can be imported and unit-tested in isolation. `tests/test_ranks.py` locks the tier boundaries, the Apex/Ascended/Legend caps, mastery vs virtuoso thresholds, and `HH_TOTAL == 46`. Run the suite with `pytest -q`.

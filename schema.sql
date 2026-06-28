-- schema.sql — Cigar Lounge Butler Postgres schema
-- Run once against your Railway Postgres instance to create all tables.

CREATE TABLE IF NOT EXISTS submissions (
    id                SERIAL PRIMARY KEY,
    submitted_at      TIMESTAMP NOT NULL,
    player_name       TEXT NOT NULL,
    discord_id        TEXT NOT NULL,
    weapon            TEXT,
    subclass          TEXT,
    map               TEXT,
    faction           TEXT,
    takedowns         INTEGER,
    kills             INTEGER,
    deaths            INTEGER,
    vip               BOOLEAN DEFAULT FALSE,
    feats             TEXT,
    message_link      TEXT,
    lobby_rank        INTEGER,
    lobby_size        INTEGER,
    kills_rank        INTEGER,
    team_rank         INTEGER,
    team_size         INTEGER,
    total_lobby_kills INTEGER,
    team_td_ratio     REAL,
    team_kill_share   REAL,
    team_td_share     REAL,
    second_place_td   INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    discord_id        TEXT PRIMARY KEY,
    player_name       TEXT NOT NULL,
    forum_thread_id   TEXT,
    total_marks       INTEGER DEFAULT 0,
    submission_count  INTEGER DEFAULT 0,
    last_submission   TIMESTAMP,
    weapon_marks      TEXT,
    class_marks       TEXT
);

CREATE TABLE IF NOT EXISTS leaderboards (
    id          SERIAL PRIMARY KEY,
    board_name  TEXT NOT NULL,
    thread_id   TEXT,
    message_ids TEXT,
    board_type  TEXT
);

CREATE TABLE IF NOT EXISTS leaderboard_data (
    id           SERIAL PRIMARY KEY,
    board_name   TEXT NOT NULL,
    player_name  TEXT NOT NULL,
    discord_id   TEXT,
    score        INTEGER,
    message_link TEXT,
    weapon       TEXT
);

CREATE TABLE IF NOT EXISTS bounties (
    id                 SERIAL PRIMARY KEY,
    title              TEXT NOT NULL,
    channel_id         TEXT,
    message_id         TEXT,
    theme_emoji        TEXT,
    weapons            TEXT,
    special_challenge  TEXT,
    special_done       BOOLEAN DEFAULT FALSE,
    completions        TEXT,
    active             BOOLEAN DEFAULT TRUE,
    role_id            TEXT,
    forum_channel_id   TEXT,
    completions_msg_id TEXT,
    bonus_msg_id       TEXT,
    progress_msg_id    TEXT,
    start_date         DATE
);

CREATE TABLE IF NOT EXISTS bounty_players (
    id            SERIAL PRIMARY KEY,
    bounty_title  TEXT,
    discord_id    TEXT,
    player_name   TEXT,
    forum_post_id TEXT,
    progress      TEXT
);

CREATE TABLE IF NOT EXISTS registry_cards (
    discord_id      TEXT PRIMARY KEY,
    player_name     TEXT,
    forum_thread_id TEXT
);

CREATE TABLE IF NOT EXISTS special_ops (
    id          SERIAL PRIMARY KEY,
    discord_id  TEXT NOT NULL,
    player_name TEXT,
    achievement TEXT
);

CREATE TABLE IF NOT EXISTS legacy_marks (
    id          SERIAL PRIMARY KEY,
    player_name TEXT,
    weapon      TEXT,
    subclass    TEXT,
    marks       INTEGER
);

CREATE TABLE IF NOT EXISTS legacy_feats (
    id           SERIAL PRIMARY KEY,
    player_name  TEXT,
    emojis       TEXT,
    message_link TEXT
);

CREATE TABLE IF NOT EXISTS legacy_bounties (
    id           SERIAL PRIMARY KEY,
    player_name  TEXT,
    bounty_title TEXT,
    completed    INTEGER
);

CREATE TABLE IF NOT EXISTS challenge_rules (
    id         SERIAL PRIMARY KEY,
    message_id TEXT,
    section    TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id             SERIAL PRIMARY KEY,
    snapshot_date  DATE,
    total_subs     INTEGER,
    weekly_subs    INTEGER,
    active_players INTEGER,
    top_weapon_1   TEXT,
    top_weapon_2   TEXT,
    top_weapon_3   TEXT,
    top_weapon_4   TEXT,
    top_weapon_5   TEXT,
    top_map_1      TEXT,
    top_map_2      TEXT,
    top_map_3      TEXT,
    avg_td         REAL,
    avg_kills      REAL,
    highscores_set INTEGER,
    boards_updated INTEGER,
    trend_weapon_1 TEXT,
    trend_weapon_2 TEXT,
    trend_weapon_3 TEXT
);

CREATE TABLE IF NOT EXISTS index_posts (
    forum_name TEXT PRIMARY KEY,
    channel_id TEXT,
    message_id TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_submissions_discord_id ON submissions(discord_id);
CREATE INDEX IF NOT EXISTS idx_submissions_weapon ON submissions(weapon);
CREATE INDEX IF NOT EXISTS idx_submissions_map ON submissions(map);
CREATE INDEX IF NOT EXISTS idx_leaderboard_data_board ON leaderboard_data(board_name);
CREATE INDEX 
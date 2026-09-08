-- Reference copy of the counting-only bootstrap in utils/db.py.
-- Names are separate from the pre-existing counting_state/counting_users tables.
CREATE TABLE IF NOT EXISTS counting_games (
    channel_id BIGINT PRIMARY KEY, guild_id BIGINT NOT NULL,
    current INTEGER NOT NULL DEFAULT 0, last_user TEXT,
    record INTEGER NOT NULL DEFAULT 0, total_counts BIGINT NOT NULL DEFAULT 0,
    last_message BIGINT NOT NULL DEFAULT 0, paused BOOLEAN NOT NULL DEFAULT TRUE,
    disruption BOOLEAN NOT NULL DEFAULT FALSE, generation BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS counting_game_users (
    channel_id BIGINT NOT NULL REFERENCES counting_games(channel_id), discord_id TEXT NOT NULL,
    name TEXT NOT NULL, counts BIGINT NOT NULL DEFAULT 0, breaks BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(channel_id,discord_id)
);
CREATE TABLE IF NOT EXISTS counting_messages (
    message_id BIGINT PRIMARY KEY, channel_id BIGINT NOT NULL REFERENCES counting_games(channel_id),
    generation BIGINT NOT NULL, discord_id TEXT NOT NULL, number INTEGER NOT NULL,
    disrupted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS counting_penalties (
    guild_id BIGINT NOT NULL, discord_id TEXT NOT NULL, role_id BIGINT NOT NULL,
    expires_at TIMESTAMP NOT NULL, state TEXT NOT NULL DEFAULT 'pending', error TEXT,
    PRIMARY KEY(guild_id,discord_id,role_id)
);
CREATE TABLE IF NOT EXISTS counting_audit (
    id BIGSERIAL PRIMARY KEY, created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    channel_id BIGINT, actor TEXT, action TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_counting_messages_channel ON counting_messages(channel_id,generation,message_id);
CREATE INDEX IF NOT EXISTS idx_counting_penalties_due ON counting_penalties(state,expires_at);

ALTER TABLE counting_games ADD COLUMN IF NOT EXISTS record_message_id BIGINT;
ALTER TABLE counting_game_users ADD COLUMN IF NOT EXISTS highest_valid INTEGER NOT NULL DEFAULT 0;
ALTER TABLE counting_game_users ADD COLUMN IF NOT EXISTS highest_message_id BIGINT;
ALTER TABLE counting_game_users ADD COLUMN IF NOT EXISTS last_active_id BIGINT;
ALTER TABLE counting_game_users ADD COLUMN IF NOT EXISTS idiot_penalties BIGINT NOT NULL DEFAULT 0;
ALTER TABLE counting_messages ADD COLUMN IF NOT EXISTS expression TEXT;

-- v0.1 schema. group_id is present everywhere even though there is one group.
-- That is the only future-proofing worth doing now.
-- IF NOT EXISTS throughout so the runner can adopt a database that initdb
-- already created from this file.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS messages (
  id            BIGSERIAL PRIMARY KEY,
  wa_msg_id     TEXT UNIQUE NOT NULL,
  group_id      TEXT NOT NULL,
  sender_jid    TEXT NOT NULL,
  sender_name   TEXT,
  body          TEXT,
  quoted_msg_id TEXT,
  is_bot        BOOLEAN NOT NULL DEFAULT FALSE,
  ts            TIMESTAMPTZ NOT NULL,
  chunked       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS messages_unchunked ON messages (group_id, ts) WHERE NOT chunked;

CREATE TABLE IF NOT EXISTS chunks (
  id           BIGSERIAL PRIMARY KEY,
  group_id     TEXT NOT NULL,
  -- content holds "Name: text" lines. The speaker prefix must live inside the
  -- text, because metadata does not survive into the model's context.
  content      TEXT NOT NULL,
  first_msg_id TEXT NOT NULL,   -- what the bot quote-replies to
  start_ts     TIMESTAMPTZ NOT NULL,
  end_ts       TIMESTAMPTZ NOT NULL,
  embedding    vector(384),     -- multilingual-e5-small
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv       ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_group_ts  ON chunks (group_id, end_ts DESC);

-- Built in week one on purpose. This is what turns "what should I build next"
-- from a design question into a data question.
CREATE TABLE IF NOT EXISTS query_log (
  id          BIGSERIAL PRIMARY KEY,
  group_id    TEXT,
  sender_jid  TEXT,
  question    TEXT NOT NULL,
  retrieved   JSONB,            -- {chunks: [{chunk_id, score, source}], timings: {step_ms}}
  answer      TEXT,
  confidence  REAL,
  tokens_in   INT,
  tokens_out  INT,
  latency_ms  INT,
  feedback    SMALLINT,         -- -1 / null / 1
  ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);

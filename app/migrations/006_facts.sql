-- Phase 4: decisions and corrections as first-class rows. Chunks stay the
-- primary retrieval path; facts are the temporal layer on top. A fact that
-- has been replaced keeps its row and points at its successor, so an answer
-- can say what changed and when.
CREATE TABLE facts (
  id            BIGSERIAL PRIMARY KEY,
  group_id      TEXT NOT NULL,
  statement     TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('decision', 'correction')),
  source_msg_id TEXT,                    -- first message of the chunk, or the correcting message
  sender_jid    TEXT,                    -- who corrected, for corrections
  valid_from    TIMESTAMPTZ NOT NULL,
  superseded_by BIGINT REFERENCES facts (id) ON DELETE SET NULL,
  embedding     vector(384),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX facts_group_active ON facts (group_id) WHERE superseded_by IS NULL;

-- Extraction runs once per chunk; remember which chunks are done.
ALTER TABLE chunks ADD COLUMN facts_extracted BOOLEAN NOT NULL DEFAULT FALSE;

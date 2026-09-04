-- Documents the admin uploads: handbooks, price lists, minutes. They are
-- searched next to the chat, so they land in the same chunks table. A chunk is
-- now either an episode of messages or a slice of a document, never both.
CREATE TABLE documents (
  id          BIGSERIAL PRIMARY KEY,
  group_id    TEXT,                    -- NULL: every group can use it
  filename    TEXT NOT NULL,
  mime        TEXT,
  bytes       INT NOT NULL,
  sha256      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'indexed', 'failed')),
  error       TEXT,
  -- The upload waits here until the loop reads it, then the bytes are dropped:
  -- the extracted text is what search needs, and backups stay small. A failed
  -- document keeps its bytes so Retry has something to work with.
  raw         BYTEA,
  content     JSONB,                   -- [[label, text], ...], so re-indexing is free
  parts       INT NOT NULL DEFAULT 0,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The same file twice in the same place is the same document.
CREATE UNIQUE INDEX documents_dedupe ON documents (coalesce(group_id, ''), sha256);
CREATE INDEX documents_pending ON documents (id) WHERE status = 'pending';

ALTER TABLE chunks
  ADD COLUMN document_id BIGINT REFERENCES documents (id) ON DELETE CASCADE,
  ADD COLUMN source_label TEXT,          -- "handbook.pdf, page 3", shown in the citation
  ALTER COLUMN group_id DROP NOT NULL,   -- NULL: a shared document, searched by every group
  ALTER COLUMN first_msg_id DROP NOT NULL,
  ALTER COLUMN start_ts DROP NOT NULL,
  ALTER COLUMN end_ts DROP NOT NULL;

CREATE INDEX chunks_document ON chunks (document_id) WHERE document_id IS NOT NULL;

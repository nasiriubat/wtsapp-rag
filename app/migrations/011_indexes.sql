-- The indexes every answered question was missing. Until now each answer
-- scanned messages by time range (the partial index excludes chunked rows),
-- query_log for the month's spend, and facts by vector distance with no index
-- at all. These turn /ask from O(corpus) to O(log corpus).
CREATE INDEX messages_group_ts ON messages (group_id, ts);
CREATE INDEX messages_sender ON messages (sender_jid);
CREATE INDEX query_log_group_ts ON query_log (group_id, ts DESC);
CREATE INDEX query_log_ts ON query_log (ts DESC);
CREATE INDEX facts_embedding ON facts USING hnsw (embedding vector_cosine_ops) WHERE superseded_by IS NULL;
CREATE INDEX facts_superseded ON facts (superseded_by) WHERE superseded_by IS NOT NULL;

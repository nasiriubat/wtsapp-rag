-- Who is in each group, as the channel last reported it. Kept in the
-- database rather than memory so a restart does not widen private access
-- until the gateway reports again.
CREATE TABLE gateway_members (
  group_id    TEXT PRIMARY KEY,
  channel     TEXT NOT NULL,
  members     TEXT[] NOT NULL,
  reported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

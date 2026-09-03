-- Phase 1: many groups, many providers. messages.group_id and chunks.group_id
-- keep holding the channel-qualified external id; groups.external_id matches it.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE providers (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('anthropic', 'gemini', 'openai')),
  base_url   TEXT,                       -- openai kind only; NULL means api.openai.com
  api_key    BYTEA NOT NULL,             -- pgp_sym_encrypt(key, SECRET_KEY)
  model      TEXT NOT NULL,
  price_in   NUMERIC(10, 4) NOT NULL DEFAULT 0,   -- EUR per 1M input tokens
  price_out  NUMERIC(10, 4) NOT NULL DEFAULT 0,   -- EUR per 1M output tokens
  options    JSONB NOT NULL DEFAULT '{}',         -- provider-specific knobs
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE groups (
  id          BIGSERIAL PRIMARY KEY,
  channel     TEXT NOT NULL,
  external_id TEXT UNIQUE NOT NULL,
  name        TEXT,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  provider_id BIGINT REFERENCES providers (id) ON DELETE SET NULL,
  settings    JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value JSONB NOT NULL
);

CREATE TABLE audit_log (
  id     BIGSERIAL PRIMARY KEY,
  ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor  TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  detail JSONB
);

ALTER TABLE query_log
  ADD COLUMN provider_id BIGINT,
  ADD COLUMN cost NUMERIC(12, 6);

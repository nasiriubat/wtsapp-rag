-- Phase 3: one row per channel kind. WhatsApp keeps its auth on the gateway's
-- disk, so its config is empty; Telegram and Discord hold a bot token.
CREATE TABLE channels (
  kind       TEXT PRIMARY KEY CHECK (kind IN ('whatsapp', 'telegram', 'discord')),
  config     BYTEA,                           -- pgp_sym_encrypt(json, SECRET_KEY)
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing installs are WhatsApp installs.
INSERT INTO channels (kind, config, enabled) VALUES ('whatsapp', NULL, TRUE);

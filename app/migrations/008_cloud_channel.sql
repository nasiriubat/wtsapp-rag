-- The Cloud API is a fourth channel kind. It answers direct messages on a
-- business number; Meta caps its groups at 8 participants and requires an
-- Official Business Account, so groups stay with the other channels.
ALTER TABLE channels DROP CONSTRAINT channels_kind_check;
ALTER TABLE channels ADD CONSTRAINT channels_kind_check
  CHECK (kind IN ('whatsapp', 'telegram', 'discord', 'whatsapp_cloud'));

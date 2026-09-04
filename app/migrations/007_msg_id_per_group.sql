-- WhatsApp lets a sender choose its message id. Uniqueness per group means a
-- crafted id cannot shadow another channel's message.
ALTER TABLE messages DROP CONSTRAINT messages_wa_msg_id_key;
CREATE UNIQUE INDEX messages_group_msg ON messages (group_id, wa_msg_id);

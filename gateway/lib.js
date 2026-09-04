// Pure functions over Baileys message objects and trigger text. No socket, no
// network, so they can be tested without a phone.

export function textOf(msg) {
  const m = msg.message ?? {};
  return m.conversation ?? m.extendedTextMessage?.text ?? m.imageMessage?.caption ?? null;
}

// A document or picture shared in the chat, as { filename, mime, media }, where
// `media` is the message shape Baileys can download. Null for anything else:
// audio and video carry no text we can index.
export function fileOf(msg) {
  const m = msg.message ?? {};
  const wrapped = m.documentWithCaptionMessage?.message?.documentMessage;
  const doc = m.documentMessage ?? wrapped;
  if (doc) {
    const media = wrapped ? { ...msg, message: { documentMessage: wrapped } } : msg;
    return { filename: doc.fileName ?? `document-${msg.key.id}`, mime: doc.mimetype ?? null, media };
  }
  if (m.imageMessage) {
    return { filename: `image-${msg.key.id}.jpg`, mime: m.imageMessage.mimetype ?? "image/jpeg", media: msg };
  }
  return null;
}

export function contextOf(msg) {
  return msg.message?.extendedTextMessage?.contextInfo;
}

// Device suffixes (":12") vary per login; the identity is the part before them.
export function bare(jid) {
  return (jid ?? "").replace(/:\d+(?=@)/, "");
}

// `isBot` is passed explicitly because "from me" is not the same as "from the
// bot": when the paired number is the operator's own, their messages are
// fromMe too, and those are questions, not answers.
export function toPayload(msg, ownJid, isBot = msg.key.fromMe === true) {
  const key = msg.key;
  return {
    wa_msg_id: key.id,
    group_id: key.remoteJid,
    // Baileys 7 addresses group members by LID; participantAlt carries the
    // phone-number JID when known, which is the stable identity across devices.
    // Our own sends carry no participant at all.
    sender_jid: key.fromMe ? ownJid : (key.participantAlt ?? key.participant),
    sender_name: msg.pushName ?? null,
    body: textOf(msg),
    quoted_msg_id: contextOf(msg)?.stanzaId ?? null,
    is_bot: isBot,
    ts: new Date(Number(msg.messageTimestamp) * 1000).toISOString(),
  };
}

export function hasPrefix(text, triggers) {
  const lower = text.toLowerCase();
  return triggers.some((t) => lower.startsWith(t));
}

export function isTrigger(msg, text, ownJids, triggers) {
  const ctx = contextOf(msg);
  if ((ctx?.mentionedJid ?? []).some((j) => ownJids.has(bare(j)))) return true;
  if (ctx?.participant && ownJids.has(bare(ctx.participant))) return true;
  return hasPrefix(text, triggers);
}

export function stripPrefix(text, triggers) {
  let q = text;
  for (const t of triggers) {
    if (q.toLowerCase().startsWith(t)) q = q.slice(t.length);
  }
  return q.trim();
}

export function questionOf(text, triggers) {
  // A JID mention renders as "@358401234567" in the text body.
  return stripPrefix(text, triggers).replace(/@\d+/g, "").trim();
}

export function quoteStub(groupJid, quote) {
  return {
    key: { remoteJid: groupJid, id: quote.wa_msg_id, participant: quote.sender_jid, fromMe: quote.is_bot },
    message: { conversation: quote.body ?? "" },
  };
}

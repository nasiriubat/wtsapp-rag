import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";

const GROUP_JID = process.env.GROUP_JID || "";
const APP_URL = process.env.APP_URL || "http://app:8000";
const TRIGGERS = (process.env.TRIGGERS || "@agent")
  .split(",")
  .map((t) => t.trim().toLowerCase())
  .filter(Boolean);

function textOf(msg) {
  const m = msg.message ?? {};
  return m.conversation ?? m.extendedTextMessage?.text ?? m.imageMessage?.caption ?? null;
}

function contextOf(msg) {
  return msg.message?.extendedTextMessage?.contextInfo;
}

// Device suffixes (":12") vary per login; the identity is the part before them.
function bare(jid) {
  return (jid ?? "").replace(/:\d+(?=@)/, "");
}

function toPayload(msg, ownJid) {
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
    is_bot: key.fromMe === true,
    ts: new Date(Number(msg.messageTimestamp) * 1000).toISOString(),
  };
}

async function post(path, body) {
  // The app may be down or mid-restart. That must not take the gateway down too.
  try {
    const res = await fetch(`${APP_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      console.error(`${path} ${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error(`${path} failed: ${err.message}`);
    return null;
  }
}

function isTrigger(msg, text, ownJids) {
  const ctx = contextOf(msg);
  if ((ctx?.mentionedJid ?? []).some((j) => ownJids.has(bare(j)))) return true;
  if (ctx?.participant && ownJids.has(bare(ctx.participant))) return true;
  const lower = text.toLowerCase();
  return TRIGGERS.some((t) => lower.startsWith(t));
}

function questionOf(text) {
  let q = text;
  for (const t of TRIGGERS) {
    if (q.toLowerCase().startsWith(t)) q = q.slice(t.length);
  }
  // A JID mention renders as "@358401234567" in the text body.
  return q.replace(/@\d+/g, "").trim();
}

function quoteStub(groupJid, quote) {
  return {
    key: { remoteJid: groupJid, id: quote.wa_msg_id, participant: quote.sender_jid, fromMe: quote.is_bot },
    message: { conversation: quote.body ?? "" },
  };
}

async function answer(sock, msg, text, ownJid) {
  const payload = toPayload(msg, ownJid);
  const reply = await post("/ask", {
    question: questionOf(text),
    group_id: payload.group_id,
    sender_jid: payload.sender_jid,
    sender_name: payload.sender_name,
    wa_msg_id: payload.wa_msg_id,
  });
  if (!reply) return;
  const quoted = reply.quote ? quoteStub(payload.group_id, reply.quote) : msg;
  const sent = await sock.sendMessage(payload.group_id, { text: reply.answer }, { quoted });
  await post("/ingest", toPayload(sent, ownJid));
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState("auth_state");
  const sock = makeWASocket({
    auth: state,
    // Baileys' default logger is info-level JSON and drowns the message payloads.
    logger: pino({ level: "warn" }),
    // Staying "offline" keeps notifications on the phone and looks less like a bot.
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) qrcode.generate(qr, { small: true });
    if (connection === "open") console.log(`connected as ${sock.user?.id} lid=${sock.user?.lid}`);
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.error("logged out; delete auth_state/ and scan again");
        process.exit(1);
      }
      console.error(`connection closed (${code}), reconnecting`);
      connect();
    }
  });

  sock.ev.on("messages.upsert", ({ type, messages }) => {
    // "append" is history sync and our own sends; only "notify" is new traffic.
    if (type !== "notify") return;
    const ownJid = bare(sock.user?.id);
    const ownJids = new Set([ownJid, bare(sock.user?.lid)].filter(Boolean));
    for (const msg of messages) {
      const jid = msg.key.remoteJid ?? "";
      if (!jid.endsWith("@g.us")) continue;
      if (!GROUP_JID) {
        console.log(`group seen: ${jid}  (set GROUP_JID in .env)`);
        continue;
      }
      if (jid !== GROUP_JID) continue;
      const text = textOf(msg);
      if (text === null) continue;
      const payload = toPayload(msg, ownJid);
      console.log(JSON.stringify(payload));
      post("/ingest", payload);
      if (!msg.key.fromMe && isTrigger(msg, text, ownJids)) answer(sock, msg, text, ownJid);
    }
  });
}

connect();

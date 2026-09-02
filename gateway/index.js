import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";

const GROUP_JID = process.env.GROUP_JID || "";
const APP_URL = process.env.APP_URL || "http://app:8000";

function textOf(msg) {
  const m = msg.message ?? {};
  return m.conversation ?? m.extendedTextMessage?.text ?? m.imageMessage?.caption ?? null;
}

function toPayload(msg) {
  const key = msg.key;
  const ctx = msg.message?.extendedTextMessage?.contextInfo;
  return {
    wa_msg_id: key.id,
    group_id: key.remoteJid,
    // Baileys 7 addresses group members by LID; participantAlt carries the
    // phone-number JID when known, which is the stable identity across devices.
    sender_jid: key.participantAlt ?? key.participant,
    sender_name: msg.pushName ?? null,
    body: textOf(msg),
    quoted_msg_id: ctx?.stanzaId ?? null,
    is_bot: key.fromMe === true,
    ts: new Date(Number(msg.messageTimestamp) * 1000).toISOString(),
  };
}

async function forward(payload) {
  console.log(JSON.stringify(payload));
  // The app service does not exist until session 2. A refused connection must
  // not take the gateway down with it.
  try {
    const res = await fetch(`${APP_URL}/ingest`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) console.error(`ingest ${res.status}`);
  } catch (err) {
    console.error(`ingest failed: ${err.message}`);
  }
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
    if (connection === "open") console.log("connected");
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
    for (const msg of messages) {
      const jid = msg.key.remoteJid ?? "";
      if (!jid.endsWith("@g.us")) continue;
      if (!GROUP_JID) {
        console.log(`group seen: ${jid}  (set GROUP_JID in .env)`);
        continue;
      }
      if (jid !== GROUP_JID) continue;
      if (textOf(msg) === null) continue;
      forward(toPayload(msg));
    }
  });
}

connect();

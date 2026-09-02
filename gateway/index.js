import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";
import { bare, isTrigger, parseTriggers, questionOf, quoteStub, textOf, toPayload } from "./lib.js";
import { createQueue } from "./queue.js";

const GROUP_JID = process.env.GROUP_JID || "";
const APP_URL = process.env.APP_URL || "http://app:8000";
const TRIGGERS = parseTriggers(process.env.TRIGGERS);

async function post(route, body) {
  // The app may be down or mid-restart. That must not take the gateway down too.
  try {
    const res = await fetch(`${APP_URL}${route}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      console.error(`${route} ${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error(`${route} failed: ${err.message}`);
    return null;
  }
}

const queue = createQueue("data/queue.jsonl", async (route, body) => (await post(route, body)) !== null);

async function ingest(payload) {
  if ((await post("/ingest", payload)) === null) queue.push("/ingest", payload);
}

async function answer(sock, msg, text, ownJid) {
  const payload = toPayload(msg, ownJid);
  const reply = await post("/ask", {
    question: questionOf(text, TRIGGERS),
    group_id: payload.group_id,
    sender_jid: payload.sender_jid,
    sender_name: payload.sender_name,
    wa_msg_id: payload.wa_msg_id,
  });
  if (!reply) return;
  const quoted = reply.quote ? quoteStub(payload.group_id, reply.quote) : msg;
  const sent = await sock.sendMessage(payload.group_id, { text: reply.answer }, { quoted });
  await ingest(toPayload(sent, ownJid));
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
      ingest(payload);
      if (!msg.key.fromMe && isTrigger(msg, text, ownJids, TRIGGERS)) answer(sock, msg, text, ownJid);
    }
  });
}

connect();

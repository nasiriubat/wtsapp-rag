import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";
import { bare, isTrigger, parseTriggers, questionOf, quoteStub, textOf, toPayload } from "./lib.js";
import { createQueue } from "./queue.js";

const GROUP_JID = process.env.GROUP_JID || "";
const APP_URL = process.env.APP_URL || "http://app:8000";
const TRIGGERS = parseTriggers(process.env.TRIGGERS);
const log = pino();

// Returns { status, data }. status 0 means the app was unreachable.
async function post(route, body) {
  try {
    const res = await fetch(`${APP_URL}${route}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = res.ok ? await res.json() : null;
    if (!res.ok) log.error({ route, status: res.status }, "app rejected request");
    return { status: res.status, data };
  } catch (err) {
    log.error({ route, err: err.message }, "app unreachable");
    return { status: 0, data: null };
  }
}

// Only outages are worth retrying. A 4xx is the app saying no to this payload.
const retryable = (status) => status === 0 || status >= 500;

const queue = createQueue("data/queue.jsonl", async (route, body) => !retryable((await post(route, body)).status));
setInterval(() => queue.flush().catch((err) => log.error({ err: err.message }, "queue flush failed")), 10_000);

async function ingest(payload) {
  // While older messages are waiting, go behind them so delivery stays in order.
  if (queue.size() === 0) {
    const { status } = await post("/ingest", payload);
    if (!retryable(status)) return;
  }
  try {
    queue.push("/ingest", payload);
  } catch (err) {
    log.error({ err: err.message, wa_msg_id: payload.wa_msg_id }, "queue write failed, message lost");
  }
}

async function answer(sock, msg, text, ownJid) {
  const payload = toPayload(msg, ownJid);
  const { data: reply } = await post("/ask", {
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
    // Baileys' info-level output drowns ours; keep only its warnings.
    logger: log.child({ module: "baileys" }, { level: "warn" }),
    // Staying "offline" keeps notifications on the phone and looks less like a bot.
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) qrcode.generate(qr, { small: true });
    if (connection === "open") log.info({ jid: sock.user?.id, lid: sock.user?.lid }, "connected");
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log.fatal("logged out; delete auth_state/ and scan again");
        process.exit(1);
      }
      log.warn({ code }, "connection closed, reconnecting");
      connect();
    }
  });

  const seen = new Set();
  sock.ev.on("messages.upsert", ({ type, messages }) => {
    // "append" is history sync and our own sends; only "notify" is new traffic.
    if (type !== "notify") return;
    const ownJid = bare(sock.user?.id);
    const ownJids = new Set([ownJid, bare(sock.user?.lid)].filter(Boolean));
    for (const msg of messages) {
      const jid = msg.key.remoteJid ?? "";
      if (!jid.endsWith("@g.us")) continue;
      if (!GROUP_JID) {
        if (!seen.has(jid)) log.info({ jid }, "group seen; set GROUP_JID in .env");
        seen.add(jid);
        continue;
      }
      if (jid !== GROUP_JID) continue;
      const text = textOf(msg);
      if (text === null) continue;
      const payload = toPayload(msg, ownJid);
      log.info(payload, "message");
      ingest(payload).catch((err) => log.error({ err: err.message }, "ingest failed"));
      if (!msg.key.fromMe && isTrigger(msg, text, ownJids, TRIGGERS)) {
        answer(sock, msg, text, ownJid).catch((err) => log.error({ err: err.message }, "answer failed"));
      }
    }
  });
}

connect();

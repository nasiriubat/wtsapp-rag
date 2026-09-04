import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import fs from "node:fs";
import qrcode from "qrcode-terminal";
import pino from "pino";
import { bare, isTrigger, questionOf, quoteStub, textOf, toPayload } from "./lib.js";
import { loadGroups } from "./config.js";
import { createQueue } from "./queue.js";

const APP_URL = process.env.APP_URL || "http://app:8000";
const TOKEN = process.env.GATEWAY_TOKEN;
const log = pino();
if (!TOKEN) {
  log.fatal("GATEWAY_TOKEN is not set");
  process.exit(1);
}

// Returns { status, data }. status 0 means the app was unreachable.
async function post(route, body) {
  try {
    const res = await fetch(`${APP_URL}${route}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${TOKEN}` },
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

// What the app knows about us: connection, the current QR, the groups we can see.
const state = { connected: false, jid: null, qr: null, groups: [] };
const report = () => post("/gateway/state", state);

let groups = new Map();
async function refreshGroups() {
  try {
    const { groups: fresh, relink } = await loadGroups(APP_URL, TOKEN);
    groups = fresh;
    if (relink) {
      // The admin asked for a new QR. Dropping the auth state and exiting lets
      // compose restart us into a fresh pairing.
      log.warn("relink requested; clearing auth state and restarting");
      fs.rmSync("auth_state", { recursive: true, force: true });
      process.exit(0);
    }
  } catch (err) {
    log.warn({ err: err.message }, "could not load groups; keeping the previous list");
  }
}
setInterval(() => refreshGroups().then(report), 30_000);

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

async function answer(sock, msg, text, ownJid, triggers) {
  const payload = toPayload(msg, ownJid);
  const { data: reply } = await post("/ask", {
    question: questionOf(text, triggers),
    group_id: payload.group_id,
    sender_jid: payload.sender_jid,
    sender_name: payload.sender_name,
    wa_msg_id: payload.wa_msg_id,
  });
  // answer: null means the app chose silence (quiet hours, opt-out, disabled).
  if (!reply?.answer) return;
  const quoted = reply.quote ? quoteStub(payload.group_id, reply.quote) : msg;
  const sent = await sock.sendMessage(payload.group_id, { text: reply.answer }, { quoted });
  await ingest(toPayload(sent, ownJid));
}

async function listGroups(sock) {
  try {
    const all = await sock.groupFetchAllParticipating();
    return Object.values(all).map((g) => ({ id: g.id, subject: g.subject }));
  } catch (err) {
    log.warn({ err: err.message }, "could not list groups");
    return [];
  }
}

async function connect() {
  const { state: creds, saveCreds } = await useMultiFileAuthState("auth_state");
  const sock = makeWASocket({
    auth: creds,
    // Baileys' info-level output drowns ours; keep only its warnings.
    logger: log.child({ module: "baileys" }, { level: "warn" }),
    // Staying "offline" keeps notifications on the phone and looks less like a bot.
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrcode.generate(qr, { small: true });
      Object.assign(state, { connected: false, qr });
      report();
    }
    if (connection === "open") {
      log.info({ jid: sock.user?.id, lid: sock.user?.lid }, "connected");
      Object.assign(state, { connected: true, jid: bare(sock.user?.id), qr: null, groups: await listGroups(sock) });
      report();
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      Object.assign(state, { connected: false });
      report();
      if (code === DisconnectReason.loggedOut) {
        log.fatal("logged out; delete auth_state/ and scan again, or use the admin's relink");
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
      const group = groups.get(jid);
      if (!group) {
        if (!seen.has(jid)) log.info({ jid }, "group seen; enable it in the admin to start logging it");
        seen.add(jid);
        continue;
      }
      const text = textOf(msg);
      if (text === null) continue;
      const payload = toPayload(msg, ownJid);
      log.info(payload, "message");
      ingest(payload).catch((err) => log.error({ err: err.message }, "ingest failed"));
      if (!msg.key.fromMe && isTrigger(msg, text, ownJids, group.triggers)) {
        answer(sock, msg, text, ownJid, group.triggers).catch((err) => log.error({ err: err.message }, "answer failed"));
      }
    }
  });
}

await refreshGroups();
await report();
connect();

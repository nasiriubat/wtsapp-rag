// Meta's official WhatsApp Cloud API. It answers direct messages on a business
// number: Meta caps Cloud API groups at 8 participants and requires an Official
// Business Account, so group watching stays with the other channels. Needs a
// public HTTPS webhook in front of this listener.
import crypto from "node:crypto";
import http from "node:http";
import { blankState } from "../core.js";

// Checked against Meta's docs when this was written; bump it when a version retires.
const GRAPH = "https://graph.facebook.com/v21.0";
const PATH = "/webhook/whatsapp_cloud";
const PORT = Number(process.env.GATEWAY_PORT || 8080);
// Meta's payloads are a few kilobytes. This listener is public, so anything
// larger is refused before the signature is even checked.
export const MAX_BODY = 1024 * 1024;
const SEEN = 1000; // message ids remembered, so a retried delivery is not answered twice

function same(a, b) {
  const x = Buffer.from(String(a ?? ""));
  const y = Buffer.from(String(b ?? ""));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

export function signatureOk(raw, header, appSecret) {
  const sent = String(header || "").replace(/^sha256=/, "");
  const mine = crypto.createHmac("sha256", appSecret).update(raw).digest("hex");
  const a = Buffer.from(sent, "hex");
  const b = Buffer.from(mine, "hex");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function verification(query, verifyToken) {
  return query.get("hub.mode") === "subscribe" && same(query.get("hub.verify_token"), verifyToken)
    ? query.get("hub.challenge")
    : null;
}

// The same person is `<number>@s.whatsapp.net` here and on the paired phone, so
// a Cloud API question finds the groups they are in on the other channel.
export function payloadFromCloud(msg, contact) {
  return {
    wa_msg_id: `wc:${msg.id}`,
    group_id: null,
    sender_jid: `${msg.from}@s.whatsapp.net`,
    sender_name: contact?.profile?.name ?? null,
    body: msg.text?.body ?? null,
    quoted_msg_id: msg.context?.id ? `wc:${msg.context.id}` : null,
    is_bot: false,
    ts: new Date(Number(msg.timestamp) * 1000).toISOString(),
  };
}

export function incoming(body) {
  const out = [];
  for (const entry of body?.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value ?? {};
      const contacts = new Map((value.contacts ?? []).map((c) => [c.wa_id, c]));
      for (const msg of value.messages ?? []) {
        if (msg.type === "text") out.push(payloadFromCloud(msg, contacts.get(msg.from)));
      }
    }
  }
  return out;
}

// Null when the body is over the cap; the caller answers 413 and drops the socket.
async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) return null;
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

export async function start(core, config, log) {
  const state = { ...blankState(), connected: true, jid: config.phone_number_id };
  const seen = new Set();
  function remember(id) {
    seen.add(id);
    if (seen.size > SEEN) seen.delete(seen.values().next().value);
  }

  async function send(to, text) {
    const res = await fetch(`${GRAPH}/${config.phone_number_id}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${config.token}` },
      body: JSON.stringify({ messaging_product: "whatsapp", to, type: "text", text: { body: text.slice(0, 4096) } }),
    });
    // Outside the 24-hour window Meta rejects a free-form reply; that is theirs to decide.
    if (!res.ok) log.error({ status: res.status, body: (await res.text()).slice(0, 300) }, "cloud send failed");
  }

  async function handle(req, res) {
    // A malformed target or a truncated body throws here, and this listener is
    // public by design: without the catch below one packet ends the process.
    const url = new URL(req.url, "http://localhost");
    if (url.pathname !== PATH) return res.writeHead(404).end();
    if (req.method === "GET") {
      const challenge = verification(url.searchParams, config.verify_token);
      return challenge ? res.writeHead(200).end(challenge) : res.writeHead(403).end();
    }
    if (req.method !== "POST") return res.writeHead(405).end();
    const raw = await readBody(req);
    if (raw === null) {
      log.warn("cloud webhook body too large");
      res.writeHead(413).end();
      return req.destroy();
    }
    if (!signatureOk(raw, req.headers["x-hub-signature-256"], config.app_secret)) {
      log.warn("cloud webhook signature rejected");
      return res.writeHead(401).end();
    }
    // Meta retries anything that is not answered quickly, so answer first.
    res.writeHead(200).end();
    let payloads = [];
    try {
      payloads = incoming(JSON.parse(raw.toString()));
    } catch (err) {
      return log.error({ err: err.message }, "cloud webhook is not JSON");
    }
    for (const payload of payloads) {
      if (payload.body === null || seen.has(payload.wa_msg_id)) continue;
      remember(payload.wa_msg_id);
      core
        .handleDirect(payload, (answer) => send(payload.sender_jid.split("@")[0], answer))
        .catch((err) => log.error({ err: err.message }, "cloud handle failed"));
    }
  }

  const server = http.createServer((req, res) => {
    handle(req, res).catch((err) => {
      log.warn({ err: err.message }, "cloud webhook request failed");
      if (!res.headersSent) res.writeHead(400);
      res.end();
    });
  });

  // A client that sends headers slowly, or a body slowly, is cut off; Meta is neither.
  server.headersTimeout = 5_000;
  server.requestTimeout = 10_000;
  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(PORT, resolve);
  });
  log.info({ port: PORT, path: PATH }, "cloud webhook listening");
  return {
    report: () => core.report("whatsapp_cloud", state),
    stop: () => {
      server.close();
      // Keep-alive sockets would otherwise hold the port through a restart.
      server.closeAllConnections();
    },
  };
}

// What every channel shares: talking to the app, the retry queue, the
// ingest-then-maybe-answer flow. Channels only map their platform's messages
// to payloads, decide triggers, and send replies.
import { createQueue } from "./queue.js";

export const blankState = () => ({ connected: false, jid: null, qr: null, groups: [] });

export function createCore({ appUrl, token, log, queueFile = process.env.QUEUE_FILE || "data/queue.jsonl" }) {
  // Returns { status, data }. status 0 means the app was unreachable.
  async function post(route, body) {
    try {
      const res = await fetch(`${appUrl}${route}`, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
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
  const queue = createQueue(queueFile, async (route, body) => !retryable((await post(route, body)).status), {
    warn: (fields, msg) => log.warn(fields, msg),
  });
  // unref: the timer must not keep a test process alive on its own.
  setInterval(() => queue.flush().catch((err) => log.error({ err: err.message }, "queue flush failed")), 10_000).unref();

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

  // Files shared in a chat, when the group has opted in. Not queued: a retry
  // file would hold megabytes of base64, and a file is never as urgent as a
  // message. The app decides whether to keep it.
  const MAX_FILE_BYTES = 10 * 1024 * 1024;

  // Channels ask this with the size the platform declares, before downloading:
  // a 500 MB attachment must be refused without ever being fetched.
  function fileAllowed(size, filename) {
    if (size != null && Number(size) > MAX_FILE_BYTES) {
      log.info({ filename, bytes: Number(size) }, "shared file skipped: too large");
      return false;
    }
    return true;
  }

  async function shareFile({ groupId, senderJid, filename, mime, bytes }) {
    if (!bytes || !fileAllowed(bytes.length, filename)) return;
    log.info({ group_id: groupId, filename, bytes: bytes.length }, "shared file");
    await post("/ingest/file", {
      group_id: groupId,
      sender_jid: senderJid,
      filename,
      mime: mime ?? null,
      data: Buffer.from(bytes).toString("base64"),
    });
  }

  let groups = new Map();

  async function refresh() {
    const res = await fetch(`${appUrl}/gateway/config`, { headers: { authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`config ${res.status}`);
    const cfg = await res.json();
    groups = new Map(
      cfg.groups.map((g) => [g.external_id, { ...g, triggers: g.triggers.map((t) => t.toLowerCase()) }]),
    );
    return cfg;
  }

  // One flow for every channel. `trigger()` returns the question when the
  // message is for us, else null; it runs after ingest so cheap channels do not
  // pay for it on chatter. `send(text, quote)` returns the payload of the
  // message the channel sent, or null.
  async function handle(payload, { trigger, send }) {
    // Metadata only: the logs must not become a plaintext copy of the chat.
    log.info(
      { wa_msg_id: payload.wa_msg_id, group_id: payload.group_id, sender_jid: payload.sender_jid,
        chars: (payload.body ?? "").length },
      "message",
    );
    const ingested = ingest(payload);
    const question = await trigger();
    if (question === null || question === undefined) return ingested;
    const [{ data: reply }] = await Promise.all([
      post("/ask", {
        question,
        group_id: payload.group_id,
        sender_jid: payload.sender_jid,
        sender_name: payload.sender_name,
        wa_msg_id: payload.wa_msg_id,
        quoted_msg_id: payload.quoted_msg_id ?? null,
      }),
      ingested,
    ]);
    // answer: null means the app chose silence (quiet hours, opt-out, disabled).
    if (!reply?.answer) return;
    const sent = await send(reply.answer, reply.quote);
    if (sent) await ingest(sent);
  }

  // A private message to the bot, as the channel's own payload. Never stored;
  // answered from the sender's groups with a text citation, or declined.
  async function handleDirect(payload, send) {
    const { data: reply } = await post("/ask", {
      question: payload.body,
      group_id: null,
      sender_jid: payload.sender_jid,
      sender_name: payload.sender_name,
      wa_msg_id: payload.wa_msg_id,
    });
    if (reply?.answer) await send(reply.answer);
  }

  return {
    refresh,
    handle,
    handleDirect,
    shareFile,
    fileAllowed,
    // One last delivery attempt before the process goes; used on SIGTERM.
    flush: () => queue.flush(),
    groupFor: (externalId) => groups.get(externalId),
    report: (channel, state) => post("/gateway/state", { channel, ...state }),
  };
}

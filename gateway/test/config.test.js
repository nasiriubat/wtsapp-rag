import { test } from "node:test";
import assert from "node:assert/strict";
import { createCore } from "../core.js";

const log = { info() {}, warn() {}, error() {} };

test("refresh loads groups with lowercased triggers and returns channels and relink", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return {
      ok: true,
      json: async () => ({
        channels: [{ kind: "telegram", config: { token: "t" } }],
        groups: [{ external_id: "1@g.us", channel: "whatsapp", triggers: ["@Agent", "Hey"] }],
        relink: true,
      }),
    };
  };
  const core = createCore({ appUrl: "http://app:8000", token: "tok", log });
  const cfg = await core.refresh();
  assert.equal(calls[0][0], "http://app:8000/gateway/config");
  assert.equal(calls[0][1].headers.authorization, "Bearer tok");
  assert.deepEqual(core.groupFor("1@g.us").triggers, ["@agent", "hey"]);
  assert.equal(cfg.relink, true);
  assert.equal(cfg.channels[0].kind, "telegram");
});

test("refresh throws on a rejected token so the caller keeps the old list", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 401 });
  const core = createCore({ appUrl: "http://app:8000", token: "bad", log });
  await assert.rejects(core.refresh(), /config 401/);
});

test("handle ingests, asks only when triggered, and ingests the reply it sent", async () => {
  const posted = [];
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    posted.push([url.replace("http://app:8000", ""), body]);
    if (url.endsWith("/ask")) return { ok: true, json: async () => ({ answer: "Mikko.", quote: null }) };
    return { ok: true, json: async () => ({ ok: true }) };
  };
  const core = createCore({ appUrl: "http://app:8000", token: "tok", log });
  const payload = { wa_msg_id: "m1", group_id: "g", sender_jid: "s", sender_name: "A", body: "@agent who?" };
  await core.handle(payload, { triggered: false, question: "who?", send: async () => null });
  assert.deepEqual(posted.map(([r]) => r), ["/ingest"]);

  posted.length = 0;
  const sent = { wa_msg_id: "m2", group_id: "g", sender_jid: "bot", body: "Mikko.", is_bot: true };
  await core.handle(payload, { triggered: true, question: "who?", send: async (text) => ({ ...sent, body: text }) });
  assert.deepEqual(posted.map(([r]) => r), ["/ingest", "/ask", "/ingest"]);
  assert.equal(posted[1][1].question, "who?");
  assert.equal(posted[2][1].is_bot, true);
});

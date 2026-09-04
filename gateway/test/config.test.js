import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createCore } from "../core.js";

const log = { info() {}, warn() {}, error() {} };
// Never touch the real data/queue.jsonl from a test run.
const queueFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "core-")), "queue.jsonl");

test("refresh loads groups with lowercased triggers and returns channels and relink", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return {
      ok: true,
      json: async () => ({
        channels: [{ kind: "telegram", config: { token: "t" } }],
        groups: [{ external_id: "1@g.us", channel: "whatsapp", triggers: ["@Agent", "Hey"] }],
        relink: ["whatsapp"],
      }),
    };
  };
  const core = createCore({ appUrl: "http://app:8000", token: "tok", log, queueFile: queueFile() });
  const cfg = await core.refresh();
  assert.equal(calls[0][0], "http://app:8000/gateway/config");
  assert.equal(calls[0][1].headers.authorization, "Bearer tok");
  assert.deepEqual(core.groupFor("1@g.us").triggers, ["@agent", "hey"]);
  assert.deepEqual(cfg.relink, ["whatsapp"]);
  assert.equal(cfg.channels[0].kind, "telegram");
});

test("refresh throws on a rejected token so the caller keeps the old list", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 401 });
  const core = createCore({ appUrl: "http://app:8000", token: "bad", log, queueFile: queueFile() });
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
  const core = createCore({ appUrl: "http://app:8000", token: "tok", log, queueFile: queueFile() });
  const payload = { wa_msg_id: "m1", group_id: "g", sender_jid: "s", sender_name: "A", body: "@agent who?" };
  await core.handle(payload, { trigger: () => null, send: async () => null });
  assert.deepEqual(posted.map(([r]) => r), ["/ingest"]);

  posted.length = 0;
  const sent = { wa_msg_id: "m2", group_id: "g", sender_jid: "bot", body: "Mikko.", is_bot: true };
  await core.handle(payload, { trigger: async () => "who?", send: async (text) => ({ ...sent, body: text }) });
  assert.deepEqual(posted.map(([r]) => r).sort(), ["/ask", "/ingest", "/ingest"]);
  assert.equal(posted.find(([r]) => r === "/ask")[1].question, "who?");
  assert.equal(posted.filter(([r]) => r === "/ingest")[1][1].is_bot, true);
});

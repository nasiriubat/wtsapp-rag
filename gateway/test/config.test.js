import { test } from "node:test";
import assert from "node:assert/strict";
import { loadGroups } from "../config.js";

test("loadGroups sends the token and lowercases triggers", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return {
      ok: true,
      json: async () => ({ groups: [{ external_id: "1@g.us", channel: "whatsapp", triggers: ["@Agent", "Hey"] }] }),
    };
  };
  const groups = await loadGroups("http://app:8000", "tok");
  assert.equal(calls[0][0], "http://app:8000/gateway/config");
  assert.equal(calls[0][1].headers.authorization, "Bearer tok");
  assert.deepEqual(groups.get("1@g.us").triggers, ["@agent", "hey"]);
});

test("loadGroups throws on a rejected token so the caller keeps the old list", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 401 });
  await assert.rejects(loadGroups("http://app:8000", "bad"), /config 401/);
});

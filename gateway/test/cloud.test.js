import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { incoming, payloadFromCloud, signatureOk, verification } from "../channels/whatsapp_cloud.js";

const SECRET = "app-secret";

test("signature must match the app secret over the raw body", () => {
  const raw = Buffer.from('{"a":1}');
  const good = "sha256=" + crypto.createHmac("sha256", SECRET).update(raw).digest("hex");
  assert.equal(signatureOk(raw, good, SECRET), true);
  assert.equal(signatureOk(raw, good, "other-secret"), false);
  assert.equal(signatureOk(Buffer.from('{"a":2}'), good, SECRET), false);
  assert.equal(signatureOk(raw, undefined, SECRET), false);
  assert.equal(signatureOk(raw, "sha256=short", SECRET), false);
});

test("webhook verification echoes the challenge only for the right token", () => {
  const q = (token) => new URLSearchParams({ "hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42" });
  assert.equal(verification(q("mine"), "mine"), "42");
  assert.equal(verification(q("theirs"), "mine"), null);
  assert.equal(verification(new URLSearchParams({ "hub.mode": "unsubscribe" }), "mine"), null);
});

test("a text message becomes a payload with the phone-number identity", () => {
  const msg = { id: "wamid.X", from: "358401234567", timestamp: "1756800000", type: "text", text: { body: "hi" } };
  const p = payloadFromCloud(msg, { wa_id: "358401234567", profile: { name: "Anna" } });
  assert.deepEqual(p, {
    wa_msg_id: "wc:wamid.X",
    group_id: null,
    // Matches the id the paired phone reports, so DM mode finds her groups.
    sender_jid: "358401234567@s.whatsapp.net",
    sender_name: "Anna",
    body: "hi",
    quoted_msg_id: null,
    is_bot: false,
    ts: "2025-09-02T08:00:00.000Z",
  });
});

test("incoming picks text messages out of a webhook and ignores the rest", () => {
  const body = {
    entry: [
      {
        changes: [
          {
            value: {
              contacts: [{ wa_id: "358401234567", profile: { name: "Anna" } }],
              messages: [
                { id: "1", from: "358401234567", timestamp: "1756800000", type: "text", text: { body: "hi" } },
                { id: "2", from: "358401234567", timestamp: "1756800001", type: "image" },
              ],
            },
          },
          { value: { statuses: [{ status: "delivered" }] } },
        ],
      },
    ],
  };
  const out = incoming(body);
  assert.equal(out.length, 1);
  assert.equal(out[0].body, "hi");
  assert.deepEqual(incoming({}), []);
});

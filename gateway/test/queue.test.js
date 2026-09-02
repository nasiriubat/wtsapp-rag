import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createQueue } from "../queue.js";

function tmpFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "q-")), "queue.jsonl");
}

test("retries until the app accepts, then empties", async () => {
  const file = tmpFile();
  let accept = false;
  const sent = [];
  const q = createQueue(file, async (route, body) => {
    if (!accept) return false;
    sent.push([route, body]);
    return true;
  }, 1e9);
  q.push("/ingest", { wa_msg_id: "1" });
  q.push("/ingest", { wa_msg_id: "2" });
  await q.flush();
  assert.equal(q.size(), 2);
  accept = true;
  await q.flush();
  assert.equal(q.size(), 0);
  assert.deepEqual(sent.map(([, b]) => b.wa_msg_id), ["1", "2"]);
  assert.equal(fs.readFileSync(file, "utf8"), "");
  q.stop();
});

test("survives a restart: items are reloaded from disk", async () => {
  const file = tmpFile();
  const q1 = createQueue(file, async () => false, 1e9);
  q1.push("/ingest", { wa_msg_id: "kept" });
  q1.stop();
  const delivered = [];
  const q2 = createQueue(file, async (route, body) => (delivered.push(body), true), 1e9);
  assert.equal(q2.size(), 1);
  await q2.flush();
  assert.deepEqual(delivered, [{ wa_msg_id: "kept" }]);
  q2.stop();
});

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createQueue } from "../queue.js";

function tmpFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "q-")), "queue.jsonl");
}

test("retries in order until the app accepts, then empties the file", async () => {
  const file = tmpFile();
  let accept = false;
  const sent = [];
  const q = createQueue(file, async (route, body) => {
    if (!accept) return false;
    sent.push(body.wa_msg_id);
    return true;
  });
  q.push("/ingest", { wa_msg_id: "1" });
  q.push("/ingest", { wa_msg_id: "2" });
  await q.flush();
  assert.equal(q.size(), 2);
  accept = true;
  await q.flush();
  assert.equal(q.size(), 0);
  assert.deepEqual(sent, ["1", "2"]);
  assert.equal(fs.readFileSync(file, "utf8"), "");
});

test("stops at the first failure and keeps the rest", async () => {
  const file = tmpFile();
  const q = createQueue(file, async (route, body) => body.wa_msg_id === "1");
  q.push("/ingest", { wa_msg_id: "1" });
  q.push("/ingest", { wa_msg_id: "2" });
  q.push("/ingest", { wa_msg_id: "3" });
  await q.flush();
  assert.equal(q.size(), 2);
  assert.equal(fs.readFileSync(file, "utf8"), '{"route":"/ingest","body":{"wa_msg_id":"2"}}\n{"route":"/ingest","body":{"wa_msg_id":"3"}}\n');
});

test("survives a restart and skips a line cut short by a crash", async () => {
  const file = tmpFile();
  const q1 = createQueue(file, async () => false);
  q1.push("/ingest", { wa_msg_id: "kept" });
  fs.appendFileSync(file, '{"route":"/ingest","body":{"wa_msg_');
  const delivered = [];
  const q2 = createQueue(file, async (route, body) => (delivered.push(body), true));
  assert.equal(q2.size(), 1);
  await q2.flush();
  assert.deepEqual(delivered, [{ wa_msg_id: "kept" }]);
});

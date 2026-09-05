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

test("a message the app keeps rejecting is set aside so the rest can flow", async () => {
  const file = tmpFile();
  const warnings = [];
  const q = createQueue(file, async (route, body) => body.wa_msg_id !== "poison", {
    maxAttempts: 3,
    warn: (fields, msg) => warnings.push(msg),
  });
  q.push("/ingest", { wa_msg_id: "poison" });
  q.push("/ingest", { wa_msg_id: "2" });
  await q.flush();
  await q.flush();
  assert.equal(q.size(), 2, "two attempts: still waiting behind the poison");
  await q.flush();
  assert.equal(q.size(), 0, "third failure moves it aside and the rest delivers");
  assert.match(warnings.join(" "), /dead-letter/);
  assert.match(fs.readFileSync(file.replace(".jsonl", ".dead.jsonl"), "utf8"), /poison/);
});

test("the queue drops its oldest messages rather than growing without bound", async () => {
  const file = tmpFile();
  const warnings = [];
  const q = createQueue(file, async () => false, { max: 3, warn: (f, m) => warnings.push(m) });
  for (const id of ["1", "2", "3", "4", "5"]) q.push("/ingest", { wa_msg_id: id });
  assert.equal(q.size(), 3);
  assert.deepEqual(
    fs.readFileSync(file, "utf8").trim().split("\n").map((l) => JSON.parse(l).body.wa_msg_id),
    ["3", "4", "5"],
  );
  assert.equal(warnings.length, 2);
});

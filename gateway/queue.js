import fs from "node:fs";
import path from "node:path";

// Messages the app could not accept because it was unreachable wait here on
// disk and are retried in order until they land. Ingest is idempotent, so a
// double delivery is harmless.
//
// Two bounds keep a long outage from becoming a second problem: the queue
// holds at most `max` items, dropping the oldest, and an item the app keeps
// rejecting with a 5xx is moved aside after `maxAttempts` so it cannot block
// everything behind it forever.
export function createQueue(file, send, { max = 50_000, maxAttempts = 20, warn = () => {} } = {}) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const dead = `${file.replace(/\.jsonl$/, "")}.dead.jsonl`;
  let items = load(file);
  let flushing = false;

  function push(route, body) {
    items.push({ route, body, attempts: 0 });
    fs.appendFileSync(file, JSON.stringify({ route, body }) + "\n");
    if (items.length > max) {
      const dropped = items.length - max;
      items = items.slice(dropped);
      rewrite();
      warn({ dropped }, "queue full; oldest messages dropped");
    }
  }

  function rewrite() {
    // Write-then-rename so a crash never leaves a half-written file behind.
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, items.map(({ route, body }) => JSON.stringify({ route, body }) + "\n").join(""));
    fs.renameSync(tmp, file);
  }

  async function flush() {
    if (flushing || !items.length) return;
    flushing = true;
    try {
      let changed = false;
      while (items.length) {
        const it = items[0];
        if (await send(it.route, it.body)) {
          items.shift();
          changed = true;
          continue;
        }
        // FIFO: if the head cannot land, nothing behind it will either, unless
        // the head itself is the problem.
        if (++it.attempts < maxAttempts) break;
        fs.appendFileSync(dead, JSON.stringify({ route: it.route, body: it.body }) + "\n");
        items.shift();
        changed = true;
        warn({ route: it.route, wa_msg_id: it.body?.wa_msg_id, attempts: it.attempts }, "message set aside; see the dead-letter file");
      }
      if (changed) rewrite();
    } finally {
      flushing = false;
    }
  }

  return { push, flush, size: () => items.length };
}

function load(file) {
  if (!fs.existsSync(file)) return [];
  const items = [];
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line) continue;
    try {
      items.push({ ...JSON.parse(line), attempts: 0 });
    } catch {
      // A line cut short by a crash mid-append. Nothing to recover from it.
    }
  }
  return items;
}

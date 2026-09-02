import fs from "node:fs";
import path from "node:path";

// Messages the app could not accept because it was unreachable wait here on
// disk and are retried in order until they land. Ingest is idempotent, so a
// double delivery is harmless.
export function createQueue(file, send) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  let items = load(file);
  let flushing = false;

  function push(route, body) {
    items.push({ route, body });
    fs.appendFileSync(file, JSON.stringify({ route, body }) + "\n");
  }

  async function flush() {
    if (flushing || !items.length) return;
    flushing = true;
    try {
      let delivered = 0;
      for (const it of items) {
        // FIFO: if the head cannot land, nothing behind it will either.
        if (!(await send(it.route, it.body))) break;
        delivered++;
      }
      if (!delivered) return;
      items = items.slice(delivered);
      // Write-then-rename so a crash never leaves a half-written file behind.
      const tmp = `${file}.tmp`;
      fs.writeFileSync(tmp, items.map((it) => JSON.stringify(it) + "\n").join(""));
      fs.renameSync(tmp, file);
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
      items.push(JSON.parse(line));
    } catch {
      // A line cut short by a crash mid-append. Nothing to recover from it.
    }
  }
  return items;
}

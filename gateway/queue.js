import fs from "node:fs";
import path from "node:path";

// Messages the app could not accept (restart, network) wait here on disk and
// are retried until they land. Ingest is idempotent, so retrying is safe.
export function createQueue(file, send, intervalMs = 10000) {
  let items = load(file);
  let flushing = false;

  function save() {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, items.map((it) => JSON.stringify(it)).join("\n") + (items.length ? "\n" : ""));
  }

  function push(route, body) {
    items.push({ route, body });
    save();
  }

  async function flush() {
    if (flushing) return;
    flushing = true;
    const rest = [];
    for (const it of items) {
      if (!(await send(it.route, it.body))) rest.push(it);
    }
    items = rest;
    save();
    flushing = false;
  }

  const timer = setInterval(flush, intervalMs);
  timer.unref();
  return { push, flush, size: () => items.length, stop: () => clearInterval(timer) };
}

function load(file) {
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

// Runs every channel the admin enabled. The app owns the list; this process
// starts, restarts and stops channels to match it every 30 seconds.
import pino from "pino";
import { createCore } from "./core.js";
import * as discord from "./channels/discord.js";
import * as telegram from "./channels/telegram.js";
import * as whatsapp from "./channels/whatsapp.js";

const APP_URL = process.env.APP_URL || "http://app:8000";
const TOKEN = process.env.GATEWAY_TOKEN;
const log = pino();
if (!TOKEN) {
  log.fatal("GATEWAY_TOKEN is not set");
  process.exit(1);
}

const MODULES = { whatsapp, telegram, discord };
const core = createCore({ appUrl: APP_URL, token: TOKEN, log });
const running = new Map(); // kind -> { handle, fingerprint }

async function sync() {
  let cfg;
  try {
    cfg = await core.refresh();
  } catch (err) {
    log.warn({ err: err.message }, "could not load config; keeping the previous state");
    for (const { handle } of running.values()) handle.report();
    return;
  }
  const wanted = new Map(cfg.channels.map((c) => [c.kind, c]));
  for (const [kind, entry] of running) {
    const want = wanted.get(kind);
    if (!want || JSON.stringify(want.config) !== entry.fingerprint) {
      log.info({ kind }, want ? "channel config changed; restarting" : "channel disabled; stopping");
      entry.handle.stop();
      running.delete(kind);
    }
  }
  for (const [kind, c] of wanted) {
    if (running.has(kind) || !MODULES[kind]) continue;
    try {
      const handle = await MODULES[kind].start(core, c.config, log.child({ channel: kind }));
      running.set(kind, { handle, fingerprint: JSON.stringify(c.config) });
    } catch (err) {
      log.error({ kind, err: err.message }, "channel failed to start");
      core.report(kind, { connected: false, jid: null, qr: null, groups: [] });
    }
  }
  if (cfg.relink && running.has("whatsapp")) await running.get("whatsapp").handle.relink();
  for (const { handle } of running.values()) handle.report();
}

await sync();
setInterval(() => sync().catch((err) => log.error({ err: err.message }, "sync failed")), 30_000);

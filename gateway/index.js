// Runs every channel the admin enabled. The app owns the list; this process
// starts, restarts and stops channels to match it.
import pino from "pino";
import { blankState, createCore } from "./core.js";
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
const running = new Map();
let syncing = false;

async function stop(kind) {
  const entry = running.get(kind);
  running.delete(kind);
  try {
    await entry.handle.stop();
  } catch (err) {
    log.warn({ kind, err: err.message }, "stop failed");
  }
  // The app keeps the last report; tell it this channel is gone.
  await core.report(kind, blankState());
}

async function start(kind, config) {
  try {
    const handle = await MODULES[kind].start(core, config, log.child({ channel: kind }));
    running.set(kind, { handle, fingerprint: JSON.stringify(config) });
  } catch (err) {
    log.error({ kind, err: err.message }, "channel failed to start");
    await core.report(kind, blankState());
  }
}

async function sync() {
  // A slow start must not let the next tick start the same channel again.
  if (syncing) return;
  syncing = true;
  try {
    let cfg;
    try {
      cfg = await core.refresh();
    } catch (err) {
      log.warn({ err: err.message }, "could not load config; keeping the previous state");
      for (const { handle } of running.values()) handle.report();
      return;
    }
    const wanted = new Map(cfg.channels.map((c) => [c.kind, c]));
    for (const [kind, entry] of [...running]) {
      const want = wanted.get(kind);
      if (!want || !MODULES[kind]) {
        log.info({ kind }, "channel disabled; stopping");
        await stop(kind);
      } else if (JSON.stringify(want.config) !== entry.fingerprint || entry.handle.dead?.()) {
        log.info({ kind }, entry.handle.dead?.() ? "channel died; restarting" : "channel config changed; restarting");
        await stop(kind);
      }
    }
    await Promise.all([...wanted].filter(([k]) => !running.has(k) && MODULES[k]).map(([k, c]) => start(k, c.config)));
    for (const kind of cfg.relink ?? []) {
      if (running.get(kind)?.handle.relink) await running.get(kind).handle.relink();
      else log.warn({ kind }, "relink requested for a channel that is not running");
    }
    for (const { handle } of running.values()) handle.report();
  } finally {
    syncing = false;
  }
}

// The app loads its models for a while after boot; poll fast until the first
// config arrives, then settle into the 30-second rhythm.
async function main() {
  while (running.size === 0) {
    await sync();
    if (running.size === 0) await new Promise((r) => setTimeout(r, 5_000));
  }
  setInterval(() => sync().catch((err) => log.error({ err: err.message }, "sync failed")), 30_000);
}

main();

// Runs every channel the admin enabled. The app owns the list; this process
// starts, restarts and stops channels to match it.
import pino from "pino";
import { blankState, createCore } from "./core.js";
import * as discord from "./channels/discord.js";
import * as telegram from "./channels/telegram.js";
import * as whatsapp from "./channels/whatsapp.js";
import * as whatsappCloud from "./channels/whatsapp_cloud.js";

const APP_URL = process.env.APP_URL || "http://app:8000";
const TOKEN = process.env.GATEWAY_TOKEN;
const log = pino();
if (!TOKEN) {
  log.fatal("GATEWAY_TOKEN is not set");
  process.exit(1);
}

const MODULES = { whatsapp, telegram, discord, whatsapp_cloud: whatsappCloud };
const core = createCore({ appUrl: APP_URL, token: TOKEN, log });
const running = new Map();

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

// Returns whether the app answered, which sets the next poll delay.
async function sync() {
  let cfg;
  try {
    cfg = await core.refresh();
  } catch (err) {
    log.warn({ err: err.message }, "could not load config; keeping the previous state");
    for (const { handle } of running.values()) handle.report();
    return false;
  }
  const wanted = new Map(cfg.channels.map((c) => [c.kind, c]));
  for (const [kind, entry] of [...running]) {
    const want = wanted.get(kind);
    const reason = !want || !MODULES[kind]
      ? "channel disabled; stopping"
      : entry.handle.dead?.()
        ? "channel died; restarting"
        : JSON.stringify(want.config) !== entry.fingerprint
          ? "channel config changed; restarting"
          : null;
    if (reason) {
      log.info({ kind }, reason);
      await stop(kind);
    }
  }
  await Promise.all([...wanted].filter(([k]) => !running.has(k) && MODULES[k]).map(([k, c]) => start(k, c.config)));
  for (const kind of cfg.relink ?? []) {
    if (running.get(kind)?.handle.relink) await running.get(kind).handle.relink();
    else log.warn({ kind }, "relink requested for a channel that is not running");
  }
  for (const { handle } of running.values()) handle.report();
  return true;
}

// One loop, so a slow sync can never overlap the next one. The app loads its
// models for a while after boot; poll fast until it answers.
for (;;) {
  const ok = await sync().catch((err) => log.error({ err: err.message }, "sync failed"));
  await new Promise((resolve) => setTimeout(resolve, ok ? 30_000 : 5_000));
}

// Runs every channel the admin enabled. The app owns the list; this process
// starts, restarts and stops channels to match it.
import fs from "node:fs";
import pino from "pino";
import { createCore } from "./core.js";
import { createSupervisor } from "./supervisor.js";
import * as discord from "./channels/discord.js";
import * as telegram from "./channels/telegram.js";
import * as whatsapp from "./channels/whatsapp.js";
import * as whatsappCloud from "./channels/whatsapp_cloud.js";

const APP_URL = process.env.APP_URL || "http://app:8000";
const TOKEN = process.env.GATEWAY_TOKEN;
const HEARTBEAT = process.env.HEARTBEAT_FILE || "data/heartbeat";
const log = pino();
if (!TOKEN) {
  log.fatal("GATEWAY_TOKEN is not set");
  process.exit(1);
}

// One channel must never take the others down with it: a rejected promise is
// logged and life goes on. An uncaught exception is different, the process is
// in an unknown state; log the trace and let the orchestrator restart it.
process.on("unhandledRejection", (err) => log.error({ err: err?.message }, "unhandled rejection"));
process.on("uncaughtException", (err) => {
  log.fatal({ err: err?.message, stack: err?.stack }, "uncaught exception; exiting");
  process.exit(1);
});

const core = createCore({ appUrl: APP_URL, token: TOKEN, log });
const supervisor = createSupervisor({
  core,
  modules: { whatsapp, telegram, discord, whatsapp_cloud: whatsappCloud },
  log,
});

// docker compose stop sends SIGTERM: close every channel cleanly, try once
// more to hand queued messages to the app, then go.
let stopping = false;
async function shutdown(signal) {
  if (stopping) return;
  stopping = true;
  log.info({ signal }, "shutting down");
  await supervisor.stopAll();
  await core.flush().catch((err) => log.warn({ err: err.message }, "final flush failed"));
  process.exit(0);
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

// The container's health check looks at this file's age.
function heartbeat() {
  try {
    fs.mkdirSync("data", { recursive: true });
    fs.writeFileSync(HEARTBEAT, String(Date.now()));
  } catch (err) {
    log.warn({ err: err.message }, "could not write heartbeat");
  }
}

// One loop, so a slow sync can never overlap the next one. The app loads its
// models for a while after boot; poll fast until it answers.
while (!stopping) {
  const ok = await supervisor.sync().catch((err) => log.error({ err: err.message }, "sync failed"));
  heartbeat();
  await new Promise((resolve) => setTimeout(resolve, ok ? 30_000 : 5_000));
}

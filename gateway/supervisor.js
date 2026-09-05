// Starts, restarts and stops channels to match what the app says is enabled.
// Pure orchestration over module objects, so it can be driven by fakes.
import { blankState } from "./core.js";

export function createSupervisor({ core, modules, log }) {
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
      const handle = await modules[kind].start(core, config, log.child({ channel: kind }));
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
      const reason = !want || !modules[kind]
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
    await Promise.all([...wanted].filter(([k]) => !running.has(k) && modules[k]).map(([k, c]) => start(k, c.config)));
    for (const kind of cfg.relink ?? []) {
      if (running.get(kind)?.handle.relink) await running.get(kind).handle.relink();
      else log.warn({ kind }, "relink requested for a channel that is not running");
    }
    for (const { handle } of running.values()) handle.report();
    return true;
  }

  async function stopAll() {
    await Promise.all([...running.keys()].map((kind) => stop(kind)));
  }

  return { sync, stopAll, running: () => [...running.keys()] };
}

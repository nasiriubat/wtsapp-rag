import { test } from "node:test";
import assert from "node:assert/strict";
import { createSupervisor } from "../supervisor.js";

const log = { info() {}, warn() {}, error() {}, child: () => log };

function fakeModule(events) {
  return {
    async start(core, config) {
      events.push(["start", config.token]);
      return {
        report: () => events.push(["report"]),
        stop: async () => events.push(["stop", config.token]),
        relink: async () => events.push(["relink"]),
        dead: () => false,
      };
    },
  };
}

function setup(cfgs) {
  const events = [];
  const reports = [];
  let i = 0;
  const core = {
    refresh: async () => {
      const cfg = cfgs[Math.min(i++, cfgs.length - 1)];
      if (cfg instanceof Error) throw cfg;
      return cfg;
    },
    report: async (kind, state) => reports.push([kind, state.connected]),
  };
  const modules = { telegram: fakeModule(events), discord: fakeModule(events) };
  return { events, reports, supervisor: createSupervisor({ core, modules, log }) };
}

test("starts what is enabled, restarts on a config change, stops what is disabled", async () => {
  const { events, supervisor } = setup([
    { channels: [{ kind: "telegram", config: { token: "a" } }] },
    { channels: [{ kind: "telegram", config: { token: "b" } }, { kind: "discord", config: { token: "d" } }] },
    { channels: [{ kind: "discord", config: { token: "d" } }] },
  ]);
  assert.equal(await supervisor.sync(), true);
  assert.deepEqual(supervisor.running(), ["telegram"]);
  await supervisor.sync();
  assert.deepEqual(events.filter((e) => e[0] !== "report"), [["start", "a"], ["stop", "a"], ["start", "b"], ["start", "d"]]);
  await supervisor.sync();
  assert.deepEqual(supervisor.running(), ["discord"]);
  assert.deepEqual(events.filter((e) => e[0] === "stop").at(-1), ["stop", "b"]);
});

test("an unchanged channel is left alone, and a relink is handed on", async () => {
  const { events, supervisor } = setup([
    { channels: [{ kind: "telegram", config: { token: "a" } }] },
    { channels: [{ kind: "telegram", config: { token: "a" } }], relink: ["telegram", "whatsapp"] },
  ]);
  await supervisor.sync();
  await supervisor.sync();
  assert.ok(events.some((e) => e[0] === "relink"));
  assert.equal(events.filter((e) => e[0] === "start").length, 1);
});

test("when the app is unreachable the channels keep running and still report", async () => {
  const { events, reports, supervisor } = setup([
    { channels: [{ kind: "telegram", config: { token: "a" } }] },
    new Error("connect ECONNREFUSED"),
  ]);
  await supervisor.sync();
  assert.equal(await supervisor.sync(), false);
  assert.deepEqual(supervisor.running(), ["telegram"]);
  assert.ok(events.filter((e) => e[0] === "report").length >= 2);
  await supervisor.stopAll();
  assert.deepEqual(supervisor.running(), []);
  assert.deepEqual(reports.at(-1), ["telegram", false]);
});

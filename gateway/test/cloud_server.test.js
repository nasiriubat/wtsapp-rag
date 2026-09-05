// The webhook is public by design, so a malformed request must not end the
// process. These drive the real listener over a socket.
process.env.GATEWAY_PORT = "18089";

import { test } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";

const { start } = await import("../channels/whatsapp_cloud.js");

const core = { report: async () => {}, handleDirect: async () => {} };
const log = { info() {}, warn() {}, error() {} };
const config = { token: "t", phone_number_id: "1", verify_token: "vt", app_secret: "sec" };
const channel = await start(core, config, log);

function raw(request) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(18089, "127.0.0.1", () => socket.write(request));
    let out = "";
    socket.on("data", (d) => (out += d));
    socket.on("end", () => resolve(out));
    socket.on("error", reject);
    setTimeout(() => socket.end(), 300);
  });
}

test("a request target the URL parser rejects does not kill the process", async () => {
  await raw("GET //[ HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n");
  // Still serving: the handshake answers on the same listener.
  const res = await raw(
    "GET /webhook/whatsapp_cloud?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=OK1 HTTP/1.1\r\n" +
      "Host: x\r\nConnection: close\r\n\r\n",
  );
  assert.match(res, /OK1/);
});

test("a body that stops short of its content-length does not kill the process", async () => {
  await raw("POST /webhook/whatsapp_cloud HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\nab");
  const res = await raw(
    "GET /webhook/whatsapp_cloud?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=OK2 HTTP/1.1\r\n" +
      "Host: x\r\nConnection: close\r\n\r\n",
  );
  assert.match(res, /OK2/);
});

test("a body over the cap is refused before the signature is checked", async () => {
  let called = false;
  core.handleDirect = async () => (called = true);
  const size = 1024 * 1024 + 10;
  const res = await raw(
    `POST /webhook/whatsapp_cloud HTTP/1.1\r\nHost: x\r\nContent-Length: ${size}\r\nConnection: close\r\n\r\n` +
      "x".repeat(size),
  );
  assert.match(res, /413/);
  assert.equal(called, false);
  const ok = await raw(
    "GET /webhook/whatsapp_cloud?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=OK3 HTTP/1.1\r\n" +
      "Host: x\r\nConnection: close\r\n\r\n",
  );
  assert.match(ok, /OK3/);
});

test("an unsigned POST is rejected and never reaches the app", async () => {
  let called = false;
  core.handleDirect = async () => (called = true);
  const res = await raw(
    "POST /webhook/whatsapp_cloud HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
  );
  assert.match(res, /401/);
  assert.equal(called, false);
  channel.stop();
});

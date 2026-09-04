import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import fs from "node:fs";
import path from "node:path";
import qrcode from "qrcode-terminal";
import { blankState } from "../core.js";
import { bare, isTrigger, questionOf, quoteStub, textOf, toPayload } from "../lib.js";

const AUTH_DIR = "auth_state";

// The directory is a bind mount under compose, so only its contents can go.
function clearAuth() {
  for (const entry of fs.existsSync(AUTH_DIR) ? fs.readdirSync(AUTH_DIR) : []) {
    fs.rmSync(path.join(AUTH_DIR, entry), { recursive: true, force: true });
  }
}

export async function start(core, config, log) {
  const state = blankState();
  let sock = null;
  let relinking = false;
  let stopped = false;
  const report = () => core.report("whatsapp", state);

  // The ids we sent ourselves. Pairing with the operator's own number makes
  // their messages fromMe as well, so this is what tells the two apart.
  const ourSends = new Set();
  function remember(id) {
    ourSends.add(id);
    if (ourSends.size > 500) ourSends.delete(ourSends.values().next().value);
  }

  async function listGroups() {
    try {
      const all = await sock.groupFetchAllParticipating();
      // Members under every id form Baileys knows, so a DM sender matches.
      const ids = (p) => [p.id, p.jid, p.phoneNumber, p.lid].filter(Boolean).map(bare);
      return Object.values(all).map((g) => ({
        id: g.id,
        subject: g.subject,
        members: [...new Set((g.participants ?? []).flatMap(ids))],
      }));
    } catch (err) {
      log.warn({ err: err.message }, "could not list groups");
      return [];
    }
  }

  async function connect() {
    const { state: creds, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    sock = makeWASocket({
      auth: creds,
      // Baileys' info-level output drowns ours; keep only its warnings.
      logger: log.child({ module: "baileys" }, { level: "warn" }),
      // Staying "offline" keeps notifications on the phone and looks less like a bot.
      markOnlineOnConnect: false,
      syncFullHistory: false,
    });
    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
      if (qr) {
        qrcode.generate(qr, { small: true });
        Object.assign(state, { connected: false, qr });
      }
      if (connection === "open") {
        log.info({ jid: sock.user?.id, lid: sock.user?.lid }, "whatsapp connected");
        Object.assign(state, { connected: true, jid: bare(sock.user?.id), qr: null, groups: await listGroups() });
      }
      if (connection === "close") {
        const code = lastDisconnect?.error?.output?.statusCode;
        state.connected = false;
        if (stopped) return;
        if (code === DisconnectReason.loggedOut) {
          // Whether the admin asked or the phone unlinked us, the outcome is the
          // same: fresh pairing, without taking the other channels down.
          clearAuth();
          log.warn(relinking ? "logged out for relink; pairing again" : "logged out by the phone; pairing again");
          relinking = false;
        } else {
          log.warn({ code }, "whatsapp closed, reconnecting");
        }
        connect();
      }
      await report();
    });

    const seen = new Set();
    sock.ev.on("messages.upsert", ({ type, messages }) => {
      // "append" is history sync and our own sends; only "notify" is new traffic.
      if (type !== "notify") return;
      const ownJid = bare(sock.user?.id);
      const ownJids = new Set([ownJid, bare(sock.user?.lid)].filter(Boolean));
      for (const msg of messages) {
        const jid = msg.key.remoteJid ?? "";
        if (jid.endsWith("@s.whatsapp.net") || jid.endsWith("@lid")) {
          if (msg.key.fromMe || ourSends.has(msg.key.id) || textOf(msg) === null) continue;
          // A DM has no participant, so the chat itself identifies the sender.
          const payload = { ...toPayload(msg, ownJid), sender_jid: bare(msg.key.remoteJidAlt ?? jid) };
          core
            .handleDirect(payload, (answer) => sock.sendMessage(jid, { text: answer }, { quoted: msg }))
            .catch((err) => log.error({ err: err.message }, "whatsapp direct failed"));
          continue;
        }
        if (!jid.endsWith("@g.us")) continue;
        const group = core.groupFor(jid);
        if (!group) {
          if (!seen.has(jid)) log.info({ jid }, "group seen; enable it in the admin to start logging it");
          seen.add(jid);
          continue;
        }
        const text = textOf(msg);
        if (text === null) continue;
        const ours = ourSends.has(msg.key.id);
        core
          .handle(toPayload(msg, ownJid, ours), {
            trigger: () =>
              !ours && isTrigger(msg, text, ownJids, group.triggers) ? questionOf(text, group.triggers) : null,
            send: async (answer, quote) => {
              const quoted = quote ? quoteStub(jid, quote) : msg;
              const sent = await sock.sendMessage(jid, { text: answer }, { quoted });
              remember(sent.key.id);
              return toPayload(sent, ownJid, true);
            },
          })
          .catch((err) => log.error({ err: err.message }, "whatsapp handle failed"));
      }
    });
  }

  await connect();
  return {
    report,
    async relink() {
      // Only a live session can log out; before that there is nothing to relink.
      if (relinking || !state.connected) {
        log.warn("relink ignored: not connected");
        return;
      }
      relinking = true;
      log.warn("relink requested; logging out");
      try {
        await sock.logout();
      } catch (err) {
        relinking = false;
        log.warn({ err: err.message }, "logout failed");
      }
    },
    stop() {
      stopped = true;
      sock?.end();
    },
  };
}

import { Bot } from "grammy";
import { blankState } from "../core.js";
import { hasPrefix, stripPrefix } from "../lib.js";

// Ids are namespaced so they cannot collide with WhatsApp JIDs in the same tables.
export const groupId = (chatId) => `tg:${chatId}`;
export const messageId = (chatId, id) => `tg:${chatId}:${id}`;
export const parseMessageId = (id) => {
  const [, chatId, msgId] = id.split(":");
  return { chatId: Number(chatId), messageId: Number(msgId) };
};
const LIMIT = 4096; // Telegram's message length cap

export function payloadFromTelegram(msg, botId) {
  const from = msg.from ?? {};
  return {
    wa_msg_id: messageId(msg.chat.id, msg.message_id),
    group_id: groupId(msg.chat.id),
    sender_jid: `tg:${from.id}`,
    sender_name: [from.first_name, from.last_name].filter(Boolean).join(" ") || from.username || null,
    body: msg.text ?? msg.caption ?? null,
    quoted_msg_id: msg.reply_to_message ? messageId(msg.chat.id, msg.reply_to_message.message_id) : null,
    is_bot: from.id === botId,
    ts: new Date(msg.date * 1000).toISOString(),
  };
}

export function telegramTrigger(msg, me, triggers) {
  const text = msg.text ?? msg.caption ?? "";
  if (text.toLowerCase().includes(`@${me.username}`.toLowerCase())) return true;
  if (msg.reply_to_message?.from?.id === me.id) return true;
  return hasPrefix(text, triggers);
}

export function telegramQuestion(msg, me, triggers) {
  const text = msg.text ?? msg.caption ?? "";
  return stripPrefix(text.replace(new RegExp(`@${me.username}`, "ig"), " ").replace(/\s+/g, " ").trim(), triggers);
}

export async function start(core, config, log) {
  const bot = new Bot(config.token);
  const me = await bot.api.getMe();
  const state = { ...blankState(), jid: `@${me.username}` };
  // Bots cannot list their groups; remember the ones that talk.
  const seen = new Map();
  let dead = false;
  const report = () => core.report("telegram", { ...state, groups: [...seen.values()] });

  bot.on("message", (ctx) => {
    const msg = ctx.message;
    if (msg.chat.type === "private") {
      const payload = payloadFromTelegram(msg, me.id);
      if (payload.body === null) return;
      core
        .handleDirect(payload, (answer) => ctx.api.sendMessage(msg.chat.id, answer.slice(0, LIMIT)))
        .catch((err) => log.error({ err: err.message }, "telegram direct failed"));
      return;
    }
    if (!["group", "supergroup"].includes(msg.chat.type)) return;
    const id = groupId(msg.chat.id);
    seen.set(id, { id, subject: msg.chat.title ?? null });
    const group = core.groupFor(id);
    if (!group) return;
    const payload = payloadFromTelegram(msg, me.id);
    if (payload.body === null) return;
    // Not awaited: grammY processes updates one at a time, and an answer takes seconds.
    core
      .handle(payload, {
        trigger: () =>
          !payload.is_bot && telegramTrigger(msg, me, group.triggers) ? telegramQuestion(msg, me, group.triggers) : null,
        send: async (answer, quote) => {
          const replyTo = quote ? parseMessageId(quote.wa_msg_id).messageId : msg.message_id;
          const sent = await ctx.api.sendMessage(msg.chat.id, answer.slice(0, LIMIT), {
            reply_parameters: { message_id: replyTo, allow_sending_without_reply: true },
          });
          return payloadFromTelegram(sent, me.id);
        },
      })
      .catch((err) => log.error({ err: err.message }, "telegram handle failed"));
  });
  bot.catch((err) => log.error({ err: err.message }, "telegram handler failed"));

  // Long polling runs until stop(); if it dies the orchestrator restarts us.
  bot.start({
    onStart: () => {
      state.connected = true;
      log.info({ username: me.username }, "telegram connected");
      report();
    },
  }).catch((err) => {
    state.connected = false;
    dead = true;
    log.error({ err: err.message }, "telegram polling stopped");
    report();
  });

  return { report, dead: () => dead, stop: () => bot.stop() };
}

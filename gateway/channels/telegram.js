import { Bot } from "grammy";
import { hasPrefix, stripPrefix } from "../lib.js";

// Ids are namespaced so they cannot collide with WhatsApp JIDs in the same tables.
export const groupId = (chatId) => `tg:${chatId}`;
export const messageId = (chatId, id) => `tg:${chatId}:${id}`;

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
  const mention = `@${me.username}`.toLowerCase();
  if (text.toLowerCase().includes(mention)) return true;
  if (msg.reply_to_message?.from?.id === me.id) return true;
  return hasPrefix(text, triggers);
}

export function telegramQuestion(msg, me, triggers) {
  const text = msg.text ?? msg.caption ?? "";
  const cleaned = text.replace(new RegExp(`@${me.username}`, "ig"), " ").replace(/\s+/g, " ").trim();
  return stripPrefix(cleaned, triggers);
}

export async function start(core, config, log) {
  const bot = new Bot(config.token);
  const me = await bot.api.getMe();
  const state = { connected: false, jid: `@${me.username}`, qr: null, groups: [] };
  // Bots cannot list their groups; remember the ones that talk.
  const seen = new Map();
  const report = () => core.report("telegram", { ...state, groups: [...seen.values()] });

  bot.on("message", async (ctx) => {
    const msg = ctx.message;
    if (!["group", "supergroup"].includes(msg.chat.type)) return;
    const id = groupId(msg.chat.id);
    seen.set(id, { id, subject: msg.chat.title ?? null });
    const group = core.groupFor(id);
    if (!group) return;
    const payload = payloadFromTelegram(msg, me.id);
    if (payload.body === null) return;
    await core.handle(payload, {
      triggered: !payload.is_bot && telegramTrigger(msg, me, group.triggers),
      question: telegramQuestion(msg, me, group.triggers),
      send: async (answer, quote) => {
        const replyTo = quote ? Number(quote.wa_msg_id.split(":")[2]) : msg.message_id;
        const sent = await ctx.api.sendMessage(msg.chat.id, answer, {
          reply_parameters: { message_id: replyTo, allow_sending_without_reply: true },
        });
        return payloadFromTelegram(sent, me.id);
      },
    });
  });
  bot.catch((err) => log.error({ err: err.message }, "telegram handler failed"));

  // Long polling runs until stop(); the promise settles only then.
  bot.start({
    onStart: () => {
      state.connected = true;
      log.info({ username: me.username }, "telegram connected");
      report();
    },
  }).catch((err) => {
    state.connected = false;
    log.error({ err: err.message }, "telegram polling stopped");
    report();
  });

  return { report, stop: () => bot.stop() };
}

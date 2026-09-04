import { test } from "node:test";
import assert from "node:assert/strict";
import { parseMessageId as tgParse, payloadFromTelegram, telegramQuestion, telegramTrigger } from "../channels/telegram.js";
import { discordQuestion, discordTrigger, parseMessageId as dcParse, payloadFromDiscord } from "../channels/discord.js";

const me = { id: 42, username: "cabin_bot" };
const triggers = ["@agent"];

function tg(text, extra = {}) {
  return {
    message_id: 7,
    date: 1756800000,
    chat: { id: -100123, type: "supergroup", title: "Crew" },
    from: { id: 5, first_name: "Anna", last_name: "K" },
    text,
    ...extra,
  };
}

test("telegram payload is namespaced and maps the reply", () => {
  const p = payloadFromTelegram(tg("hello", { reply_to_message: { message_id: 3, from: { id: 9 } } }), me.id);
  assert.deepEqual(p, {
    wa_msg_id: "tg:-100123:7",
    group_id: "tg:-100123",
    sender_jid: "tg:5",
    sender_name: "Anna K",
    body: "hello",
    quoted_msg_id: "tg:-100123:3",
    is_bot: false,
    ts: "2025-09-02T08:00:00.000Z",
  });
  assert.equal(payloadFromTelegram(tg("x", { from: { id: 42, first_name: "Bot" } }), me.id).is_bot, true);
  assert.deepEqual(tgParse("tg:-100123:7"), { chatId: -100123, messageId: 7 });
});

test("telegram triggers on @username, reply to the bot, or a prefix", () => {
  assert.equal(telegramTrigger(tg("@Cabin_bot who?"), me, triggers), true);
  assert.equal(telegramTrigger(tg("why?", { reply_to_message: { message_id: 1, from: { id: 42 } } }), me, triggers), true);
  assert.equal(telegramTrigger(tg("@agent who?"), me, triggers), true);
  assert.equal(telegramTrigger(tg("who?"), me, triggers), false);
  assert.equal(telegramQuestion(tg("@cabin_bot   who books?"), me, triggers), "who books?");
  assert.equal(telegramQuestion(tg("@agent who books?"), me, triggers), "who books?");
});

const bot = "777";
function dc(content, extra = {}) {
  return {
    id: "1001",
    channelId: "555",
    author: { id: "5", username: "anna", globalName: "Anna" },
    member: { displayName: "Anna K" },
    content,
    createdTimestamp: 1756800000000,
    mentions: { users: new Set() },
    ...extra,
  };
}

test("discord payload is namespaced and maps the reply", () => {
  const p = payloadFromDiscord(dc("hello", { reference: { messageId: "900" } }), bot);
  assert.deepEqual(p, {
    wa_msg_id: "dc:1001",
    group_id: "dc:555",
    sender_jid: "dc:5",
    sender_name: "Anna K",
    body: "hello",
    quoted_msg_id: "dc:900",
    is_bot: false,
    ts: "2025-09-02T08:00:00.000Z",
  });
  assert.equal(dcParse("dc:900"), "900");
});

test("discord triggers on a mention, a reply to the bot, or a prefix, fetching only when needed", async () => {
  let fetched = 0;
  const replied = async () => (fetched++, true);
  assert.equal(await discordTrigger(dc(`<@${bot}> who?`, { mentions: { users: new Set([bot]) } }), bot, triggers, replied), true);
  assert.equal(await discordTrigger(dc("@agent who?"), bot, triggers, replied), true);
  assert.equal(fetched, 0);
  assert.equal(await discordTrigger(dc("why?", { reference: { messageId: "1" } }), bot, triggers, replied), true);
  assert.equal(fetched, 1);
  assert.equal(await discordTrigger(dc("who?"), bot, triggers, replied), false);
  assert.equal(discordQuestion(`<@!${bot}>  who books?`, bot, triggers), "who books?");
});

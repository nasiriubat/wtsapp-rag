import { test } from "node:test";
import assert from "node:assert/strict";
import { bare, isTrigger, questionOf, quoteStub, textOf, toPayload } from "../lib.js";

const OWN = "358401111111@s.whatsapp.net";
const OWN_LID = "123456789@lid";
const ownJids = new Set([OWN, OWN_LID]);
const triggers = ["@agent", "hey bot"];

function msg({ text, mentioned = [], quotedParticipant, fromMe = false, participant = "358402222222@s.whatsapp.net" }) {
  const contextInfo = { mentionedJid: mentioned, participant: quotedParticipant, stanzaId: quotedParticipant ? "Q1" : undefined };
  return {
    key: { remoteJid: "120363@g.us", id: "M1", fromMe, participant: "111@lid", participantAlt: participant },
    pushName: "Anna",
    messageTimestamp: 1756800000,
    message: mentioned.length || quotedParticipant ? { extendedTextMessage: { text, contextInfo } } : { conversation: text },
  };
}

test("textOf reads plain, extended and caption bodies", () => {
  assert.equal(textOf({ message: { conversation: "hi" } }), "hi");
  assert.equal(textOf({ message: { extendedTextMessage: { text: "ext" } } }), "ext");
  assert.equal(textOf({ message: { imageMessage: { caption: "cap" } } }), "cap");
  assert.equal(textOf({ message: { stickerMessage: {} } }), null);
});

test("bare strips the device suffix only", () => {
  assert.equal(bare("358401111111:12@s.whatsapp.net"), OWN);
  assert.equal(bare(OWN), OWN);
  assert.equal(bare(undefined), "");
});

test("toPayload maps a member message", () => {
  const p = toPayload(msg({ text: "hello" }), OWN);
  assert.deepEqual(p, {
    wa_msg_id: "M1",
    group_id: "120363@g.us",
    sender_jid: "358402222222@s.whatsapp.net",
    sender_name: "Anna",
    body: "hello",
    quoted_msg_id: null,
    is_bot: false,
    ts: "2025-09-02T08:00:00.000Z",
  });
});

test("toPayload marks our own sends as bot and uses our jid", () => {
  const p = toPayload(msg({ text: "answer", fromMe: true }), OWN);
  assert.equal(p.is_bot, true);
  assert.equal(p.sender_jid, OWN);
});

test("a fromMe message the bot did not send is a question, not an answer", () => {
  // The operator paired their own number: what they type is fromMe too.
  const p = toPayload(msg({ text: "@agent hi", fromMe: true }), OWN, false);
  assert.equal(p.is_bot, false);
  assert.equal(p.sender_jid, OWN);
});

test("trigger 1: a true mention of our jid or lid", () => {
  assert.equal(isTrigger(msg({ text: "@358401111111 hi", mentioned: ["358401111111:3@s.whatsapp.net"] }), "@358401111111 hi", ownJids, triggers), true);
  assert.equal(isTrigger(msg({ text: "hi", mentioned: [OWN_LID] }), "hi", ownJids, triggers), true);
  assert.equal(isTrigger(msg({ text: "hi", mentioned: ["999@s.whatsapp.net"] }), "hi", ownJids, triggers), false);
});

test("trigger 2: text prefix, case-insensitive", () => {
  assert.equal(isTrigger(msg({ text: "@Agent what?" }), "@Agent what?", ownJids, triggers), true);
  assert.equal(isTrigger(msg({ text: "HEY BOT what?" }), "HEY BOT what?", ownJids, triggers), true);
  assert.equal(isTrigger(msg({ text: "what @agent" }), "what @agent", ownJids, triggers), false);
});

test("trigger 3: a reply to one of our messages", () => {
  assert.equal(isTrigger(msg({ text: "why?", quotedParticipant: "358401111111:5@s.whatsapp.net" }), "why?", ownJids, triggers), true);
  assert.equal(isTrigger(msg({ text: "why?", quotedParticipant: "999@s.whatsapp.net" }), "why?", ownJids, triggers), false);
});

test("questionOf strips the trigger and mention tokens", () => {
  assert.equal(questionOf("@agent what did we decide?", triggers), "what did we decide?");
  assert.equal(questionOf("@358401111111 what did we decide?", triggers), "what did we decide?");
  assert.equal(questionOf("Hey Bot   who books?", triggers), "who books?");
});

test("quoteStub builds the key Baileys needs", () => {
  const stub = quoteStub("120363@g.us", { wa_msg_id: "S1", sender_jid: "358@s.whatsapp.net", is_bot: false, body: "text" });
  assert.deepEqual(stub.key, { remoteJid: "120363@g.us", id: "S1", participant: "358@s.whatsapp.net", fromMe: false });
  assert.equal(stub.message.conversation, "text");
});

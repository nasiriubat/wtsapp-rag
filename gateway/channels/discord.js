import { ChannelType, Client, GatewayIntentBits, Partials } from "discord.js";
import { blankState } from "../core.js";
import { hasPrefix, stripPrefix } from "../lib.js";

export const groupId = (channelId) => `dc:${channelId}`;
export const messageId = (id) => `dc:${id}`;
export const parseMessageId = (id) => id.split(":")[1];
const LIMIT = 2000; // Discord's message length cap

// `m` is a discord.js Message; only plain fields are read so tests can pass objects.
export function payloadFromDiscord(m, botId) {
  return {
    wa_msg_id: messageId(m.id),
    group_id: groupId(m.channelId),
    sender_jid: `dc:${m.author.id}`,
    sender_name: m.member?.displayName ?? m.author.globalName ?? m.author.username ?? null,
    body: m.content || null,
    quoted_msg_id: m.reference?.messageId ? messageId(m.reference.messageId) : null,
    is_bot: m.author.id === botId,
    ts: new Date(m.createdTimestamp).toISOString(),
  };
}

// The free checks first; `repliedToBot` is a thunk because finding out costs a
// REST call on Discord.
export async function discordTrigger(m, botId, triggers, repliedToBot) {
  if (m.mentions.users.has(botId) || hasPrefix(m.content ?? "", triggers)) return true;
  return m.reference?.messageId ? await repliedToBot() : false;
}

export function discordQuestion(content, botId, triggers) {
  return stripPrefix(content.replace(new RegExp(`<@!?${botId}>`, "g"), " ").replace(/\s+/g, " ").trim(), triggers);
}

export async function start(core, config, log) {
  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
      GatewayIntentBits.DirectMessages,
    ],
    // DM channels are not cached until a message arrives.
    partials: [Partials.Channel],
    // An answer quoting "@everyone" from the chat must not ping anyone.
    allowedMentions: { parse: [] },
  });
  const state = blankState();
  let dead = false;

  function listChannels() {
    const out = [];
    for (const guild of client.guilds.cache.values()) {
      for (const ch of guild.channels.cache.values()) {
        if (ch.type === ChannelType.GuildText) out.push({ id: groupId(ch.id), subject: `${guild.name} / #${ch.name}` });
      }
    }
    return out;
  }
  // Recomputed per report so a channel created after connect shows up.
  const report = () => core.report("discord", { ...state, groups: state.connected ? listChannels() : [] });

  async function shareFile(payload, attachment) {
    const res = await fetch(attachment.url);
    if (!res.ok) throw new Error(`attachment download ${res.status}`);
    await core.shareFile({
      groupId: payload.group_id,
      senderJid: payload.sender_jid,
      filename: attachment.name ?? "attachment",
      mime: attachment.contentType,
      bytes: Buffer.from(await res.arrayBuffer()),
    });
  }

  client.once("clientReady", () => {
    Object.assign(state, { connected: true, jid: client.user.tag });
    log.info({ tag: client.user.tag }, "discord connected");
    report();
  });
  client.on("messageCreate", (m) => {
    // Other bots are noise; our own sends are ingested on the way out.
    if (m.author.bot) return;
    if (!m.guildId) {
      const payload = payloadFromDiscord(m, client.user.id);
      if (payload.body === null) return;
      core
        .handleDirect(payload, (answer) => m.channel.send({ content: answer.slice(0, LIMIT) }))
        .catch((err) => log.error({ err: err.message }, "discord direct failed"));
      return;
    }
    const group = core.groupFor(groupId(m.channelId));
    if (!group) return;
    const payload = payloadFromDiscord(m, client.user.id);
    if (group.files) {
      for (const attachment of m.attachments.values()) {
        if (!core.fileAllowed(attachment.size, attachment.name)) continue;
        shareFile(payload, attachment).catch((err) =>
          log.warn({ err: err.message, filename: attachment.name }, "could not fetch shared file"),
        );
      }
    }
    if (payload.body === null) return;
    const repliedToBot = async () => (await m.fetchReference().catch(() => null))?.author?.id === client.user.id;
    core
      .handle(payload, {
        trigger: async () =>
          (await discordTrigger(m, client.user.id, group.triggers, repliedToBot))
            ? discordQuestion(m.content, client.user.id, group.triggers)
            : null,
        send: async (answer, quote) => {
          const messageReference = quote ? parseMessageId(quote.wa_msg_id) : m.id;
          const sent = await m.channel.send({
            content: answer.slice(0, LIMIT),
            reply: { messageReference, failIfNotExists: false },
          });
          return payloadFromDiscord(sent, client.user.id);
        },
      })
      .catch((err) => log.error({ err: err.message }, "discord handle failed"));
  });
  client.on("error", (err) => log.error({ err: err.message }, "discord error"));
  client.on("shardDisconnect", () => {
    state.connected = false;
    dead = true;
    report();
  });

  await client.login(config.token);
  return { report, dead: () => dead, stop: () => client.destroy() };
}

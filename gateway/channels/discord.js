import { ChannelType, Client, GatewayIntentBits } from "discord.js";
import { hasPrefix, stripPrefix } from "../lib.js";

export const groupId = (channelId) => `dc:${channelId}`;
export const messageId = (id) => `dc:${id}`;
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

export function discordTrigger(m, botId, triggers, repliedToBot) {
  if (m.mentions?.users?.has?.(botId) || m.mentionedIds?.includes(botId)) return true;
  if (repliedToBot) return true;
  return hasPrefix(m.content ?? "", triggers);
}

export function discordQuestion(content, botId, triggers) {
  const cleaned = content.replace(new RegExp(`<@!?${botId}>`, "g"), " ").replace(/\s+/g, " ").trim();
  return stripPrefix(cleaned, triggers);
}

export async function start(core, config, log) {
  const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent],
  });
  const state = { connected: false, jid: null, qr: null, groups: [] };
  const report = () => core.report("discord", state);

  function listChannels() {
    const out = [];
    for (const guild of client.guilds.cache.values()) {
      for (const ch of guild.channels.cache.values()) {
        if (ch.type === ChannelType.GuildText) out.push({ id: groupId(ch.id), subject: `${guild.name} / #${ch.name}` });
      }
    }
    return out;
  }

  client.once("clientReady", () => {
    Object.assign(state, { connected: true, jid: client.user.tag, groups: listChannels() });
    log.info({ tag: client.user.tag }, "discord connected");
    report();
  });
  client.on("messageCreate", async (m) => {
    // Other bots are noise; our own sends are ingested on the way out.
    if (!m.guildId || m.author.bot) return;
    const group = core.groupFor(groupId(m.channelId));
    if (!group) return;
    const payload = payloadFromDiscord(m, client.user.id);
    if (payload.body === null) return;
    let repliedToBot = false;
    if (m.reference?.messageId) {
      const ref = await m.fetchReference().catch(() => null);
      repliedToBot = ref?.author?.id === client.user.id;
    }
    await core
      .handle(payload, {
        triggered: discordTrigger(m, client.user.id, group.triggers, repliedToBot),
        question: discordQuestion(m.content, client.user.id, group.triggers),
        send: async (answer, quote) => {
          const messageReference = quote ? quote.wa_msg_id.split(":")[1] : m.id;
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

  await client.login(config.token);
  return { report, stop: () => client.destroy() };
}

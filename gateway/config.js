// The app owns the list of groups and their triggers. The gateway pulls it.
// `relink` is the admin asking for a fresh QR pairing.
export async function loadGroups(appUrl, token) {
  const res = await fetch(`${appUrl}/gateway/config`, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`config ${res.status}`);
  const { groups, relink } = await res.json();
  return {
    groups: new Map(groups.map((g) => [g.external_id, { ...g, triggers: g.triggers.map((t) => t.toLowerCase()) }])),
    relink: Boolean(relink),
  };
}

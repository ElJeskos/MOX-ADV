const normalized = (value: unknown) => String(value ?? "").replace(/\s+/g, " ").trim();

function joinRoles(roles: string[]) {
  const unique = [...new Set(roles)];
  const joined = unique.length < 2 ? unique[0] ?? "" : `${unique.slice(0, -1).join(", ")} и ${unique.at(-1)}`;
  return joined ? `${joined[0].toUpperCase()}${joined.slice(1)}` : "";
}

export function inferDecisionMakers(evidence: unknown) {
  const text = normalized(evidence).toLowerCase();
  const roles: string[] = [];

  if (/байер|\bbuyer|закуп/u.test(text)) roles.push("байеры и руководители по закупкам");
  if (/производител|manufactur/u.test(text)) roles.push("представители компаний-производителей");
  if (/инвестор|investor/u.test(text)) roles.push("инвесторы");
  if (/предпринимател|entrepreneur|business owner/u.test(text)) roles.push("предприниматели и владельцы бизнеса");
  if (/руководител|директор|executive|decision[- ]maker/u.test(text)) roles.push("руководители компаний");
  if (/орган.{0,12}власт|правительств|government|public authorit/u.test(text)) roles.push("представители органов власти");

  return joinRoles(roles);
}

export function isUnprocessedAudience(audience: unknown, evidence: unknown) {
  const value = normalized(audience);
  const quote = normalized(evidence);
  if (!value) return false;
  return (Boolean(quote) && value === quote) || value.length > 140;
}

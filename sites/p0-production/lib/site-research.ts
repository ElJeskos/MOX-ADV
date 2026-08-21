import { isPublicIpAddress, normalizePublicHttpsUrl, requirePublicHttpsUrl } from "./site-url.ts";
import { cleanText } from "./text.ts";
import type { PageEvidence, SiteAnalysis } from "./p0-application.ts";

const DEFAULT_LIMITS = {
  maximumPages: 6,
  maximumRedirects: 4,
  maximumTotalBytes: 5_000_000,
};
const RESEARCH_TERMS = [
  "about", "product", "service", "solution", "particip", "partner", "price", "tariff",
  "registration", "become", "visitor", "client", "faq", "contact", "услов", "участ",
  "партнер", "регистра", "посетител", "клиент", "контакт",
];
const SAFETY_ERROR_CODES = new Set([
  "SITE_TARGET_PRIVATE",
  "SITE_REDIRECT_UNSAFE",
  "SITE_REDIRECT_LIMIT",
  "SITE_RESPONSE_TOO_LARGE",
]);

type SiteResearchLimits = {
  maximumPages: number;
  maximumRedirects: number;
  maximumTotalBytes: number;
};

type SiteResearchDependencies = {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  resolveHostname(hostname: string): Promise<string[]>;
  now(): string;
  limits?: Partial<SiteResearchLimits>;
};

export type PublicCompetitorResearchPolicy = {
  allowedHosts: string[];
  policyId: string;
  policyVersion: string;
  policyUrl: string;
  observationScope: string;
};

export type PublicCompetitorPageObservation = {
  source_url: string;
  observed_at: string;
  collected_via: "PUBLIC_RESEARCH_EGRESS_V1";
  locator: { url: string; selector: "document" };
  policy: {
    policy_id: string;
    version: string;
    policy_url: string;
    access: "PUBLIC_NO_AUTH";
    allowed_hosts: string[];
  };
  scope: {
    host: string;
    pages_observed: 1;
    observation_scope: string;
  };
  page: PageEvidence;
  raw_quote: string;
  limitations: string[];
};

export class SiteResearchError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "SiteResearchError";
    this.code = code;
  }
}

function fail(code: string, message: string): never {
  throw new SiteResearchError(code, message);
}

function normalizeHost(hostname: string) {
  return hostname.toLowerCase().replace(/^www\./u, "");
}

function firstParty(base: string, candidate: string) {
  return candidate === base || candidate.endsWith(`.${base}`);
}

function exactLimits(input?: Partial<SiteResearchLimits>): SiteResearchLimits {
  return {
    maximumPages: Math.max(1, Math.min(6, Math.trunc(input?.maximumPages ?? DEFAULT_LIMITS.maximumPages))),
    maximumRedirects: Math.max(0, Math.min(4, Math.trunc(input?.maximumRedirects ?? DEFAULT_LIMITS.maximumRedirects))),
    maximumTotalBytes: Math.max(1, Math.min(5_000_000, Math.trunc(input?.maximumTotalBytes ?? DEFAULT_LIMITS.maximumTotalBytes))),
  };
}

function extractMatches(source: string, pattern: RegExp, maximum: number) {
  const values: string[] = [];
  for (const match of source.matchAll(pattern)) {
    const value = cleanText(match[1] ?? "", 1_000);
    if (value && !values.includes(value)) values.push(value);
    if (values.length >= maximum) break;
  }
  return values;
}

async function assertPublicResolution(url: URL, resolveHostname: SiteResearchDependencies["resolveHostname"]) {
  if (!url.hostname || !isPublicIpAddress(url.hostname)) {
    fail("SITE_TARGET_PRIVATE", "Сайт разрешается в локальный, частный или link-local адрес.");
  }
  if (/^\[.*\]$/u.test(url.hostname) || /^\d+(?:\.\d+){3}$/u.test(url.hostname)) return;
  let addresses: string[];
  try {
    addresses = await resolveHostname(url.hostname);
  } catch {
    fail("SITE_DNS_UNAVAILABLE", "Не удалось безопасно проверить публичность адреса сайта.");
  }
  if (!addresses.length) fail("SITE_DNS_UNAVAILABLE", "DNS не вернул публичный адрес сайта.");
  if (addresses.some((address) => !isPublicIpAddress(address))) {
    fail("SITE_TARGET_PRIVATE", "Сайт разрешается в локальный, частный или link-local адрес.");
  }
}

async function boundedText(response: Response, maximumBytes: number) {
  const announced = Number(response.headers.get("content-length"));
  if (Number.isFinite(announced) && announced > maximumBytes) {
    await response.body?.cancel();
    fail("SITE_RESPONSE_TOO_LARGE", "Ответ сайта превышает безопасный лимит размера.");
  }
  if (!response.body) return { text: "", bytes: 0 };
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let text = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    bytes += chunk.value.byteLength;
    if (bytes > maximumBytes) {
      await reader.cancel("size limit");
      fail("SITE_RESPONSE_TOO_LARGE", "Ответ сайта превышает безопасный лимит размера.");
    }
    text += decoder.decode(chunk.value, { stream: true });
  }
  text += decoder.decode();
  return { text, bytes };
}

async function fetchPage(
  rawUrl: string,
  baseHost: string,
  dependencies: SiteResearchDependencies,
  limits: SiteResearchLimits,
  remainingBytes: number,
  exactAllowedHosts?: Set<string>,
) {
  let current = requirePublicHttpsUrl(rawUrl);
  for (let redirectCount = 0; ; redirectCount += 1) {
    if (!firstParty(baseHost, normalizeHost(current.hostname))) {
      fail("SITE_REDIRECT_UNSAFE", "Redirect вывел исследование за пределы first-party HTTPS target.");
    }
    if (exactAllowedHosts && !exactAllowedHosts.has(current.hostname.toLowerCase())) {
      fail("SITE_HOST_NOT_ALLOWLISTED", "Public research host отсутствует в exact allowlist.");
    }
    await assertPublicResolution(current, dependencies.resolveHostname);
    const response = await dependencies.fetch(current, {
      method: "GET",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: {
        "User-Agent": "MOX-ADV-GPT-Sites/1.0",
        Accept: "text/html,application/xhtml+xml",
      },
      redirect: "manual",
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      await response.body?.cancel();
      if (redirectCount >= limits.maximumRedirects) {
        fail("SITE_REDIRECT_LIMIT", "Сайт превысил безопасный лимит redirects.");
      }
      const location = response.headers.get("location");
      if (!location) fail("SITE_REDIRECT_UNSAFE", "Redirect сайта не содержит безопасного Location.");
      let target: URL;
      try {
        target = requirePublicHttpsUrl(new URL(location, current).toString());
      } catch {
        fail("SITE_REDIRECT_UNSAFE", "Redirect ведёт на небезопасный target.");
      }
      if (!firstParty(baseHost, normalizeHost(target.hostname))) {
        fail("SITE_REDIRECT_UNSAFE", "Redirect вывел исследование за пределы first-party HTTPS target.");
      }
      if (exactAllowedHosts && !exactAllowedHosts.has(target.hostname.toLowerCase())) {
        fail("SITE_HOST_NOT_ALLOWLISTED", "Redirect host отсутствует в exact public research allowlist.");
      }
      current = target;
      continue;
    }
    if (!response.ok) fail("SITE_HTTP_UNAVAILABLE", `Сайт вернул HTTP ${response.status}.`);
    const contentType = response.headers.get("content-type") ?? "";
    if (!/text\/html|application\/xhtml\+xml/iu.test(contentType)) {
      fail("SITE_CONTENT_UNSUPPORTED", "Страница не вернула HTML.");
    }
    const { text: html, bytes } = await boundedText(response, remainingBytes);
    const title = extractMatches(html, /<title[^>]*>([\s\S]*?)<\/title>/giu, 1)[0] ?? "";
    const descriptions = extractMatches(
      html,
      /<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']*)["'][^>]*>/giu,
      2,
    );
    const headings = extractMatches(html, /<h[12][^>]*>([\s\S]*?)<\/h[12]>/giu, 20);
    const links = extractMatches(html, /<a[^>]+href=["']([^"']+)["'][^>]*>/giu, 500);
    const body = cleanText(
      html
        .replace(/<script[\s\S]*?<\/script>/giu, " ")
        .replace(/<style[\s\S]*?<\/style>/giu, " ")
        .replace(/<noscript[\s\S]*?<\/noscript>/giu, " "),
      8_000,
    );
    return {
      bytes,
      links,
      page: {
        url: current.toString(),
        title,
        description: descriptions[0] ?? "",
        headings: headings.slice(0, 10),
        forms_detected: (html.match(/<form\b/giu) ?? []).length,
        text_excerpt: body,
      } satisfies PageEvidence,
    };
  }
}

function rankedLinks(baseUrl: string, links: string[]) {
  const base = new URL(baseUrl);
  const baseHost = normalizeHost(base.hostname);
  const scores = new Map<string, number>();
  for (const href of links) {
    if (/^(mailto:|tel:|javascript:)/iu.test(href) || /privacy|cookie|login|logout|\.pdf|\.zip/iu.test(href)) continue;
    let candidate: URL;
    try {
      candidate = requirePublicHttpsUrl(new URL(href, base).toString());
    } catch {
      continue;
    }
    const candidateHost = normalizeHost(candidate.hostname);
    if (!firstParty(baseHost, candidateHost)) continue;
    candidate.search = "";
    candidate.hash = "";
    if (candidate.toString().replace(/\/$/u, "") === base.toString().replace(/\/$/u, "")) continue;
    const haystack = candidate.pathname.toLowerCase();
    let score = RESEARCH_TERMS.reduce((total, term) => total + (haystack.includes(term) ? 3 : 0), 0);
    if (candidateHost !== baseHost) score += 6;
    if (/terms.*particip|услов.*участ/iu.test(haystack)) score += 10;
    if (/become|стать-участ/iu.test(haystack)) score += 8;
    if (/participants|partner-country|list/iu.test(haystack)) score -= 4;
    if (score > 0) scores.set(candidate.toString(), Math.max(score, scores.get(candidate.toString()) ?? -100));
  }
  return [...scores.entries()].sort((left, right) => right[1] - left[1]).map(([url]) => url);
}

export async function researchAllowlistedPublicCompetitorPage(
  rawUrl: string,
  policy: PublicCompetitorResearchPolicy,
  dependencies: SiteResearchDependencies,
): Promise<PublicCompetitorPageObservation> {
  const requested = normalizePublicHttpsUrl(rawUrl);
  const allowedHosts = [...new Set(policy.allowedHosts.map((item) => item.trim().toLowerCase()).filter(Boolean))].sort();
  if (!allowedHosts.includes(requested.hostname.toLowerCase())) {
    fail("SITE_HOST_NOT_ALLOWLISTED", "Public competitor host отсутствует в exact allowlist.");
  }
  if (!policy.policyId.trim() || !policy.policyVersion.trim() || !policy.policyUrl.trim() || !policy.observationScope.trim()) {
    fail("SITE_POLICY_REQUIRED", "Public competitor research требует policy, version, URL и observation scope.");
  }
  requirePublicHttpsUrl(policy.policyUrl);
  const limits = exactLimits({
    maximumPages: 1,
    maximumRedirects: dependencies.limits?.maximumRedirects,
    maximumTotalBytes: dependencies.limits?.maximumTotalBytes,
  });
  const result = await fetchPage(
    requested.toString(),
    normalizeHost(requested.hostname),
    dependencies,
    limits,
    limits.maximumTotalBytes,
    new Set(allowedHosts),
  );
  const observedAt = dependencies.now();
  const finalUrl = new URL(result.page.url);
  return {
    source_url: finalUrl.toString(),
    observed_at: observedAt,
    collected_via: "PUBLIC_RESEARCH_EGRESS_V1",
    locator: { url: finalUrl.toString(), selector: "document" },
    policy: {
      policy_id: cleanText(policy.policyId, 100),
      version: cleanText(policy.policyVersion, 100),
      policy_url: requirePublicHttpsUrl(policy.policyUrl).toString(),
      access: "PUBLIC_NO_AUTH",
      allowed_hosts: allowedHosts,
    },
    scope: {
      host: finalUrl.hostname.toLowerCase(),
      pages_observed: 1,
      observation_scope: cleanText(policy.observationScope, 500),
    },
    page: result.page,
    raw_quote: cleanText(result.page.text_excerpt, 1_000),
    limitations: [
      "Одно public observation не доказывает prevalence или effectiveness.",
      "Budgets, CPC, conversions, account state и internal strategy не наблюдаются.",
    ],
  };
}

export async function researchPublicFirstPartySite(
  rawUrl: string,
  dependencies: SiteResearchDependencies,
): Promise<SiteAnalysis> {
  const limits = exactLimits(dependencies.limits);
  const requested = normalizePublicHttpsUrl(rawUrl);
  const requestedHost = normalizeHost(requested.hostname);
  let consumedBytes = 0;
  const entry = await fetchPage(
    requested.toString(),
    requestedHost,
    dependencies,
    limits,
    limits.maximumTotalBytes,
  );
  consumedBytes += entry.bytes;
  const entryHost = normalizeHost(new URL(entry.page.url).hostname);
  const pages = [entry.page];
  const attempted = new Set<string>();
  let candidates = rankedLinks(entry.page.url, entry.links);
  while (candidates.length && pages.length < limits.maximumPages) {
    const candidate = candidates.shift()!;
    if (attempted.has(candidate)) continue;
    attempted.add(candidate);
    try {
      const result = await fetchPage(
        candidate,
        entryHost,
        dependencies,
        limits,
        limits.maximumTotalBytes - consumedBytes,
      );
      consumedBytes += result.bytes;
      const pageHost = normalizeHost(new URL(result.page.url).hostname);
      if (!firstParty(entryHost, pageHost) || pages.some((item) => item.url === result.page.url)) continue;
      pages.push(result.page);
      candidates = [
        ...rankedLinks(result.page.url, result.links).filter((item) => !attempted.has(item)),
        ...candidates,
      ];
    } catch (error) {
      if (error instanceof SiteResearchError && SAFETY_ERROR_CODES.has(error.code)) throw error;
      // A non-safety failure on a secondary page does not erase authoritative entry-page evidence.
    }
  }
  return {
    ...entry.page,
    fetched_at: dependencies.now(),
    forms_detected: pages.reduce((sum, page) => sum + page.forms_detected, 0),
    text_excerpt: cleanText(pages.map((page) => page.text_excerpt).join(" "), 8_000),
    pages,
    research: {
      pages_analyzed: pages.length,
      links_discovered: entry.links.length,
      scope: "FIRST_PARTY_PUBLIC_HTTPS",
    },
  };
}

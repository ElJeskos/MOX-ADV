import { redactSensitiveEvidenceText } from "./analytics-evidence.ts";
import { strategyAnswerValue } from "./campaign-strategy.ts";
import { isPublicIpAddress, normalizePublicHttpsUrl, requirePublicHttpsUrl } from "./site-url.ts";
import { cleanText } from "./text.ts";

export const LANDING_ADVISORY_SCHEMA = "p0-landing-advisory-run-v1";
export const LANDING_ADVISORY_CONTRACT_VERSION = "1.0.0";
export const LANDING_ADVISORY_HARNESS_VERSION = "p0-landing-advisory-harness-v1";
export const LANDING_BROWSER_POLICY_VERSION = "first-party-public-advisory-browser-v1";
export const LANDING_ARTIFACT_MAX_BYTES = 64_000;
const LANDING_RESPONSE_MAX_BYTES = 5_000_000;
const LANDING_RUN_MAX_BYTES = 160_000;
const LANDING_OPERATION_TIMEOUT_MS = 30_000;
const LANDING_DETAIL_MAX = 2_000;
const AXE_ITEMS_PER_CATEGORY_MAX = 10;

export const PINNED_LANDING_TOOL_VERSIONS = {
  lighthouse: "12.8.2",
  chrome: "136.0.7103.113",
  lighthouse_config: "p0-lighthouse-desktop-1920x1080-v1",
  axe_core: "4.10.3",
} as const;

export const LANDING_ADVISORY_DIMENSIONS = [
  "OFFER_MESSAGE_MATCH",
  "CTA_ACTION",
  "FORMS",
  "MEASUREMENT_READINESS",
  "TECHNICAL_ACCESS",
  "PERFORMANCE",
  "ACCESSIBILITY",
  "OBSERVED_METRIKA_BEHAVIOR",
] as const;

export type LandingAdvisoryDimension = typeof LANDING_ADVISORY_DIMENSIONS[number];
export type LandingFindingType = "OBSERVED_FACT" | "DETERMINISTIC_CHECK" | "LLM_HYPOTHESIS";
export type LandingEvidenceStatus = "ISSUE_OBSERVED" | "NO_ISSUE_FOUND" | "INSUFFICIENT_EVIDENCE" | "NOT_APPLICABLE";
export type LandingAdvisoryStatus = "COMPLETE" | "COMPLETE_WITH_GAPS" | "INSUFFICIENT_EVIDENCE" | "SAFETY_BLOCKED";

type LandingNetworkRequest = {
  url: string;
  method: string;
  resource_type: string;
  headers?: Record<string, unknown>;
  body_present?: boolean;
  resolved_addresses: string[];
};

export type LandingBrowserPolicy = {
  version: typeof LANDING_BROWSER_POLICY_VERSION;
  allowed_hosts: string[];
  profile: {
    public_https_only: true;
    dns_ip_preflight_required: true;
    allow_form_submission: false;
    allow_clicks: false;
    allow_uploads: false;
    allow_downloads: false;
    allow_external_writes: false;
    allow_authenticated_pages: false;
    allow_cross_party_subresources: false;
    persist_cookies: false;
    allow_credentials: false;
    maximum_response_bytes: number;
    operation_timeout_ms: number;
  };
  bindHostResolution(hostname: string, addresses: string[]): void;
  boundAddresses(hostname: string): string[];
  authorizeRequest(request: LandingNetworkRequest): void;
};

export type LandingPageInspection = {
  requested_url: string;
  final_url: string;
  redirect_chain: string[];
  network_requests: LandingNetworkRequest[];
  response_bytes: number;
  page: {
    title: string;
    headings: string[];
    text_excerpt: string;
    ctas: Array<{ label: string; kind: string }>;
    forms: Array<{ method: string; action_kind: string; fields_count: number }>;
    metrika_tag_detected: boolean | null;
    http_status: number;
    content_type: string;
  };
  hypotheses?: Array<{
    dimension: LandingAdvisoryDimension;
    title: string;
    detail: string;
  }>;
};

export type LighthouseAdapterResult = {
  performance_score: number;
  metrics: {
    first_contentful_paint_ms: number;
    largest_contentful_paint_ms: number;
    cumulative_layout_shift: number;
    total_blocking_time_ms: number;
    speed_index_ms: number;
  };
};

type AxeItem = { id: string; impact: string | null; nodes: number; help: string };
type AxeCategory = { count: number; items: AxeItem[] };
export type AxeAdapterResult = {
  violations: AxeCategory;
  passes: AxeCategory;
  incomplete: AxeCategory;
  inapplicable: AxeCategory;
};

export interface LandingAdvisoryAdapter {
  availability: { available: boolean; reason: string | null };
  resolveHostname(hostname: string, signal: AbortSignal): Promise<string[]>;
  versions(signal: AbortSignal): Promise<Record<keyof typeof PINNED_LANDING_TOOL_VERSIONS, string>>;
  inspect(input: { url: string; viewport: typeof DESKTOP_VIEWPORT; policy: LandingBrowserPolicy; signal: AbortSignal }): Promise<LandingPageInspection>;
  runLighthouse(input: { url: string; sequence: number; viewport: typeof DESKTOP_VIEWPORT; policy: LandingBrowserPolicy; signal: AbortSignal }): Promise<LighthouseAdapterResult>;
  runAxe(input: { url: string; viewport: typeof DESKTOP_VIEWPORT; policy: LandingBrowserPolicy; signal: AbortSignal }): Promise<AxeAdapterResult>;
}

export type LandingFinding = {
  finding_id: string;
  dimension: LandingAdvisoryDimension;
  type: LandingFindingType;
  evidence_status: LandingEvidenceStatus;
  priority: number;
  title: string;
  detail: string;
  evidence_refs: string[];
};

type LighthouseRun = {
  sequence: number;
  status: "SUCCEEDED" | "FAILED";
  result: LighthouseAdapterResult | null;
  error_code: "LIGHTHOUSE_RUN_FAILED" | null;
};

type PersistedAxeCategory = AxeCategory & { items_truncated: boolean };

export type LandingAdvisoryRun = {
  schema_version: typeof LANDING_ADVISORY_SCHEMA;
  contract_version: typeof LANDING_ADVISORY_CONTRACT_VERSION;
  harness_version: typeof LANDING_ADVISORY_HARNESS_VERSION;
  run_id: string;
  advisory_key: string;
  strategy_revision_id: string;
  requested_url: string;
  final_url: string | null;
  status: LandingAdvisoryStatus;
  started_at: string;
  completed_at: string;
  viewport: typeof DESKTOP_VIEWPORT;
  browser_safety: {
    policy_version: typeof LANDING_BROWSER_POLICY_VERSION;
    allowed_hosts: string[];
    public_no_auth: true;
    cross_party_egress_denied: true;
    interactions_disabled: true;
    cookies_credentials_and_client_storage_disabled: true;
    bounded_response_bytes: number;
    bounded_artifact_bytes: number;
    safety_result: "PASSED" | "BLOCKED" | "NOT_RUN";
  };
  tools: {
    required: typeof PINNED_LANDING_TOOL_VERSIONS;
    observed: Record<keyof typeof PINNED_LANDING_TOOL_VERSIONS, string | null>;
    version_status: "PINNED_MATCH" | "PINNED_MISMATCH" | "UNAVAILABLE";
  };
  lighthouse: {
    expected_runs: 5;
    sequential: true;
    aggregation: "COMPONENT_MEDIAN_OF_EXACTLY_FIVE_NO_AVERAGING";
    runs: LighthouseRun[];
    median: LighthouseAdapterResult | null;
  };
  axe: {
    status: "COLLECTED" | "UNAVAILABLE";
    categories: {
      violations: PersistedAxeCategory;
      passes: PersistedAxeCategory;
      incomplete: PersistedAxeCategory;
      inapplicable: PersistedAxeCategory;
    };
    manual_review: { required: boolean; disclosure: string };
  };
  metrika: {
    source: "PERSISTED_ANALYTICS_EVIDENCE_ONLY";
    browser_cabinet_used: false;
    counter_id: string;
    goal_id: string;
    status: "OBSERVED" | "PARTIAL" | "UNAVAILABLE";
    period_start: string | null;
    period_end: string | null;
    visits: string | null;
    goal_visits: string | null;
    sampling_disclosure: string;
    evidence_ids: string[];
  };
  coverage: Array<{ dimension: LandingAdvisoryDimension; evidence_status: LandingEvidenceStatus }>;
  findings: LandingFinding[];
  artifacts: Array<{ artifact_id: string; kind: "PAGE_OBSERVATION" | "LIGHTHOUSE_SUMMARY" | "AXE_SUMMARY" | "METRIKA_SUMMARY"; value: unknown }>;
};

const DESKTOP_VIEWPORT = {
  form_factor: "desktop",
  width: 1920,
  height: 1080,
  device_scale_factor: 1,
} as const;

const FINDING_TYPES = new Set<LandingFindingType>(["OBSERVED_FACT", "DETERMINISTIC_CHECK", "LLM_HYPOTHESIS"]);
const EVIDENCE_STATUSES = new Set<LandingEvidenceStatus>(["ISSUE_OBSERVED", "NO_ISSUE_FOUND", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE"]);
const RUN_STATUSES = new Set<LandingAdvisoryStatus>(["COMPLETE", "COMPLETE_WITH_GAPS", "INSUFFICIENT_EVIDENCE", "SAFETY_BLOCKED"]);
const RESTRICTED_PATH = /(?:^|\/)(?:admin|administrator|auth|account|accounts|backend|cabinet|cms|console|dashboard|login|logout|manage|manager|oauth|phpmyadmin|private|signin|sign-in|user|users|wp-admin|wp-json|wp-login)(?:\/|$)/iu;
const SENSITIVE_HEADER = /^(?:authorization|cookie|proxy-authorization|x-api-key|x-auth-token)$/iu;

class LandingSafetyError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "LandingSafetyError";
    this.code = code;
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function boundedArtifactText(value: unknown, maximum = LANDING_DETAIL_MAX) {
  const bounded = cleanText(String(value ?? "").normalize("NFKC"), maximum);
  return cleanText(redactSensitiveEvidenceText(bounded, maximum), maximum + 20);
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

function resolvedAddressIsPublic(value: string) {
  const address = value.trim().toLowerCase().replace(/^\[|\]$/gu, "").split("%", 1)[0];
  const syntacticallyIp = /^\d{1,3}(?:\.\d{1,3}){3}$/u.test(address)
    || (address.includes(":") && /^[\da-f:]+$/u.test(address));
  return syntacticallyIp && isPublicIpAddress(address);
}

function rootHost(hostname: string) {
  return hostname.toLowerCase().replace(/^www\./u, "");
}

function hostIsIpLiteral(hostname: string) {
  const value = hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  return /^\d{1,3}(?:\.\d{1,3}){3}$/u.test(value) || value.includes(":");
}

function sameFirstPartyFamily(left: string, right: string) {
  const leftRoot = rootHost(left);
  const rightRoot = rootHost(right);
  if (hostIsIpLiteral(leftRoot) || hostIsIpLiteral(rightRoot)) return leftRoot === rightRoot;
  return leftRoot === rightRoot || leftRoot.endsWith(`.${rightRoot}`) || rightRoot.endsWith(`.${leftRoot}`);
}

function urlContainsSensitiveData(url: URL) {
  return [...url.searchParams.entries()].some(([key, value]) => {
    const source = `${key}=${value}`;
    return redactSensitiveEvidenceText(source, 2_000) !== source;
  });
}

function safeUrl(raw: string) {
  try {
    const url = requirePublicHttpsUrl(raw);
    if (urlContainsSensitiveData(url)) throw new Error("sensitive URL");
    return url;
  } catch {
    throw new LandingSafetyError("LANDING_CREDENTIAL_DENIED");
  }
}

function artifactSafeUrl(raw: string) {
  const url = normalizePublicHttpsUrl(raw);
  if (urlContainsSensitiveData(url)) url.search = "";
  return url.toString();
}

export function createLandingBrowserPolicy(requestedUrl: string, contextSiteUrl: string): LandingBrowserPolicy {
  const requested = safeUrl(normalizePublicHttpsUrl(requestedUrl).toString());
  const context = safeUrl(normalizePublicHttpsUrl(contextSiteUrl).toString());
  if (!sameFirstPartyFamily(requested.hostname, context.hostname)) {
    throw new LandingSafetyError("LANDING_EGRESS_DENIED");
  }
  if (RESTRICTED_PATH.test(requested.pathname)) throw new LandingSafetyError("LANDING_RESTRICTED_PATH_DENIED");
  const allowedHosts = [...new Set([requested.hostname.toLowerCase(), context.hostname.toLowerCase()])].sort();
  const boundResolutions = new Map<string, string[]>();
  const profile = {
    public_https_only: true,
    dns_ip_preflight_required: true,
    allow_form_submission: false,
    allow_clicks: false,
    allow_uploads: false,
    allow_downloads: false,
    allow_external_writes: false,
    allow_authenticated_pages: false,
    allow_cross_party_subresources: false,
    persist_cookies: false,
    allow_credentials: false,
    maximum_response_bytes: LANDING_RESPONSE_MAX_BYTES,
    operation_timeout_ms: LANDING_OPERATION_TIMEOUT_MS,
  } as const;
  return {
    version: LANDING_BROWSER_POLICY_VERSION,
    allowed_hosts: allowedHosts,
    profile,
    bindHostResolution(hostname, addresses) {
      const host = hostname.trim().toLowerCase();
      if (!allowedHosts.includes(host) || !addresses.length || addresses.some((address) => !resolvedAddressIsPublic(address))) {
        throw new LandingSafetyError("LANDING_DNS_IP_DENIED");
      }
      boundResolutions.set(host, [...new Set(addresses.map((address) => address.trim().toLowerCase()))].sort());
    },
    boundAddresses(hostname) {
      return [...(boundResolutions.get(hostname.trim().toLowerCase()) ?? [])];
    },
    authorizeRequest(request) {
      let url: URL;
      try {
        url = safeUrl(String(request.url ?? ""));
      } catch {
        throw new LandingSafetyError("LANDING_CREDENTIAL_DENIED");
      }
      const host = url.hostname.toLowerCase();
      if (!allowedHosts.includes(host)) throw new LandingSafetyError("LANDING_EGRESS_DENIED");
      const bound = boundResolutions.get(host) ?? [];
      const connected = list(request.resolved_addresses).map(String).map((address) => address.trim().toLowerCase());
      if (
        !bound.length
        || !connected.length
        || connected.some((address) => !resolvedAddressIsPublic(address) || !bound.includes(address))
      ) throw new LandingSafetyError("LANDING_DNS_IP_DENIED");
      if (RESTRICTED_PATH.test(url.pathname)) throw new LandingSafetyError("LANDING_RESTRICTED_PATH_DENIED");
      const method = String(request.method ?? "GET").toUpperCase();
      if (!["GET", "HEAD"].includes(method) || request.body_present === true) throw new LandingSafetyError("LANDING_WRITE_DENIED");
      if (Object.keys(record(request.headers)).some((header) => SENSITIVE_HEADER.test(header))) {
        throw new LandingSafetyError("LANDING_CREDENTIAL_DENIED");
      }
    },
  };
}

function emptyAxeCategories(): LandingAdvisoryRun["axe"]["categories"] {
  const empty = () => ({ count: 0, items: [], items_truncated: false });
  return { violations: empty(), passes: empty(), incomplete: empty(), inapplicable: empty() };
}

function baseRun(
  strategyRevisionId: string,
  requestedUrl: string,
  startedAt: string,
  completedAt: string,
  policy: LandingBrowserPolicy | null,
): Omit<LandingAdvisoryRun, "run_id" | "advisory_key"> {
  return {
    schema_version: LANDING_ADVISORY_SCHEMA,
    contract_version: LANDING_ADVISORY_CONTRACT_VERSION,
    harness_version: LANDING_ADVISORY_HARNESS_VERSION,
    strategy_revision_id: strategyRevisionId,
    requested_url: requestedUrl,
    final_url: null,
    status: "INSUFFICIENT_EVIDENCE",
    started_at: startedAt,
    completed_at: completedAt,
    viewport: DESKTOP_VIEWPORT,
    browser_safety: {
      policy_version: LANDING_BROWSER_POLICY_VERSION,
      allowed_hosts: policy?.allowed_hosts ?? [],
      public_no_auth: true,
      cross_party_egress_denied: true,
      interactions_disabled: true,
      cookies_credentials_and_client_storage_disabled: true,
      bounded_response_bytes: LANDING_RESPONSE_MAX_BYTES,
      bounded_artifact_bytes: LANDING_ARTIFACT_MAX_BYTES,
      safety_result: "NOT_RUN",
    },
    tools: {
      required: PINNED_LANDING_TOOL_VERSIONS,
      observed: { lighthouse: null, chrome: null, lighthouse_config: null, axe_core: null },
      version_status: "UNAVAILABLE",
    },
    lighthouse: {
      expected_runs: 5,
      sequential: true,
      aggregation: "COMPONENT_MEDIAN_OF_EXACTLY_FIVE_NO_AVERAGING",
      runs: [],
      median: null,
    },
    axe: {
      status: "UNAVAILABLE",
      categories: emptyAxeCategories(),
      manual_review: { required: true, disclosure: "axe-core evidence unavailable; accessibility requires manual review." },
    },
    metrika: {
      source: "PERSISTED_ANALYTICS_EVIDENCE_ONLY",
      browser_cabinet_used: false,
      counter_id: "",
      goal_id: "",
      status: "UNAVAILABLE",
      period_start: null,
      period_end: null,
      visits: null,
      goal_visits: null,
      sampling_disclosure: "Exact persisted Metrika observation unavailable; zero and success are not inferred.",
      evidence_ids: [],
    },
    coverage: LANDING_ADVISORY_DIMENSIONS.map((dimension) => ({ dimension, evidence_status: "INSUFFICIENT_EVIDENCE" })),
    findings: [],
    artifacts: [],
  };
}

async function finalizeRun(input: Omit<LandingAdvisoryRun, "run_id" | "advisory_key">): Promise<LandingAdvisoryRun> {
  const advisoryKey = `landing-advisory-key:${await sha256({
    strategy_revision_id: input.strategy_revision_id,
    final_url: input.final_url ?? input.requested_url,
  })}`;
  const withKey = { ...input, advisory_key: advisoryKey };
  return {
    ...withKey,
    run_id: `landing-advisory:${await sha256(withKey)}`,
  };
}

function unavailableFindings(reason: string): LandingFinding[] {
  return LANDING_ADVISORY_DIMENSIONS.map((dimension, index) => ({
    finding_id: `landing-finding-${dimension.toLowerCase().replaceAll("_", "-")}-unavailable`,
    dimension,
    type: dimension === "OBSERVED_METRIKA_BEHAVIOR" ? "OBSERVED_FACT" : "DETERMINISTIC_CHECK",
    evidence_status: "INSUFFICIENT_EVIDENCE",
    priority: index + 1,
    title: "Недостаточно доказательств",
    detail: boundedArtifactText(reason, 500),
    evidence_refs: [],
  }));
}

async function withTimeout<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("LANDING_OPERATION_TIMEOUT"), LANDING_OPERATION_TIMEOUT_MS);
  try {
    // Await the adapter promise even after abort: a timed-out operation must terminate before
    // the next sequential browser/tool operation can begin.
    const result = await operation(controller.signal);
    if (controller.signal.aborted) throw new Error("LANDING_OPERATION_TIMEOUT");
    return result;
  } finally {
    clearTimeout(timer);
  }
}

function exactPinnedVersions(observed: Record<string, string>) {
  return Object.entries(PINNED_LANDING_TOOL_VERSIONS)
    .every(([key, value]) => observed[key] === value);
}

function sanitizeInspection(raw: LandingPageInspection, policy: LandingBrowserPolicy, requestedUrl: string) {
  if (Number(raw.response_bytes) > LANDING_RESPONSE_MAX_BYTES || Number(raw.response_bytes) < 0) {
    throw new LandingSafetyError("LANDING_RESPONSE_LIMIT_DENIED");
  }
  for (const request of list(raw.network_requests)) policy.authorizeRequest(request as LandingNetworkRequest);
  const redirects = list(raw.redirect_chain).map(String);
  if (redirects.length === 0 || redirects.length > 5) throw new LandingSafetyError("LANDING_REDIRECT_DENIED");
  for (const redirect of redirects) {
    policy.authorizeRequest({
      url: redirect,
      method: "GET",
      resource_type: "document",
      headers: {},
      body_present: false,
      resolved_addresses: policy.boundAddresses(new URL(redirect).hostname),
    });
  }
  const finalUrl = safeUrl(String(raw.final_url ?? ""));
  policy.authorizeRequest({
    url: finalUrl.toString(),
    method: "GET",
    resource_type: "document",
    headers: {},
    body_present: false,
    resolved_addresses: policy.boundAddresses(finalUrl.hostname),
  });
  if (normalizePublicHttpsUrl(String(raw.requested_url ?? "")).toString() !== requestedUrl) {
    throw new LandingSafetyError("LANDING_REQUEST_MISMATCH_DENIED");
  }
  const page = record(raw.page);
  return {
    final_url: finalUrl.toString(),
    response_bytes: Math.trunc(Number(raw.response_bytes)),
    page: {
      title: boundedArtifactText(page.title, 500),
      headings: list(page.headings).slice(0, 20).map((item) => boundedArtifactText(item, 500)).filter(Boolean),
      text_excerpt: boundedArtifactText(page.text_excerpt, 8_000),
      ctas: list(page.ctas).slice(0, 20).map((item) => ({
        label: boundedArtifactText(record(item).label, 500),
        kind: boundedArtifactText(record(item).kind, 50),
      })),
      forms: list(page.forms).slice(0, 20).map((item) => ({
        method: boundedArtifactText(record(item).method, 20).toUpperCase(),
        action_kind: boundedArtifactText(record(item).action_kind, 50),
        fields_count: Math.max(0, Math.min(100, Math.trunc(Number(record(item).fields_count ?? 0)))),
      })),
      metrika_tag_detected: typeof page.metrika_tag_detected === "boolean" ? page.metrika_tag_detected : null,
      http_status: Math.trunc(Number(page.http_status ?? 0)),
      content_type: boundedArtifactText(page.content_type, 100),
    },
    hypotheses: list(raw.hypotheses).slice(0, 10).flatMap((item) => {
      const value = record(item);
      const dimension = String(value.dimension) as LandingAdvisoryDimension;
      if (!LANDING_ADVISORY_DIMENSIONS.includes(dimension)) return [];
      const title = boundedArtifactText(value.title, 500);
      const detail = boundedArtifactText(value.detail, LANDING_DETAIL_MAX);
      return title && detail ? [{ dimension, title, detail }] : [];
    }),
  };
}

function validNumber(value: unknown, minimum: number, maximum: number) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < minimum || numeric > maximum) throw new Error("LANDING_METRIC_INVALID");
  return numeric;
}

function sanitizeLighthouse(raw: LighthouseAdapterResult): LighthouseAdapterResult {
  const metrics = record(raw.metrics);
  return {
    performance_score: validNumber(raw.performance_score, 0, 1),
    metrics: {
      first_contentful_paint_ms: validNumber(metrics.first_contentful_paint_ms, 0, 600_000),
      largest_contentful_paint_ms: validNumber(metrics.largest_contentful_paint_ms, 0, 600_000),
      cumulative_layout_shift: validNumber(metrics.cumulative_layout_shift, 0, 100),
      total_blocking_time_ms: validNumber(metrics.total_blocking_time_ms, 0, 600_000),
      speed_index_ms: validNumber(metrics.speed_index_ms, 0, 600_000),
    },
  };
}

function median(values: number[]) {
  return [...values].sort((left, right) => left - right)[Math.floor(values.length / 2)];
}

function medianLighthouse(runs: LighthouseRun[]): LighthouseAdapterResult | null {
  const values = runs.map((run) => run.result).filter((value): value is LighthouseAdapterResult => Boolean(value));
  if (runs.length !== 5 || values.length !== 5) return null;
  return {
    performance_score: median(values.map((item) => item.performance_score)),
    metrics: {
      first_contentful_paint_ms: median(values.map((item) => item.metrics.first_contentful_paint_ms)),
      largest_contentful_paint_ms: median(values.map((item) => item.metrics.largest_contentful_paint_ms)),
      cumulative_layout_shift: median(values.map((item) => item.metrics.cumulative_layout_shift)),
      total_blocking_time_ms: median(values.map((item) => item.metrics.total_blocking_time_ms)),
      speed_index_ms: median(values.map((item) => item.metrics.speed_index_ms)),
    },
  };
}

function sanitizeAxeCategory(value: AxeCategory): PersistedAxeCategory {
  const raw = record(value);
  const count = Math.max(0, Math.min(100_000, Math.trunc(Number(raw.count ?? 0))));
  const allItems = list(raw.items);
  return {
    count,
    items: allItems.slice(0, AXE_ITEMS_PER_CATEGORY_MAX).map((item) => {
      const row = record(item);
      return {
        id: boundedArtifactText(row.id, 100),
        impact: row.impact === null || row.impact === undefined ? null : boundedArtifactText(row.impact, 50),
        nodes: Math.max(0, Math.min(100_000, Math.trunc(Number(row.nodes ?? 0)))),
        help: boundedArtifactText(row.help, 500),
      };
    }),
    items_truncated: allItems.length > AXE_ITEMS_PER_CATEGORY_MAX || count > allItems.length,
  };
}

function sanitizeAxe(raw: AxeAdapterResult): LandingAdvisoryRun["axe"] {
  const categories = {
    violations: sanitizeAxeCategory(raw.violations),
    passes: sanitizeAxeCategory(raw.passes),
    incomplete: sanitizeAxeCategory(raw.incomplete),
    inapplicable: sanitizeAxeCategory(raw.inapplicable),
  };
  const required = categories.incomplete.count > 0;
  return {
    status: "COLLECTED",
    categories,
    manual_review: {
      required,
      disclosure: required
        ? `${categories.incomplete.count} axe incomplete item(s) remain explicit manual review; they are neither pass nor fail.`
        : "axe incomplete category is empty; manual review may still find issues outside automated coverage.",
    },
  };
}

function extractMetrika(
  contextState: Record<string, unknown>,
  analyticsEvidence: Record<string, unknown>,
): LandingAdvisoryRun["metrika"] {
  const facts = record(contextState.facts);
  const binding = record(facts.metrika);
  const counterId = boundedArtifactText(binding.counter_id, 100);
  const goalId = boundedArtifactText(binding.goal_id, 100);
  const claim = list(analyticsEvidence.claims).map(record).find((item) => item.predicate === "observed_performance");
  const normalized = record(record(claim?.normalized).value);
  const report = record(normalized.report);
  const exactBinding = counterId && goalId && normalized.counter_id === counterId && normalized.goal_id === goalId;
  const validMetric = (value: unknown) => typeof value === "string" && /^\d+(?:\.\d+)?$/u.test(value) && Number.isFinite(Number(value));
  const metricsComplete = validMetric(normalized.visits) && validMetric(normalized.goal_visits);
  const complete = exactBinding
    && metricsComplete
    && report.metadata_complete === true
    && report.sampled === false
    && report.contains_sensitive_data === false
    && Number(report.data_lag ?? 0) === 0
    && record(claim?.confidence).coverage === "complete_for_scope";
  const visits = exactBinding && validMetric(normalized.visits) ? boundedArtifactText(normalized.visits, 100) : null;
  const goalVisits = exactBinding && validMetric(normalized.goal_visits) ? boundedArtifactText(normalized.goal_visits, 100) : null;
  const hasPositiveVisits = visits !== null && Number(visits) > 0;
  return {
    source: "PERSISTED_ANALYTICS_EVIDENCE_ONLY",
    browser_cabinet_used: false,
    counter_id: counterId,
    goal_id: goalId,
    status: complete && hasPositiveVisits ? "OBSERVED" : claim && exactBinding ? "PARTIAL" : "UNAVAILABLE",
    period_start: exactBinding ? boundedArtifactText(report.period_start, 20) || null : null,
    period_end: exactBinding ? boundedArtifactText(report.period_end, 20) || null : null,
    visits,
    goal_visits: goalVisits,
    sampling_disclosure: complete
      ? "Exact API-bound counter/goal observation is complete for its persisted report scope; it is not a browser measurement test."
      : "Metrika evidence is missing, partial, sampled, privacy-limited, lagged or has no observed visits; zero and success are not inferred.",
    evidence_ids: list(claim?.evidence_ids).slice(0, 20).map((item) => boundedArtifactText(item, 255)).filter(Boolean),
  };
}

function tokens(value: unknown) {
  return new Set(
    String(value ?? "").toLowerCase().normalize("NFKC").match(/[\p{L}\p{N}]{4,}/gu) ?? [],
  );
}

function tokenCoverage(haystack: string, expected: string) {
  const source = tokens(haystack);
  const target = [...tokens(expected)];
  if (target.length === 0) return null;
  return target.filter((item) => source.has(item)).length / target.length;
}

function finding(
  dimension: LandingAdvisoryDimension,
  type: LandingFindingType,
  status: LandingEvidenceStatus,
  priority: number,
  title: string,
  detail: string,
  evidenceRefs: string[],
): LandingFinding {
  return {
    finding_id: `landing-finding-${dimension.toLowerCase().replaceAll("_", "-")}-${type.toLowerCase().replaceAll("_", "-")}`,
    dimension,
    type,
    evidence_status: status,
    priority,
    title: boundedArtifactText(title, 500),
    detail: boundedArtifactText(detail, LANDING_DETAIL_MAX),
    evidence_refs: evidenceRefs.slice(0, 20).map((item) => boundedArtifactText(item, 255)).filter(Boolean),
  };
}

function buildFindings(
  strategy: Record<string, unknown>,
  inspection: ReturnType<typeof sanitizeInspection>,
  lighthouse: LandingAdvisoryRun["lighthouse"],
  axe: LandingAdvisoryRun["axe"],
  metrika: LandingAdvisoryRun["metrika"],
) {
  const pageText = [inspection.page.title, ...inspection.page.headings, inspection.page.text_excerpt].join(" ");
  const expectedMessage = `${String(strategyAnswerValue(strategy, "advertised_offer") ?? "")} ${String(strategyAnswerValue(strategy, "core_message") ?? "")}`;
  const match = tokenCoverage(pageText, expectedMessage);
  const qualifiedResult = String(strategyAnswerValue(strategy, "qualified_result") ?? "");
  const ctaText = inspection.page.ctas.map((item) => item.label).join(" ");
  const ctaMatch = tokenCoverage(ctaText, qualifiedResult);
  const formExpected = /заяв|форм|регистра|submit|application|register/iu.test(qualifiedResult);
  const toolFindings: LandingFinding[] = [
    finding(
      "OFFER_MESSAGE_MATCH",
      "DETERMINISTIC_CHECK",
      match === null ? "INSUFFICIENT_EVIDENCE" : match >= 0.5 ? "NO_ISSUE_FOUND" : "ISSUE_OBSERVED",
      2,
      match === null ? "Недостаточно текста для offer/message check" : match >= 0.5 ? "Offer и core message представлены на странице" : "Offer/message match требует внимания",
      match === null ? "Strategy или bounded page text не дают сравнимого набора терминов." : `Deterministic token coverage: ${Math.round(match * 100)}%.`,
      ["artifact:page-observation"],
    ),
    finding(
      "CTA_ACTION",
      "DETERMINISTIC_CHECK",
      inspection.page.ctas.length === 0 ? "ISSUE_OBSERVED" : ctaMatch === null || ctaMatch === 0 ? "INSUFFICIENT_EVIDENCE" : "NO_ISSUE_FOUND",
      1,
      inspection.page.ctas.length === 0 ? "CTA не обнаружен" : ctaMatch ? "CTA соответствует qualified action" : "CTA требует ручной проверки на соответствие действию",
      `${inspection.page.ctas.length} bounded CTA observation(s); advisory browser did not click any of them.`,
      ["artifact:page-observation"],
    ),
    finding(
      "FORMS",
      "DETERMINISTIC_CHECK",
      inspection.page.forms.length > 0 ? "NO_ISSUE_FOUND" : formExpected ? "ISSUE_OBSERVED" : "NOT_APPLICABLE",
      3,
      inspection.page.forms.length > 0 ? "Форма обнаружена без отправки" : formExpected ? "Ожидаемая форма не обнаружена" : "Форма не требуется доказанным qualified action",
      `${inspection.page.forms.length} form observation(s); submit, upload and field interaction were disabled.`,
      ["artifact:page-observation"],
    ),
    finding(
      "MEASUREMENT_READINESS",
      "DETERMINISTIC_CHECK",
      inspection.page.metrika_tag_detected === false ? "ISSUE_OBSERVED" : "INSUFFICIENT_EVIDENCE",
      4,
      inspection.page.metrika_tag_detected === false ? "Public Metrika marker not detected" : "Goal instrumentation requires manual verification",
      inspection.page.metrika_tag_detected
        ? "A public marker was observed, but no form/action was triggered and exact goal semantics were not inferred."
        : "A bounded public-page observation cannot prove goal readiness; no private cabinet was inspected.",
      ["artifact:page-observation"],
    ),
    finding(
      "TECHNICAL_ACCESS",
      "DETERMINISTIC_CHECK",
      inspection.page.http_status >= 200 && inspection.page.http_status < 300 && /html/iu.test(inspection.page.content_type) ? "NO_ISSUE_FOUND" : "ISSUE_OBSERVED",
      5,
      inspection.page.http_status >= 200 && inspection.page.http_status < 300 ? "Public HTTPS page is technically accessible" : "Landing returned a technical access issue",
      `HTTP ${inspection.page.http_status}; ${inspection.page.content_type || "content type unavailable"}; final URL passed exact first-party safety policy.`,
      ["artifact:page-observation"],
    ),
    finding(
      "PERFORMANCE",
      "DETERMINISTIC_CHECK",
      lighthouse.median === null ? "INSUFFICIENT_EVIDENCE" : lighthouse.median.performance_score >= 0.9 ? "NO_ISSUE_FOUND" : "ISSUE_OBSERVED",
      6,
      lighthouse.median === null ? "Five-run performance coverage is insufficient" : lighthouse.median.performance_score >= 0.9 ? "Median Lighthouse performance has no issue at policy contour" : "Median Lighthouse performance requires attention",
      lighthouse.median === null ? "All five sequential attempts are retained; no median is claimed unless all five succeed." : `Five-run component median performance score: ${lighthouse.median.performance_score}.`,
      ["artifact:lighthouse-summary"],
    ),
    finding(
      "ACCESSIBILITY",
      "DETERMINISTIC_CHECK",
      axe.status !== "COLLECTED" ? "INSUFFICIENT_EVIDENCE" : axe.categories.violations.count > 0 ? "ISSUE_OBSERVED" : axe.categories.incomplete.count > 0 ? "INSUFFICIENT_EVIDENCE" : "NO_ISSUE_FOUND",
      7,
      axe.status !== "COLLECTED" ? "Accessibility evidence unavailable" : axe.categories.violations.count > 0 ? "axe-core found accessibility violations" : axe.categories.incomplete.count > 0 ? "Accessibility needs manual review" : "axe-core found no automated violations",
      axe.manual_review.disclosure,
      ["artifact:axe-summary"],
    ),
    finding(
      "OBSERVED_METRIKA_BEHAVIOR",
      "OBSERVED_FACT",
      metrika.status !== "OBSERVED" ? "INSUFFICIENT_EVIDENCE" : Number(metrika.goal_visits ?? 0) > 0 ? "NO_ISSUE_FOUND" : "ISSUE_OBSERVED",
      8,
      metrika.status !== "OBSERVED" ? "Недостаточно persisted Metrika evidence" : Number(metrika.goal_visits ?? 0) > 0 ? "Exact bound goal behavior is present in persisted observations" : "Visits were observed without bound goal visits",
      metrika.sampling_disclosure,
      ["artifact:metrika-summary", ...metrika.evidence_ids],
    ),
  ];
  const hypotheses = inspection.hypotheses.map((item, index) => finding(
    item.dimension,
    "LLM_HYPOTHESIS",
    "INSUFFICIENT_EVIDENCE",
    50 + index,
    item.title,
    `${item.detail} Гипотеза не повышена до факта и требует ручной проверки.`,
    ["artifact:page-observation"],
  ));
  return [...toolFindings, ...hypotheses];
}

function coverageFromFindings(findings: LandingFinding[]) {
  const precedence: Record<LandingEvidenceStatus, number> = {
    ISSUE_OBSERVED: 4,
    INSUFFICIENT_EVIDENCE: 3,
    NO_ISSUE_FOUND: 2,
    NOT_APPLICABLE: 1,
  };
  return LANDING_ADVISORY_DIMENSIONS.map((dimension) => {
    const deterministic = findings.filter((item) => item.dimension === dimension && item.type !== "LLM_HYPOTHESIS");
    const evidenceStatus = deterministic
      .map((item) => item.evidence_status)
      .sort((left, right) => precedence[right] - precedence[left])[0] ?? "INSUFFICIENT_EVIDENCE";
    return { dimension, evidence_status: evidenceStatus };
  });
}

function artifactsFor(
  inspection: ReturnType<typeof sanitizeInspection>,
  lighthouse: LandingAdvisoryRun["lighthouse"],
  axe: LandingAdvisoryRun["axe"],
  metrika: LandingAdvisoryRun["metrika"],
): LandingAdvisoryRun["artifacts"] {
  const artifacts: LandingAdvisoryRun["artifacts"] = [
    { artifact_id: "artifact:page-observation", kind: "PAGE_OBSERVATION", value: inspection.page },
    { artifact_id: "artifact:lighthouse-summary", kind: "LIGHTHOUSE_SUMMARY", value: lighthouse },
    { artifact_id: "artifact:axe-summary", kind: "AXE_SUMMARY", value: axe },
    { artifact_id: "artifact:metrika-summary", kind: "METRIKA_SUMMARY", value: metrika },
  ];
  const artifactBytes = () => new TextEncoder().encode(JSON.stringify(artifacts)).byteLength;
  if (artifactBytes() > LANDING_ARTIFACT_MAX_BYTES) {
    const page = record(artifacts[0].value);
    page.text_excerpt = boundedArtifactText(page.text_excerpt, 1_000);
    page.headings = list(page.headings).slice(0, 5);
    page.ctas = list(page.ctas).slice(0, 5);
    page.forms = list(page.forms).slice(0, 5);
  }
  if (artifactBytes() > LANDING_ARTIFACT_MAX_BYTES) {
    const axeValue = record(artifacts[2].value);
    const categories = record(axeValue.categories);
    for (const name of ["violations", "passes", "incomplete", "inapplicable"]) {
      const category = record(categories[name]);
      category.items = list(category.items).slice(0, 2);
      category.items_truncated = true;
    }
  }
  if (artifactBytes() > LANDING_ARTIFACT_MAX_BYTES) {
    const page = record(artifacts[0].value);
    page.text_excerpt = "[TRUNCATED_TO_ARTIFACT_BUDGET]";
    page.headings = [];
    page.ctas = [];
    page.forms = [];
  }
  return artifacts;
}

export const unavailableLandingAdvisoryAdapter: LandingAdvisoryAdapter = {
  availability: { available: false, reason: "Pinned isolated landing audit runtime is unavailable in this deployment." },
  async resolveHostname() { return []; },
  async versions() {
    return { lighthouse: "", chrome: "", lighthouse_config: "", axe_core: "" };
  },
  async inspect() { throw new Error("LANDING_ADVISORY_UNAVAILABLE"); },
  async runLighthouse() { throw new Error("LANDING_ADVISORY_UNAVAILABLE"); },
  async runAxe() { throw new Error("LANDING_ADVISORY_UNAVAILABLE"); },
};

export async function runLandingAdvisory({
  strategy,
  contextState,
  analyticsEvidence,
  adapter,
  now,
}: {
  strategy: Record<string, unknown>;
  contextState: Record<string, unknown>;
  analyticsEvidence: Record<string, unknown>;
  adapter: LandingAdvisoryAdapter;
  now(): string;
}): Promise<LandingAdvisoryRun> {
  const startedAt = now();
  const strategyRevisionId = boundedArtifactText(strategy.strategy_revision_id, 255);
  const rawRequestedUrl = normalizePublicHttpsUrl(String(strategyAnswerValue(strategy, "landing_page") ?? "")).toString();
  const persistedRequestedUrl = artifactSafeUrl(rawRequestedUrl);
  const contextSiteUrl = String(record(record(contextState.facts).site).url ?? "");
  let policy: LandingBrowserPolicy | null = null;
  try {
    policy = createLandingBrowserPolicy(rawRequestedUrl, contextSiteUrl);
  } catch {
    const blocked = baseRun(strategyRevisionId, persistedRequestedUrl, startedAt, now(), null);
    blocked.status = "SAFETY_BLOCKED";
    blocked.browser_safety.safety_result = "BLOCKED";
    blocked.findings = unavailableFindings("Landing target was denied by the exact first-party public browser policy.");
    return finalizeRun(blocked);
  }
  const requestedUrl = rawRequestedUrl;
  const draft = baseRun(strategyRevisionId, requestedUrl, startedAt, startedAt, policy);
  draft.metrika = extractMetrika(contextState, analyticsEvidence);
  if (!adapter.availability.available) {
    draft.completed_at = now();
    draft.findings = unavailableFindings(adapter.availability.reason || "Pinned landing tools are unavailable.");
    return finalizeRun(draft);
  }

  let observedVersions: Record<keyof typeof PINNED_LANDING_TOOL_VERSIONS, string>;
  try {
    for (const hostname of policy.allowed_hosts) {
      const addresses = await withTimeout((signal) => adapter.resolveHostname(hostname, signal));
      policy.bindHostResolution(hostname, addresses);
    }
    observedVersions = await withTimeout((signal) => adapter.versions(signal));
  } catch (error) {
    if (error instanceof LandingSafetyError) {
      draft.status = "SAFETY_BLOCKED";
      draft.browser_safety.safety_result = "BLOCKED";
      draft.findings = unavailableFindings("Landing hostname did not pass public DNS/IP safety preflight.");
    } else {
      draft.findings = unavailableFindings("Exact landing tool versions could not be verified.");
    }
    draft.completed_at = now();
    return finalizeRun(draft);
  }
  draft.tools.observed = {
    lighthouse: cleanText(String(observedVersions.lighthouse ?? ""), 100),
    chrome: cleanText(String(observedVersions.chrome ?? ""), 100),
    lighthouse_config: cleanText(String(observedVersions.lighthouse_config ?? ""), 100),
    axe_core: cleanText(String(observedVersions.axe_core ?? ""), 100),
  };
  if (!exactPinnedVersions(draft.tools.observed as Record<string, string>)) {
    draft.tools.version_status = "PINNED_MISMATCH";
    draft.completed_at = now();
    draft.findings = unavailableFindings("Observed landing tool versions do not match the pinned contract.");
    return finalizeRun(draft);
  }
  draft.tools.version_status = "PINNED_MATCH";

  let inspection: ReturnType<typeof sanitizeInspection>;
  try {
    inspection = sanitizeInspection(
      await withTimeout((signal) => adapter.inspect({ url: requestedUrl, viewport: DESKTOP_VIEWPORT, policy, signal })),
      policy,
      requestedUrl,
    );
  } catch {
    draft.status = "SAFETY_BLOCKED";
    draft.browser_safety.safety_result = "BLOCKED";
    draft.completed_at = now();
    draft.findings = unavailableFindings("Browser navigation or returned trace failed the fail-closed landing safety policy.");
    return finalizeRun(draft);
  }
  draft.final_url = inspection.final_url;
  draft.browser_safety.safety_result = "PASSED";

  for (let sequence = 1; sequence <= 5; sequence += 1) {
    try {
      const finalHost = new URL(inspection.final_url).hostname;
      policy.authorizeRequest({
        url: inspection.final_url,
        method: "GET",
        resource_type: "document",
        headers: {},
        body_present: false,
        resolved_addresses: policy.boundAddresses(finalHost),
      });
      const result = sanitizeLighthouse(await withTimeout((signal) => adapter.runLighthouse({
        url: inspection.final_url,
        sequence,
        viewport: DESKTOP_VIEWPORT,
        policy,
        signal,
      })));
      draft.lighthouse.runs.push({ sequence, status: "SUCCEEDED", result, error_code: null });
    } catch {
      draft.lighthouse.runs.push({ sequence, status: "FAILED", result: null, error_code: "LIGHTHOUSE_RUN_FAILED" });
    }
  }
  draft.lighthouse.median = medianLighthouse(draft.lighthouse.runs);

  try {
    const finalHost = new URL(inspection.final_url).hostname;
    policy.authorizeRequest({
      url: inspection.final_url,
      method: "GET",
      resource_type: "document",
      headers: {},
      body_present: false,
      resolved_addresses: policy.boundAddresses(finalHost),
    });
    draft.axe = sanitizeAxe(await withTimeout((signal) => adapter.runAxe({
      url: inspection.final_url,
      viewport: DESKTOP_VIEWPORT,
      policy,
      signal,
    })));
  } catch {
    draft.axe = {
      status: "UNAVAILABLE",
      categories: emptyAxeCategories(),
      manual_review: { required: true, disclosure: "axe-core collection failed; accessibility remains explicit manual review." },
    };
  }
  draft.findings = buildFindings(strategy, inspection, draft.lighthouse, draft.axe, draft.metrika);
  draft.coverage = coverageFromFindings(draft.findings);
  draft.status = draft.lighthouse.median && draft.axe.status === "COLLECTED"
    ? draft.coverage.some((item) => item.evidence_status === "INSUFFICIENT_EVIDENCE") ? "COMPLETE_WITH_GAPS" : "COMPLETE"
    : "COMPLETE_WITH_GAPS";
  draft.artifacts = artifactsFor(inspection, draft.lighthouse, draft.axe, draft.metrika);
  draft.completed_at = now();
  return finalizeRun(draft);
}

export function landingAdvisoryPriorities(value: unknown): LandingFinding[] {
  const findings = list(record(value).findings).map(record) as LandingFinding[];
  return findings
    .filter((item) => item.type !== "LLM_HYPOTHESIS" && ["ISSUE_OBSERVED", "INSUFFICIENT_EVIDENCE"].includes(item.evidence_status))
    .sort((left, right) => Number(left.priority) - Number(right.priority) || String(left.finding_id).localeCompare(String(right.finding_id)))
    .slice(0, 3);
}

function persistedArtifactValueIsSafe(value: unknown, depth = 0): boolean {
  if (depth > 8) return false;
  if (typeof value === "string") {
    return value.length <= 8_020 && boundedArtifactText(value, 8_000) === value;
  }
  if (value === null || typeof value === "number" || typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.length <= 100 && value.every((item) => persistedArtifactValueIsSafe(item, depth + 1));
  if (!value || typeof value !== "object") return false;
  const entries = Object.entries(value as Record<string, unknown>);
  return entries.length <= 100 && entries.every(([key, item]) => key.length <= 100 && persistedArtifactValueIsSafe(item, depth + 1));
}

function persistedAxeCategoryIsValid(value: unknown) {
  const category = record(value);
  const items = list(category.items).map(record);
  return Number.isSafeInteger(category.count)
    && Number(category.count) >= 0
    && Number(category.count) <= 100_000
    && typeof category.items_truncated === "boolean"
    && items.length <= AXE_ITEMS_PER_CATEGORY_MAX
    && items.every((item) => (
      typeof item.id === "string" && item.id.length <= 120
      && (item.impact === null || (typeof item.impact === "string" && item.impact.length <= 70))
      && Number.isSafeInteger(item.nodes) && Number(item.nodes) >= 0 && Number(item.nodes) <= 100_000
      && typeof item.help === "string" && item.help.length <= 520
    ));
}

function persistedLighthouseResultIsValid(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  try {
    return JSON.stringify(sanitizeLighthouse(value as LighthouseAdapterResult)) === JSON.stringify(value);
  } catch {
    return false;
  }
}

function persistedLandingUrlPolicyIsConsistent(
  run: Record<string, unknown>,
  browserSafety: Record<string, unknown>,
) {
  let requested: URL;
  let final: URL | null = null;
  try {
    requested = safeUrl(String(run.requested_url));
    if (requested.toString() !== run.requested_url) return false;
    if (run.final_url !== null) {
      final = safeUrl(String(run.final_url));
      if (final.toString() !== run.final_url || RESTRICTED_PATH.test(final.pathname)) return false;
    }
  } catch {
    return false;
  }
  if (final && !sameFirstPartyFamily(requested.hostname, final.hostname)) return false;

  const rawAllowedHosts = list(browserSafety.allowed_hosts);
  if (rawAllowedHosts.some((host) => typeof host !== "string")) return false;
  const allowedHosts = rawAllowedHosts as string[];
  const canonicalAllowedHosts = [...new Set(allowedHosts)].sort();
  if (JSON.stringify(allowedHosts) !== JSON.stringify(canonicalAllowedHosts)) return false;
  for (const host of allowedHosts) {
    try {
      const hostUrl = safeUrl(`https://${host}/`);
      if (hostUrl.hostname !== host || !sameFirstPartyFamily(requested.hostname, host)) return false;
    } catch {
      return false;
    }
  }

  const safetyResult = String(browserSafety.safety_result ?? "");
  const policyBlockedBeforeNavigation = run.status === "SAFETY_BLOCKED"
    && safetyResult === "BLOCKED"
    && final === null
    && allowedHosts.length === 0;
  if (RESTRICTED_PATH.test(requested.pathname)) return policyBlockedBeforeNavigation;
  if (allowedHosts.length === 0) return policyBlockedBeforeNavigation;
  if (!allowedHosts.includes(requested.hostname)) return false;
  if (final && (!allowedHosts.includes(final.hostname) || safetyResult !== "PASSED")) return false;
  if (safetyResult === "PASSED" && final === null) return false;
  if (["COMPLETE", "COMPLETE_WITH_GAPS"].includes(String(run.status))) {
    return final !== null
      && allowedHosts.includes(requested.hostname)
      && allowedHosts.includes(final.hostname);
  }
  return true;
}

export async function verifyLandingAdvisoryRun(value: unknown): Promise<boolean> {
  const run = record(value);
  if (
    run.schema_version !== LANDING_ADVISORY_SCHEMA
    || run.contract_version !== LANDING_ADVISORY_CONTRACT_VERSION
    || run.harness_version !== LANDING_ADVISORY_HARNESS_VERSION
    || !RUN_STATUSES.has(String(run.status) as LandingAdvisoryStatus)
    || typeof run.strategy_revision_id !== "string"
    || typeof run.requested_url !== "string"
    || !Array.isArray(run.coverage)
    || !Array.isArray(run.findings)
    || !Array.isArray(run.artifacts)
    || new TextEncoder().encode(JSON.stringify(run)).byteLength > LANDING_RUN_MAX_BYTES
  ) return false;
  try {
    normalizePublicHttpsUrl(run.requested_url).toString();
    if (run.final_url !== null) normalizePublicHttpsUrl(String(run.final_url)).toString();
  } catch {
    return false;
  }
  if (
    !String(run.strategy_revision_id).trim()
    || !Number.isFinite(Date.parse(String(run.started_at ?? "")))
    || !Number.isFinite(Date.parse(String(run.completed_at ?? "")))
    || Date.parse(String(run.completed_at)) < Date.parse(String(run.started_at))
    || JSON.stringify(run.viewport) !== JSON.stringify(DESKTOP_VIEWPORT)
  ) return false;
  const browserSafety = record(run.browser_safety);
  if (
    browserSafety.policy_version !== LANDING_BROWSER_POLICY_VERSION
    || browserSafety.public_no_auth !== true
    || browserSafety.cross_party_egress_denied !== true
    || browserSafety.interactions_disabled !== true
    || browserSafety.cookies_credentials_and_client_storage_disabled !== true
    || browserSafety.bounded_response_bytes !== LANDING_RESPONSE_MAX_BYTES
    || browserSafety.bounded_artifact_bytes !== LANDING_ARTIFACT_MAX_BYTES
    || !Array.isArray(browserSafety.allowed_hosts)
    || browserSafety.allowed_hosts.length > 2
    || browserSafety.allowed_hosts.some((host) => typeof host !== "string" || host.length > 255)
    || !persistedLandingUrlPolicyIsConsistent(run, browserSafety)
  ) return false;
  const coverage = run.coverage.map(record);
  if (
    coverage.length !== LANDING_ADVISORY_DIMENSIONS.length
    || coverage.some((item, index) => item.dimension !== LANDING_ADVISORY_DIMENSIONS[index] || !EVIDENCE_STATUSES.has(String(item.evidence_status) as LandingEvidenceStatus))
  ) return false;
  if (run.findings.length > 50) return false;
  const findingIds = new Set<string>();
  for (const rawFinding of run.findings) {
    const item = record(rawFinding);
    const evidenceRefs = list(item.evidence_refs);
    if (
      typeof item.finding_id !== "string" || !item.finding_id || item.finding_id.length > 255 || findingIds.has(item.finding_id)
      || !LANDING_ADVISORY_DIMENSIONS.includes(String(item.dimension) as LandingAdvisoryDimension)
      || !FINDING_TYPES.has(String(item.type) as LandingFindingType)
      || !EVIDENCE_STATUSES.has(String(item.evidence_status) as LandingEvidenceStatus)
      || (item.type === "LLM_HYPOTHESIS" && item.evidence_status !== "INSUFFICIENT_EVIDENCE")
      || !Number.isSafeInteger(item.priority) || Number(item.priority) < 0 || Number(item.priority) > 100
      || typeof item.title !== "string" || item.title.length > 520 || boundedArtifactText(item.title, 500) !== item.title
      || typeof item.detail !== "string" || item.detail.length > LANDING_DETAIL_MAX + 20 || boundedArtifactText(item.detail, LANDING_DETAIL_MAX) !== item.detail
      || evidenceRefs.length > 20
      || evidenceRefs.some((reference) => typeof reference !== "string" || reference.length > 275 || boundedArtifactText(reference, 255) !== reference)
    ) return false;
    findingIds.add(item.finding_id);
  }
  if (JSON.stringify(coverageFromFindings(run.findings as LandingFinding[])) !== JSON.stringify(run.coverage)) return false;
  const artifacts = run.artifacts.map(record);
  const expectedArtifacts = [
    ["artifact:page-observation", "PAGE_OBSERVATION"],
    ["artifact:lighthouse-summary", "LIGHTHOUSE_SUMMARY"],
    ["artifact:axe-summary", "AXE_SUMMARY"],
    ["artifact:metrika-summary", "METRIKA_SUMMARY"],
  ];
  if (
    new TextEncoder().encode(JSON.stringify(run.artifacts)).byteLength > LANDING_ARTIFACT_MAX_BYTES
    || ![0, 4].includes(artifacts.length)
    || (artifacts.length === 4 && artifacts.some((artifact, index) => (
      artifact.artifact_id !== expectedArtifacts[index][0]
      || artifact.kind !== expectedArtifacts[index][1]
      || !persistedArtifactValueIsSafe(artifact.value)
    )))
  ) return false;
  const lighthouse = record(run.lighthouse);
  const lighthouseRuns = list(lighthouse.runs).map(record);
  if (
    lighthouse.expected_runs !== 5
    || lighthouse.sequential !== true
    || lighthouse.aggregation !== "COMPONENT_MEDIAN_OF_EXACTLY_FIVE_NO_AVERAGING"
    || lighthouseRuns.length > 5
    || lighthouseRuns.some((item, index) => (
      item.sequence !== index + 1
      || !["SUCCEEDED", "FAILED"].includes(String(item.status))
      || (item.status === "SUCCEEDED" && (item.error_code !== null || !persistedLighthouseResultIsValid(item.result)))
      || (item.status === "FAILED" && (item.error_code !== "LIGHTHOUSE_RUN_FAILED" || item.result !== null))
    ))
    || (lighthouse.median !== null && !persistedLighthouseResultIsValid(lighthouse.median))
  ) return false;
  const reconstructedMedian = medianLighthouse(lighthouseRuns as unknown as LighthouseRun[]);
  if (JSON.stringify(reconstructedMedian) !== JSON.stringify(lighthouse.median)) return false;
  const tools = record(run.tools);
  const observedTools = record(tools.observed);
  if (
    JSON.stringify(tools.required) !== JSON.stringify(PINNED_LANDING_TOOL_VERSIONS)
    || Object.keys(PINNED_LANDING_TOOL_VERSIONS).some((name) => observedTools[name] !== null && (typeof observedTools[name] !== "string" || String(observedTools[name]).length > 100))
    || !["PINNED_MATCH", "PINNED_MISMATCH", "UNAVAILABLE"].includes(String(tools.version_status))
    || (tools.version_status === "PINNED_MATCH" && !exactPinnedVersions(record(tools.observed) as Record<string, string>))
  ) return false;
  const axe = record(run.axe);
  const axeCategories = record(axe.categories);
  const manualReview = record(axe.manual_review);
  const metrika = record(run.metrika);
  if (
    !["COLLECTED", "UNAVAILABLE"].includes(String(axe.status))
    || !["violations", "passes", "incomplete", "inapplicable"].every((name) => persistedAxeCategoryIsValid(axeCategories[name]))
    || typeof manualReview.required !== "boolean"
    || typeof manualReview.disclosure !== "string"
    || manualReview.disclosure.length > 520
    || boundedArtifactText(manualReview.disclosure, 500) !== manualReview.disclosure
    || manualReview.required !== (Number(record(axeCategories.incomplete).count) > 0 || axe.status === "UNAVAILABLE")
    || metrika.source !== "PERSISTED_ANALYTICS_EVIDENCE_ONLY"
    || metrika.browser_cabinet_used !== false
    || typeof metrika.counter_id !== "string" || metrika.counter_id.length > 120
    || typeof metrika.goal_id !== "string" || metrika.goal_id.length > 120
    || !["OBSERVED", "PARTIAL", "UNAVAILABLE"].includes(String(metrika.status))
    || !Array.isArray(metrika.evidence_ids) || metrika.evidence_ids.length > 20
    || metrika.evidence_ids.some((item) => typeof item !== "string" || item.length > 275 || boundedArtifactText(item, 255) !== item)
    || typeof metrika.sampling_disclosure !== "string" || metrika.sampling_disclosure.length > 520
    || boundedArtifactText(metrika.sampling_disclosure, 500) !== metrika.sampling_disclosure
  ) return false;
  if (artifacts.length === 4) {
    const page = record(artifacts[0].value);
    if (
      typeof page.title !== "string"
      || !Array.isArray(page.headings) || page.headings.length > 20
      || typeof page.text_excerpt !== "string"
      || !Array.isArray(page.ctas) || page.ctas.length > 20
      || !Array.isArray(page.forms) || page.forms.length > 20
      || ![true, false, null].includes(page.metrika_tag_detected as never)
      || !Number.isSafeInteger(page.http_status)
      || typeof page.content_type !== "string"
      || JSON.stringify(artifacts[1].value) !== JSON.stringify(run.lighthouse)
      || JSON.stringify(artifacts[2].value) !== JSON.stringify(run.axe)
      || JSON.stringify(artifacts[3].value) !== JSON.stringify(run.metrika)
    ) return false;
  }
  if (["COMPLETE", "COMPLETE_WITH_GAPS"].includes(String(run.status)) && (
    !run.final_url
    || browserSafety.safety_result !== "PASSED"
    || tools.version_status !== "PINNED_MATCH"
    || lighthouseRuns.length !== 5
    || artifacts.length !== 4
  )) return false;
  if (run.status === "COMPLETE" && (lighthouse.median === null || axe.status !== "COLLECTED")) return false;
  const expectedAdvisoryKey = `landing-advisory-key:${await sha256({
    strategy_revision_id: run.strategy_revision_id,
    final_url: run.final_url ?? run.requested_url,
  })}`;
  if (run.advisory_key !== expectedAdvisoryKey) return false;
  const expectedRunId = `landing-advisory:${await sha256(Object.fromEntries(Object.entries(run).filter(([key]) => key !== "run_id")))}`;
  return run.run_id === expectedRunId;
}

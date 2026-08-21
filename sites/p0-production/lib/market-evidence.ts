export const MARKET_EVIDENCE_CONTRACT = "demand-cost-packing-v1";
export const WORDSTAT_BATCH_SCHEMA = "wordstat-observation-batch-v1";
export const WORDSTAT_API_HOST = "api.wordstat.yandex.net";
export const WORDSTAT_ENDPOINTS = {
  top_requests: `https://${WORDSTAT_API_HOST}/v1/topRequests`,
  dynamics: `https://${WORDSTAT_API_HOST}/v1/dynamics`,
  regions: `https://${WORDSTAT_API_HOST}/v1/regions`,
} as const;

const WORDSTAT_METHODS = ["top_requests", "dynamics", "regions"] as const;
const WORDSTAT_DEVICES = new Set(["all", "desktop", "phone", "tablet"]);

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type WordstatMethod = typeof WORDSTAT_METHODS[number];
export type WordstatOperatorProfile = "BROAD_CONTAINING" | "FIXED_WORD_COUNT" | "FIXED_ORDER_FORM" | "DYNAMICS_BROAD";
export type WordstatSeed = {
  seed_id: string;
  cluster_id: string;
  phrase: string;
  dynamics_phrase: string;
  dynamics_period: "monthly" | "weekly" | "daily";
  dynamics_from_date: string;
  dynamics_to_date: string;
  operator_profile: Exclude<WordstatOperatorProfile, "DYNAMICS_BROAD">;
  region_ids: number[];
  region_names: string[];
  device: "all" | "desktop" | "phone" | "tablet";
};
export type WordstatCall = {
  call_id: string;
  batch_id: string;
  seed_id: string;
  cluster_id: string;
  method: WordstatMethod;
  endpoint: string;
  requested_at: string;
  status: "AVAILABLE" | "UNAVAILABLE";
  operator_profile: WordstatOperatorProfile;
  canonical_phrase: string;
  period: WordstatSeed["dynamics_period"] | null;
  from_date: string | null;
  to_date: string | null;
  scope: {
    region_ids: number[];
    region_names: string[];
    device: WordstatSeed["device"];
    region_filter_applied: boolean;
  };
  request_fingerprint: string;
  rows: Array<Record<string, unknown>>;
  gaps: Array<{ code: string; detail: string; retry_after_seconds: number | null }>;
};
export type WordstatObservationBatch = {
  schema_version: typeof WORDSTAT_BATCH_SCHEMA;
  source: "YANDEX_WORDSTAT_V1";
  batch_id: string;
  batch_started_at: string;
  batch_finished_at: string;
  declared_window: "rolling_last_30_days";
  source_window_end: "undisclosed_by_api";
  calls: WordstatCall[];
};

function normalizedText(value: unknown) {
  return String(value ?? "").normalize("NFKC").replace(/\s+/gu, " ").trim();
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => [key, canonicalize(item)]));
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

function finiteNonNegative(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function wordstatRows(method: WordstatMethod, payload: Record<string, unknown>) {
  const raw = method === "top_requests"
    ? payload.topRequests
    : method === "dynamics"
      ? payload.dynamics
      : payload.regions;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const rows = raw.slice(0, 50).map((item) => {
    const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
    if (method === "top_requests") {
      return { phrase: normalizedText(row.phrase), count: finiteNonNegative(row.count) };
    }
    if (method === "dynamics") {
      return {
        date: normalizedText(row.date),
        count: finiteNonNegative(row.count),
        share: finiteNonNegative(row.share),
      };
    }
    return {
      region_id: finiteNonNegative(row.regionId),
      region_name: normalizedText(row.regionName),
      count: finiteNonNegative(row.count),
      share: finiteNonNegative(row.share),
      affinity_index: finiteNonNegative(row.affinityIndex),
    };
  });
  const valid = rows.every((row) => method === "top_requests"
    ? Boolean(row.phrase) && row.count !== null
    : method === "dynamics"
      ? Boolean(row.date) && row.count !== null && row.share !== null
      : row.region_id !== null && Boolean(row.region_name) && row.count !== null && row.share !== null && row.affinity_index !== null);
  return valid ? rows : null;
}

function requestFor(method: WordstatMethod, seed: WordstatSeed) {
  if (method === "dynamics") {
    return {
      phrase: seed.dynamics_phrase,
      period: seed.dynamics_period,
      fromDate: seed.dynamics_from_date,
      toDate: seed.dynamics_to_date,
      regions: seed.region_ids,
      devices: [seed.device],
    };
  }
  if (method === "regions") return { phrase: seed.phrase, devices: [seed.device] };
  return { phrase: seed.phrase, regions: seed.region_ids, devices: [seed.device] };
}

function validateSeed(seed: WordstatSeed) {
  if (!normalizedText(seed.seed_id) || !normalizedText(seed.cluster_id) || !normalizedText(seed.phrase)) {
    throw new Error("Wordstat seed identity and phrase are required.");
  }
  if (!WORDSTAT_DEVICES.has(seed.device)) throw new Error("Wordstat device scope is invalid.");
  if (!seed.region_ids.length || seed.region_ids.some((item) => !Number.isSafeInteger(item) || item <= 0)) {
    throw new Error("Wordstat region scope must use explicit positive region IDs.");
  }
  if (seed.region_names.length !== seed.region_ids.length) throw new Error("Wordstat region names must map exactly to region IDs.");
  if (!normalizedText(seed.dynamics_phrase) || /[!"[\]()|]/u.test(seed.dynamics_phrase)) {
    throw new Error("Wordstat dynamics supports only the + operator profile.");
  }
  if (!Number.isFinite(Date.parse(seed.dynamics_from_date)) || !Number.isFinite(Date.parse(seed.dynamics_to_date))) {
    throw new Error("Wordstat dynamics requires an explicit valid date range.");
  }
}

function failureGap(status: number, retryAfter: string | null) {
  const retry = finiteNonNegative(retryAfter);
  if (status === 429) return { code: "WORDSTAT_QUOTA_EXHAUSTED", detail: "Personal Wordstat quota exhausted.", retry_after_seconds: retry };
  if (status === 503) return { code: "WORDSTAT_PROVIDER_UNAVAILABLE", detail: "Wordstat service quota or provider is unavailable.", retry_after_seconds: retry };
  return { code: "WORDSTAT_PROVIDER_ERROR", detail: `Wordstat API returned HTTP ${status}.`, retry_after_seconds: retry };
}

export async function collectOfficialWordstatBatch(
  input: { token: string; clientId: string; seeds: WordstatSeed[] },
  fetchImpl: FetchLike,
  now: () => string,
): Promise<WordstatObservationBatch> {
  const started = now();
  const seeds = [...input.seeds].sort((left, right) => left.seed_id.localeCompare(right.seed_id));
  seeds.forEach(validateSeed);
  const batchId = await sha256({ source: "YANDEX_WORDSTAT_V1", batch_started_at: started, seeds });
  const calls: WordstatCall[] = [];
  for (const seed of seeds) {
    for (const method of WORDSTAT_METHODS) {
      const endpoint = WORDSTAT_ENDPOINTS[method];
      const request = requestFor(method, seed);
      const requestedAt = now();
      const operatorProfile = method === "dynamics" ? "DYNAMICS_BROAD" : seed.operator_profile;
      const base = {
        call_id: `${batchId}:${seed.seed_id}:${method}`,
        batch_id: batchId,
        seed_id: seed.seed_id,
        cluster_id: seed.cluster_id,
        method,
        endpoint,
        requested_at: requestedAt,
        operator_profile: operatorProfile as WordstatOperatorProfile,
        canonical_phrase: method === "dynamics" ? seed.dynamics_phrase : seed.phrase,
        period: method === "dynamics" ? seed.dynamics_period : null,
        from_date: method === "dynamics" ? seed.dynamics_from_date : null,
        to_date: method === "dynamics" ? seed.dynamics_to_date : null,
        scope: {
          region_ids: [...seed.region_ids],
          region_names: [...seed.region_names],
          device: seed.device,
          region_filter_applied: method !== "regions",
        },
        request_fingerprint: await sha256({ endpoint, request, operator_profile: operatorProfile }),
      };
      if (!normalizedText(input.token) || !normalizedText(input.clientId)) {
        calls.push({ ...base, status: "UNAVAILABLE", rows: [], gaps: [{ code: "WORDSTAT_AUTHORITY_UNAVAILABLE", detail: "Wordstat server-side authority is not configured.", retry_after_seconds: null }] });
        continue;
      }
      try {
        const response = await fetchImpl(endpoint, {
          method: "POST",
          redirect: "error",
          headers: {
            Authorization: `Bearer ${input.token}`,
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify(request),
        });
        if (!response.ok) {
          calls.push({ ...base, status: "UNAVAILABLE", rows: [], gaps: [failureGap(response.status, response.headers.get("retry-after"))] });
          continue;
        }
        const payload = await response.json() as Record<string, unknown>;
        const rows = wordstatRows(method, payload);
        if (!rows || payload.error) {
          calls.push({ ...base, status: "UNAVAILABLE", rows: [], gaps: [{ code: "WORDSTAT_RESPONSE_PARTIAL", detail: `Wordstat ${method} rows are missing or invalid.`, retry_after_seconds: null }] });
          continue;
        }
        calls.push({ ...base, status: "AVAILABLE", rows, gaps: [] });
      } catch {
        calls.push({ ...base, status: "UNAVAILABLE", rows: [], gaps: [{ code: "WORDSTAT_PROVIDER_ERROR", detail: "Wordstat request failed closed.", retry_after_seconds: null }] });
      }
    }
  }
  return {
    schema_version: WORDSTAT_BATCH_SCHEMA,
    source: "YANDEX_WORDSTAT_V1",
    batch_id: batchId,
    batch_started_at: started,
    batch_finished_at: now(),
    declared_window: "rolling_last_30_days",
    source_window_end: "undisclosed_by_api",
    calls,
  };
}

export type DemandClusterSpec = {
  cluster_id: string;
  semantic_key: { product: string; need: string; intent: string; offer: string };
};

type DemandGap = { code: string; detail: string; retry_after_seconds: number | null };
type DemandScopeEvidence = {
  scope_fingerprint: string;
  operator_profile: WordstatOperatorProfile;
  region_ids: number[];
  region_names: string[];
  device: WordstatSeed["device"];
  observed_unique_count: { value: number | null; semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS" };
  unique_assigned_row_ids: string[];
};

type AssignedDemandRow = {  row_id: string;
  phrase: string;
  normalized_phrase: string;
  count: number;
  assigned_cluster_id: string;
  scope_fingerprint: string;
  provenance: { call_ids: string[]; seed_ids: string[]; request_fingerprints: string[] };
};

function normalizedPhrase(value: unknown) {
  return normalizedText(value).toLocaleLowerCase("ru-RU");
}

function tokenCount(value: string) {
  return normalizedPhrase(value).replace(/[^\p{L}\p{N}]+/gu, " ").split(" ").filter(Boolean).length;
}

function topScopeKey(call: WordstatCall) {
  return JSON.stringify({
    batch_id: call.batch_id,
    operator_profile: call.operator_profile,
    region_ids: [...call.scope.region_ids].sort((left, right) => left - right),
    device: call.scope.device,
  });
}

async function assignedRowsForScope(calls: WordstatCall[]) {
  const candidates = new Map<string, Array<{ call: WordstatCall; phrase: string; normalized: string; count: number }>>();
  for (const call of calls) {
    for (const row of call.rows) {
      const phrase = normalizedText(row.phrase);
      const normalized = normalizedPhrase(phrase);
      const count = finiteNonNegative(row.count);
      if (!phrase || count === null) continue;
      const values = candidates.get(normalized) ?? [];
      values.push({ call, phrase, normalized, count });
      candidates.set(normalized, values);
    }
  }
  const rows: AssignedDemandRow[] = [];
  const conflicts: DemandGap[] = [];
  for (const [normalized, observations] of [...candidates.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    const counts = [...new Set(observations.map((item) => item.count))];
    if (counts.length !== 1) {
      conflicts.push({ code: "WORDSTAT_ROW_COUNT_CONFLICT", detail: `Conflicting counts for normalized Wordstat row: ${normalized}.`, retry_after_seconds: null });
      continue;
    }
    const ranked = observations
      .map((item) => ({
        ...item,
        exact: normalized === normalizedPhrase(item.call.canonical_phrase),
        required_tokens: tokenCount(item.call.canonical_phrase),
      }))
      .sort((left, right) => Number(right.exact) - Number(left.exact)
        || right.required_tokens - left.required_tokens
        || left.call.cluster_id.localeCompare(right.call.cluster_id)
        || left.call.seed_id.localeCompare(right.call.seed_id));
    const assigned = ranked[0];
    const scopeFingerprint = await sha256(JSON.parse(topScopeKey(assigned.call)));
    rows.push({
      row_id: `wordstat-row:${(await sha256({ scope: scopeFingerprint, normalized_phrase: normalized })).slice("sha256:".length)}`,
      phrase: observations.map((item) => item.phrase).sort()[0],
      normalized_phrase: normalized,
      count: counts[0],
      assigned_cluster_id: assigned.call.cluster_id,
      scope_fingerprint: scopeFingerprint,
      provenance: {
        call_ids: [...new Set(observations.map((item) => item.call.call_id))].sort(),
        seed_ids: [...new Set(observations.map((item) => item.call.seed_id))].sort(),
        request_fingerprints: [...new Set(observations.map((item) => item.call.request_fingerprint))].sort(),
      },
    });
  }
  return { rows, conflicts };
}

export async function buildScopedDemandEvidence(batch: WordstatObservationBatch, clusterSpecs: DemandClusterSpec[]) {
  const topCalls = batch.calls.filter((call) => call.method === "top_requests");
  const availableTopCalls = topCalls.filter((call) => call.status === "AVAILABLE");
  const gaps: DemandGap[] = batch.calls.flatMap((call) => call.gaps);
  const byScope = Map.groupBy(availableTopCalls, topScopeKey);
  const scopes: DemandScopeEvidence[] = [];
  const allRows: AssignedDemandRow[] = [];
  for (const [scopeKey, calls] of [...byScope.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    const { rows, conflicts } = await assignedRowsForScope(calls);
    gaps.push(...conflicts);
    const scope = JSON.parse(scopeKey) as Record<string, unknown>;
    const first = calls[0];
    const value = rows.reduce((sum, row) => sum + row.count, 0);
    scopes.push({
      scope_fingerprint: rows[0]?.scope_fingerprint ?? await sha256(scope),
      operator_profile: first.operator_profile,
      region_ids: first.scope.region_ids,
      region_names: first.scope.region_names,
      device: first.scope.device,
      observed_unique_count: { value: rows.length ? value : null, semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS" },
      unique_assigned_row_ids: rows.map((row) => row.row_id),
    });
    allRows.push(...rows);
  }
  const multipleScopes = scopes.length > 1;
  if (multipleScopes) gaps.push({
    code: "INCOMPARABLE_WORDSTAT_SCOPES",
    detail: "Operator, region or device scopes differ and are disclosed separately rather than added.",
    retry_after_seconds: null,
  });
  const unavailableTop = topCalls.length - availableTopCalls.length;
  const status = availableTopCalls.length === 0
    ? "UNAVAILABLE"
    : unavailableTop > 0 || multipleScopes || gaps.some((gap) => gap.code === "WORDSTAT_ROW_COUNT_CONFLICT")
      ? "PARTIAL"
      : "AVAILABLE";
  const clusterIds = new Set(clusterSpecs.map((cluster) => cluster.cluster_id));
  const clusters = clusterSpecs
    .map((cluster) => {
      const rows = allRows.filter((row) => row.assigned_cluster_id === cluster.cluster_id);
      return {
        cluster_id: cluster.cluster_id,
        semantic_key: cluster.semantic_key,
        status: rows.length ? status : "PARTIAL",
        assigned_row_ids: rows.map((row) => row.row_id).sort(),
        observed_unique_count: {
          value: rows.length ? rows.reduce((sum, row) => sum + row.count, 0) : null,
          semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS",
        },
      };
    })
    .sort((left, right) => left.cluster_id.localeCompare(right.cluster_id));
  const unknownAssignments = allRows.filter((row) => !clusterIds.has(row.assigned_cluster_id));
  if (unknownAssignments.length) gaps.push({
    code: "WORDSTAT_CLUSTER_ASSIGNMENT_UNKNOWN",
    detail: `${unknownAssignments.length} Wordstat rows reference an unknown Demand Cluster.`,
    retry_after_seconds: null,
  });
  const seedMatchedRowCounts = topCalls
    .map((call) => {
      const matched = call.status === "AVAILABLE"
        ? call.rows.find((row) => normalizedPhrase(row.phrase) === normalizedPhrase(call.canonical_phrase))
        : undefined;
      const value = matched ? finiteNonNegative(matched.count) : null;
      return {
        seed_id: call.seed_id,
        cluster_id: call.cluster_id,
        value,
        status: value === null ? "UNAVAILABLE" : "AVAILABLE",
        call_id: call.call_id,
      };
    })
    .sort((left, right) => left.seed_id.localeCompare(right.seed_id));
  const dynamics = batch.calls.filter((call) => call.method === "dynamics");
  const regions = batch.calls.filter((call) => call.method === "regions");
  return {
    status,
    source: "YANDEX_WORDSTAT_V1",
    method: "/v1/topRequests",
    snapshot_batch_id: batch.batch_id,
    batch_started_at: batch.batch_started_at,
    batch_finished_at: batch.batch_finished_at,
    declared_window: batch.declared_window,
    source_window_end: batch.source_window_end,
    canonical_phrases: topCalls.map((call) => call.canonical_phrase),
    observed_unique_count: {
      value: status === "UNAVAILABLE" || multipleScopes || scopes.length !== 1 ? null : scopes[0].observed_unique_count.value,
      semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS",
    },
    semantics: {
      lower_bound: true,
      counts_are_queries_not_users_clicks_or_impressions: true,
      unique_assignment_rule: "exact canonical seed; required token count; stable cluster_id",
    },
    scopes,
    unique_assigned_rows: allRows.sort((left, right) => left.row_id.localeCompare(right.row_id)),
    seed_matched_row_counts: seedMatchedRowCounts,
    clusters,
    seasonality: {
      status: dynamics.every((call) => call.status === "AVAILABLE") && dynamics.length ? "AVAILABLE" : "UNAVAILABLE",
      source: "/v1/dynamics",
      operator_profile: "DYNAMICS_BROAD",
      observations: dynamics.map((call) => ({
        call_id: call.call_id,
        scope: call.scope,
        period: call.period,
        from_date: call.from_date,
        to_date: call.to_date,
        rows: call.rows,
        gaps: call.gaps,
      })),
    },
    geo_evidence: {
      status: regions.every((call) => call.status === "AVAILABLE") && regions.length ? "AVAILABLE" : "UNAVAILABLE",
      source: "/v1/regions",
      observations: regions.map((call) => ({ call_id: call.call_id, scope: call.scope, rows: call.rows, gaps: call.gaps })),
    },
    gaps,
  };
}

export type CostSource = "LEGACY_LIVE4_SCENARIO" | "KEYWORDBIDS_V5_CURRENT_PROXY" | "DIRECT_HISTORY_OWN_EMPIRICAL";
export type CostObservation = {
  observation_id: string;
  source: CostSource;
  status: "AVAILABLE" | "UNAVAILABLE";
  scenario: string;
  scope: Record<string, unknown>;
  as_of: string;
  currency: string;
  vat_treatment: "INCLUDED" | "EXCLUDED" | "NOT_APPLICABLE" | "UNKNOWN";
  sample_size: { unit: string; value: number };
  range: { low: number; high: number; kind: "SCENARIO" | "EMPIRICAL_IQR" } | null;
  qualification: Record<string, unknown>;
  unavailable_reason?: string;
  capacity?: { forecast_clicks: number; forecast_total_spend: number };
};

const COST_PRECEDENCE: CostSource[] = [
  "LEGACY_LIVE4_SCENARIO",
  "KEYWORDBIDS_V5_CURRENT_PROXY",
  "DIRECT_HISTORY_OWN_EMPIRICAL",
];

function sameOrMapped(value: unknown) {
  return value === "SAME" || value === "MAPPED";
}

function commonCostQualification(observation: CostObservation) {
  const range = observation.range;
  return observation.status === "AVAILABLE"
    && Boolean(normalizedText(observation.observation_id))
    && Boolean(normalizedText(observation.scenario))
    && Object.keys(observation.scope ?? {}).length > 0
    && Number.isFinite(Date.parse(observation.as_of))
    && Boolean(normalizedText(observation.currency))
    && ["INCLUDED", "EXCLUDED", "NOT_APPLICABLE", "UNKNOWN"].includes(observation.vat_treatment)
    && Number.isFinite(observation.sample_size?.value)
    && observation.sample_size.value > 0
    && Boolean(normalizedText(observation.sample_size?.unit))
    && Boolean(range)
    && Number.isFinite(range?.low)
    && Number.isFinite(range?.high)
    && Number(range?.low) >= 0
    && Number(range?.high) >= Number(range?.low);
}

function qualifiedCost(observation: CostObservation) {
  if (!commonCostQualification(observation)) return false;
  if (observation.source === "LEGACY_LIVE4_SCENARIO") {
    return observation.qualification.account_specific === true
      && observation.qualification.capability_status === "AVAILABLE"
      && observation.qualification.exact_scope === true;
  }
  if (observation.source === "KEYWORDBIDS_V5_CURRENT_PROXY") {
    return observation.qualification.current === true
      && observation.qualification.existing_comparable_keyword === true
      && observation.scope.phrase === "EXACT"
      && sameOrMapped(observation.scope.geography)
      && observation.scope.placement === "SAME"
      && observation.scope.strategy === "SAME"
      && observation.scope.season === "SAME"
      && Boolean(normalizedText(observation.scope.keyword_id));
  }
  return observation.qualification.first_party === true
    && Number(observation.qualification.clicks) > 0
    && ["EXACT", "CLUSTER"].includes(String(observation.scope.phrase))
    && sameOrMapped(observation.scope.geography)
    && observation.scope.placement === "SAME"
    && observation.scope.strategy === "SAME"
    && observation.scope.season === "SAME";
}

function costReason(observation: CostObservation) {
  if (observation.unavailable_reason) return normalizedText(observation.unavailable_reason);
  return `${observation.source}_NOT_QUALIFIED:${normalizedText(observation.observation_id) || "unknown"}`;
}

export function selectCostEvidence(rawObservations: CostObservation[]) {
  const observations = [...rawObservations].sort((left, right) => left.source.localeCompare(right.source)
    || right.as_of.localeCompare(left.as_of)
    || left.observation_id.localeCompare(right.observation_id));
  let selected: CostObservation | null = null;
  for (const source of COST_PRECEDENCE) {
    selected = observations
      .filter((observation) => observation.source === source && qualifiedCost(observation))
      .sort((left, right) => right.as_of.localeCompare(left.as_of) || left.observation_id.localeCompare(right.observation_id))[0] ?? null;
    if (selected) break;
  }
  const missingReasons = observations.filter((observation) => !qualifiedCost(observation)).map(costReason);
  if (!selected) {
    if (!observations.length) missingReasons.push("NO_QUALIFIED_PRELAUNCH_COST_SOURCE");
    return {
      status: "UNAVAILABLE" as const,
      compact_source: null,
      scenario: null,
      scope: null,
      as_of: null,
      currency: null,
      vat_treatment: null,
      sample_size: null,
      range: null,
      aggregation: "FIRST_QUALIFIED_SOURCE_NO_AVERAGING" as const,
      observations,
      missing_or_conflict_reasons: [...new Set(missingReasons)],
    };
  }
  return {
    status: "AVAILABLE" as const,
    compact_source: selected.source,
    scenario: selected.scenario,
    scope: selected.scope,
    as_of: selected.as_of,
    currency: selected.currency,
    vat_treatment: selected.vat_treatment,
    sample_size: selected.sample_size,
    range: selected.range,
    aggregation: "FIRST_QUALIFIED_SOURCE_NO_AVERAGING" as const,
    observations,
    missing_or_conflict_reasons: [...new Set(missingReasons)],
  };
}

export type DemandRelationshipState = "EXACT_DUPLICATE" | "NEAR_DUPLICATE" | "ALREADY_COVERED_DEMAND" | "OVERLAP_RISK" | "OBSERVED_CANNIBALIZATION" | "UNKNOWN";

export function classifyDemandRelationship(input: {
  left: string;
  right: string;
  near_duplicate?: boolean;
  already_covered?: boolean;
  overlap_signal?: boolean;
  observed_cannibalization?: {
    first_party?: boolean;
    evidence_id?: string;
    period_from?: string;
    period_to?: string;
    metric?: string;
  };
}) {
  const observed = input.observed_cannibalization;
  const observedQualified = observed?.first_party === true
    && Boolean(normalizedText(observed.evidence_id))
    && Number.isFinite(Date.parse(String(observed.period_from)))
    && Number.isFinite(Date.parse(String(observed.period_to)))
    && Boolean(normalizedText(observed.metric));
  let state: DemandRelationshipState = "UNKNOWN";
  if (observedQualified) state = "OBSERVED_CANNIBALIZATION";
  else if (normalizedPhrase(input.left) === normalizedPhrase(input.right)) state = "EXACT_DUPLICATE";
  else if (input.near_duplicate === true) state = "NEAR_DUPLICATE";
  else if (input.already_covered === true) state = "ALREADY_COVERED_DEMAND";
  else if (input.overlap_signal === true) state = "OVERLAP_RISK";
  return {
    state,
    query_overlap_proves_cannibalization: false,
    observed_evidence_id: state === "OBSERVED_CANNIBALIZATION" ? observed?.evidence_id : null,
  };
}

export type DeliveryKeyInput = {
  goal: unknown;
  economics: unknown;
  geography: unknown;
  landing: unknown;
  message: unknown;
  management: unknown;
};

function normalizedDimension(value: unknown) {
  if (value && typeof value === "object") return JSON.stringify(canonicalize(value)).toLocaleLowerCase("ru-RU");
  return normalizedPhrase(value);
}

function normalizedLanding(value: unknown) {
  try {
    const url = new URL(normalizedText(value));
    if (url.protocol !== "https:") return normalizedDimension(value);
    url.hostname = url.hostname.toLowerCase();
    url.hash = "";
    url.searchParams.sort();
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/+$/u, "");
    return url.toString().replace(/\/$/u, "");
  } catch {
    return normalizedDimension(value);
  }
}

export function normalizeDeliveryKey(input: DeliveryKeyInput) {
  return {
    goal: normalizedDimension(input.goal),
    economics: normalizedDimension(input.economics),
    geography: normalizedDimension(input.geography),
    landing: normalizedLanding(input.landing),
    message: normalizedDimension(input.message),
    management: normalizedDimension(input.management),
  };
}

export type PackableDemandCluster = {
  cluster_id: string;
  primary?: boolean;
  demand_status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE";
  unique_publish_row_ids: string[];
  delivery_key: DeliveryKeyInput;
  provisional_monthly_budget: number;
  relationship_state?: DemandRelationshipState;
  capacity?: {
    status: "AVAILABLE" | "UNAVAILABLE";
    source: "LEGACY_LIVE4_SCENARIO" | "OWN_CALIBRATED_VOLUME_MODEL" | "KEYWORDBIDS_V5_CURRENT_PROXY" | null;
    forecast_clicks?: number;
    forecast_total_spend?: number;
  };
};

function capacityDecision(cluster: PackableDemandCluster) {
  const capacity = cluster.capacity;
  if (!capacity || capacity.status !== "AVAILABLE") return { supported: false, sufficient: false, reason: "STANDALONE_CAPACITY_UNAVAILABLE" };
  if (!(["LEGACY_LIVE4_SCENARIO", "OWN_CALIBRATED_VOLUME_MODEL"] as unknown[]).includes(capacity.source)) {
    return { supported: false, sufficient: false, reason: "CAPACITY_SOURCE_NOT_QUALIFIED" };
  }
  const clicks = Number(capacity.forecast_clicks);
  const spend = Number(capacity.forecast_total_spend);
  if (!Number.isFinite(clicks) || !Number.isFinite(spend)) return { supported: false, sufficient: false, reason: "STANDALONE_CAPACITY_UNAVAILABLE" };
  return {
    supported: true,
    sufficient: clicks > 0 && spend >= Number(cluster.provisional_monthly_budget),
    reason: clicks > 0 && spend >= Number(cluster.provisional_monthly_budget)
      ? "EVIDENCE_BACKED_STANDALONE_CAPACITY"
      : "INSUFFICIENT_STANDALONE_CAPACITY",
  };
}

export async function packDemandClusters(input: PackableDemandCluster[]) {
  const clusters = [...input].sort((left, right) => left.cluster_id.localeCompare(right.cluster_id));
  const prepared = await Promise.all(clusters.map(async (cluster) => {
    const deliveryKey = normalizeDeliveryKey(cluster.delivery_key);
    return { ...cluster, normalized_delivery_key: deliveryKey, fingerprint: await sha256(deliveryKey) };
  }));
  const eligibleForGroups = prepared.filter((cluster) => cluster.demand_status !== "UNAVAILABLE"
    && cluster.unique_publish_row_ids.length > 0
    && !["EXACT_DUPLICATE", "NEAR_DUPLICATE", "ALREADY_COVERED_DEMAND"].includes(cluster.relationship_state ?? "UNKNOWN"));
  const byKey = Map.groupBy(eligibleForGroups, (cluster) => cluster.fingerprint);
  const groups = [...byKey.entries()].sort(([left], [right]) => left.localeCompare(right));
  const explicitPrimary = prepared.find((cluster) => cluster.primary);
  const primaryFingerprint = explicitPrimary?.fingerprint ?? groups[0]?.[0] ?? null;
  const deliveryBuckets: Array<Record<string, unknown>> = [];
  const clusterDispositions: Record<string, { disposition: "PACKED" | "STANDALONE" | "HIDDEN" | "EVIDENCE_GAP"; reason_codes: string[]; delivery_bucket_id: string | null }> = {};

  for (const cluster of prepared) {
    if (cluster.demand_status === "UNAVAILABLE") {
      clusterDispositions[cluster.cluster_id] = { disposition: "EVIDENCE_GAP", reason_codes: ["DEMAND_EVIDENCE_UNAVAILABLE"], delivery_bucket_id: null };
    } else if (!cluster.unique_publish_row_ids.length || ["EXACT_DUPLICATE", "NEAR_DUPLICATE", "ALREADY_COVERED_DEMAND"].includes(cluster.relationship_state ?? "UNKNOWN")) {
      clusterDispositions[cluster.cluster_id] = { disposition: "HIDDEN", reason_codes: ["DUPLICATE_OR_ALREADY_COVERED"], delivery_bucket_id: null };
    }
  }

  for (const [fingerprint, group] of groups) {
    const clusterIds = group.map((cluster) => cluster.cluster_id).sort();
    const bucketId = `delivery-bucket:${fingerprint.slice("sha256:".length, "sha256:".length + 20)}`;
    if (fingerprint === primaryFingerprint) {
      deliveryBuckets.push({
        delivery_bucket_id: bucketId,
        delivery_key: group[0].normalized_delivery_key,
        delivery_key_fingerprint: fingerprint,
        demand_cluster_ids: clusterIds,
        disposition: "PACKED",
        reason_codes: [clusterIds.length > 1 ? "COMPATIBLE_LONG_TAIL_PACKED" : "PRIMARY_DELIVERY_BUCKET"],
      });
      for (const cluster of group) clusterDispositions[cluster.cluster_id] = { disposition: "PACKED", reason_codes: ["DELIVERY_KEY_COMPATIBLE"], delivery_bucket_id: bucketId };
      continue;
    }
    const capacity = capacityDecision(group[0]);
    if (capacity.supported && capacity.sufficient) {
      deliveryBuckets.push({
        delivery_bucket_id: bucketId,
        delivery_key: group[0].normalized_delivery_key,
        delivery_key_fingerprint: fingerprint,
        demand_cluster_ids: clusterIds,
        disposition: "STANDALONE",
        reason_codes: [capacity.reason],
      });
      for (const cluster of group) clusterDispositions[cluster.cluster_id] = { disposition: "STANDALONE", reason_codes: ["MATERIAL_DELIVERY_KEY_DIFFERENCE", capacity.reason], delivery_bucket_id: bucketId };
    } else {
      const disposition = capacity.supported ? "HIDDEN" : "EVIDENCE_GAP";
      for (const cluster of group) clusterDispositions[cluster.cluster_id] = {
        disposition,
        reason_codes: ["MATERIAL_DELIVERY_KEY_DIFFERENCE", capacity.reason],
        delivery_bucket_id: null,
      };
    }
  }
  return {
    contract_version: "delivery-packing-v1",
    delivery_buckets: deliveryBuckets.sort((left, right) => String(left.delivery_bucket_id).localeCompare(String(right.delivery_bucket_id))),
    cluster_dispositions: Object.fromEntries(Object.entries(clusterDispositions).sort(([left], [right]) => left.localeCompare(right))),
    semantics: {
      full_delivery_key: ["goal", "economics", "geography", "landing", "message", "management"],
      compatible_long_tail_suppressed: false,
      split_requires_material_difference_and_evidence_backed_capacity: true,
    },
  };
}

export type MarketEvidenceInput = {
  wordstat_batch: WordstatObservationBatch;
  demand_clusters: DemandClusterSpec[];
  cost_observations: CostObservation[];
  relationship_observations?: Array<ReturnType<typeof classifyDemandRelationship> & { left_cluster_id: string; right_cluster_id: string }>;
};

function containsSensitiveMarketInput(value: unknown): boolean {
  if (typeof value === "string") return /(?:Bearer|OAuth|Api-Key)\s+[^\s,;]+/iu.test(value);
  if (Array.isArray(value)) return value.some(containsSensitiveMarketInput);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) =>
    /(?:authorization|cookie|credential|oauth|token|password|passwd|secret|api[_-]?key)/iu.test(key)
    || containsSensitiveMarketInput(item));
}

export async function buildMarketEvidence(input: MarketEvidenceInput) {
  if (containsSensitiveMarketInput(input)) throw new Error("Market evidence contains credential-bearing input and cannot be persisted.");
  const frequency = await buildScopedDemandEvidence(input.wordstat_batch, input.demand_clusters);
  const cost = selectCostEvidence(input.cost_observations ?? []);
  const relationshipAssessments = input.relationship_observations?.length
    ? input.relationship_observations
    : input.demand_clusters.map((cluster) => ({
        left_cluster_id: cluster.cluster_id,
        right_cluster_id: "current-direct-demand",
        ...classifyDemandRelationship({ left: cluster.cluster_id, right: "current-direct-demand" }),
      }));
  return {
    contract_version: MARKET_EVIDENCE_CONTRACT,
    snapshot_batch_id: input.wordstat_batch.batch_id,
    batch_started_at: input.wordstat_batch.batch_started_at,
    batch_finished_at: input.wordstat_batch.batch_finished_at,
    frequency,
    cost,
    overlap: {
      taxonomy: [
        "EXACT_DUPLICATE",
        "NEAR_DUPLICATE",
        "ALREADY_COVERED_DEMAND",
        "OVERLAP_RISK",
        "OBSERVED_CANNIBALIZATION",
        "UNKNOWN",
      ] as DemandRelationshipState[],
      assessments: [...relationshipAssessments].sort((left, right) => left.left_cluster_id.localeCompare(right.left_cluster_id)
        || left.right_cluster_id.localeCompare(right.right_cluster_id)),
      query_overlap_proves_cannibalization: false,
    },
    packing: {
      status: "AWAITING_APPROVED_CAMPAIGN_STRATEGY" as const,
      demand_cluster_ids: input.demand_clusters.map((cluster) => cluster.cluster_id).sort(),
      delivery_key_dimensions: ["goal", "economics", "geography", "landing", "message", "management"],
      policy: "Compatible long-tail is packed; material split requires evidence-backed standalone capacity.",
    },
  };
}

export async function unavailableWordstatBatch(reason: string, generatedAt: string): Promise<WordstatObservationBatch> {
  const batchId = await sha256({ source: "YANDEX_WORDSTAT_V1", generated_at: generatedAt, unavailable: normalizedText(reason) });
  return {
    schema_version: WORDSTAT_BATCH_SCHEMA,
    source: "YANDEX_WORDSTAT_V1",
    batch_id: batchId,
    batch_started_at: generatedAt,
    batch_finished_at: generatedAt,
    declared_window: "rolling_last_30_days",
    source_window_end: "undisclosed_by_api",
    calls: [{
      call_id: `${batchId}:unavailable:top_requests`,
      batch_id: batchId,
      seed_id: "unavailable",
      cluster_id: "unavailable",
      method: "top_requests",
      endpoint: WORDSTAT_ENDPOINTS.top_requests,
      requested_at: generatedAt,
      status: "UNAVAILABLE",
      operator_profile: "BROAD_CONTAINING",
      canonical_phrase: "",
      period: null,
      from_date: null,
      to_date: null,
      scope: { region_ids: [], region_names: [], device: "all", region_filter_applied: true },
      request_fingerprint: await sha256({ endpoint: WORDSTAT_ENDPOINTS.top_requests, unavailable: true }),
      rows: [],
      gaps: [{ code: "WORDSTAT_AUTHORITY_UNAVAILABLE", detail: normalizedText(reason) || "Wordstat evidence unavailable.", retry_after_seconds: null }],
    }],
  };
}

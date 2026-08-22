import JSONbigFactory from "json-bigint";

import { fingerprintDirectProjection } from "./campaign-fanout.ts";
import {
  createSuspendedCampaign,
  DirectWriteError,
  type DirectConfig,
  type DirectProjection,
  type DirectRecovery,
} from "./direct-write.ts";

const JSONbig = JSONbigFactory({ useNativeBigInt: true });

const EXECUTION_SCHEMA = "p0-direct-single-campaign-execution-v1";
const MUTATION_OPERATIONS = new Set([
  "campaigns.add",
  "campaigns.suspend",
  "adgroups.add",
  "keywords.add",
  "ads.add",
  "ads.moderate",
]);
const TERMINAL_SUCCESS = new Set(["MODERATION_PENDING", "READY_TO_LAUNCH", "REJECTED_NEEDS_EDIT"]);
const TERMINAL_FAILURE = new Set(["PROVIDER_REJECTED", "SYSTEM_FAILED"]);
const MUTATION_COMPLETION_PROGRESS: Record<string, string> = {
  "campaigns.add": "CAMPAIGN_CREATED",
  "campaigns.suspend": "NON_SERVING_CONFIRMED",
  "adgroups.add": "AD_GROUP_CREATED",
  "keywords.add": "KEYWORD_CREATED",
  "ads.add": "AD_CREATED",
  "ads.moderate": "MODERATION_SUBMITTED",
};

export type DirectExecutionAuthority = {
  direct_account_binding: {
    source_kind: "YANDEX_DIRECT_API_V501";
    account: string;
    client_id: string;
    verified: true;
  };
  direct_capability_snapshot: Record<string, unknown>;
  capability_profile: Record<string, unknown>;
  publish_fingerprint: string;
  publication_blockers: unknown[];
};

export type DirectExecutionIdentity = {
  execution_id: string;
  account: string;
  publish_fingerprint: string;
  capability_profile_id: string;
  capability_profile_version: string;
};

export type DirectDispatchIntent = {
  operation: string;
  request_fingerprint: string;
  request_json: string;
  dispatched_at: string;
};

export type DirectExecutionRecord = DirectExecutionIdentity & {
  schema_version: typeof EXECUTION_SCHEMA;
  status: string;
  lock_state: "HELD" | "RELEASED";
  provider_ids: {
    campaign_id: string | null;
    ad_group_id: string | null;
    keyword_id: string | null;
    ad_ids: string[];
  };
  completed_steps: string[];
  pending_dispatch: DirectDispatchIntent | null;
  result: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export interface DirectExecutionJournal {
  acquire(identity: DirectExecutionIdentity): Promise<DirectExecutionRecord | null>;
  save(record: DirectExecutionRecord): Promise<void>;
  release(identity: DirectExecutionIdentity): Promise<void>;
  hold(identity: DirectExecutionIdentity): Promise<void>;
}

export type SafeSingleCampaignExecutionInput = {
  execution_id: string;
  config: DirectConfig;
  projection: DirectProjection;
  authority: DirectExecutionAuthority;
  journal: DirectExecutionJournal;
  fetcher?: typeof fetch;
  now?: () => string;
};

function valueRecord(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function exactKeys(value: unknown, expected: string[]) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return JSON.stringify(Object.keys(value as Record<string, unknown>).sort())
    === JSON.stringify([...expected].sort());
}

function requiredText(value: unknown) {
  return typeof value === "string" && value.trim().length > 0;
}

function projectionShapeIsComplete(projection: DirectProjection) {
  const direct = valueRecord(projection.direct);
  const campaign = valueRecord(direct.campaign);
  const unifiedCampaign = valueRecord(campaign.UnifiedCampaign);
  const bidding = valueRecord(unifiedCampaign.BiddingStrategy);
  const search = valueRecord(bidding.Search);
  const placementTypes = valueRecord(search.PlacementTypes);
  const maximumClicks = valueRecord(search.WbMaximumClicks);
  const network = valueRecord(bidding.Network);
  const adGroup = valueRecord(direct.ad_group);
  const negativeKeywords = valueRecord(adGroup.NegativeKeywords);
  const unifiedAdGroup = valueRecord(adGroup.UnifiedAdGroup);
  const keyword = valueRecord(direct.keyword);
  const ad = valueRecord(direct.ad);
  const textAd = valueRecord(ad.TextAd);
  const lineage = valueRecord(projection.lineage);
  const amount = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
  const textArray = (value: unknown) => Array.isArray(value)
    && value.length > 0
    && value.every(requiredText);
  const idArray = (value: unknown) => Array.isArray(value)
    && value.length > 0
    && value.every((item) => Number.isSafeInteger(item) && Number(item) > 0);

  return projection.schema_version === "p0-direct-projection-v3"
    && exactKeys(direct, ["campaign", "ad_group", "keyword", "ad"])
    && exactKeys(campaign, ["Name", "StartDate", "EndDate", "UnifiedCampaign"])
    && exactKeys(unifiedCampaign, ["BiddingStrategy"])
    && exactKeys(bidding, ["Search", "Network"])
    && exactKeys(search, ["BiddingStrategyType", "PlacementTypes", "WbMaximumClicks"])
    && exactKeys(placementTypes, ["SearchResults", "ProductGallery"])
    && exactKeys(maximumClicks, ["WeeklySpendLimit", "BidCeiling"])
    && exactKeys(network, ["BiddingStrategyType"])
    && exactKeys(adGroup, ["Name", "RegionIds", "NegativeKeywords", "UnifiedAdGroup"])
    && exactKeys(negativeKeywords, ["Items"])
    && exactKeys(unifiedAdGroup, ["OfferRetargeting"])
    && exactKeys(keyword, ["Keyword"])
    && exactKeys(ad, ["TextAd"])
    && exactKeys(textAd, ["Title", "Text", "Href", "Mobile"])
    && ["strategy_revision_id", "draft_id", "draft_revision_id", "capability_profile_id", "capability_profile_version"]
      .every((key) => requiredText(lineage[key]))
    && [campaign.Name, campaign.StartDate, campaign.EndDate, adGroup.Name, keyword.Keyword, textAd.Title, textAd.Text, textAd.Href]
      .every(requiredText)
    && idArray(adGroup.RegionIds)
    && textArray(negativeKeywords.Items)
    && amount(maximumClicks.WeeklySpendLimit)
    && amount(maximumClicks.BidCeiling)
    && search.BiddingStrategyType === "WB_MAXIMUM_CLICKS"
    && placementTypes.SearchResults === "YES"
    && placementTypes.ProductGallery === "NO"
    && network.BiddingStrategyType === "SERVING_OFF"
    && unifiedAdGroup.OfferRetargeting === "NO"
    && textAd.Mobile === "NO";
}

function capabilityMatchesCore(
  config: DirectConfig,
  projection: DirectProjection,
  authority: DirectExecutionAuthority,
) {
  const binding = authority.direct_account_binding;
  const snapshot = valueRecord(authority.direct_capability_snapshot);
  const profile = valueRecord(authority.capability_profile);
  const lineage = valueRecord(projection.lineage);
  const criteria = Array.isArray(profile.criteria) ? profile.criteria.map(String) : [];
  const conditionalNotEnabled = Array.isArray(profile.conditional_not_enabled)
    ? profile.conditional_not_enabled.map(String).sort()
    : [];
  return binding.source_kind === "YANDEX_DIRECT_API_V501"
    && binding.verified === true
    && requiredText(binding.client_id)
    && binding.account === config.account
    && snapshot.schema_version === "direct-account-capability-snapshot-v1"
    && snapshot.snapshot_id
    && snapshot.source === "YANDEX_DIRECT_API_V501"
    && snapshot.account === binding.account
    && snapshot.api_version === "v501"
    && snapshot.archived === "NO"
    && snapshot.edit_campaigns_grant === "YES"
    && Array.isArray(snapshot.available_campaign_types)
    && snapshot.available_campaign_types.includes("UNIFIED_CAMPAIGN")
    && profile.profile_id === "direct-v501-unified-search-explicit-text"
    && profile.profile_version === "1.0.0"
    && (profile.endpoint_version ?? profile.api_version) === "v501"
    && profile.campaign_type === "UNIFIED_CAMPAIGN"
    && profile.ad_group_type === "UNIFIED_AD_GROUP"
    && profile.search_strategy === "WB_MAXIMUM_CLICKS"
    && profile.network_strategy === "SERVING_OFF"
    && criteria.length === 1
    && criteria[0] === "EXPLICIT_KEYWORDS"
    && profile.ad_type === "TEXT_AD"
    && JSON.stringify(conditionalNotEnabled) === JSON.stringify(["AUTOTARGETING", "NETWORK", "PRODUCT_GALLERY", "SITELINKS"])
    && lineage.capability_profile_id === profile.profile_id
    && lineage.capability_profile_version === profile.profile_version;
}

async function sha256Text(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

async function validatePreflight(input: SafeSingleCampaignExecutionInput) {
  if (!requiredText(input.execution_id)) {
    throw new DirectWriteError("P0_EXECUTION_ID_INVALID", "Single-campaign execution ID отсутствует.");
  }
  if (!input.config.token || !input.config.account) {
    throw new DirectWriteError("P0_WRITE_CREDENTIAL_MISSING", "Direct production credentials не настроены.");
  }
  if (!Array.isArray(input.authority.publication_blockers) || input.authority.publication_blockers.length > 0) {
    throw new DirectWriteError("P0_PUBLICATION_BLOCKED", "Campaign Draft содержит publication blockers.");
  }
  if (!projectionShapeIsComplete(input.projection)) {
    throw new DirectWriteError(
      "P0_PROJECTION_INCOMPLETE",
      "Exact Direct projection неполна, содержит неизвестное selected field или не соответствует core profile.",
    );
  }
  if (
    input.projection.safety.must_end_non_serving !== true
    || input.projection.safety.resume_allowed !== false
    || input.projection.safety.network_serving !== false
  ) {
    throw new DirectWriteError("P0_PROJECTION_UNSAFE", "Campaign Draft нарушает обязательный safety-контракт.");
  }
  if (!capabilityMatchesCore(input.config, input.projection, input.authority)) {
    throw new DirectWriteError("P0_CAPABILITY_OR_ACCOUNT_MISMATCH", "Exact account binding или Direct capability profile не подтверждены.");
  }
  const actualFingerprint = await fingerprintDirectProjection(input.projection as unknown as Record<string, unknown>);
  if (input.authority.publish_fingerprint !== actualFingerprint) {
    throw new DirectWriteError("P0_PROJECTION_FINGERPRINT_MISMATCH", "Approved publish fingerprint не совпадает с exact projection.");
  }
}

function identityFor(input: SafeSingleCampaignExecutionInput): DirectExecutionIdentity {
  const profile = input.authority.capability_profile;
  return {
    execution_id: input.execution_id,
    account: input.config.account,
    publish_fingerprint: input.authority.publish_fingerprint,
    capability_profile_id: String(profile.profile_id ?? ""),
    capability_profile_version: String(profile.profile_version ?? ""),
  };
}

function identityMatches(record: DirectExecutionRecord, identity: DirectExecutionIdentity) {
  return record.schema_version === EXECUTION_SCHEMA
    && record.execution_id === identity.execution_id
    && record.account === identity.account
    && record.publish_fingerprint === identity.publish_fingerprint
    && record.capability_profile_id === identity.capability_profile_id
    && record.capability_profile_version === identity.capability_profile_version;
}

function recoveryFrom(record: DirectExecutionRecord): DirectRecovery | null {
  const campaignId = record.provider_ids.campaign_id;
  if (!campaignId) return null;
  return {
    campaignId,
    ...(record.provider_ids.ad_group_id ? { adGroupId: record.provider_ids.ad_group_id } : {}),
    ...(record.provider_ids.keyword_id ? { keywordId: record.provider_ids.keyword_id } : {}),
    ...(record.provider_ids.ad_ids.length === 1 ? { adId: record.provider_ids.ad_ids[0] } : {}),
    ...(record.completed_steps.includes("MODERATION_SUBMITTED") ? { moderationSubmitted: true } : {}),
  };
}

function resultProviderIds(result: Record<string, unknown>, current: DirectExecutionRecord["provider_ids"]) {
  return {
    campaign_id: result.campaign_id ? String(result.campaign_id) : current.campaign_id,
    ad_group_id: result.ad_group_id ? String(result.ad_group_id) : current.ad_group_id,
    keyword_id: result.keyword_id ? String(result.keyword_id) : current.keyword_id,
    ad_ids: result.ad_id ? [String(result.ad_id)] : current.ad_ids,
  };
}

export async function executeSafeSingleCampaign(input: SafeSingleCampaignExecutionInput) {
  await validatePreflight(input);
  const now = input.now ?? (() => new Date().toISOString());
  const identity = identityFor(input);
  let record: DirectExecutionRecord | null;
  try {
    record = await input.journal.acquire(identity);
  } catch (error) {
    throw new DirectWriteError(
      "P0_ACCOUNT_WRITE_LOCKED",
      error instanceof Error ? error.message : "Direct account single-writer недоступен.",
    );
  }
  if (record && !identityMatches(record, identity)) {
    await input.journal.hold(identity);
    throw new DirectWriteError(
      "P0_EXECUTION_IDENTITY_MISMATCH",
      "Restart recovery разрешена только для exact projection fingerprint и capability identity.",
      { requires_reconciliation: true },
    );
  }
  if (record?.pending_dispatch) {
    await input.journal.hold(identity);
    throw new DirectWriteError(
      "P0_RECONCILIATION_REQUIRED",
      `Pending ${record.pending_dispatch.operation} must be reconciled by exact known provider IDs before any retry.`,
      { requires_reconciliation: true, pending_dispatch: record.pending_dispatch },
    );
  }
  if (record && TERMINAL_SUCCESS.has(record.status) && Object.keys(record.result).length) {
    await input.journal.release(identity);
    return structuredClone(record.result);
  }
  if (record && TERMINAL_FAILURE.has(record.status)) {
    await input.journal.release(identity);
    throw new DirectWriteError(
      "P0_EXECUTION_ALREADY_TERMINAL",
      `Execution ${record.execution_id} already ended as ${record.status}; blind retry is forbidden.`,
      { previous_status: record.status, previous_result: structuredClone(record.result) },
    );
  }
  const timestamp = now();
  record = record ?? {
    schema_version: EXECUTION_SCHEMA,
    ...identity,
    status: "PREPARED",
    lock_state: "HELD",
    provider_ids: { campaign_id: null, ad_group_id: null, keyword_id: null, ad_ids: [] },
    completed_steps: [],
    pending_dispatch: null,
    result: {},
    created_at: timestamp,
    updated_at: timestamp,
  };
  record.lock_state = "HELD";
  record.updated_at = timestamp;
  await input.journal.save(record);

  const journaledFetcher: typeof fetch = async (url, init) => {
    const requestJson = String(init?.body ?? "");
    let method = "";
    try {
      method = String(valueRecord(JSONbig.parse(requestJson)).method ?? "");
    } catch (error) {
      throw new DirectWriteError("P0_DIRECT_SERIALIZATION_FAILED", "Direct request serialization is invalid.", {}, { cause: error });
    }
    const service = new URL(typeof url === "string" ? url : url.toString()).pathname.split("/").at(-1) ?? "";
    const operation = `${service}.${method}`;
    if (method === "resume" || (method !== "get" && !MUTATION_OPERATIONS.has(operation))) {
      throw new DirectWriteError("P0_DIRECT_METHOD_NOT_ALLOWED", `${operation} отсутствует в P0 execution interface и allowlist.`);
    }
    if (method === "get") return (input.fetcher ?? fetch)(url, init);
    if (record.pending_dispatch) {
      throw new DirectWriteError(
        "P0_RECONCILIATION_REQUIRED",
        "A mutation cannot dispatch while another outcome is unresolved.",
        { requires_reconciliation: true, pending_dispatch: record.pending_dispatch },
      );
    }
    record.pending_dispatch = {
      operation,
      request_fingerprint: await sha256Text(requestJson),
      request_json: requestJson,
      dispatched_at: now(),
    };
    record.status = "DISPATCHING";
    record.updated_at = now();
    try {
      await input.journal.save(record);
    } catch (error) {
      record.pending_dispatch = null;
      throw new DirectWriteError(
        "P0_EXECUTION_JOURNAL_FAILED",
        "Dispatch intent не сохранён durable; network mutation не выполнялась.",
        { dispatch_not_attempted: true },
        { cause: error },
      );
    }
    try {
      return await (input.fetcher ?? fetch)(url, init);
    } catch (error) {
      record.status = "RECONCILIATION_REQUIRED";
      record.updated_at = now();
      try {
        await input.journal.save(record);
      } catch {
        // The durable pre-dispatch intent remains the recovery authority.
      }
      throw new DirectWriteError(
        "P0_DIRECT_OUTCOME_AMBIGUOUS",
        `${operation} lost its result; blind retry is forbidden.`,
        { requires_reconciliation: true, ambiguous_operation: operation },
        { cause: error },
      );
    }
  };

  const persistProgress = async (status: string, result: Record<string, unknown>) => {
    const pendingBeforeProgress = record.pending_dispatch;
    const reconciliationRequired = status === "RECONCILIATION_REQUIRED"
      || status === "MANUAL_RECONCILIATION_REQUIRED"
      || mustHoldAccountLock(result);
    const pendingCompleted = record.pending_dispatch
      ? MUTATION_COMPLETION_PROGRESS[record.pending_dispatch.operation] === status
      : false;
    if (!reconciliationRequired && pendingCompleted) record.pending_dispatch = null;
    record.status = status;
    record.provider_ids = resultProviderIds(result, record.provider_ids);
    record.completed_steps = Array.isArray(result.steps) ? result.steps.map(String) : record.completed_steps;
    record.result = structuredClone(result);
    record.updated_at = now();
    try {
      await input.journal.save(record);
    } catch (error) {
      record.pending_dispatch = pendingBeforeProgress;
      throw new DirectWriteError(
        "P0_EXECUTION_JOURNAL_FAILED",
        "Direct result не сохранён durable; reconciliation is required before continuing.",
        { requires_reconciliation: true },
        { cause: error },
      );
    }
  };

  try {
    const result = await createSuspendedCampaign(
      input.config,
      input.projection,
      journaledFetcher,
      persistProgress,
      recoveryFrom(record),
    );
    const resultRecord = result as Record<string, unknown>;
    record.status = String(resultRecord.status ?? "MODERATION_PENDING");
    record.lock_state = "RELEASED";
    record.pending_dispatch = null;
    record.provider_ids = resultProviderIds(resultRecord, record.provider_ids);
    record.completed_steps = Array.isArray(resultRecord.steps) ? resultRecord.steps.map(String) : record.completed_steps;
    record.result = structuredClone(resultRecord);
    record.updated_at = now();
    await input.journal.save(record);
    await input.journal.release(identity);
    return result;
  } catch (error) {
    const directError = error instanceof DirectWriteError
      ? error
      : new DirectWriteError("P0_DIRECT_SYSTEM_FAILURE", "Single-campaign Direct orchestration failed.", {}, { cause: error });
    const partial = { ...record.result, ...directError.partial };
    const definitelyRejected = directError.partial.rejected === true;
    const dispatchNotAttempted = directError.partial.dispatch_not_attempted === true;
    if (definitelyRejected || dispatchNotAttempted) record.pending_dispatch = null;
    const hold = !definitelyRejected
      && !dispatchNotAttempted
      && (Boolean(record.pending_dispatch) || mustHoldAccountLock(partial));
    record.status = hold ? "RECONCILIATION_REQUIRED" : definitelyRejected ? "PROVIDER_REJECTED" : "SYSTEM_FAILED";
    record.lock_state = hold ? "HELD" : "RELEASED";
    record.provider_ids = resultProviderIds(partial, record.provider_ids);
    record.result = partial;
    record.updated_at = now();
    await input.journal.save(record);
    if (hold) await input.journal.hold(identity);
    else await input.journal.release(identity);
    throw new DirectWriteError(directError.code, directError.message, {
      ...partial,
      execution_id: identity.execution_id,
      account_lock: hold ? "HELD_FOR_RECONCILIATION" : "RELEASED",
    }, { cause: directError });
  }
}

export function mustHoldAccountLock(partial: Record<string, unknown>) {
  return partial.requires_reconciliation === true
    || partial.dispatch_ambiguous === true
    || Boolean(partial.pending_dispatch)
    || partial.containment === "RECONCILIATION_REQUIRED"
    || partial.containment === "MANUAL_RECONCILIATION_REQUIRED";
}

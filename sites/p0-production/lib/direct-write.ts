import JSONbigFactory from "json-bigint";

const JSONbig = JSONbigFactory({ useNativeBigInt: true });

export type DirectProjection = {
  schema_version: string;
  lineage: {
    strategy_revision_id?: unknown;
    draft_id?: unknown;
    draft_revision_id?: unknown;
    capability_profile_id?: unknown;
    capability_profile_version?: unknown;
    playbook_release_id?: unknown;
    playbook_release_version?: unknown;
    playbook_rule_id?: unknown;
    playbook_rule_version?: unknown;
  };
  business: Record<string, unknown>;
  safety: { must_end_non_serving: true; resume_allowed: false; network_serving: false };
  direct: {
    campaign: Record<string, unknown>;
    ad_group: Record<string, unknown>;
    keyword: Record<string, unknown>;
    ad: Record<string, unknown>;
  };
};

export type DirectConfig = {
  token: string;
  account: string;
};

export type DirectRecovery = {
  campaignId: string;
  adGroupId?: string;
  keywordId?: string;
  adId?: string;
  moderationSubmitted?: boolean;
};

type DirectResult = Record<string, unknown>;
type Fetcher = typeof fetch;
type DirectApiIssue = { code: number | string; message: string; details: string };
type ProviderGraphIds = { campaignId: string; adGroupId: string; keywordId: string; adId: string };
type ProviderGraphReadback = {
  campaign: Record<string, unknown>;
  adGroup: Record<string, unknown>;
  keyword: Record<string, unknown>;
  ad: Record<string, unknown>;
};

function directApiIssues(value: unknown): DirectApiIssue[] {
  if (!Array.isArray(value)) return [];
  return value.map((issue) => {
    const row = issue && typeof issue === "object" ? issue as Record<string, unknown> : {};
    return {
      code: Number.isFinite(Number(row.Code)) ? Number(row.Code) : String(row.Code ?? ""),
      message: String(row.Message ?? "Direct API отклонил объект"),
      details: String(row.Details ?? ""),
    };
  });
}

function issueMessage(issue: DirectApiIssue) {
  return [issue.message, issue.details].filter(Boolean).join(": ");
}

export class DirectWriteError extends Error {
  readonly code: string;
  readonly partial: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    partial: Record<string, unknown> = {},
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "DirectWriteError";
    this.code = code;
    this.partial = partial;
  }
}

async function callDirect(
  config: DirectConfig,
  service: "Campaigns" | "AdGroups" | "Keywords" | "Ads",
  method: "add" | "suspend" | "get" | "moderate",
  params: Record<string, unknown>,
  fetcher: Fetcher,
): Promise<DirectResult> {
  const response = await fetcher(`https://api.direct.yandex.com/json/v501/${service.toLowerCase()}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.token}`,
      "Client-Login": config.account,
      Accept: "application/json",
      "Accept-Language": "ru",
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSONbig.stringify({ method, params }),
  });
  if (!response.ok) {
    throw new DirectWriteError(
      "P0_DIRECT_HTTP_FAILED",
      `Яндекс Директ вернул HTTP ${response.status}.`,
      { requires_reconciliation: true, ambiguous_operation: `${service}.${method}` },
    );
  }
  let payload: { error?: Record<string, unknown>; result?: unknown };
  try {
    payload = JSONbig.parse(await response.text()) as typeof payload;
  } catch (error) {
    throw new DirectWriteError(
      "P0_DIRECT_RESPONSE_INVALID",
      "Ответ Яндекс Директа не является допустимым JSON.",
      { requires_reconciliation: true, ambiguous_operation: `${service}.${method}` },
      { cause: error },
    );
  }
  if (payload.error) {
    const apiError: DirectApiIssue = {
      code: Number.isFinite(Number(payload.error.error_code)) ? Number(payload.error.error_code) : String(payload.error.error_code ?? ""),
      message: String(payload.error.error_string ?? "Direct API отклонил запрос"),
      details: String(payload.error.error_detail ?? ""),
    };
    throw new DirectWriteError(
      "P0_DIRECT_API_REJECTED",
      `${service}.${method}: ${issueMessage(apiError)}`,
      method === "get"
        ? { requires_reconciliation: true, api_error: apiError }
        : { rejected: true, api_error: apiError },
    );
  }
  if (!payload.result || typeof payload.result !== "object") {
    throw new DirectWriteError(
      "P0_DIRECT_RESPONSE_INVALID",
      "Ответ Яндекс Директа не соответствует P0-контракту.",
      { requires_reconciliation: true, ambiguous_operation: `${service}.${method}` },
    );
  }
  return payload.result as DirectResult;
}

function directId(value: string) {
  if (!/^\d+$/u.test(value)) {
    throw new DirectWriteError("P0_DIRECT_ID_INVALID", "Direct API вернул некорректный идентификатор.");
  }
  return BigInt(value);
}

function preservedIssues(operation: string, severity: "WARNING" | "ERROR", issues: DirectApiIssue[]) {
  return issues.map((issue) => ({ operation, severity, ...issue }));
}

function appendWarnings(
  target: Record<string, unknown>,
  operation: string,
  value: unknown,
) {
  const warnings = directApiIssues(value);
  if (!warnings.length) return;
  const current = Array.isArray(target.provider_issues) ? target.provider_issues : [];
  target.provider_issues = [...current, ...preservedIssues(operation, "WARNING", warnings)];
}

function addedId(
  result: DirectResult,
  key: string,
  operation: string,
  progress: Record<string, unknown>,
) {
  const rows = result[key];
  const issues = directApiIssues(Array.isArray(rows) ? rows[0]?.Errors : undefined);
  if (!Array.isArray(rows) || rows.length !== 1 || issues.length || !rows[0]?.Id) {
    throw new DirectWriteError(
      "P0_DIRECT_ITEM_FAILED",
      issues.length ? `${operation}: ${issues.map(issueMessage).join("; ")}` : `${operation} отклонил объект.`,
      issues.length ? {
        rejected: true,
        api_errors: issues,
        provider_issues: preservedIssues(operation, "ERROR", issues),
      } : {},
    );
  }
  appendWarnings(progress, operation, rows[0]?.Warnings);
  return String(rows[0].Id);
}

function actionAccepted(
  result: DirectResult,
  key: string,
  operation: string,
  progress: Record<string, unknown>,
  expectedIds: string[],
) {
  const rows = result[key];
  const issues = directApiIssues(Array.isArray(rows) ? rows[0]?.Errors : undefined);
  if (!Array.isArray(rows) || rows.length !== 1 || issues.length) {
    throw new DirectWriteError(
      "P0_DIRECT_ACTION_FAILED",
      issues.length ? `${operation}: ${issues.map(issueMessage).join("; ")}` : `${operation} не подтверждён.`,
      issues.length ? {
        rejected: true,
        api_errors: issues,
        provider_issues: preservedIssues(operation, "ERROR", issues),
      } : {},
    );
  }
  const returnedIds = rows.map((row) => String(row?.Id ?? ""));
  if (JSON.stringify(returnedIds) !== JSON.stringify(expectedIds)) {
    throw new DirectWriteError(
      "P0_DIRECT_ACTION_FAILED",
      `${operation} acknowledged unexpected or missing provider IDs.`,
      { expected_ids: expectedIds, returned_ids: returnedIds },
    );
  }
  appendWarnings(progress, operation, rows[0]?.Warnings);
}

function readbackRow(result: DirectResult, key: string, operation: string) {
  const rows = result[key];
  if (!Array.isArray(rows) || rows.length !== 1 || !rows[0] || typeof rows[0] !== "object") {
    throw new DirectWriteError("P0_DIRECT_READBACK_FAILED", `${operation} не подтвердил ровно один созданный объект.`);
  }
  return rows[0] as Record<string, unknown>;
}

export async function campaignReadback(config: DirectConfig, campaignId: string, fetcher: Fetcher) {
  return readbackRow(await callDirect(
    config,
    "Campaigns",
    "get",
    {
      SelectionCriteria: { Ids: [directId(campaignId)] },
      FieldNames: ["Id", "Name", "Type", "Status", "State", "StartDate", "EndDate"],
      UnifiedCampaignFieldNames: ["BiddingStrategy"],
    },
    fetcher,
  ), "Campaigns", "Campaigns.get");
}

async function adGroupReadback(config: DirectConfig, adGroupId: string, fetcher: Fetcher) {
  return readbackRow(await callDirect(
    config,
    "AdGroups",
    "get",
    {
      SelectionCriteria: { Ids: [directId(adGroupId)] },
      FieldNames: ["Id", "CampaignId", "Name", "Type", "Status", "ServingStatus", "RegionIds", "NegativeKeywords"],
      UnifiedAdGroupFieldNames: ["OfferRetargeting"],
    },
    fetcher,
  ), "AdGroups", "AdGroups.get");
}

async function keywordReadback(config: DirectConfig, keywordId: string, fetcher: Fetcher) {
  return readbackRow(await callDirect(
    config,
    "Keywords",
    "get",
    {
      SelectionCriteria: { Ids: [directId(keywordId)] },
      FieldNames: ["Id", "AdGroupId", "Keyword", "Status", "State"],
    },
    fetcher,
  ), "Keywords", "Keywords.get");
}

export async function adReadback(config: DirectConfig, adId: string, fetcher: Fetcher) {
  return readbackRow(await callDirect(
    config,
    "Ads",
    "get",
    {
      SelectionCriteria: { Ids: [directId(adId)] },
      FieldNames: ["Id", "CampaignId", "AdGroupId", "Type", "Status", "State", "StatusClarification"],
      TextAdFieldNames: ["Title", "Text", "Href", "Mobile"],
    },
    fetcher,
  ), "Ads", "Ads.get");
}

function record(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function normalizedProviderText(value: unknown) {
  return String(value ?? "").normalize("NFKC").replace(/\s+/gu, " ").trim();
}

function normalizedProviderValue(value: unknown): unknown {
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (Array.isArray(value)) return value.map(normalizedProviderValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => [key, normalizedProviderValue(item)]));
}

function normalizedProviderIds(value: unknown) {
  return (Array.isArray(value) ? value : [])
    .map((item) => String(item))
    .sort((left, right) => left.localeCompare(right, "en", { numeric: true }));
}

function normalizedProviderTexts(value: unknown) {
  return (Array.isArray(value) ? value : [])
    .map(normalizedProviderText)
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function semanticGraph(
  projection: DirectProjection,
  ids: ProviderGraphIds,
  readback: ProviderGraphReadback,
) {
  const expectedCampaign = projection.direct.campaign;
  const expectedGroup = projection.direct.ad_group;
  const expectedKeyword = projection.direct.keyword;
  const expectedAd = projection.direct.ad;
  const actualCampaignUnified = record(readback.campaign.UnifiedCampaign);
  const expectedCampaignUnified = record(expectedCampaign.UnifiedCampaign);
  const actualGroupUnified = record(readback.adGroup.UnifiedAdGroup);
  const expectedGroupUnified = record(expectedGroup.UnifiedAdGroup);
  const actualNegativeKeywords = record(readback.adGroup.NegativeKeywords);
  const expectedNegativeKeywords = record(expectedGroup.NegativeKeywords);
  const actualTextAd = record(readback.ad.TextAd);
  const expectedTextAd = record(expectedAd.TextAd);
  const expected = {
    campaign: {
      Id: ids.campaignId,
      Name: normalizedProviderText(expectedCampaign.Name),
      Type: "UNIFIED_CAMPAIGN",
      State: "SUSPENDED",
      StartDate: String(expectedCampaign.StartDate ?? ""),
      EndDate: String(expectedCampaign.EndDate ?? ""),
      BiddingStrategy: normalizedProviderValue(expectedCampaignUnified.BiddingStrategy),
    },
    ad_group: {
      Id: ids.adGroupId,
      CampaignId: ids.campaignId,
      Name: normalizedProviderText(expectedGroup.Name),
      Type: "UNIFIED_AD_GROUP",
      RegionIds: normalizedProviderIds(expectedGroup.RegionIds),
      NegativeKeywords: normalizedProviderTexts(expectedNegativeKeywords.Items),
      OfferRetargeting: String(expectedGroupUnified.OfferRetargeting ?? ""),
    },
    keyword: {
      Id: ids.keywordId,
      AdGroupId: ids.adGroupId,
      Keyword: normalizedProviderText(expectedKeyword.Keyword),
    },
    ad: {
      Id: ids.adId,
      CampaignId: ids.campaignId,
      AdGroupId: ids.adGroupId,
      Type: "TEXT_AD",
      Title: normalizedProviderText(expectedTextAd.Title),
      Text: normalizedProviderText(expectedTextAd.Text),
      Href: String(expectedTextAd.Href ?? ""),
      Mobile: String(expectedTextAd.Mobile ?? ""),
    },
  };
  const actual = {
    campaign: {
      Id: String(readback.campaign.Id ?? ""),
      Name: normalizedProviderText(readback.campaign.Name),
      Type: String(readback.campaign.Type ?? ""),
      State: String(readback.campaign.State ?? ""),
      StartDate: String(readback.campaign.StartDate ?? ""),
      EndDate: String(readback.campaign.EndDate ?? ""),
      BiddingStrategy: normalizedProviderValue(actualCampaignUnified.BiddingStrategy),
    },
    ad_group: {
      Id: String(readback.adGroup.Id ?? ""),
      CampaignId: String(readback.adGroup.CampaignId ?? ""),
      Name: normalizedProviderText(readback.adGroup.Name),
      Type: String(readback.adGroup.Type ?? ""),
      RegionIds: normalizedProviderIds(readback.adGroup.RegionIds),
      NegativeKeywords: normalizedProviderTexts(actualNegativeKeywords.Items),
      OfferRetargeting: String(actualGroupUnified.OfferRetargeting ?? ""),
    },
    keyword: {
      Id: String(readback.keyword.Id ?? ""),
      AdGroupId: String(readback.keyword.AdGroupId ?? ""),
      Keyword: normalizedProviderText(readback.keyword.Keyword),
    },
    ad: {
      Id: String(readback.ad.Id ?? ""),
      CampaignId: String(readback.ad.CampaignId ?? ""),
      AdGroupId: String(readback.ad.AdGroupId ?? ""),
      Type: String(readback.ad.Type ?? ""),
      Title: normalizedProviderText(actualTextAd.Title),
      Text: normalizedProviderText(actualTextAd.Text),
      Href: String(actualTextAd.Href ?? ""),
      Mobile: String(actualTextAd.Mobile ?? ""),
    },
  };
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new DirectWriteError(
      "P0_DIRECT_GRAPH_MISMATCH",
      "Direct silently altered or omitted a selected field in the supported campaign graph.",
      { expected_graph: expected, actual_graph: actual },
    );
  }
  return { ...readback, semantic_graph: actual };
}

async function readAndVerifyGraph(
  config: DirectConfig,
  projection: DirectProjection,
  ids: ProviderGraphIds,
  fetcher: Fetcher,
) {
  const campaign = await campaignReadback(config, ids.campaignId, fetcher);
  const adGroup = await adGroupReadback(config, ids.adGroupId, fetcher);
  const keyword = await keywordReadback(config, ids.keywordId, fetcher);
  const ad = await adReadback(config, ids.adId, fetcher);
  return semanticGraph(projection, ids, { campaign, adGroup, keyword, ad });
}

async function suspendAndReadback(
  config: DirectConfig,
  campaignId: string,
  fetcher: Fetcher,
  progress: Record<string, unknown>,
) {
  const suspended = await callDirect(
    config,
    "Campaigns",
    "suspend",
    { SelectionCriteria: { Ids: [directId(campaignId)] } },
    fetcher,
  );
  actionAccepted(suspended, "SuspendResults", "Campaigns.suspend", progress, [campaignId]);
  return campaignReadback(config, campaignId, fetcher);
}

async function ensureNonServing(
  config: DirectConfig,
  campaignId: string,
  fetcher: Fetcher,
  progress: Record<string, unknown>,
) {
  let campaign = await campaignReadback(config, campaignId, fetcher);
  if (campaign.State === "OFF" || campaign.State === "SUSPENDED") return campaign;
  campaign = await suspendAndReadback(config, campaignId, fetcher, progress);
  if (campaign.State !== "OFF" && campaign.State !== "SUSPENDED") {
    throw new DirectWriteError("P0_NON_SERVING_NOT_CONFIRMED", "Директ не подтвердил выключенные показы кампании.");
  }
  return campaign;
}

async function ensureExplicitlySuspended(
  config: DirectConfig,
  campaignId: string,
  fetcher: Fetcher,
  progress: Record<string, unknown>,
) {
  let campaign = await campaignReadback(config, campaignId, fetcher);
  if (campaign.State === "SUSPENDED") return campaign;
  campaign = await suspendAndReadback(config, campaignId, fetcher, progress);
  if (campaign.State !== "SUSPENDED") {
    throw new DirectWriteError(
      "P0_EXPLICIT_SUSPEND_NOT_CONFIRMED",
      "Direct не подтвердил явную остановку кампании до дочерних записей.",
    );
  }
  return campaign;
}

export async function createSuspendedCampaign(
  config: DirectConfig,
  projection: DirectProjection,
  fetcher: Fetcher = fetch,
  onProgress: (status: string, result: Record<string, unknown>) => void | Promise<void> = () => undefined,
  recovery: DirectRecovery | null = null,
) {
  if (!config.token || !config.account) {
    throw new DirectWriteError("P0_WRITE_CREDENTIAL_MISSING", "Direct production credentials не настроены.");
  }
  if (
    projection.safety.must_end_non_serving !== true
    || projection.safety.resume_allowed !== false
    || projection.safety.network_serving !== false
  ) {
    throw new DirectWriteError("P0_PROJECTION_UNSAFE", "Campaign Draft нарушает обязательный safety-контракт.");
  }

  const result: Record<string, unknown> = { steps: [] as string[], provider_issues: [] };
  let campaignId = recovery?.campaignId ?? "";
  try {
    if (campaignId) {
      result.campaign_id = campaignId;
      result.recovered_existing = true;
      (result.steps as string[]).push("CAMPAIGN_RECOVERED");
      await onProgress("CAMPAIGN_RECOVERED", result);
    } else {
      result.add_attempted = true;
      campaignId = addedId(
        await callDirect(config, "Campaigns", "add", { Campaigns: [projection.direct.campaign] }, fetcher),
        "AddResults",
        "Campaigns.add",
        result,
      );
      result.campaign_id = campaignId;
      (result.steps as string[]).push("CAMPAIGN_CREATED");
      await onProgress("CAMPAIGN_CREATED", result);
    }

    if (result.recovered_existing === true) {
      await ensureExplicitlySuspended(config, campaignId, fetcher, result);
    } else {
      const explicitlySuspended = await suspendAndReadback(config, campaignId, fetcher, result);
      if (explicitlySuspended.State !== "SUSPENDED") {
        throw new DirectWriteError(
          "P0_EXPLICIT_SUSPEND_NOT_CONFIRMED",
          "Direct не подтвердил явную остановку новой кампании до дочерних записей.",
        );
      }
    }
    (result.steps as string[]).push("NON_SERVING_CONFIRMED");
    await onProgress("NON_SERVING_CONFIRMED", result);

    let adGroupId = recovery?.adGroupId ?? "";
    let keywordId = recovery?.keywordId ?? "";
    let adId = recovery?.adId ?? "";
    if (adGroupId) {
      result.ad_group_id = adGroupId;
      (result.steps as string[]).push("AD_GROUP_RECOVERED");
      await onProgress("AD_GROUP_RECOVERED", result);
    } else {
      const adGroup = { ...projection.direct.ad_group, CampaignId: directId(campaignId) };
      adGroupId = addedId(
        await callDirect(config, "AdGroups", "add", { AdGroups: [adGroup] }, fetcher),
        "AddResults",
        "AdGroups.add",
        result,
      );
      result.ad_group_id = adGroupId;
      (result.steps as string[]).push("AD_GROUP_CREATED");
      await onProgress("AD_GROUP_CREATED", result);
    }
    if (keywordId) {
      result.keyword_id = keywordId;
      (result.steps as string[]).push("KEYWORD_RECOVERED");
      await onProgress("KEYWORD_RECOVERED", result);
    } else {
      const keyword = { ...projection.direct.keyword, AdGroupId: directId(adGroupId) };
      keywordId = addedId(
        await callDirect(config, "Keywords", "add", { Keywords: [keyword] }, fetcher),
        "AddResults",
        "Keywords.add",
        result,
      );
      result.keyword_id = keywordId;
      (result.steps as string[]).push("KEYWORD_CREATED");
      await onProgress("KEYWORD_CREATED", result);
    }
    if (adId) {
      result.ad_id = adId;
      (result.steps as string[]).push("AD_RECOVERED");
      await onProgress("AD_RECOVERED", result);
    } else {
      const ad = { ...projection.direct.ad, AdGroupId: directId(adGroupId) };
      adId = addedId(
        await callDirect(config, "Ads", "add", { Ads: [ad] }, fetcher),
        "AddResults",
        "Ads.add",
        result,
      );
      result.ad_id = adId;
      (result.steps as string[]).push("AD_CREATED");
      await onProgress("AD_CREATED", result);
    }

    const ids = { campaignId, adGroupId, keywordId, adId };
    await readAndVerifyGraph(config, projection, ids, fetcher);
    (result.steps as string[]).push("OBJECT_GRAPH_VERIFIED");
    await onProgress("OBJECT_GRAPH_VERIFIED", result);

    if (recovery?.moderationSubmitted) {
      (result.steps as string[]).push("MODERATION_RECOVERED");
      await onProgress("MODERATION_RECOVERED", result);
    } else {
      const moderated = await callDirect(
        config,
        "Ads",
        "moderate",
        { SelectionCriteria: { Ids: [directId(adId)] } },
        fetcher,
      );
      actionAccepted(moderated, "ModerateResults", "Ads.moderate", result, [adId]);
      (result.steps as string[]).push("MODERATION_SUBMITTED");
      await onProgress("MODERATION_SUBMITTED", result);
    }
    const finalGraph = await readAndVerifyGraph(config, projection, ids, fetcher);
    const moderation = String(finalGraph.ad.Status ?? "UNKNOWN");
    const status = moderation === "ACCEPTED"
      ? "READY_TO_LAUNCH"
      : moderation === "REJECTED"
        ? "REJECTED_NEEDS_EDIT"
        : "MODERATION_PENDING";
    const completed = {
      ...result,
      status,
      campaign_state: String(finalGraph.campaign.State ?? "UNKNOWN"),
      moderation_status: moderation,
      semantic_graph: finalGraph.semantic_graph,
      spend_started: false,
    };
    await onProgress(status, completed);
    return completed;
  } catch (error) {
    if (campaignId) {
      if (error instanceof DirectWriteError && error.partial.requires_reconciliation === true) {
        result.containment = (result.steps as string[]).includes("NON_SERVING_CONFIRMED")
          ? "NON_SERVING_CONFIRMED"
          : "MANUAL_RECONCILIATION_REQUIRED";
      } else {
        try {
          await ensureNonServing(config, campaignId, fetcher, result);
          result.containment = "NON_SERVING_CONFIRMED";
        } catch {
          result.containment = "MANUAL_RECONCILIATION_REQUIRED";
        }
      }
      await onProgress(String(result.containment), result);
    } else if (
      result.add_attempted
      && !(error instanceof DirectWriteError && error.partial.rejected === true)
      && !(error instanceof DirectWriteError && error.partial.dispatch_not_attempted === true)
    ) {
      result.containment = "RECONCILIATION_REQUIRED";
      await onProgress("RECONCILIATION_REQUIRED", result);
    }
    if (error instanceof DirectWriteError) {
      throw new DirectWriteError(error.code, error.message, { ...result, ...error.partial });
    }
    throw new DirectWriteError(
      "P0_DIRECT_WRITE_FAILED",
      "Директ не завершил безопасное создание. Требуется сверка журнала.",
      result,
    );
  }
}

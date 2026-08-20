export type DirectProjection = {
  schema_version: string;
  business: Record<string, unknown>;
  safety: { must_end_suspended: true; resume_allowed: false; network_serving: false };
  direct: {
    campaign: Record<string, unknown>;
    ad_group: Record<string, unknown>;
    keyword: Record<string, unknown>;
    ad: Record<string, unknown>;
  };
};

type DirectConfig = {
  token: string;
  account: string;
};

type DirectResult = Record<string, unknown>;
type Fetcher = typeof fetch;
type DirectApiIssue = { code: number | string; message: string; details: string };

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

  constructor(code: string, message: string, partial: Record<string, unknown> = {}) {
    super(message);
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
    body: JSON.stringify({ method, params }),
  });
  if (!response.ok) {
    throw new DirectWriteError("P0_DIRECT_HTTP_FAILED", `Яндекс Директ вернул HTTP ${response.status}.`);
  }
  const payload = (await response.json()) as { error?: Record<string, unknown>; result?: unknown };
  if (payload.error) {
    const apiError: DirectApiIssue = {
      code: Number.isFinite(Number(payload.error.error_code)) ? Number(payload.error.error_code) : String(payload.error.error_code ?? ""),
      message: String(payload.error.error_string ?? "Direct API отклонил запрос"),
      details: String(payload.error.error_detail ?? ""),
    };
    throw new DirectWriteError(
      "P0_DIRECT_API_REJECTED",
      `${service}.${method}: ${issueMessage(apiError)}`,
      { rejected: true, api_error: apiError },
    );
  }
  if (!payload.result || typeof payload.result !== "object") {
    throw new DirectWriteError("P0_DIRECT_RESPONSE_INVALID", "Ответ Яндекс Директа не соответствует P0-контракту.");
  }
  return payload.result as DirectResult;
}

function addedId(result: DirectResult, key: string, operation: string) {
  const rows = result[key];
  const issues = directApiIssues(Array.isArray(rows) ? rows[0]?.Errors : undefined);
  if (!Array.isArray(rows) || rows.length !== 1 || issues.length || !rows[0]?.Id) {
    throw new DirectWriteError(
      "P0_DIRECT_ITEM_FAILED",
      issues.length ? `${operation}: ${issues.map(issueMessage).join("; ")}` : `${operation} отклонил объект.`,
      issues.length ? { rejected: true, api_errors: issues } : {},
    );
  }
  return String(rows[0].Id);
}

function actionAccepted(result: DirectResult, key: string, operation: string) {
  const rows = result[key];
  const issues = directApiIssues(Array.isArray(rows) ? rows[0]?.Errors : undefined);
  if (!Array.isArray(rows) || rows.length !== 1 || issues.length) {
    throw new DirectWriteError(
      "P0_DIRECT_ACTION_FAILED",
      issues.length ? `${operation}: ${issues.map(issueMessage).join("; ")}` : `${operation} не подтверждён.`,
      { rejected: true, api_errors: issues },
    );
  }
}

async function campaignReadback(config: DirectConfig, campaignId: string, fetcher: Fetcher) {
  const result = await callDirect(
    config,
    "Campaigns",
    "get",
    {
      SelectionCriteria: { Ids: [Number(campaignId)] },
      FieldNames: ["Id", "Name", "Type", "Status", "State"],
      UnifiedCampaignFieldNames: ["BiddingStrategy"],
    },
    fetcher,
  );
  const rows = result.Campaigns;
  if (!Array.isArray(rows) || rows.length !== 1) {
    throw new DirectWriteError("P0_DIRECT_READBACK_FAILED", "Campaigns.get не подтвердил созданную кампанию.");
  }
  return rows[0] as Record<string, unknown>;
}

async function adReadback(config: DirectConfig, adId: string, fetcher: Fetcher) {
  const result = await callDirect(
    config,
    "Ads",
    "get",
    {
      SelectionCriteria: { Ids: [Number(adId)] },
      FieldNames: ["Id", "CampaignId", "AdGroupId", "Type", "Status", "State", "StatusClarification"],
      TextAdFieldNames: ["Title", "Text", "Href", "Mobile"],
    },
    fetcher,
  );
  const rows = result.Ads;
  if (!Array.isArray(rows) || rows.length !== 1) {
    throw new DirectWriteError("P0_DIRECT_READBACK_FAILED", "Ads.get не подтвердил созданное объявление.");
  }
  return rows[0] as Record<string, unknown>;
}

async function ensureSuspended(config: DirectConfig, campaignId: string, fetcher: Fetcher) {
  const suspended = await callDirect(
    config,
    "Campaigns",
    "suspend",
    { SelectionCriteria: { Ids: [Number(campaignId)] } },
    fetcher,
  );
  actionAccepted(suspended, "SuspendResults", "Campaigns.suspend");
  const campaign = await campaignReadback(config, campaignId, fetcher);
  if (campaign.State !== "SUSPENDED") {
    throw new DirectWriteError("P0_SUSPEND_NOT_CONFIRMED", "Директ не подтвердил остановленное состояние кампании.");
  }
  return campaign;
}

export async function createSuspendedCampaign(
  config: DirectConfig,
  projection: DirectProjection,
  fetcher: Fetcher = fetch,
  onProgress: (status: string, result: Record<string, unknown>) => void | Promise<void> = () => undefined,
) {
  if (!config.token || !config.account) {
    throw new DirectWriteError("P0_WRITE_CREDENTIAL_MISSING", "Direct production credentials не настроены.");
  }
  if (
    projection.safety.must_end_suspended !== true
    || projection.safety.resume_allowed !== false
    || projection.safety.network_serving !== false
  ) {
    throw new DirectWriteError("P0_PROJECTION_UNSAFE", "Campaign Draft нарушает обязательный safety-контракт.");
  }

  const result: Record<string, unknown> = { steps: [] as string[] };
  let campaignId = "";
  try {
    result.add_attempted = true;
    campaignId = addedId(
      await callDirect(config, "Campaigns", "add", { Campaigns: [projection.direct.campaign] }, fetcher),
      "AddResults",
      "Campaigns.add",
    );
    result.campaign_id = campaignId;
    (result.steps as string[]).push("CAMPAIGN_CREATED");
    await onProgress("CAMPAIGN_CREATED", result);

    await ensureSuspended(config, campaignId, fetcher);
    (result.steps as string[]).push("SUSPENDED_CONFIRMED");
    await onProgress("SUSPENDED_CONFIRMED", result);

    const adGroup = { ...projection.direct.ad_group, CampaignId: Number(campaignId) };
    const adGroupId = addedId(
      await callDirect(config, "AdGroups", "add", { AdGroups: [adGroup] }, fetcher),
      "AddResults",
      "AdGroups.add",
    );
    const keyword = { ...projection.direct.keyword, AdGroupId: Number(adGroupId) };
    const keywordId = addedId(
      await callDirect(config, "Keywords", "add", { Keywords: [keyword] }, fetcher),
      "AddResults",
      "Keywords.add",
    );
    const ad = { ...projection.direct.ad, AdGroupId: Number(adGroupId) };
    const adId = addedId(
      await callDirect(config, "Ads", "add", { Ads: [ad] }, fetcher),
      "AddResults",
      "Ads.add",
    );
    Object.assign(result, { ad_group_id: adGroupId, keyword_id: keywordId, ad_id: adId });
    (result.steps as string[]).push("OBJECT_GRAPH_CREATED");
    await onProgress("OBJECT_GRAPH_CREATED", result);

    const moderated = await callDirect(
      config,
      "Ads",
      "moderate",
      { SelectionCriteria: { Ids: [Number(adId)] } },
      fetcher,
    );
    actionAccepted(moderated, "ModerateResults", "Ads.moderate");
    const adState = await adReadback(config, adId, fetcher);
    const finalCampaign = await campaignReadback(config, campaignId, fetcher);
    if (finalCampaign.State !== "SUSPENDED") {
      throw new DirectWriteError("P0_SUSPEND_LOST", "Остановленное состояние кампании потеряно после модерации.", result);
    }
    const moderation = String(adState.Status ?? "UNKNOWN");
    const status = moderation === "ACCEPTED"
      ? "READY_TO_LAUNCH"
      : moderation === "REJECTED"
        ? "REJECTED_NEEDS_EDIT"
        : "MODERATION_PENDING";
    (result.steps as string[]).push("MODERATION_SUBMITTED");
    const completed = {
      ...result,
      status,
      campaign_state: "SUSPENDED",
      moderation_status: moderation,
      spend_started: false,
    };
    await onProgress(status, completed);
    return completed;
  } catch (error) {
    if (campaignId) {
      try {
        await ensureSuspended(config, campaignId, fetcher);
        result.containment = "SUSPENDED_CONFIRMED";
      } catch {
        result.containment = "MANUAL_RECONCILIATION_REQUIRED";
      }
      await onProgress(String(result.containment), result);
    } else if (result.add_attempted && !(error instanceof DirectWriteError && error.partial.rejected === true)) {
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

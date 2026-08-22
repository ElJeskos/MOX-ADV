import { sealCuratedPlaybookRelease } from "./campaign-playbook.ts";
import { P0_E2E_FIXTURE_SCENARIO } from "./p0-e2e-boundary.ts";
import type { LandingAdvisoryAdapter } from "./landing-advisory.ts";
import { collectOfficialWordstatBatch } from "./market-evidence.ts";
import {
  correctSuspendedCampaignAndResubmitModeration,
  createSuspendedCampaign,
  pollSuspendedCampaignModeration,
  type DirectProjection,
} from "./direct-write.ts";
import type { P0ApplicationAdapters, P0Command, P0Context } from "./p0-application.ts";
import { P0Application } from "./p0-application.ts";
import { D1P0ApplicationStore } from "./p0.ts";

const applications = new Map<string, {
  application: P0Application;
  evidence: FixtureAcceptanceEvidence;
  advanceClock(milliseconds: number): void;
}>();

function fixtureContext(observedAt = "2026-08-21T10:00:00.000Z"): P0Context {
  return {
    environment: "PRODUCTION",
    test_scenario: false,
    direct: {
      ready: true,
      inventory_ready: true,
      authority: "VERIFIED",
      access: "YANDEX_DIRECT_API_V501",
      account: "owner-account",
      client_id: "client-4242",
      binding: {
        expected_account: "owner-account",
        api_account: "owner-account",
        matched: true,
      },
      campaigns_total: 1,
      minimum_weekly_budget_rub: 300,
      observed_at: observedAt,
      capability_snapshot: {
        schema_version: "direct-account-capability-snapshot-v1",
        snapshot_id: "direct-capability:e2e-owner-account",
        source: "YANDEX_DIRECT_API_V501",
        account: "owner-account",
        observed_at: observedAt,
        api_version: "v501",
        archived: "NO",
        currency: "RUB",
        edit_campaigns_grant: "YES",
        available_campaign_types: ["UNIFIED_CAMPAIGN"],
        restrictions: [{ element: "CAMPAIGNS_TOTAL_PER_CLIENT", value: 3000 }],
        conditional_capabilities: [],
      },
      read_limitations: {
        inventory_complete: true,
        limited_by: null,
        methods_read: ["Campaigns.get"],
        methods_not_read: ["AdGroups.get", "Keywords.get", "Ads.get", "SEARCH_QUERY_PERFORMANCE_REPORT"],
        statistics_provisional_days: 3,
      },
    },
    metrika: {
      ready: true,
      authority: "VERIFIED",
      access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
      counter_id: "424242",
      goal_id: "1717",
      time_zone: "Europe/Moscow",
      binding: {
        expected_counter_id: "424242",
        api_counter_id: "424242",
        matched: true,
      },
      goal_binding: {
        expected_goal_id: "1717",
        api_goal_id: "1717",
        matched: true,
      },
      observed_at: observedAt,
    },
    campaign_catalog: { total: 1, active: [] },
    performance: {
      period_start: "2026-08-01",
      period_end: "2026-08-20",
      display_metrics: { visits: "10", goal_visits: "2" },
      provenance: {
        source_kind: "METRIKA_REPORTS_API",
        observed_at: observedAt,
        attribution: "last_direct_click_order_dimension",
        timezone: "Europe/Moscow",
        dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
        filters: "ym:s:lastDirectClickOrder=='77'",
        sampling: {
          sampled: false,
          contains_sensitive_data: false,
          sample_share: 1,
          sample_size: 10,
          sample_space: 10,
          data_lag: 0,
        },
      },
    },
  };
}

async function fixtureMarketEvidence() {
  let tick = 0;
  const wordstatBatch = await collectOfficialWordstatBatch({
    token: "e2e-fixture-token",
    clientId: "e2e-fixture-client",
    seeds: [{
      seed_id: "seed-participation",
      cluster_id: "cluster-participation",
      phrase: "участие в выставке",
      dynamics_phrase: "+участие +выставке",
      dynamics_period: "monthly",
      dynamics_from_date: "2024-01-01",
      dynamics_to_date: "2026-07-31",
      operator_profile: "BROAD_CONTAINING",
      region_ids: [213],
      region_names: ["Москва"],
      device: "desktop",
    }],
  }, async (input) => {
    const path = new URL(String(input)).pathname;
    const value = path.endsWith("topRequests")
      ? {
        topRequests: [
          { phrase: "Стенд на выставке", count: 41 },
          { phrase: "участие в выставке", count: 19 },
          { phrase: "заявка на выставку", count: 7 },
        ],
        associations: [{ phrase: "промышленная выставка", count: 13 }],
      }
      : path.endsWith("dynamics")
        ? {
          dynamics: [
            { date: "2025-07-01", count: 105, share: 0.000012 },
            { date: "2026-06-01", count: 120, share: 0.000014 },
            { date: "2026-07-01", count: 150, share: 0.000017 },
          ],
        }
        : {
          regions: [{ regionId: 213, regionName: "Москва", count: 88, share: 0.21, affinityIndex: 127.4 }],
        };
    return new Response(JSON.stringify(value), {
      headers: { "Content-Type": "application/json" },
    });
  }, () => `2026-08-21T10:00:${String(tick++).padStart(2, "0")}.000Z`);
  return {
    wordstat_batch: wordstatBatch,
    demand_clusters: [{
      cluster_id: "cluster-participation",
      semantic_key: {
        product: "выставка",
        need: "участие",
        intent: "commercial",
        offer: "стенд",
      },
    }],
    cost_observations: [],
  };
}

const fixtureLandingAdvisory: LandingAdvisoryAdapter = {
  availability: { available: true, reason: null },
  async resolveHostname() {
    return ["93.184.216.34"];
  },
  async versions() {
    return {
      lighthouse: "12.8.2",
      chrome: "136.0.7103.113",
      lighthouse_config: "p0-lighthouse-desktop-1920x1080-v1",
      axe_core: "4.10.3",
    };
  },
  async inspect(input) {
    input.policy.authorizeRequest({
      url: input.url,
      method: "GET",
      resource_type: "document",
      headers: {},
      body_present: false,
      resolved_addresses: ["93.184.216.34"],
    });
    return {
      requested_url: input.url,
      final_url: input.url,
      redirect_chain: [input.url],
      network_requests: [{
        url: input.url,
        method: "GET",
        resource_type: "document",
        headers: {},
        body_present: false,
        resolved_addresses: ["93.184.216.34"],
      }],
      response_bytes: 100,
      page: {
        title: "Промышленная выставка",
        headings: ["Найдите новых покупателей"],
        text_excerpt: "Оставьте заявку на участие в промышленной выставке.",
        ctas: [{ label: "Оставить заявку", kind: "link" }],
        forms: [{ method: "POST", action_kind: "same_page", fields_count: 4 }],
        metrika_tag_detected: true,
        http_status: 200,
        content_type: "text/html",
      },
      hypotheses: [],
    };
  },
  async runLighthouse() {
    return {
      performance_score: 0.8,
      metrics: {
        first_contentful_paint_ms: 1000,
        largest_contentful_paint_ms: 2000,
        cumulative_layout_shift: 0.05,
        total_blocking_time_ms: 150,
        speed_index_ms: 2400,
      },
    };
  },
  async runAxe() {
    return {
      violations: { count: 0, items: [] },
      passes: { count: 10, items: [] },
      incomplete: { count: 1, items: [{ id: "manual", impact: null, nodes: 1, help: "manual review" }] },
      inapplicable: { count: 2, items: [] },
    };
  },
};

async function fixturePlaybookRelease() {
  return sealCuratedPlaybookRelease({
    schema_version: "p0-curated-playbook-release-v1",
    contract_version: "1.0.0",
    release_id: "fixture-release-package",
    release_version: "1.0.0",
    status: "ACTIVE",
    approval_status: "APPROVED",
    promotion_policy: {
      policy_id: "fixture-promotion-policy",
      policy_version: "1.0.0",
      content_digest: `sha256:${"b".repeat(64)}`,
    },
    approval_attestation: {
      decision_id: "decision-package",
      actor_id: "fixture-steward",
      actor_role: "KNOWLEDGE_STEWARD",
      approved_at: "2026-08-21T09:00:00.000Z",
    },
    superseded_by_release_id: null,
    competitive_sample_rules: [],
    rules: [{
      rule_id: "fixture-qualified_action",
      rule_version: "1.0.0",
      contract_version: "1.0.0",
      state: "ACTIVE",
      approval_status: "APPROVED",
      changed_family: "QUALIFIED_ACTION",
      mechanism: "Deterministic governed fixture treatment.",
      changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      required_capabilities: [],
      evidence_quality: 80,
      priority: 10,
      promotion_policy_id: "fixture-promotion-policy",
      qualified_evidence_refs: ["fixture-evidence:QUALIFIED_ACTION"],
      applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    }],
  });
}

type FixtureProviderCall = {
  request_id: string;
  response_id: string;
  operation: string;
  kind: "READ" | "MUTATION";
  provider_ids: string[];
};

type FixtureAcceptanceEvidence = {
  schema_version: "p0-production-candidate-fixture-evidence-v1";
  scenario: typeof P0_E2E_FIXTURE_SCENARIO;
  official_api_shape: true;
  external_network_requests: 0;
  production_credentials_loaded: false;
  spend_started: false;
  contract_coverage: Array<{
    scenario: string;
    executable_test: string;
  }>;
  calls: FixtureProviderCall[];
};

type FixtureProviderIds = {
  campaignId: string;
  adGroupId: string;
  keywordId: string;
  adId: string;
};

function directResponse(result: Record<string, unknown>) {
  return new Response(JSON.stringify({ result }), {
    headers: { "Content-Type": "application/json" },
  });
}

function recordProviderCall(
  evidence: FixtureAcceptanceEvidence,
  operation: string,
  providerIds: string[],
) {
  const sequence = evidence.calls.length + 1;
  const suffix = String(sequence).padStart(4, "0");
  evidence.calls.push({
    request_id: `fixture-request-${suffix}`,
    response_id: `fixture-response-${suffix}`,
    operation,
    kind: /\.(?:add|suspend|moderate|update)$/u.test(operation) ? "MUTATION" : "READ",
    provider_ids: providerIds,
  });
}

function officialCreateFetcher(
  projection: DirectProjection,
  ids: FixtureProviderIds,
  evidence: FixtureAcceptanceEvidence,
) {
  let adReads = 0;
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { method: string };
    const service = new URL(String(input)).pathname.split("/").at(-1);
    const operation = `${service}.${body.method}`;
    recordProviderCall(evidence, operation, [ids.campaignId, ids.adGroupId, ids.keywordId, ids.adId]);
    if (operation === "campaigns.add") return directResponse({ AddResults: [{ Id: Number(ids.campaignId) }] });
    if (operation === "campaigns.suspend") return directResponse({ SuspendResults: [{ Id: Number(ids.campaignId) }] });
    if (operation === "adgroups.add") return directResponse({ AddResults: [{ Id: Number(ids.adGroupId) }] });
    if (operation === "keywords.add") return directResponse({ AddResults: [{ Id: Number(ids.keywordId) }] });
    if (operation === "ads.add") return directResponse({ AddResults: [{ Id: Number(ids.adId) }] });
    if (operation === "ads.moderate") return directResponse({ ModerateResults: [{ Id: Number(ids.adId) }] });
    if (operation === "campaigns.get") return directResponse({ Campaigns: [{
      Id: Number(ids.campaignId),
      Type: "UNIFIED_CAMPAIGN",
      State: "SUSPENDED",
      Status: "MODERATION",
      ...projection.direct.campaign,
    }] });
    if (operation === "adgroups.get") return directResponse({ AdGroups: [{
      Id: Number(ids.adGroupId),
      CampaignId: Number(ids.campaignId),
      Type: "UNIFIED_AD_GROUP",
      Status: "ACCEPTED",
      ServingStatus: "ELIGIBLE",
      ...projection.direct.ad_group,
    }] });
    if (operation === "keywords.get") return directResponse({ Keywords: [{
      Id: Number(ids.keywordId),
      AdGroupId: Number(ids.adGroupId),
      Status: "ACCEPTED",
      State: "ON",
      ...projection.direct.keyword,
    }] });
    if (operation === "ads.get") {
      adReads += 1;
      return directResponse({ Ads: [{
        Id: Number(ids.adId),
        CampaignId: Number(ids.campaignId),
        AdGroupId: Number(ids.adGroupId),
        Type: "TEXT_AD",
        Status: adReads === 1 ? "DRAFT" : "MODERATION",
        State: "OFF",
        StatusClarification: null,
        ...projection.direct.ad,
      }] });
    }
    throw new Error(`Unexpected E2E Direct operation ${operation}`);
  };
}

function officialPollFetcher(
  projection: DirectProjection,
  ids: FixtureProviderIds,
  evidence: FixtureAcceptanceEvidence,
  status: "ACCEPTED" | "REJECTED" | "PREACCEPTED" | "MODERATION",
  clarification: string | null,
) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { method: string };
    const service = new URL(String(input)).pathname.split("/").at(-1);
    const operation = `${service}.${body.method}`;
    recordProviderCall(evidence, operation, [ids.campaignId, ids.adGroupId, ids.keywordId, ids.adId]);
    if (operation === "campaigns.get") return directResponse({ Campaigns: [{
      Id: Number(ids.campaignId),
      Type: "UNIFIED_CAMPAIGN",
      State: "SUSPENDED",
      Status: status === "ACCEPTED" ? "ACCEPTED" : "MODERATION",
      ...projection.direct.campaign,
    }] });
    if (operation === "adgroups.get") return directResponse({ AdGroups: [{
      Id: Number(ids.adGroupId),
      CampaignId: Number(ids.campaignId),
      Type: "UNIFIED_AD_GROUP",
      Status: "ACCEPTED",
      ServingStatus: "ELIGIBLE",
      ...projection.direct.ad_group,
    }] });
    if (operation === "keywords.get") return directResponse({ Keywords: [{
      Id: Number(ids.keywordId),
      AdGroupId: Number(ids.adGroupId),
      Status: "ACCEPTED",
      State: "ON",
      ...projection.direct.keyword,
    }] });
    if (operation === "ads.get") return directResponse({ Ads: [{
      Id: Number(ids.adId),
      CampaignId: Number(ids.campaignId),
      AdGroupId: Number(ids.adGroupId),
      Type: "TEXT_AD",
      Status: status,
      State: "OFF",
      StatusClarification: clarification,
      ...projection.direct.ad,
    }] });
    throw new Error(`Unexpected E2E Direct poll operation ${operation}`);
  };
}

function officialCorrectionFetcher(
  projection: DirectProjection,
  ids: FixtureProviderIds,
  evidence: FixtureAcceptanceEvidence,
) {
  let adReads = 0;
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { method: string };
    const service = new URL(String(input)).pathname.split("/").at(-1);
    const operation = `${service}.${body.method}`;
    recordProviderCall(evidence, operation, [ids.campaignId, ids.adGroupId, ids.keywordId, ids.adId]);
    if (operation === "campaigns.get") return directResponse({ Campaigns: [{
      Id: Number(ids.campaignId),
      Type: "UNIFIED_CAMPAIGN",
      State: "SUSPENDED",
      Status: "MODERATION",
      ...projection.direct.campaign,
    }] });
    if (operation === "adgroups.get") return directResponse({ AdGroups: [{
      Id: Number(ids.adGroupId),
      CampaignId: Number(ids.campaignId),
      Type: "UNIFIED_AD_GROUP",
      ...projection.direct.ad_group,
    }] });
    if (operation === "keywords.get") return directResponse({ Keywords: [{
      Id: Number(ids.keywordId),
      AdGroupId: Number(ids.adGroupId),
      ...projection.direct.keyword,
    }] });
    if (operation === "ads.get") {
      adReads += 1;
      return directResponse({ Ads: [{
        Id: Number(ids.adId),
        CampaignId: Number(ids.campaignId),
        AdGroupId: Number(ids.adGroupId),
        Type: "TEXT_AD",
        Status: adReads === 1 ? "DRAFT" : "MODERATION",
        State: "OFF",
        StatusClarification: null,
        ...projection.direct.ad,
      }] });
    }
    if (body.method === "update") return directResponse({ UpdateResults: [{ Id: Number({ campaigns: ids.campaignId, adgroups: ids.adGroupId, keywords: ids.keywordId, ads: ids.adId }[String(service) as "campaigns" | "adgroups" | "keywords" | "ads"]) }] });
    if (operation === "ads.moderate") return directResponse({ ModerateResults: [{ Id: Number(ids.adId) }] });
    throw new Error(`Unexpected E2E Direct correction operation ${operation}`);
  };
}

function fixtureAdapters(): {
  adapters: P0ApplicationAdapters;
  evidence: FixtureAcceptanceEvidence;
  advanceClock(milliseconds: number): void;
} {
  let tick = 0;
  let offsetMs = 0;
  const playbookRelease = fixturePlaybookRelease();
  const evidence: FixtureAcceptanceEvidence = {
    schema_version: "p0-production-candidate-fixture-evidence-v1",
    scenario: P0_E2E_FIXTURE_SCENARIO,
    official_api_shape: true,
    external_network_requests: 0,
    production_credentials_loaded: false,
    spend_started: false,
    contract_coverage: [
      {
        scenario: "all-success",
        executable_test: "direct-write.test.mjs · creates a real-shape Direct graph and ends owner-suspended after moderation",
      },
      {
        scenario: "mixed-provider-outcomes",
        executable_test: "test_p0_production_candidate.py · UI mixed acceptance/rejection package",
      },
      {
        scenario: "pending-and-preaccepted",
        executable_test: "direct-write.test.mjs · official PREACCEPTED remains pending before the same suspended graph becomes accepted",
      },
      {
        scenario: "unknown-and-reconciliation",
        executable_test: "execution-safety.test.mjs · holds the account writer after an ambiguous add and forbids blind restart",
      },
      {
        scenario: "system-failure",
        executable_test: "p0-application-contract.test.mjs · package dispatch continues after contained system failure but stops unsafe remaining items behind reconciliation",
      },
      {
        scenario: "correction",
        executable_test: "test_p0_production_candidate.py · renewed Gate and PASS_AFTER_CORRECTION",
      },
    ],
    calls: [],
  };
  const providerIds = new Map<string, FixtureProviderIds>();
  const correctedItemIds = new Set<string>();
  const currentTime = () => new Date(
    Date.UTC(2026, 7, 21, 10, 0, tick) + offsetMs,
  ).toISOString();
  const adapters: P0ApplicationAdapters = {
    now() {
      const value = currentTime();
      tick += 1;
      return value;
    },
    async readContext() {
      return fixtureContext(currentTime());
    },
    async researchSite(url) {
      return {
        url,
        fetched_at: "2026-08-21T10:00:00.000Z",
        title: "Промышленная выставка",
        description: "Выставка помогает производителям найти новых покупателей и партнёров.",
        headings: ["Стать участником выставки"],
        forms_detected: 1,
        text_excerpt: "Руководители производственных компаний могут оставить заявку на участие.",
        pages: [{
          url,
          title: "Промышленная выставка",
          description: "Выставка помогает производителям найти новых покупателей и партнёров.",
          headings: ["Стать участником выставки"],
          forms_detected: 1,
          text_excerpt: "Руководители производственных компаний могут оставить заявку на участие.",
        }],
        research: {
          pages_analyzed: 1,
          links_discovered: 0,
          scope: "FIRST_PARTY_PUBLIC_HTTPS",
        },
      };
    },
    async readCurrencyLimits() {
      return { minimum_weekly_budget_rub: 300 };
    },
    async readMarketEvidence() {
      return fixtureMarketEvidence();
    },
    landingAdvisory: fixtureLandingAdvisory,
    async readPlaybookReleases() {
      return [await playbookRelease];
    },
    externalWriteConfiguration() {
      return { ready: true, blockers: [], account: "owner-account" };
    },
    async createExternalOutcome() {
      throw new Error("Legacy single-Draft execution is unavailable in the E2E fixture.");
    },
    async createPackageItemOutcome(input) {
      const position = input.state.shortlist?.selections.findIndex(
        (item) => item.draft_id === input.selection.draft_id,
      ) ?? 0;
      const base = 7101 + Math.max(position, 0) * 100;
      const ids = {
        campaignId: String(base),
        adGroupId: String(base + 1),
        keywordId: String(base + 2),
        adId: String(base + 3),
      };
      providerIds.set(input.item_execution_id, ids);
      const result = await createSuspendedCampaign(
        { token: "e2e-fixture-only", account: "owner-account" },
        input.projection,
        officialCreateFetcher(input.projection, ids, evidence),
      );
      offsetMs += 61_000;
      return {
        execution_id: input.item_execution_id,
        ...result,
        account_lock: "RELEASED",
      };
    },
    async resubmitCorrectedPackageItemOutcome(input) {
      const sourceIds = input.source_item.provider_ids;
      const ids = {
        campaignId: String(sourceIds.campaign_id),
        adGroupId: String(sourceIds.ad_group_id),
        keywordId: String(sourceIds.keyword_id),
        adId: String(sourceIds.ad_ids[0]),
      };
      providerIds.set(input.item_execution_id, ids);
      correctedItemIds.add(input.item_execution_id);
      const changedPointers = ["/direct/ad/TextAd/Text"];
      const result = await correctSuspendedCampaignAndResubmitModeration(
        { token: "e2e-fixture-only", account: "owner-account" },
        input.projection,
        ids,
        changedPointers,
        officialCorrectionFetcher(input.projection, ids, evidence),
      );
      return {
        execution_id: input.item_execution_id,
        ...result,
        account_lock: "RELEASED",
      };
    },
    async pollPackageItemOutcome(input) {
      const ids = providerIds.get(input.item_execution_id);
      if (!ids) throw new Error("E2E provider IDs are unavailable for moderation poll.");
      const corrected = correctedItemIds.has(input.item_execution_id);
      const status = corrected || input.item.position === 0 ? "ACCEPTED" : "REJECTED";
      const clarification = status === "REJECTED"
        ? "Уточните формулировку обещания в тексте объявления."
        : null;
      const result = await pollSuspendedCampaignModeration(
        { token: "e2e-fixture-only", account: "owner-account" },
        input.projection,
        {
          campaignId: ids.campaignId,
          adGroupId: ids.adGroupId,
          keywordId: ids.keywordId,
          adIds: [ids.adId],
        },
        officialPollFetcher(input.projection, ids, evidence, status, clarification),
      );
      offsetMs += 61_000;
      return {
        execution_id: input.item_execution_id,
        ...result,
        account_lock: "RELEASED",
      };
    },
  };
  return {
    adapters,
    evidence,
    advanceClock(milliseconds: number) {
      offsetMs += milliseconds;
    },
  };
}

function fixtureApplication(scenario: string, key: string) {
  if (scenario !== P0_E2E_FIXTURE_SCENARIO) {
    throw new Error(`Unknown P0 E2E fixture scenario: ${scenario}`);
  }
  const applicationKey = `${scenario}:${key}`;
  let entry = applications.get(applicationKey);
  if (!entry) {
    const fixture = fixtureAdapters();
    entry = {
      application: new P0Application({
        store: new D1P0ApplicationStore(),
        adapters: fixture.adapters,
      }),
      evidence: fixture.evidence,
      advanceClock: fixture.advanceClock,
    };
    applications.set(applicationKey, entry);
  }
  return entry;
}

function withFixtureEvidence(
  value: Awaited<ReturnType<P0Application["query"]>>,
  evidence: FixtureAcceptanceEvidence,
) {
  const state = value.state;
  const calls = structuredClone(evidence.calls);
  const packageExecution = state.package_execution;
  const corrections = state.package_corrections ?? [];
  return {
    ...value,
    fixture_acceptance_evidence: {
      ...structuredClone(evidence),
      operations: {
        reads: calls.filter((call) => call.kind === "READ").map((call) => call.operation),
        mutations: calls.filter((call) => call.kind === "MUTATION").map((call) => call.operation),
        resume_calls: calls.filter((call) => call.operation === "campaigns.resume").length,
      },
      application: {
        document_revision: value.revision,
        strategy_revision_id: state.strategy?.strategy_revision_id ?? null,
        recommendation_set_id: state.recommendation_set?.recommendation_set_id ?? null,
        analytics_evidence_snapshot_id: state.analytics_evidence_snapshot?.snapshot_id ?? null,
        landing_advisory: state.landing_advisory_run ? {
          run_id: state.landing_advisory_run.run_id,
          tool_versions: state.landing_advisory_run.tools?.observed ?? null,
          lighthouse_runs: state.landing_advisory_run.lighthouse?.runs.length ?? 0,
          axe_incomplete: state.landing_advisory_run.axe?.categories.incomplete.count ?? null,
        } : null,
        selected_drafts: state.package_review?.authority.ordered_selections ?? [],
        package: packageExecution ? {
          package_id: packageExecution.package_id,
          package_review_id: packageExecution.package_review_id,
          gate_id: packageExecution.gate_id,
          verdict: packageExecution.verdict,
          status: packageExecution.status,
          items: packageExecution.items.map((item) => ({
            item_execution_id: item.item_execution_id,
            draft_revision_id: item.selection.draft_revision_id,
            publish_fingerprint: item.selection.publish_fingerprint,
            status: item.status,
            ownership: item.ownership,
            campaign_state: item.campaign_state,
            provider_ids: item.provider_ids,
            containment: item.containment,
            account_lock: item.account_lock,
            direct_accepted: item.accountability.direct_accepted,
          })),
        } : null,
        corrections: corrections.map((correction) => ({
          correction_id: correction.correction_id,
          source_item_execution_id: correction.source.item_execution_id,
          source_initial_package_verdict: correction.source.initial_package_verdict,
          corrected_draft_revision_id: correction.corrected_draft?.draft_revision_id ?? null,
          corrected_publish_fingerprint: correction.corrected_draft?.publish_fingerprint ?? null,
          status: correction.status,
          terminal_outcome: correction.terminal_outcome,
          item_statuses: correction.execution?.items.map((item) => item.status) ?? [],
          campaign_states: correction.execution?.items.map((item) => item.campaign_state) ?? [],
        })),
      },
    },
  };
}

export async function fixtureOverview(scenario: string, key: string) {
  const fixture = fixtureApplication(scenario, key);
  const value = await fixture.application.query(`e2e:${scenario}:${key}`);
  return withFixtureEvidence(value, fixture.evidence);
}

export async function fixtureApplyAction(
  scenario: string,
  key: string,
  payload: Record<string, unknown>,
) {
  const fixture = fixtureApplication(scenario, key);
  const value = await fixture.application.command(
    `e2e:${scenario}:${key}`,
    payload as P0Command,
  );
  if (payload.action === "resubmit_package_correction") {
    fixture.advanceClock(61_000);
  }
  return withFixtureEvidence(value, fixture.evidence);
}

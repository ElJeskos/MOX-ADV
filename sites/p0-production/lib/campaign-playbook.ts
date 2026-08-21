export const CURATED_PLAYBOOK_RELEASE_SCHEMA = "p0-curated-playbook-release-v1";
export const CURATED_PLAYBOOK_RELEASE_CONTRACT_VERSION = "1.0.0";
export const PLAYBOOK_RULE_CONTRACT_VERSION = "1.0.0";

export type PlaybookChangedFamily =
  | "MESSAGE_OFFER"
  | "AUDIENCE_SPECIFICITY"
  | "QUALIFIED_ACTION"
  | "CRITERIA_AUTOTARGETING"
  | "PLACEMENT"
  | "EXTENSION";

export type CuratedPlaybookRule = {
  rule_id: string;
  rule_version: string;
  contract_version: string;
  state: "ACTIVE" | "QUARANTINED" | "CONTRADICTED" | "DEACTIVATED";
  approval_status: "APPROVED" | "UNAPPROVED";
  changed_family: PlaybookChangedFamily;
  mechanism: string;
  changed_fields: string[];
  required_capabilities: string[];
  evidence_quality: number;
  priority: number;
  applicability: { campaign_fanout_contract: "campaign-fanout-v1" | string };
};

export type CompetitiveSampleRule = {
  sample_rule_id: string;
  sample_rule_version: string;
  state: "ACTIVE" | "QUARANTINED" | "CONTRADICTED" | "DEACTIVATED";
  approval_status: "APPROVED" | "UNAPPROVED";
  minimum_independent_sources: number;
  required_source_status: "VERIFIED";
  require_pattern_id: true;
  require_evidence_ids: true;
};

export type CuratedPlaybookRelease = {
  schema_version: string;
  contract_version: string;
  release_id: string;
  release_version: string;
  content_digest: string;
  status: "ACTIVE" | "APPROVED" | "QUARANTINED" | "DEACTIVATED" | "SUPERSEDED";
  approval_status: "APPROVED" | "UNAPPROVED";
  approved_by: string | null;
  superseded_by_release_id: string | null;
  rules: CuratedPlaybookRule[];
  competitive_sample_rules: CompetitiveSampleRule[];
};

export type PlaybookAuditRecord = {
  audit_id: string;
  subject_type: "RELEASE" | "RULE" | "COMPETITIVE_SAMPLE_RULE";
  subject_id: string;
  visibility: "HIDDEN";
  reason_code: string;
  release_id: string | null;
  rule_id: string | null;
};

const text = (value: unknown) => String(value ?? "").normalize("NFKC").replace(/\s+/gu, " ").trim();
const semver = (value: unknown) => /^\d+\.\d+\.\d+$/u.test(text(value));
const sha256Pattern = /^sha256:[a-f0-9]{64}$/u;
const allowedFamilies = new Set<PlaybookChangedFamily>([
  "MESSAGE_OFFER",
  "AUDIENCE_SPECIFICITY",
  "QUALIFIED_ACTION",
  "CRITERIA_AUTOTARGETING",
  "PLACEMENT",
  "EXTENSION",
]);

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

async function digest(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const result = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(result)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

export async function sealCuratedPlaybookRelease(
  input: Omit<CuratedPlaybookRelease, "content_digest"> & { content_digest?: string },
): Promise<CuratedPlaybookRelease> {
  const unsigned = Object.fromEntries(Object.entries(input).filter(([key]) => key !== "content_digest"));
  return { ...input, content_digest: await digest(unsigned) } as CuratedPlaybookRelease;
}

async function releaseDigestMatches(release: CuratedPlaybookRelease) {
  if (!sha256Pattern.test(text(release.content_digest))) return false;
  const unsigned = Object.fromEntries(Object.entries(release).filter(([key]) => key !== "content_digest"));
  return release.content_digest === await digest(unsigned);
}

function releaseAudit(release: Partial<CuratedPlaybookRelease>, reasonCode: string): PlaybookAuditRecord {
  const releaseId = text(release.release_id) || null;
  return {
    audit_id: `playbook-release:${releaseId ?? "unknown"}:${reasonCode}`,
    subject_type: "RELEASE",
    subject_id: releaseId ?? "UNKNOWN_RELEASE",
    visibility: "HIDDEN",
    reason_code: reasonCode,
    release_id: releaseId,
    rule_id: null,
  };
}

function ruleAudit(releaseId: string, rule: Partial<CuratedPlaybookRule>, reasonCode: string): PlaybookAuditRecord {
  const ruleId = text(rule.rule_id) || "UNKNOWN_RULE";
  return {
    audit_id: `playbook-rule:${releaseId}:${ruleId}:${reasonCode}`,
    subject_type: "RULE",
    subject_id: ruleId,
    visibility: "HIDDEN",
    reason_code: reasonCode,
    release_id: releaseId,
    rule_id: ruleId,
  };
}

function sampleRuleAudit(releaseId: string, rule: Partial<CompetitiveSampleRule>, reasonCode: string): PlaybookAuditRecord {
  const ruleId = text(rule.sample_rule_id) || "UNKNOWN_SAMPLE_RULE";
  return {
    audit_id: `playbook-sample-rule:${releaseId}:${ruleId}:${reasonCode}`,
    subject_type: "COMPETITIVE_SAMPLE_RULE",
    subject_id: ruleId,
    visibility: "HIDDEN",
    reason_code: reasonCode,
    release_id: releaseId,
    rule_id: ruleId,
  };
}

function ruleExclusionReason(rule: Partial<CuratedPlaybookRule>) {
  if (rule.contract_version !== PLAYBOOK_RULE_CONTRACT_VERSION) return "PLAYBOOK_RULE_UNKNOWN_VERSION";
  if (!text(rule.rule_id) || !semver(rule.rule_version) || !allowedFamilies.has(rule.changed_family as PlaybookChangedFamily)) {
    return "PLAYBOOK_RULE_MALFORMED";
  }
  if (!text(rule.mechanism) || !Array.isArray(rule.changed_fields) || rule.changed_fields.length === 0
    || rule.changed_fields.some((pointer) => !text(pointer).startsWith("/direct/"))
    || !Array.isArray(rule.required_capabilities)
    || !Number.isFinite(rule.evidence_quality) || Number(rule.evidence_quality) < 0 || Number(rule.evidence_quality) > 100
    || !Number.isFinite(rule.priority)) {
    return "PLAYBOOK_RULE_MALFORMED";
  }
  if (rule.approval_status !== "APPROVED") return "PLAYBOOK_RULE_UNAPPROVED";
  if (rule.state === "QUARANTINED") return "PLAYBOOK_RULE_QUARANTINED";
  if (rule.state === "CONTRADICTED") return "PLAYBOOK_RULE_CONTRADICTED";
  if (rule.state === "DEACTIVATED") return "PLAYBOOK_RULE_DEACTIVATED";
  if (rule.state !== "ACTIVE") return "PLAYBOOK_RULE_UNKNOWN_STATE";
  if (rule.applicability?.campaign_fanout_contract !== "campaign-fanout-v1") return "PLAYBOOK_RULE_INCOMPATIBLE";
  return null;
}

function sampleRuleExclusionReason(rule: Partial<CompetitiveSampleRule>) {
  if (!text(rule.sample_rule_id) || !semver(rule.sample_rule_version)
    || !Number.isSafeInteger(rule.minimum_independent_sources) || Number(rule.minimum_independent_sources) < 2
    || rule.required_source_status !== "VERIFIED" || rule.require_pattern_id !== true || rule.require_evidence_ids !== true) {
    return "COMPETITIVE_SAMPLE_RULE_MALFORMED";
  }
  if (rule.approval_status !== "APPROVED") return "COMPETITIVE_SAMPLE_RULE_UNAPPROVED";
  if (rule.state !== "ACTIVE") return `COMPETITIVE_SAMPLE_RULE_${text(rule.state) || "UNKNOWN_STATE"}`;
  return null;
}

export async function resolveCuratedPlaybookReleases(releases: CuratedPlaybookRelease[]) {
  const audits: PlaybookAuditRecord[] = [];
  const accepted: CuratedPlaybookRelease[] = [];
  for (const release of releases) {
    let reason: string | null = null;
    if (release.schema_version !== CURATED_PLAYBOOK_RELEASE_SCHEMA
      || release.contract_version !== CURATED_PLAYBOOK_RELEASE_CONTRACT_VERSION) reason = "PLAYBOOK_RELEASE_UNKNOWN_VERSION";
    else if (!text(release.release_id) || !semver(release.release_version) || !Array.isArray(release.rules)
      || !Array.isArray(release.competitive_sample_rules) || !await releaseDigestMatches(release)) reason = "PLAYBOOK_RELEASE_MALFORMED";
    else if (release.approval_status !== "APPROVED" || !text(release.approved_by)) reason = "PLAYBOOK_RELEASE_UNAPPROVED";
    else if (release.status !== "ACTIVE") reason = `PLAYBOOK_RELEASE_${text(release.status) || "UNKNOWN_STATE"}`;
    else if (text(release.superseded_by_release_id)) reason = "PLAYBOOK_RELEASE_SUPERSEDED";
    if (reason) audits.push(releaseAudit(release, reason));
    else accepted.push(release);
  }
  if (accepted.length !== 1) {
    if (accepted.length === 0) audits.push(releaseAudit({}, "PLAYBOOK_NO_ACTIVE_APPROVED_RELEASE"));
    for (const release of accepted) audits.push(releaseAudit(release, "PLAYBOOK_MULTIPLE_ACTIVE_APPROVED_RELEASES"));
    return { release: null, rules: [] as CuratedPlaybookRule[], competitiveSampleRules: [] as CompetitiveSampleRule[], audits };
  }
  const release = accepted[0];
  const rules: CuratedPlaybookRule[] = [];
  for (const rule of release.rules) {
    const reason = ruleExclusionReason(rule);
    if (reason) audits.push(ruleAudit(release.release_id, rule, reason));
    else rules.push(rule);
  }
  const competitiveSampleRules: CompetitiveSampleRule[] = [];
  for (const rule of release.competitive_sample_rules) {
    const reason = sampleRuleExclusionReason(rule);
    if (reason) audits.push(sampleRuleAudit(release.release_id, rule, reason));
    else competitiveSampleRules.push(rule);
  }
  return {
    release,
    rules: rules.sort((left, right) => left.priority - right.priority
      || right.evidence_quality - left.evidence_quality
      || left.rule_id.localeCompare(right.rule_id)),
    competitiveSampleRules: competitiveSampleRules.sort((left, right) => left.sample_rule_id.localeCompare(right.sample_rule_id)),
    audits,
  };
}

const BUNDLED_RELEASE: Omit<CuratedPlaybookRelease, "content_digest"> = {
  schema_version: CURATED_PLAYBOOK_RELEASE_SCHEMA,
  contract_version: CURATED_PLAYBOOK_RELEASE_CONTRACT_VERSION,
  release_id: "p0-curated-playbook-2026-08",
  release_version: "1.0.0",
  status: "ACTIVE",
  approval_status: "APPROVED",
  approved_by: "KNOWLEDGE_STEWARD",
  superseded_by_release_id: null,
  rules: [
    {
      rule_id: "qualified-action-v1",
      rule_version: "1.0.0",
      contract_version: PLAYBOOK_RULE_CONTRACT_VERSION,
      state: "ACTIVE",
      approval_status: "APPROVED",
      changed_family: "QUALIFIED_ACTION",
      mechanism: "Явное квалифицированное действие может точнее отделить коммерческий спрос.",
      changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      required_capabilities: [],
      evidence_quality: 82,
      priority: 10,
      applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    },
    {
      rule_id: "audience-specificity-v1",
      rule_version: "1.0.0",
      contract_version: PLAYBOOK_RULE_CONTRACT_VERSION,
      state: "ACTIVE",
      approval_status: "APPROVED",
      changed_family: "AUDIENCE_SPECIFICITY",
      mechanism: "Явное обращение к принимающей решение роли может повысить релевантность сообщения.",
      changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      required_capabilities: [],
      evidence_quality: 76,
      priority: 20,
      applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    },
    {
      rule_id: "message-offer-contradicted-v1",
      rule_version: "1.0.0",
      contract_version: PLAYBOOK_RULE_CONTRACT_VERSION,
      state: "CONTRADICTED",
      approval_status: "APPROVED",
      changed_family: "MESSAGE_OFFER",
      mechanism: "Историческая framing-гипотеза сохранена только для audit.",
      changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      required_capabilities: [],
      evidence_quality: 70,
      priority: 30,
      applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    },
  ],
  competitive_sample_rules: [{
    sample_rule_id: "competitive-pattern-independent-sources",
    sample_rule_version: "1.0.0",
    state: "ACTIVE",
    approval_status: "APPROVED",
    minimum_independent_sources: 2,
    required_source_status: "VERIFIED",
    require_pattern_id: true,
    require_evidence_ids: true,
  }],
};

export async function bundledCuratedPlaybookReleases(): Promise<CuratedPlaybookRelease[]> {
  return [await sealCuratedPlaybookRelease(structuredClone(BUNDLED_RELEASE))];
}

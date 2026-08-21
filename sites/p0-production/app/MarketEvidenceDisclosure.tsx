/* eslint-disable @typescript-eslint/no-explicit-any -- revisioned evidence payloads are validated by the server contract. */
type MarketEvidence = Record<string, any>;

function frequencySummary(frequency: MarketEvidence) {
  const value = frequency.observed_unique_count?.value;
  return typeof value === "number" ? `${value}+ запросов` : "Частотность недоступна";
}

function scopeSummary(scope: MarketEvidence) {
  const regions = Array.isArray(scope.region_names) && scope.region_names.length
    ? scope.region_names.join(", ")
    : "регион не подтверждён";
  return `${regions} · ${scope.device || "device unknown"} · ${scope.operator_profile || "operator unknown"}`;
}

function costSummary(cost: MarketEvidence) {
  if (cost.status !== "AVAILABLE" || !cost.range) return "Сопоставимая оценка цены недоступна";
  return `${cost.range.low}–${cost.range.high} ${cost.currency}`;
}

export function MarketEvidenceDisclosure({ evidence, context = "model" }: { evidence: MarketEvidence; context?: "model" | "draft" }) {
  const frequency = evidence.frequency || {};
  const cost = evidence.cost || {};
  const scopes = Array.isArray(frequency.scopes) ? frequency.scopes : [];
  const rows = Array.isArray(frequency.unique_assigned_rows) ? frequency.unique_assigned_rows : [];
  const gaps = Array.isArray(frequency.gaps) ? frequency.gaps : [];
  const costReasons = Array.isArray(cost.missing_or_conflict_reasons) ? cost.missing_or_conflict_reasons : [];
  return <section className="market-evidence" aria-label={context === "model" ? "Спрос и стоимость до запуска" : "Evidence Campaign Draft"}>
    <header>
      <div><p className="eyebrow">Official scoped market evidence</p><h4>Спрос и стоимость до запуска</h4></div>
      <strong className={String(frequency.status || "UNAVAILABLE").toLowerCase()}>{frequency.status || "UNAVAILABLE"}</strong>
    </header>
    <div className="market-evidence-grid">
      <article>
        <span>Wordstat · {frequency.method || "/v1/topRequests"}</span>
        <strong>{frequencySummary(frequency)}</strong>
        <small>{frequency.observed_unique_count?.semantics || "UNAVAILABLE — не нулевой спрос"}</small>
        <small>{rows.length} уникальных assigned rows · каждая учтена не более одного раза</small>
      </article>
      <article>
        <span>Qualified pre-launch cost</span>
        <strong>{costSummary(cost)}</strong>
        <small>{cost.compact_source || "UNAVAILABLE"}</small>
        <small>{cost.aggregation || "FIRST_QUALIFIED_SOURCE_NO_AVERAGING"}</small>
      </article>
    </div>
    <details>
      <summary>Раскрыть scope, snapshot batch и ограничения частотности</summary>
      <div className="market-evidence-detail">
        <p><b>Snapshot batch:</b> <code>{frequency.snapshot_batch_id || evidence.snapshot_batch_id || "UNAVAILABLE"}</code></p>
        {scopes.length ? <ul>{scopes.map((scope: MarketEvidence, index: number) => <li key={`${scope.scope_fingerprint || "scope"}-${index}`}>{scopeSummary(scope)} · {scope.observed_unique_count?.value ?? "UNAVAILABLE"}+</li>)}</ul> : <p>Operator/region/device scope недоступен — это не frequency zero.</p>}
        <p><b>Window:</b> последние 30 дней; точный конец окна API не раскрывает ({frequency.source_window_end || "undisclosed_by_api"}).</p>
        <p><b>Semantics:</b> LOWER_BOUND_OBSERVED_TOP_ROWS; это запросы, не пользователи, клики или гарантированные показы.</p>
        <p><b>Dynamics:</b> {frequency.seasonality?.status || "UNAVAILABLE"} · /v1/dynamics · DYNAMICS_BROAD. <b>Regions:</b> {frequency.geo_evidence?.status || "UNAVAILABLE"} · /v1/regions.</p>
        {gaps.length > 0 && <ul className="limitations">{gaps.map((gap: MarketEvidence, index: number) => <li key={`${gap.code}-${index}`}>{gap.code}: {gap.detail}</li>)}</ul>}
      </div>
    </details>
    <details>
      <summary>Раскрыть источник, сценарий и scope стоимости</summary>
      <div className="market-evidence-detail">
        {cost.status === "AVAILABLE" ? <>
          <p><b>Source:</b> {cost.compact_source}</p>
          <p><b>Scenario:</b> {cost.scenario}</p>
          <p><b>Scope:</b> <code>{JSON.stringify(cost.scope)}</code></p>
          <p><b>As of:</b> {cost.as_of} · <b>VAT {cost.vat_treatment}</b> · <b>sample:</b> {cost.sample_size?.value} {cost.sample_size?.unit}</p>
          <p><b>Range:</b> {cost.range?.kind}; источники не усредняются ({cost.aggregation}).</p>
        </> : <>
          <p><b>Сопоставимая оценка цены недоступна.</b> Нулевые или выдуманные bounds не подставляются.</p>
          {costReasons.length > 0 && <ul className="limitations">{costReasons.map((reason: string) => <li key={reason}>{reason}</li>)}</ul>}
        </>}
      </div>
    </details>
    {context === "draft" && evidence.packing && <details>
      <summary>Раскрыть deterministic delivery packing</summary>
      <div className="market-evidence-detail"><code>{JSON.stringify(evidence.packing)}</code></div>
    </details>}
  </section>;
}

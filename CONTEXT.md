# MOX-ADV

MOX-ADV is a controlled advertising optimization context that links Yandex Direct campaign facts with Yandex Metrica conversion facts and turns them into explainable, policy-bounded decisions.

## Language

**Test Scenario**:
A coherent set of operator-supplied campaign and conversion facts used to observe how the test control loop responds without affecting a real campaign.
_Avoid_: Fake metrics, mock campaign

**Integrated Prototype**:
The persistent Dashboard shell in which each completed module replaces its matching Test Scenario module while not-yet-developed modules remain explicitly simulated. Real and simulated state never mix within one module.
_Avoid_: Disposable prototype, all-production Dashboard

**Production Module**:
A module whose data and available actions are backed by real connected business state. A control belongs here only when it invokes a supported real operation or edits real business input that the agent actually consumes.
_Avoid_: Test Scenario module, roadmap mock, inert control

**Agent-Owned Work**:
Work within the active Mandate that is permitted, bounded, reversible or containable, observable, and supported by sufficient evidence. The agent completes it end to end without turning routine research, synthesis, or execution into operator tasks.
_Avoid_: Assisted questionnaire, routine approval, recommendation-only workflow

**Critical Decision**:
A decision that grants or expands authority, exceeds the active Mandate, creates material irreversible exposure, or chooses among materially different business outcomes without sufficient evidence. It belongs to a named human owner.
_Avoid_: Every external write, routine confirmation, missing form field

**Material Uncertainty**:
Missing or conflicting evidence that can change a material business outcome and cannot be resolved from permitted sources with sufficient confidence.
_Avoid_: Any unknown, inconvenient research, low-risk ambiguity

**Human Decision Gate**:
A pause that delegates one Critical Decision or Material Uncertainty to a named human together with the agent's prepared options, evidence, confidence, consequences, and recommendation.
_Avoid_: Blank form, generic approval, routine data collection

**Campaign Strategy**:
An operator-approved statement of the real offer, audience, qualified outcome, exclusions, business goal, geography, period, landing page, budget, target result cost, and core message that guides a Recommendation Set of one or more Campaign Drafts.
_Avoid_: Single-campaign instruction, Yandex payload, technical bidding configuration

**Campaign Draft**:
The editable, pre-approval representation of exactly one real campaign and the supported child objects that MOX-ADV will create in Yandex Direct. Every control changes either the approved Campaign Strategy or a field that will be published.
_Avoid_: Test Scenario campaign, unsupported future configuration, silent publish subset

**Analytics Evidence Snapshot**:
An immutable, versioned set of normalized observations, claims, provenance, confidence dimensions, conflicts, and known gaps for one analysis moment. Every material recommendation can be traced back through it to permitted evidence.
_Avoid_: Unversioned analytics narrative, LLM memory, hidden chain of thought

**Recommendation Set**:
The explainable result that ties one Campaign Strategy and one Analytics Evidence Snapshot to eligible, suppressed, and ranked Campaign Drafts. It supports shortlist selection but is not an atomic external operation.
_Avoid_: One mandatory campaign, score-only recommendation, transactional campaign batch

**Pre-launch Viability Score**:
A versioned, deterministic `0–100` comparative priority for hard-eligible Campaign Drafts within one Recommendation Set, calculated from frozen pre-launch evidence and policy with rank, evidence quality, and sensitivity bounds. It is not a probability or performance forecast; hard blockers and landing-page advice remain separate.
_Avoid_: Success probability, predicted CPA or profit, platform optimization score, eligibility gate

**Derived KPI**:
A performance indicator calculated from Test Scenario facts, such as CTR, CPC, conversion rate, CPA, or budget utilization.
_Avoid_: Entered KPI, editable result

**Monitoring Cycle**:
One linked measurement, analysis, decision, policy evaluation, and recorded outcome for a campaign.

**Decision Trigger**:
A deterministic condition that makes a scheduled Monitoring Cycle eligible to continue into a decision.
_Avoid_: Prompt, alert rule

**Test Autopilot**:
A recurring test-only Monitoring Cycle that uses saved Test Scenario facts and Decision Triggers and can apply changes only to a sealed fake target.
_Avoid_: Production automation, live campaign manager

**Autonomous Campaign Operator (Автономный оператор кампаний)**:
A production operating role that continuously manages eligible campaigns in one Yandex Direct account within revocable operator-authorized limits and escalates exceptions.
_Avoid_: Test Autopilot, unrestricted agent

**Mandate**:
An immutable operator-approved authorization for one advertiser scope that fixes allowed action classes, validity period, spend exposure, change limits, and experiment-loss limits. It may narrow but never weaken the Gate 0 Boundary.
_Avoid_: Global autonomy switch, self-renewing approval, budget setting

**Account Write Freeze**:
An account-wide safety state that blocks new value-seeking writes while preserving campaign delivery, observation, reconciliation, and allowed containment.
_Avoid_: Account pause, campaign shutdown

**Emergency Account Pause**:
An exceptional state that stops delivery for all eligible campaigns when explicit operator authority or confirmed account-wide uncontrolled spend or compromise makes continued delivery unsafe.
_Avoid_: Account Write Freeze, ordinary campaign pause

**Campaign Effectiveness Profile**:
An immutable operator-approved revision of the effectiveness goals, metric roles, targets, constraints, source-quality rules, and conflict policy for one campaign. An account-level default may initialize a revision but never changes an approved campaign implicitly.
_Avoid_: One global metric set for every campaign, mutable KPI settings

**Operational Hypothesis**:
A versioned, testable claim that a bounded campaign treatment will cause a defined outcome for an eligible population under named conditions. Its result remains scoped evidence and never expands execution authority by itself.
_Avoid_: Recommendation, code change, policy rule, universal playbook

**Hypothesis Preregistration**:
The immutable pre-experiment commitment to the mechanism, treatment contrast, primary decision metric, guardrails, comparator, maturity rule, and statistical decision rule.
_Avoid_: Editable experiment note, post-hoc analysis plan

**Knowledge Claim**:
A versioned, provenance-linked assertion that keeps its observation, Hypothesis Preregistration, scoped result, causal status, applicability, replications, and contradictions without rewriting prior evidence.
_Avoid_: Winner, universal rule, mutable experiment note

**Playbook Rule**:
An immutable, scoped template admitted from qualified replicated evidence that may rank or draft a new Operational Hypothesis or typed proposal but never grants execution authority by itself.
_Avoid_: Auto-apply command, protective policy, Mandate, universal playbook

**Promotion Policy**:
A versioned, human-approved governance policy that defines evidence gates and per-family activation, demotion, quarantine, and reactivation authority for Playbook Rules without granting campaign execution authority.
_Avoid_: Runtime execution policy, Mandate, mutable threshold, human evidence override

**Knowledge Steward**:
A named human governance role appointed by the Mandate owner to approve Promotion Policy, human-gated playbook releases, delegations, and semantic retirement, and to stop playbook use without overriding evidence.
_Avoid_: Knowledge Evaluator, Autonomous Campaign Operator, anonymous approval group

**Decision Record**:
The durable operator-facing account of which facts and Decision Triggers were considered, what action was proposed, why it was chosen, and whether policy allowed it.
_Avoid_: Debug log, model reasoning

**Gate 0 Boundary**:
The approved safety limits that operator-edited rules may tighten but never weaken.
_Avoid_: Default settings, suggestions

# MOX-ADV

MOX-ADV is a controlled advertising optimization context that links Yandex Direct campaign facts with Yandex Metrica conversion facts and turns them into explainable, policy-bounded decisions.

## Language

**Test Scenario**:
A coherent set of operator-supplied campaign and conversion facts used to observe how the test control loop responds without affecting a real campaign.
_Avoid_: Fake metrics, mock campaign

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

**Campaign Effectiveness Profile**:
The operator-approved set of effectiveness metrics and targets for one campaign, optionally initialized from an account-level default.
_Avoid_: One global metric set for every campaign

**Decision Record**:
The durable operator-facing account of which facts and Decision Triggers were considered, what action was proposed, why it was chosen, and whether policy allowed it.
_Avoid_: Debug log, model reasoning

**Gate 0 Boundary**:
The approved safety limits that operator-edited rules may tighten but never weaken.
_Avoid_: Default settings, suggestions

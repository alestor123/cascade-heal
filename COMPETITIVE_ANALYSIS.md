# COMPETITIVE_ANALYSIS.md — CascadeHeal Market Positioning

> Web-researched 2026-08-22. Claims verified against public sources, not asserted from memory.

## What Already Exists

| Category | Products | Capabilities |
|---|---|---|
| **Smart Payment Routing** | Razorpay Optimizer, Cashfree, Primer.io | AI-based dynamic routing, cascading retries, multi-PSP failover |
| **Gateway Orchestration** | IXOPAY, Spreedly, Hyperswitch, CellPoint | Multi-acquirer routing, token vaults, rules-based guardrails |
| **Payment Aggregators** | BillDesk, PayU, Paytm B2B | Multi-bank routing, reconciliation |
| **Payment Retry** | Stripe Radar, Recurly | Subscription retry with backoff |
| **Fraud Detection** | Razorpay Fraud Shield, Signifyd, Clevertap | ML fraud scoring |
| **Cart Recovery** | Klaviyo, CartStack | Email/SMS abandoned cart |
| **Payment Analytics** | Razorpay Analytics, Cashfree | Success rate trends, dashboards |
| **Resilience Monitoring** | Site24x7, PagerDuty | Gateway uptime alerts |

## What We Do NOT Claim as Novel
- "First-ever intelligent payment routing" — Razorpay Optimizer has AI routing (confirmed)
- "AI-powered payment recovery" — email/SMS recovery tools exist
- "Multi-rail routing" — all orchestration platforms do this
- "Payment cascading" — Razorpay Optimizer explicitly offers this

## The Defensible Gap

**What no existing product provides as a package:**

1. **Auditable guardrail layer testable in CI/CD** — Razorpay Optimizer routing is a black box. CascadeHeal's `guardrail_policy.py` has zero LLM dependency, is unit-testable adversarially with no API key, and every safety limit is a Python constant in version-controlled source code.

2. **Structured failure taxonomy with confidence scores surfaced to merchants** — existing gateways show aggregate success rates. CascadeHeal shows: "This failure was BANK_TIMEOUT with 0.91 confidence, blast radius 47 transactions, rerouted to UPI (health 0.97)."

3. **Append-only decision ledger for compliance** — every routing decision, guardrail verdict (PASS/VETO + reason), and recovery action is recorded immutably.

4. **Customer-facing recovery loop triggered by AI decision** — gateway cascading is silent at the API level. CascadeHeal generates a signed, single-use, 90-second recovery link for the customer, closing the human loop.

5. **Hard-coded safety envelope with adversarial test suite** — limits are constants in source code, not configurable sliders. Tests prove an LLM recommendation for 20% discount or INVALID_OTP retry is vetoed.

## How CascadeHeal Should Position Itself

**Do not say:** "We do AI payment routing better than Razorpay."

**Say instead:** "CascadeHeal is a *safety layer* that sits above any payment gateway and adds: structured failure intelligence with confidence scores, a provably LLM-independent guardrail engine (testable in CI), an immutable audit ledger, and a customer recovery loop. It complements Razorpay Optimizer rather than replacing it — targeting merchants who need auditable, compliance-grade payment resilience."

**Primary target:** Mid-market Indian merchants with audit/compliance requirements (fintech, insurance, healthcare payments), not startups using basic Razorpay dashboard.

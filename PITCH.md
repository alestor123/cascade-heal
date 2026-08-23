# PITCH.md — CascadeHeal Pitch Assets

---

## 10-Second Pitch

"CascadeHeal detects failing payment rails in real time, reroutes traffic intelligently, and recovers customers — but every AI decision passes through a codified safety layer that cannot be bypassed, tested in CI, and logged immutably."

---

## 30-Second Pitch

"When HDFC NetBanking starts failing at 3 AM, most merchants find out from angry customers 20 minutes later. CascadeHeal detects the failure statistically within seconds, classifies whether it's infrastructure or customer error, reroutes new transactions to a healthy rail, and sends affected customers a signed one-tap payment link — all while a code-enforced guardrail prevents it from ever retrying a fraud case or exceeding 1 retry per order. Every decision is auditable."

---

## 60-Second Pitch

"India processes 14 billion UPI transactions per month. Every 1% failure rate is millions of lost transactions. The problem isn't detection — it's safe, intelligent recovery at the moment of failure.

CascadeHeal is a payment resilience engine built around three ideas the market doesn't address together: first, a CUSUM statistical detector that identifies sustained rail degradation in under 90 seconds without waiting for an alert threshold to be manually set. Second, an LLM that maps ambiguous, bank-specific error signals to a structured failure taxonomy with a confidence score — distinguishing a bank timeout from an invalid OTP, which is critical because you must never retry the latter. Third, a guardrail engine that is provably independent of the AI — pure Python, zero API dependencies, 107 adversarial unit tests, and 0 violations in our benchmark.

The result: in our 1,000-transaction benchmark, CascadeHeal achieves 100% recovery rate on reroutable failures vs 0% for static rule engines, with ₹0 false-positive cost vs ₹37,500, and 0 guardrail violations — all verified with real code execution."

---

## 3-Minute Pitch

### The Problem
Indian payment failures cost merchants real revenue. A 10% failure rate on a ₹10L GMV day means ₹1L in lost transactions. The current state: merchants get Razorpay's aggregate dashboard, see "HDFC success rate dropped," and manually intervene — if they're awake. Gateway cascading exists, but it's silent, opaque, and will retry a fraud case the same as a timeout.

### The Gap
Existing solutions have routing intelligence but lack the safety envelope to deploy it confidently:
- Routing decisions are black boxes — you can't test them adversarially in CI
- No structured failure intelligence surfaced to merchants
- No customer-facing recovery loop after the failure
- No immutable compliance audit trail

### What CascadeHeal Does
Three layers working together:

**Detection**: A CUSUM sliding-window detector monitors every payment rail continuously. Unlike a simple threshold alert, CUSUM detects *sustained drift* — it won't fire on a single bad request, but it will fire within 3-5 failures of a genuine outage, producing a `DriftSignal` with the exact error type breakdown.

**Intelligence**: When CUSUM fires, an LLM call at temperature=0.0 classifies the failure into our 8-value taxonomy: BANK_TIMEOUT, GATEWAY_TIMEOUT, INVALID_OTP, SUSPECTED_FRAUD, etc. — with a confidence score and human-readable explanation. This is where AI earns its place: mapping ambiguous, bank-specific error strings to actionable classifications that if-else statements would need per-bank hardcoding to approximate.

**Safety**: Every proposed action passes through `guardrail_policy.py` — a pure Python function with zero LLM dependency, testable with no API key. It enforces: max 1 retry per order, max 5% discount, 90-second recovery link TTL, hard block on all security-sensitive error codes regardless of AI classification. Every decision — including vetoes — is written to an append-only SQLite audit ledger.

### The Numbers (SIMULATED, 1,000 transactions)
- Recovery rate: 100% vs 0% (static rules)
- False-positive cost: ₹0 vs ₹37,500
- Guardrail violations: **0** (assertion in automated test)
- Guardrail evaluation latency: 2.51 µs [REAL/MEASURED]

### Why It's Defensible
The key claim is not "AI routing" — that's commoditized. The defensible claim is: **the safety envelope is provably independent of the AI**. You can read every limit in source code, test every adversarial bypass in 0.23 seconds, and audit every decision in the immutable log. That's what compliance-grade payment infrastructure looks like.

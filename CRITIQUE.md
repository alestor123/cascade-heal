# CRITIQUE.md — Phase 0: Self-Adversarial Pre-Mortem

> **Status:** Written before a single line of application code was created.  
> Date: 2026-08-22

---

## 0.1 Weakness Inventory

Each weakness is tagged **CRITICAL / HIGH / MEDIUM / LOW**. For each: the attack vector, the required defense artifact, the concrete fix, and hackathon ROI assessment.

---

### W-01 — "Isn't this just a wrapper around Razorpay?"  **[CRITICAL]**

**Judge attack:** "You're hitting the Razorpay API, reading their error codes, and rerouting through Razorpay again. This is literally a thin middleware around one vendor."

**Defense artifact required:** Architectural diagram showing the system is gateway-agnostic and the intelligence layer sits *above* any gateway. The guardrail engine and state machine must be runnable with zero Razorpay calls.

**Concrete fix:** The core modules (`anomaly_engine.py`, `guardrail_policy.py`, `state_machine.py`, `agent_core.py`) must have zero import dependency on `razorpay_gateway.py`. The gateway module is a *plugin* — swappable. Unit tests prove this because they run the full pipeline without touching any gateway API.

**Worth implementing?** YES — this is structural, and the boundary is enforced by Python import rules. Low effort, high defense value.

---

### W-02 — "Razorpay already does Smart Routing — what's different?"  **[CRITICAL]**

**Judge attack:** "Razorpay Optimizer has AI-powered dynamic routing, cascading payments, failover, multi-gateway orchestration — you've just described their product page."

**Defense artifact required:** `COMPETITIVE_ANALYSIS.md` with specific, sourced differentiation.

**Research finding (sourced):** Razorpay Optimizer *does* have: AI routing, cascading retries, failover, multi-PSP orchestration, unified reconciliation dashboard. This is confirmed and documented.

**What Razorpay does NOT have (defensible gap):**
1. A **provably LLM-independent, codified guardrail layer** — Razorpay's routing is a black box; you cannot unit-test their routing decisions with adversarial inputs in your own CI/CD pipeline.
2. **Structured root-cause taxonomy** surfaced to merchants with per-failure classification and confidence score — Razorpay shows aggregate metrics, not "this specific failure was BANK_TIMEOUT with 0.91 confidence, blast radius 47 transactions."
3. **Auditable, append-only decision ledger** — every routing decision, guardrail verdict (pass/veto + reason), and recovery action is cryptographically sequenced and exportable.
4. **Customer-facing recovery flow** triggered by the AI decision — Razorpay cascades silently at the API level. CascadeHeal generates a signed, single-use, TTL-bound recovery link for the *customer*, closing the human loop.
5. **Hard-coded safety envelope tested in CI** — the limits (max 1 retry, max 5% discount, 90-second TTL) are unit-tested with adversarial LLM outputs, not configurable via dashboard sliders.

**Concrete fix:** Reposition CascadeHeal away from "AI routing" (commoditized) toward "**guardrail-governed, auditable payment resilience with structured failure intelligence and customer recovery loop**." Routing is a *consequence* of the classification, not the product.

**Worth implementing?** YES — this reframing costs nothing in code; it's a positioning and documentation decision.

---

### W-03 — "Payment retries already exist industry-wide."  **[HIGH]**

**Judge attack:** "Stripe, Adyen, Checkout.com, every gateway does automatic retries. Why build this?"

**Defense:** Standard gateway retries are: (a) blind to failure cause, (b) will retry INVALID_OTP and fraud failures (dangerous), (c) operate within a single gateway's network, (d) have no auditable guardrail preventing them. CascadeHeal's retry is: cause-aware, safety-gated, cross-rail, auditable, and customer-loop-closing.

**Concrete fix:** The demo must show an `INVALID_OTP` failure being *refused* retry, with a visible audit log entry. This is the proof point.

**Worth implementing?** YES — this is already in the spec and is 30 minutes of work.

---

### W-04 — "Where is the AI, actually?"  **[CRITICAL]**

**Judge attack:** "Show me the model. What does it take as input, what does it output, what would change if you replaced it with if-else?"

**Defense artifact required:** `ARCHITECTURE.md` section "AI is used for X. AI is NOT used for Y."

**Concrete fix:**
- **CUSUM anomaly detection**: NOT AI — statistical method. Say so explicitly. Justify: CUSUM is more explainable and defensible for a hackathon than a trained ML model.
- **Rail health scoring**: NOT AI — exponentially-weighted Bayesian estimator. Say so.
- **Failure classification**: THIS IS WHERE THE LLM EARNS ITS PLACE. Input: structured telemetry payload (error code, latency, rail, issuer, pattern). Output: fixed JSON taxonomy `{classification: "BANK_TIMEOUT", confidence: 0.91, blast_radius: 47, reasoning: "..."}`. Temperature: 0.0. If replaced with if-else: you'd need to hardcode every error code from every Indian bank and update it manually. The LLM handles ambiguous, novel error messages gracefully.
- **Routing decision**: NOT AI — deterministic policy consuming the LLM classification + CUSUM signal + health score. Say so.

**Worth implementing?** YES — this documentation is mandatory.

---

### W-05 — "Why can't a handful of if-statements do this?"  **[HIGH]**

**Judge attack:** "HDFC error rate > 10% → route to UPI. Done. No AI needed."

**Defense:** For known error codes on known rails, yes, if-else works. The LLM earns its place on: (a) novel/ambiguous error messages from new bank integrations, (b) mixed-signal situations (timeout rate is elevated but OTP failures are also elevated — is this infrastructure or a fraud wave?), (c) producing human-readable explanation strings for the dashboard and customer communications. Document this explicitly.

**Concrete fix:** In `ARCHITECTURE.md`, show a case where CUSUM fires but the error composition is ambiguous. The LLM resolves the ambiguity. Show a concrete example in `JUDGE_QA.md`.

**Worth implementing?** YES.

---

### W-06 — "How do you know the bank is actually down vs. your detector being wrong?"  **[HIGH]**

**Judge attack:** "Your CUSUM fires. Maybe it's a temporary network blip on your own server, not HDFC. How do you prove it?"

**Defense:** (1) CUSUM uses a rolling baseline — it won't fire on a single outlier, only on a sustained shift. (2) The system checks *multiple signals*: error type distribution must shift (not just rate), latency must be elevated, and a minimum N=3 failures must occur. (3) The LLM classification includes a `confidence` field — low-confidence diagnoses trigger a "monitor" action, not a full reroute. (4) Circuit breaker has a cooldown — if the signal resolves, it re-admits the rail before any permanent damage.

**Concrete fix:** Implement the multi-signal threshold in `anomaly_engine.py`. Document it in `ARCHITECTURE.md`.

**Worth implementing?** YES.

---

### W-07 — "What if UPI — your fallback rail — is also degraded?"  **[HIGH]**

**Judge attack:** "You route to UPI when HDFC fails. UPI degrades 10 minutes later. What happens?"

**Defense:** The routing engine checks the live health score of EVERY candidate rail before selecting. If no rail exceeds the health threshold (default: 0.70), it returns `NO_ELIGIBLE_RAIL` — a hard stop, not a forced bad route. The dashboard shows this explicitly. The demo includes a "Simulate Multi-Rail Failure" scenario.

**Concrete fix:** The `NO_ELIGIBLE_RAIL` code path must be implemented and tested in unit tests. Implement `"Simulate Multi-Rail Failure"` injection button.

**Worth implementing?** YES — this is the most important "edge case" demo moment.

---

### W-08 — "What hard-stops infinite retry loops?"  **[CRITICAL]**

**Judge attack:** "The system retries, it fails, it retries again, it fails again. Infinite loop. Customer gets charged 5 times."

**Defense:** `guardrail_policy.py` enforces `MAX_RETRIES_PER_ORDER = 1`. This is a Python constant — not a config value, not a dashboard slider, not a database setting. It is checked before any retry or reroute action is executed, and the check is synchronous, side-effect-free, and unit-tested. Any LLM or upstream system recommendation to retry more is vetoed.

**Concrete fix:** The constant is defined in code, not config. Unit test with adversarial input (`retries=5` recommendation) must assert veto fires. Implement and test.

**Worth implementing?** YES — non-negotiable.

---

### W-09 — "How do you distinguish customer-caused vs. infrastructure-caused failure?"  **[CRITICAL]**

**Judge attack:** "Wrong PIN is a customer error. HDFC timeout is infrastructure. Your AI treats them the same."

**Defense:** This is the core classification problem, and it's explicitly what the LLM structured-output call solves. Error taxonomy:
- **Customer-caused (NO RETRY):** `INVALID_OTP`, `INSUFFICIENT_FUNDS`, `INCORRECT_CREDENTIALS` → hard-block in guardrail
- **Infrastructure-caused (ELIGIBLE FOR REROUTE):** `BANK_TIMEOUT`, `GATEWAY_TIMEOUT`, `NETWORK_ERROR`, `BANK_UNAVAILABLE`
- **Ambiguous (ESCALATE):** `ISSUER_DECLINE`, `SUSPECTED_FRAUD`, `UNKNOWN`

The classification is explicit, the routing policy is keyed on it, and the guardrail engine enforces the hard-block list.

**Concrete fix:** Implement the taxonomy in `schemas.py`, the LLM prompt in `agent_core.py`, and the guardrail check in `guardrail_policy.py`. Already planned.

**Worth implementing?** YES — this is the core differentiator.

---

### W-10 — "How do you prevent fraud from exploiting the recovery-link flow?"  **[HIGH]**

**Judge attack:** "A fraudster intercepts the recovery link URL and uses it to pay with a stolen card."

**Defense:** Recovery links are: (a) HMAC-SHA256 signed with a server secret (link forgery → signature verification fails), (b) single-use (DB unique constraint on `used_at IS NULL` + atomic update, not application-layer check), (c) 90-second TTL enforced at check time (not stored as a flag), (d) bound to the specific `order_id` + `customer_id` in the payload, (e) never retried for fraud/auth failures (guardrail hard-block).

**Concrete fix:** Implement all five controls. Sign the link payload with HMAC. Atomic DB update.

**Worth implementing?** YES — security is non-negotiable.

---

### W-11 — "Race condition: recovery link paid AND original transaction succeeds simultaneously"  **[HIGH]**

**Judge attack:** "Customer pays the recovery link AND the original HDFC transaction clears at the same time. Double charge."

**Defense:** Transaction state machine: once in `RECOVERED` state, the state machine rejects any attempt to move to `SUCCESS` from the original path. The state transition is enforced in `state_machine.py` with a DB-level atomic `UPDATE WHERE status = 'RECOVERY_PENDING'` — only one path can win the race to update from `RECOVERY_PENDING`. The losing path writes an audit entry `RACE_CONDITION_VOIDED` and is rolled back. The customer is refunded for the duplicate via the audit workflow.

**Concrete fix:** Implement state machine with DB-level atomic transitions. Unit-test the race condition.

**Worth implementing?** YES.

---

### W-12 — "Where does your model's training data come from?"  **[HIGH]**

**Judge attack:** "What did you train this classifier on? 40 synthetic transactions from a hackathon?"

**Defense:** The LLM (e.g., Google Gemini, OpenAI GPT-4o) is used as a general-purpose pretrained language model in a **structured-output role**, not as a custom-trained classifier. It is not fine-tuned. It processes structured telemetry JSON and maps to a fixed taxonomy. This is explicitly stated in `ARCHITECTURE.md`. The LLM has general knowledge of banking error codes, HTTP timeout patterns, and Indian payment rail behavior from its pretraining corpus. The synthetic benchmark (`generate_dataset.py`) tests the *guardrail* behavior with known-label data, not the LLM's classification accuracy.

**Concrete fix:** `ARCHITECTURE.md` must say: "The LLM is used as a structured-output mapper (zero-shot), not a fine-tuned classifier. Training data: none (pretrained general-purpose LLM)."

**Worth implementing?** YES — documentation.

---

### W-13 — "What happens when the model is wrong?"  **[MEDIUM]**

**Judge attack:** "The LLM classifies a `SUSPECTED_FRAUD` as `BANK_TIMEOUT`. System retries. Fraud is amplified."

**Defense:** (1) Low-confidence classifications (< 0.70 threshold) trigger a conservative `MONITOR` action, never a reroute. (2) The guardrail engine does *not* trust the LLM classification alone — it also checks the raw error code against a hard-coded safety list. If the raw error code is in `{INVALID_OTP, SUSPECTED_FRAUD, AUTH_REJECTED}`, the guardrail vetoes regardless of LLM classification. (3) The fallback path (LLM unavailable) defaults to the conservative action.

**Concrete fix:** Implement the dual-check in `guardrail_policy.py`: raw error code check AND LLM classification check. Lower wins (more conservative).

**Worth implementing?** YES.

---

### W-14 — "How does this work at real scale (thousands of TPS)?"  **[MEDIUM]**

**Judge attack:** "FastAPI + SQLite won't handle 10,000 TPS. This is a toy."

**Defense:** (1) Explicitly acknowledge this is a hackathon prototype, not a production deployment. (2) State the upgrade path in `ARCHITECTURE.md`: SQLite → PostgreSQL (WAL-mode SQLite is already structured for this), FastAPI → deployed behind a message queue (Kafka/Pub/Sub), CUSUM → runs on aggregated windows, not per-transaction. (3) The bottleneck is the LLM call — but LLM is called *per incident* (when CUSUM fires), not per transaction. At 1,000 TPS with 0.1% failure rate, CUSUM fires maybe once per minute. LLM call budget: 1/minute.

**Concrete fix:** Document the scalability upgrade path explicitly in `ARCHITECTURE.md`. Do not overclaim production readiness.

**Worth implementing (production scale)?** NO — document the upgrade path instead.

---

### W-15 — "Why would a merchant deploy this?"  **[MEDIUM]**

**Judge attack:** "Merchants use Razorpay Optimizer. It already does this. Why switch or add yet another layer?"

**Defense:** CascadeHeal is positioned as a *complementary layer* for merchants who need: (a) auditable compliance records of every routing decision, (b) control over safety limits that are verifiable in CI/CD, (c) the customer recovery loop that existing gateways don't close. Target customer: mid-market Indian merchant with compliance requirements, not a startup using the Razorpay dashboard.

**Worth implementing?** This is a positioning question — document in `COMPETITIVE_ANALYSIS.md`.

---

### W-16 — "What measurable business value beyond a nicer dashboard?"  **[HIGH]**

**Judge attack:** "Pretty charts. So what? What's the dollar impact?"

**Defense artifact required:** `evaluate_benchmark.py` must produce *real computed numbers* from the synthetic dataset run. Specifically: Recovery Rate %, MTTR seconds, Revenue Recovered per ₹10L GMV, False-Positive Rate %, Guardrail Violations (must be 0).

**Concrete fix:** Build and run `evaluate_benchmark.py` before finalizing `JUDGE_QA.md`. Every number cited must be tagged SIMULATED (came from `generate_dataset.py` synthetic run) or INDUSTRY ASSUMPTION (cited external source).

**Worth implementing?** YES — this is the "measurable impact" requirement.

---

### W-17 — "What is genuinely novel here?"  **[HIGH]**

See 0.2 below.

---

## 0.2 Novelty Determination

### What Already Exists (and We Do NOT Claim as Novel)

| Category | Existing Products | What They Do |
|---|---|---|
| Payment Gateways | Razorpay, Cashfree, PayU, Stripe | Accept payments, basic retry, basic failover |
| Payment Aggregators | BillDesk, Paytm, PhonePe B2B | Multi-bank routing, reconciliation |
| Smart Payment Routing | Razorpay Optimizer, Primer.io, Hyperswitch | AI-based dynamic routing across multiple PSPs |
| Gateway Orchestration | IXOPAY, Spreedly, CellPoint Digital | Multi-acquirer orchestration, token vaults |
| Payment Retry Systems | Stripe Radar retries, Recurly | Subscription retry with backoff |
| Fraud Detection | Razorpay Fraud Shield, Signifyd | ML-based fraud scoring |
| Abandoned Cart Recovery | Klaviyo, CartStack, Mailchimp | Email/SMS for abandoned carts |
| Payment Analytics Dashboards | Razorpay Analytics, Cashfree | Transaction reporting, success rate trends |
| Payment Resilience | Site24x7 payment monitoring, PagerDuty | Gateway uptime monitoring |

**What we do NOT claim:**
- "First-ever intelligent payment routing" — Razorpay Optimizer has this
- "AI-powered payment recovery" — email/SMS recovery tools exist
- "Multi-rail routing" — all orchestration platforms do this

### The Single Strongest Defensible Differentiator

CascadeHeal's defensible differentiator is the **provably safe, auditable, AI-governed decision layer with code-enforced guardrails** — not the routing itself. The specific novelty is the combination of: (1) a CUSUM-based real-time anomaly detector that fires on sustained drift, not point anomalies; (2) an LLM-based failure classifier that maps ambiguous Indian multi-rail error signals to a structured taxonomy with confidence scores; (3) a guardrail engine that is *provably independent of the LLM* — it can be unit-tested adversarially in CI/CD without any API call; (4) an append-only audit ledger that records every guardrail verdict (pass/veto + reason) for compliance review; and (5) a signed, TTL-bound customer recovery loop that closes the human side of the failure, which gateway-level cascading does not address. No single existing product combines all five layers with an explicit, testable safety envelope — in particular, no payment orchestration platform exposes its routing safety guarantees as unit-testable code artifacts.

### Concept Change / Pivot

**Original framing (weak):** "AI routing and payment recovery"  
**Revised framing (defensible):** "Guardrail-governed, auditable payment resilience engine with structured failure intelligence"

The code build is unchanged — the framing change is in documentation and pitch assets only. Logged in `DECISIONS.md`.

---

## 0.3 Decision Log

→ See `DECISIONS.md`

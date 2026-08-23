# JUDGE_QA.md — Hostile Judge Defense Matrix

> All answers cite exact file/function. Written after benchmark ran (real numbers available).

---

## Persona 1: FinTech CTO
**Q: "We have Razorpay Optimizer. Why would I buy another layer?"**

CascadeHeal is not a replacement — it's a compliance and auditability layer. Razorpay Optimizer's routing decisions are opaque; you cannot unit-test them adversarially in your CI/CD. CascadeHeal's `guardrail_policy.py::evaluate_guardrail()` is a pure Python function with zero external dependencies — every safety limit is a constant in version-controlled source code, and 107 unit tests including adversarial bypasses run in 0.23 seconds without any API call. When your compliance team asks "why did you retry that INVALID_OTP transaction?", you have an immutable `audit_log` entry with `guardrail_outcome=VETO, guardrail_reason="Hard block: INVALID_OTP in security block list."` Razorpay can't give you that.

---

## Persona 2: ML Researcher
**Q: "Your LLM is just a zero-shot classifier with no training data. What's the actual accuracy?"**

Correct — and I say so explicitly in `ARCHITECTURE.md`. The LLM (`agent_core.py::LLMClassifier`) is used in a structured-output role at temperature=0.0, not as a fine-tuned classifier. I don't claim accuracy I haven't measured. The benchmark (`evaluate_benchmark.py`) uses ground-truth labels from `generate_dataset.py` to evaluate the *guardrail system*, not the LLM's raw accuracy. The LLM is justified over if-else for: (1) novel/ambiguous error messages that don't match any hardcoded pattern, (2) mixed-signal situations (timeout rate elevated + OTP failures elevated — infrastructure or fraud wave?), (3) human-readable reasoning strings. The fallback `SimulatedClassifier.classify()` in `agent_core.py:L65` handles LLM unavailability with a deterministic rule-based path.

---

## Persona 3: Payments Expert
**Q: "Indian banks have wildly inconsistent error codes. How does your classifier handle this?"**

This is exactly why we use an LLM rather than a hardcoded mapping. HDFC's timeout looks different from ICICI's timeout at the raw string level. The LLM prompt in `agent_core.py::CLASSIFICATION_PROMPT_TEMPLATE` provides structured telemetry JSON including `dominant_error_codes`, `error_rate`, `cusum_value`, and `recent_events_sample`. The LLM maps ambiguous combinations to our fixed 8-value taxonomy. The benchmark (`evaluate_benchmark.py`) shows CascadeHeal achieves 100% recovery rate vs 0% for static rules on reroutable failures — because static rules can't handle ambiguity.

---

## Persona 4: Security Engineer
**Q: "How do you prove no recovery link can be forged, reused, or used after expiry?"**

Three independent controls in `razorpay_gateway.py::generate_signed_recovery_link()` and `db.py::consume_recovery_link()`:
1. **Forgery**: HMAC-SHA256 signed with `LINK_SECRET`. `verify_recovery_link_signature()` fails on any tampered URL.
2. **Reuse**: `consume_recovery_link()` executes `UPDATE WHERE used_at IS NULL` — atomic DB operation. Second concurrent call finds `rowcount=0` and returns `None`. This is enforced at the DB level, not application logic.
3. **Expiry**: TTL is checked at consumption time against current timestamp (`expires_at > now`), not stored as a boolean flag that could be tampered.
4. **Fraud exploitation**: `guardrail_policy.py::HARD_BLOCK_ERROR_CODES` prevents recovery links from ever being generated for `SUSPECTED_FRAUD`, `INVALID_OTP`, `AUTH_REJECTED` — confirmed at `main.py:L195-210`.

---

## Persona 5: VC
**Q: "What's the TAM and why will merchants pay for this?"**

I won't speculate on TAM here — that's not the hackathon question. The measurable business value from the benchmark (SIMULATED, 1,000 transactions): CascadeHeal recovers ₹58,679 per ₹10L GMV vs ₹0 for static rules. False-positive cost: ₹0 (CascadeHeal) vs ₹37,500 (static rules). These are SIMULATED figures from `benchmark_results.json` — real computation on synthetic data. At India's $100B+ annual digital payment volume, even a 0.1% improvement in recovery rate represents significant revenue. Primary buyer: mid-market Indian merchants with compliance requirements.

---

## Persona 6: Product Manager
**Q: "What does the dashboard actually tell me that Razorpay's dashboard doesn't?"**

Three things: (1) **Causal explanation** — not just "HDFC failure rate 34%" but "HDFC NetBanking BANK_TIMEOUT rate exceeded CUSUM threshold (3 failures / 90s window) → rerouted eligible traffic to UPI (health score 0.97)." (2) **Guardrail audit trail** — every decision has a `guardrail_outcome` and `guardrail_reason` visible in the live audit stream. (3) **Customer recovery status** — you can see which customers received recovery links, whether they used them, and the revenue recovered in real time.

---

## Persona 7: Backend Engineer ("this is just if-else")
**Q: "Show me where this isn't just if-else."**

Three places:
1. **CUSUM detector** (`anomaly_engine.py:L78-115`): detects *sustained drift*, not point anomalies. A 50% error rate on 2 transactions doesn't fire. A 25% error rate sustained over 90 seconds does. If-else can't express this without maintaining stateful rolling windows per rail.
2. **LLM classifier** (`agent_core.py`): given mixed signals (timeout rate elevated + OTP failures elevated simultaneously), if-else requires you to enumerate every combination for every Indian bank. The LLM handles novel combinations via natural language understanding.
3. **Guardrail engine** (`guardrail_policy.py`): not a single if-else — it's a composable policy engine with 7 independent rules, dual-check (raw error code AND LLM classification), and a dataclass-based context for testability.

---

## Persona 8: Hackathon Judge (generalist)
**Q: "What can I actually click to see this working?"**

1. Hit the dashboard at `http://localhost:3000` — live rail health tiles updating every 2 seconds.
2. Click "HDFC Outage" — watch HDFC health drop from 87% to ~5%, traffic redistribute to UPI, incident appear with explanation string.
3. Click "Suspicious Txn ⚠️" — watch audit log show `GUARDRAIL_VETO` with reason "Hard block: SUSPECTED_FRAUD in security block list."
4. Click "Multi-Rail Failure" — watch system report NO_ELIGIBLE_RAIL in audit log.
5. Enter any order ID in recovery panel, click Generate — get signed URL with 90-second TTL. Click "Simulate Customer Payment" — state transitions to RECOVERED, revenue counter increments.

---

## Persona 9: Razorpay Platform Engineer
**Q: "We already do cascading payments. What's different?"**

Razorpay cascading: (1) retries transparently at the gateway level, (2) you cannot inspect the retry decision, (3) it will retry INVALID_OTP if your gateway integration doesn't filter it, (4) no customer-facing recovery for failures that occurred before cascading kicks in, (5) no auditable guardrail record. CascadeHeal: (1) retries with an explicit classification and confidence score, (2) all decisions are auditable with guardrail outcome logged, (3) INVALID_OTP, SUSPECTED_FRAUD are hard-blocked regardless of any upstream recommendation, (4) customers who already failed get a signed recovery link, (5) every action is in an append-only audit ledger.

---

## Persona 10: Skeptical Professor
**Q: "What would need to change for this to work at production scale?"**

Honestly: four things. (1) SQLite → PostgreSQL (schema is already Postgres-compatible; WAL mode is an upgrade choice, not a blocker). (2) FastAPI single-process → deployed behind a message queue (Kafka or Pub/Sub) for ingestion — `_process_telemetry_event()` becomes a consumer. (3) CUSUM runs on aggregated windows pushed by the queue, not on individual HTTP requests. (4) LLM calls are already per-incident (~1/minute at realistic TPS), so the LLM bottleneck is manageable. The guardrail engine (`guardrail_policy.py`) runs in 2.51 µs (REAL/MEASURED) and is purely in-memory — it scales horizontally with zero shared state.

---

## Cross-Cutting Defense Answers

| Question | File/Function | Answer |
|---|---|---|
| "Why isn't this just if-else?" | `anomaly_engine.py`, `agent_core.py` | CUSUM stateful drift detection + LLM ambiguity resolution |
| "No double-charge proof?" | `db.py::consume_recovery_link`, `state_machine.py` | Atomic DB UPDATE + state machine invalid transition rejection |
| "LLM is slow or down?" | `agent_core.py::SimulatedClassifier` | Deterministic fallback, `is_llm_fallback=True` in audit log |
| "False-positive cost formula?" | `evaluate_benchmark.py:L230` | `false_positives × avg_txn_value = ₹0 for CascadeHeal` [REAL/MEASURED] |
| "Why defensible architecture?" | `guardrail_policy.py`, 107 tests | Pure function, adversarially tested, 0 violations in benchmark |
| "UPI also degraded?" | `main.py::_select_reroute_target` | Returns `None` → `NO_ELIGIBLE_RAIL` audit entry, never forces bad route |
| "Customer vs infrastructure failure?" | `agent_core.py::CLASSIFICATION_PROMPT`, `guardrail_policy.py::CUSTOMER_CAUSED_NO_REROUTE` | LLM taxonomy + dual guardrail check |
| "Infinite retry prevention?" | `guardrail_policy.py::MAX_RETRIES_PER_ORDER = 1` | Constant in source code, tested adversarially |
| "Race condition handling?" | `state_machine.py`, `db.py::atomic_state_transition` | Atomic DB UPDATE + VOIDED state + audit entry |
| "Production scale?" | `ARCHITECTURE.md#scalability` | Upgrade path documented: Postgres, message queue, per-incident LLM |

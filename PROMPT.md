# CascadeHeal — Master Build Prompt for Antigravity (v2, War-Room Edition)

## ROLE & MISSION

You are operating inside Antigravity in full autonomous agentic mode, simultaneously acting as:

1. Principal FinTech Systems Architect
2. Staff AI/ML Engineer
3. Senior Payments Infrastructure Engineer
4. Security/Fraud Engineer
5. Product/UX Designer
6. Startup CTO
7. Hostile hackathon grand-prize judge who actively wants to reject this project

Your objective is not to make the output *look* impressive. Your objective is to produce a system that is **technically defensible, commercially meaningful, demonstrable, and extremely difficult for a skeptical judge to dismiss** — and then actually build it, end-to-end, as runnable code.

You must be ruthless with yourself. Do not accept a weak design just because it was asked for. If a component is fake AI, replace it. If something already exists in the market (Razorpay's own smart routing, gateway orchestration, etc.), do not claim it as novel — reposition around what's genuinely defensible. If the architecture is over-engineered for the time available, simplify it. Never fabricate production integrations, real transaction data, partnerships, or performance/accuracy numbers — everything must be clearly labeled as SIMULATED, REAL/MEASURED, or INDUSTRY ASSUMPTION.

Work in small, verifiable increments. After each module, run it or smoke-test it before moving to the next. Do not silently skip a phase below — if a phase concludes "don't build X," record that decision in the repo (e.g., in `DECISIONS.md`) rather than omitting it.

---

## PROJECT SUMMARY (grounding, not marketing copy)

**Name:** CascadeHeal
**One-line concept:** An AI-governed payment resilience engine that detects failing payment rails in real time, intelligently reroutes eligible new transactions to healthier rails, and recovers customers whose payments already failed — while a hardcoded deterministic guardrail layer prevents the AI from ever retrying fraud/auth failures, double-charging, or exceeding fixed safety bounds.

**Core flow:** payment attempt → real-time monitoring → failure detection → failure classification → root-cause inference → intelligent decision (retry / reroute / recover / stop) → customer recovery → revenue recovery → continuous monitoring, feeding back into detection.

**Canonical demo scenario:** A customer attempts ₹2,000 via HDFC NetBanking. HDFC NetBanking begins failing at a statistically significant rate. CascadeHeal determines the failure is infrastructure-related, not customer-related, throttles traffic to that rail, reroutes new eligible transactions to a healthier rail (e.g., UPI), and sends the affected customer a secure one-tap recovery link. A separate injected `INVALID_OTP` / suspicious-activity failure must be visibly **refused** — no retry, no reroute, straight to escalation.

**Payment rails to simulate (prototype/simulation only unless a real integration is explicitly wired):** UPI, Visa, Mastercard, RuPay, NetBanking via HDFC Bank / ICICI Bank / SBI / Axis Bank, and wallet-style methods (e.g., PhonePe Wallet, Paytm-style). Never claim these are live production integrations, real partnerships, or real transaction data unless a real Razorpay Test Mode call actually executes it.

---

## PHASE 0 — SELF-ADVERSARIAL AUDIT (produce `CRITIQUE.md` before writing any code)

Before building anything, generate a hostile pre-mortem of the project as it currently stands. Structure it exactly as follows:

### 0.1 Weakness inventory
List every weakness you can find, each tagged **CRITICAL / HIGH / MEDIUM / LOW**, and for each one give:
1. Why a skeptical judge would attack it
2. What evidence/artifact would be required to defend it
3. The concrete fix
4. Whether that fix is actually worth implementing given hackathon time constraints — be honest if the answer is no

Explicitly stress-test against these attack vectors (do not skip any):
- "Isn't this just a wrapper around Razorpay?"
- "Razorpay already does smart routing — what's different?"
- "Payment retries already exist industry-wide."
- "Where is the AI, actually? Show me the model."
- "Why can't a handful of if-statements do this?"
- "How do you know the bank is actually down vs. your own detector being wrong?"
- "What happens if UPI — your fallback rail — is also degraded?"
- "What hard-stops infinite retry loops?"
- "How do you distinguish customer-caused failure (wrong PIN, insufficient funds) from infrastructure-caused failure?"
- "How do you prevent fraud from exploiting the recovery-link flow?"
- "What happens on a race condition — recovery link paid AND original transaction succeeds at the same time?"
- "How do you prevent duplicate/double payment?"
- "Where does your model's training data come from, given this is a hackathon?"
- "What happens when the model/classifier is simply wrong?"
- "How does this work at real scale (thousands of TPS)?"
- "Why would a merchant actually deploy this instead of what they already have?"
- "What measurable business value does this create beyond a nicer dashboard?"
- "What is genuinely, defensibly novel here?"

### 0.2 Novelty determination
Explicitly differentiate CascadeHeal from each of: payment gateways, payment aggregators, smart payment routing (as offered by Razorpay/Cashfree/etc.), gateway orchestration platforms, payment retry systems, fraud detection systems, abandoned-cart recovery tools, payment failure analytics dashboards, and existing payment resilience products. Do not claim uniqueness where the capability already exists in the market — use `web_search` if you need to verify current claims about competitors rather than asserting from memory. State plainly, in one paragraph, what the single strongest defensible differentiator is. If the original concept is too weak to defend, propose the smallest viable pivot that keeps the codebase you're about to build but repositions the value claim (e.g., positioning around the **guardrail-governed decision layer** and **auditable safety envelope**, not "AI routing" in the abstract, since routing itself is commoditized).

### 0.3 Decision log
Write the outcome of 0.1 and 0.2 into `DECISIONS.md`, including any concept changes made and why. This file must be updated any time a later phase changes scope.

---

## PART 1 — SYSTEM ARCHITECTURE (`ARCHITECTURE.md` + Mermaid diagram)

Design and document, with data flow shown end-to-end (Detect → Diagnose → Decide → Guardrail-Check → Reroute/Recover → Measure → back to Detect):

1. **Event ingestion** — webhook/event processor for high-throughput telemetry (transaction attempts, error codes, latency series, per-rail gateway status).
2. **Transaction state management** — explicit state machine (see Part 8 below) with an append-only store, not implicit status flags.
3. **Streaming pipeline** — how events flow from ingestion to feature generation to the anomaly engine without blocking the request path.
4. **Feature generation** — rolling per-rail/per-issuer features (error rate, latency percentiles, error-type distribution) that feed both the statistical detector and the classifier.
5. **Anomaly detection** — sliding-window CUSUM detector, triggers within ≤3 failed transactions on a rail without invoking the LLM on every single event.
6. **Failure classification / root-cause inference** — structured-output LLM call (temperature 0.0) producing a fixed taxonomy: `BANK_TIMEOUT`, `GATEWAY_TIMEOUT`, `ISSUER_DECLINE`, `INVALID_OTP`, `INSUFFICIENT_FUNDS`, `SUSPECTED_FRAUD`, `NETWORK_ERROR`, `UNKNOWN`, with confidence and blast radius.
7. **Payment rail health scoring** — live, probabilistic health score per rail based on rolling success/failure windows, not a binary up/down flag.
8. **Routing engine** — selects the best *eligible* alternate rail (not random fallback), and must explicitly refuse to route if no healthy eligible rail exists ("safe failure" per Phase 5/8).
9. **Recovery engine** — generates the one-tap, single-use, time-bound recovery link/flow for customers who already failed.
10. **Fraud/safety layer** — separate from the health-based router; hard-blocks retry/reroute for security-sensitive classifications.
11. **Idempotency & duplicate-payment prevention** — enforced at the database/constraint level, not just in application logic (see Part 8).
12. **Circuit breakers & cooldown periods** — once a rail is marked unhealthy, define exact re-entry criteria (e.g., N consecutive successes or a fixed cooldown window) before traffic is shifted back.
13. **Fallback strategies** — deterministic behavior when the LLM diagnostic call is slow/unavailable (see Part 4).
14. **Observability** — structured logs, metrics, and the audit ledger.
15. **Audit logs** — immutable, append-only, WAL-mode SQLite (Postgres-upgradeable), logging every state transition, telemetry payload, guardrail verdict (pass/veto + reason), and recovery confirmation.
16. **Dashboard** — see Part 5.
17. **Simulation environment** — see Part 4.

For **every** component in the list above, document explicitly:
- WHAT IT DOES
- WHY IT EXISTS (tie back to a Phase 0 attack it defends against)
- INPUT
- OUTPUT
- TECHNOLOGY CHOICE
- IMPLEMENTATION DIFFICULTY (S/M/L)
- DEMO VALUE (does a judge visibly see this working?)
- JUDGE VALUE (which hostile question does this component answer?)

---

## PART 2 — MAKE THE AI GENUINELY LEGITIMATE (no fake AI)

Do not add a model or an LLM call anywhere it isn't earning its place. For each of the following, decide if ML/LLM usage is justified, and if not, say so explicitly and use a deterministic method instead:

- Anomaly/drift detection → justify CUSUM (statistical, not ML) vs. a learned detector; default to CUSUM for hackathon-time defensibility and explainability.
- Time-series failure prediction (optional/stretch) → only include if time permits; mark as NICE TO HAVE.
- Failure classification (taxonomy above) → this is where the LLM's structured-output call earns its place: mapping messy/ambiguous error signals to a fixed taxonomy with confidence.
- Probabilistic rail health scoring → likely a simple Bayesian/exponentially-weighted success-rate estimator, not a "model" — say so, don't oversell it.
- Contextual routing / expected success probability → derive from the health score + classification, not a separate opaque model, unless you have time to genuinely justify one.
- Recovery probability estimation → optional stretch; only if it changes an actual decision.

For every component that does use ML/LLM, document:
- INPUT FEATURES
- MODEL (name/version, e.g., which LLM, temperature)
- "TRAINING DATA" — must state this is a hackathon prototype using synthetic data and/or a general-purpose pretrained LLM in a structured-output role, not a custom-trained classifier, unless one is actually trained
- INFERENCE path and latency budget
- OUTPUT schema
- DECISION POLICY (how the output is consumed downstream)
- FALLBACK IF MODEL FAILS — must reference a real code path in `agent_core.py`, not just a design intention

State plainly in `ARCHITECTURE.md`: "AI is used for X and Y. AI is deliberately NOT used for Z, because [reason]." This line is a direct defense against "where is the AI, actually?"

---

## PART 3 — DETERMINISTIC POLICY GUARDRAIL ENGINE (the load-bearing wall of the whole pitch)

This is the single most important module for surviving hostile judging — the LLM proposes, this layer disposes, and it must be provably LLM-independent.

Hardcoded, non-negotiable, code-enforced (never merely prompted) limits:
- Max discount/concession: ≤5%
- Max retries per order: 1
- Recovery link TTL: ≤90 seconds, single-use
- Hard block on retry/reroute for `INVALID_OTP`, `SUSPECTED_FRAUD`, `AUTH_REJECTED`, `INCORRECT_CREDENTIALS` — always escalate, never retry
- One recovery link per customer per order, idempotency enforced at the DB constraint level
- Router must return an explicit "no eligible rail — stop" result rather than ever forcing a transaction onto an unhealthy rail

`guardrail_policy.py` must be pure, synchronous, side-effect-free given its inputs, and have zero import dependency on the LLM client — this is what lets you truthfully say to a judge "you can unit test this without ever calling an API." Write unit tests proving each limit cannot be bypassed, including adversarial inputs (e.g., an LLM recommendation that tries to set a 20% discount, or retries an `INVALID_OTP` case) and assert the veto fires every time.

---

## PART 4 — REALISTIC PAYMENT SIMULATION ENVIRONMENT

Simulate rails: UPI, Visa, Mastercard, RuPay, HDFC NetBanking, ICICI NetBanking, SBI NetBanking, Axis NetBanking, and wallet-style methods.

Simulate realistic event outcomes: `SUCCESS`, `TIMEOUT`, `BANK_UNAVAILABLE`, `GATEWAY_TIMEOUT`, `INVALID_OTP`, `INSUFFICIENT_FUNDS`, `ISSUER_DECLINED`, `SUSPECTED_FRAUD`, `NETWORK_ERROR`.

Expose failure-injection controls as both API endpoints and dashboard buttons, at minimum:
- "Simulate HDFC Outage"
- "Simulate UPI Degradation"
- "Simulate Gateway Timeout"
- "Simulate 30% Payment Failure Spike"
- "Simulate Suspicious Transaction" (must prove the no-retry path)
- "Simulate Multi-Rail Failure" (two rails degraded at once — proves the "what if UPI is also down" defense; system must be able to report "no healthy eligible rail" rather than force a bad route)

The system must respond dynamically and visibly — traffic distribution numbers on the dashboard must actually move (e.g., HDFC NetBanking 70%→5%, UPI 15%→80%) as a direct, traceable consequence of injected events, not as a scripted animation.

---

## PART 5 — DASHBOARD (judge-proof, not overloaded)

Design and build exactly this set — resist the urge to add more:
- Total transactions
- Success rate / failure rate
- Active incidents (with human-readable explanation strings, e.g., "HDFC NetBanking timeout rate exceeded CUSUM threshold (3 failures / 90s window) → rerouted eligible new traffic to UPI (health score 0.97)")
- Payment rail health tiles (live scores)
- Traffic distribution (before/after visualization)
- Routing decisions log
- Recovery attempts / successful recoveries / recovery rate
- Simulated revenue saved (clearly labeled SIMULATED)
- Model confidence per decision
- Incident timeline

Prioritize whatever most directly proves business impact and decision explainability; cut anything that's decoration.

---

## PART 6 — SECURITY & PAYMENT CORRECTNESS (mandatory, not optional)

Design and implement protection against:
- Duplicate payment
- Replay attacks on recovery links
- Malicious/forged recovery links (must be signed, single-use, short-TTL, bound to the specific order)
- Unauthorized recovery attempts
- Fraud exploitation of the recovery flow itself
- Race conditions (original transaction succeeding at the same moment the recovery link is paid)
- Double charging
- Stale routing decisions (health score changed between decision and execution)
- Model errors (classification wrong or low-confidence)
- Payment-state inconsistency between the simulator, the ledger, and Razorpay's webhook confirmation

**Payment state machine (implement literally, with invalid transitions explicitly rejected in code):**
```
INITIATED → PROCESSING → SUCCESS
PROCESSING → FAILED
FAILED → RECOVERY_PENDING
RECOVERY_PENDING → RECOVERED
RECOVERY_PENDING → RECOVERY_EXPIRED
```
Enumerate and unit-test invalid transitions (e.g., `RECOVERED → PROCESSING` must be rejected; `SUCCESS` reached via both original and recovery path must be caught and one path voided with an audit entry, never silently double-captured).

---

## PART 7 — QUANTIFY BUSINESS VALUE (mathematically defensible, clearly labeled)

Build `evaluate_benchmark.py` and `generate_dataset.py` producing 1,000 (or, if you want to also support a larger "100,000 transactions" scale claim, a configurable N) realistic synthetic Indian checkout records with rail distribution UPI 65%, Cards 20%, NetBanking 10%, Wallets 5%.

Compare three systems on the identical dataset:
1. Static rule-based engine (naive if-else)
2. Raw unbounded LLM (no guardrails)
3. CascadeHeal (agent + guardrails)

Report, and clearly tag each figure as **REAL/MEASURED** (came out of an actual run of the code), **SIMULATED** (came out of the synthetic dataset but is a real computation), or **INDUSTRY ASSUMPTION** (an input parameter borrowed from public industry figures, cited):
- Recovery Rate (%)
- Mean Time to Remediate — MTTR (seconds)
- False-Positive Intervention Rate (%) — and show the formula: false-positive interventions × average transaction value = false-positive cost
- Guardrail Violations (must be 0.0% for CascadeHeal — assert this in an automated test, not just a demo claim)
- Net simulated revenue recovered per ₹10,00,000 GMV

Never invent numbers that didn't come from an actual run of `evaluate_benchmark.py`. If the script hasn't been run yet when you write `DEMO_SCRIPT.md` or `JUDGE_QA.md`, run it first and paste the real output.

---

## PART 8 — COMPETITIVE POSITIONING (`COMPETITIVE_ANALYSIS.md`)

Use `web_search` to check current claims rather than relying on memory. Produce:
- WHAT ALREADY EXISTS (payment orchestration, intelligent routing, smart retries, payment recovery tools, fraud detection, payment analytics, resilience products — name real categories/products where relevant)
- WHAT WE SHOULD NOT CLAIM as a result
- WHAT GAP IS DEFENSIBLE (tie back to Phase 0.2's novelty conclusion — likely the guardrail-governed, auditable decision layer combined with the specific Indian multi-rail failure taxonomy, not "AI routing" in general)
- HOW CASCADEHEAL SHOULD POSITION ITSELF given the above

---

## PART 9 — CODEBASE TO GENERATE (Python FastAPI backend + Next.js/Tailwind frontend)

Implement in this order, running/smoke-testing after each:

1. `schemas.py` — Pydantic v2 models: `TelemetryEvent`, `TelemetryBatch`, `DiagnosticReport`, `RemediationAction`, `GuardrailVerdict`, `AuditEntry`, `RailHealth`, transaction state enum from Part 6. Bound illegal states at the type level (e.g., discount percent constrained 0–5 via `Field`).
2. `db.py` — WAL-mode SQLite, migrations, append-only audit ledger, DB-level idempotency constraints (unique constraint on recovery-link-per-order).
3. `anomaly_engine.py` — CUSUM sliding-window detector; `check_drift(rail_id) -> DriftSignal | None`.
4. `guardrail_policy.py` — as specified in Part 3, with full unit test suite.
5. `rail_simulator.py` — Part 4's simulation engine (health scores, failure injection, traffic distribution, event generation).
6. `agent_core.py` — LLM diagnostic pipeline, structured JSON output, temperature 0.0, with a real deterministic fallback code path for LLM timeout/failure.
7. `razorpay_gateway.py` — async Razorpay Test API client: order creation, signed single-use recovery-link generation with TTL, webhook signature verification.
8. `state_machine.py` — Part 6's transaction state machine with invalid-transition rejection.
9. `main.py` — FastAPI app exposing:
   - `POST /telemetry`
   - `POST /inject/{scenario}`
   - `POST /recover/{order_id}`
   - `GET /audit/stream` (SSE/WebSocket)
   - `GET /rails/health`
   - `GET /incidents`
10. `/frontend` (Next.js + Tailwind) — dashboard per Part 5, failure-injection control panel, before/after traffic view, mobile-recovery-flow simulator component.
11. `/tests` — unit tests for `guardrail_policy.py` (every hard limit + adversarial bypass attempts), `anomaly_engine.py`, and `state_machine.py` (every invalid transition).
12. `generate_dataset.py` and `evaluate_benchmark.py` per Part 7, run against the real modules (not mocked).

---

## PART 10 — 90-SECOND WOW DEMO (`DEMO_SCRIPT.md`)

Design the demo as a precise table with columns: **TIMESTAMP | ACTION | WHAT JUDGE SEES | WHAT I SAY | TECHNICAL EVENT**, covering exactly this sequence:
1. Normal payment traffic on the dashboard
2. Live failure injection (HDFC NetBanking outage)
3. Detection (CUSUM fires)
4. AI diagnosis (root cause classified, shown on screen)
5. Rail health visibly degrades
6. Automatic routing decision, explanation string shown
7. Customer recovery flow (mobile simulator, one-tap UPI link)
8. Successful recovered payment (webhook → `RECOVERED` state)
9. Revenue recovered counter updates
10. A separate `INVALID_OTP` injection is refused live, proving the safe-failure path

Every "technical event" column entry must correspond to a real API call or log line the running system actually produces — write the script only after the system runs, using real captured output.

---

## PART 11 — HOSTILE JUDGE Q&A DEFENSE MATRIX (`JUDGE_QA.md`)

Simulate 10 distinct hostile judge personas and their toughest question each, with a direct, non-hand-wavy, code-referencing answer:
1. FinTech CTO
2. ML researcher
3. Payments expert
4. Security engineer
5. VC
6. Product manager
7. Backend engineer ("this is just if-else")
8. Hackathon judge (generalist)
9. Razorpay-style platform engineer ("we already do this")
10. Extremely skeptical professor

At minimum, explicitly answer (cite the exact file/function in each answer):
- Why isn't this just if/else in an API gateway?
- How do you prove no double-charge / no recovery-link spam?
- What happens if the LLM is slow or down?
- How do you calculate false-positive cost?
- Why is this a defensible architecture rather than an LLM toy?
- What happens if UPI (the fallback) is also degraded?
- How do you distinguish customer-caused vs. infrastructure-caused failure?
- What prevents infinite retry loops?
- How does this behave under a race condition between original and recovery payment?
- What would need to change for this to work at real production scale?

---

## PART 12 — PRIORITIZED BUILD PLAN (`BUILD_PLAN.md`)

Categorize every feature above into **MUST BUILD / SHOULD BUILD / NICE TO HAVE / DO NOT BUILD**, with a one-line reason for each "do not build."

Optimize the plan against this scoring weight: 40% technical depth, 25% innovation, 20% measurable impact, 10% demo quality, 5% presentation.

Lay out a day-by-day plan (Day 1 / Day 2 / Day 3 / Day 4 / Final Day) with exact implementation priorities per day, assuming limited hackathon time. Guardrail engine, state machine, and anomaly engine (the parts that prove "this isn't just an LLM toy") should land early, not last.

---

## PART 13 — PITCH ASSETS (`PITCH.md`)

Write four pitch lengths: 10-second, 30-second, 60-second, 3-minute. Each must be understandable to a non-technical judge while surviving technical scrutiny from a technical one. Do not use "revolutionary," "game-changing," "first-ever," or similar unsupported superlatives. Ground every claim in something the running system can actually show.

---

## PART 14 — FINAL SCORING & SINGLE BIGGEST LEVER (`SCORECARD.md`)

After the system is built and the benchmark has actually run, self-score out of 100 on: Novelty, Technical Depth, AI Quality, FinTech Relevance, Business Impact, Security, Demo Quality, Scalability, Pitch Quality, Overall Winning Potential. Justify each score with one sentence tied to a real artifact in the repo (a file, a test, a benchmark number) — not a vibe. Conclude with the single biggest change that would most increase winning probability, and be willing to say if that change means cutting something already built.

---

## FINAL RULES FOR ANTIGRAVITY

- Never fabricate production integrations, real customer data, partnerships, performance statistics, AI accuracy figures, or industry claims. Every number in the final deliverables must trace to either a real code run or a cited external source.
- Do not skip Phase 0. If you find the concept weak anywhere, change it and log the change in `DECISIONS.md` rather than silently building around the weakness.
- Do not add AI where a deterministic method is more defensible — say so explicitly in `ARCHITECTURE.md`.
- Guardrail logic must remain provably independent of the LLM (importable and unit-testable with zero LLM calls).
- Every dashboard number and demo claim must be reproducible by re-running the code, not hardcoded for show.
- If any external API key (Razorpay Test, LLM provider) is missing, stub that specific call behind an interface so the rest of the system still runs end-to-end in "simulation mode," and clearly flag in `README.md` what needs a real key to go fully live.
- End with a top-level `README.md`: setup instructions, required env vars, run commands for backend and frontend, and a summary of what was actually built vs. what's in `BUILD_PLAN.md` as not-yet-built.
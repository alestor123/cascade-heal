# DECISIONS.md — CascadeHeal Decision Log

> Append-only. Every scope change, architectural decision, and concept pivot is recorded here.

---

## D-001 — Concept Reframe (Phase 0, 2026-08-22)

**Decision:** Reframe CascadeHeal away from "AI routing" toward "guardrail-governed, auditable payment resilience engine with structured failure intelligence."

**Reason:** Razorpay Optimizer already offers AI-powered intelligent routing (confirmed via web research). Claiming "AI routing" as novel would be immediately attacked and correctly rejected. The defensible differentiator is the combination of: CUSUM detection + LLM taxonomy classification + provably LLM-independent guardrail engine (unit-testable adversarially) + append-only audit ledger + customer recovery loop. No existing product exposes safety guarantees as testable code artifacts.

**Impact:** Documentation, pitch assets, and `COMPETITIVE_ANALYSIS.md` rewritten. Codebase unchanged.

**Logged by:** Phase 0 Self-Adversarial Audit (CRITIQUE.md)

---

## D-002 — AI Usage Boundaries (Phase 0/Part 2, 2026-08-22)

**Decision:** Use AI/LLM ONLY for failure classification (taxonomy mapping). Explicitly NOT for: anomaly detection, health scoring, routing decision, recovery link generation.

**Reason:** 
- CUSUM is more explainable, computationally lighter, and defensible for a hackathon than a trained ML model. Statistical method, not AI.
- Rail health scoring is a Bayesian exponentially-weighted estimator — not "AI." Claiming it as AI would be dishonest.
- Routing decision is deterministic policy consuming classification output — if this were AI, you couldn't prove the guardrails hold.
- LLM earns its place on classification: handles novel/ambiguous error messages, mixed signals (timeout + OTP failure together), and produces human-readable explanation strings.

**Impact:** `ARCHITECTURE.md` must include the explicit "AI is used for X, NOT for Y" statement.

---

## D-003 — Guardrail Independence Requirement (Part 3, 2026-08-22)

**Decision:** `guardrail_policy.py` must have zero import dependency on `razorpay_gateway.py`, `agent_core.py`, or any LLM client. Must be pure, synchronous, and side-effect-free.

**Reason:** This is the load-bearing proof that the system isn't just an LLM toy. If the guardrail imports the LLM, a judge can correctly say "you're trusting the AI to police itself." The import boundary makes it structurally impossible for the LLM to bypass its own guardrail.

**Impact:** Module structure enforced by Python import rules. Unit tests prove this without mocking.

---

## D-004 — SQLite WAL Mode for Audit Ledger (Part 1, 2026-08-22)

**Decision:** Use WAL-mode SQLite for the audit ledger, structured for Postgres migration.

**Reason:** SQLite with WAL mode supports concurrent reads without blocking writes, is sufficient for hackathon-scale demo, and the schema is designed to be Postgres-compatible (no SQLite-specific types). The audit table is append-only (no UPDATE/DELETE on audit rows).

**Impact:** `db.py` must enable WAL mode explicitly: `PRAGMA journal_mode=WAL`.

---

## D-005 — LLM as Zero-Shot Mapper, Not Fine-Tuned Classifier (Part 2, 2026-08-22)

**Decision:** Use a general-purpose pretrained LLM (Gemini or GPT-4o) at temperature 0.0 for structured-output failure classification. No fine-tuning.

**Reason:** Fine-tuning would require labeled transaction data we don't have. Zero-shot structured output is honest, defensible, and sufficient for the classification task. Must be documented as such.

**Impact:** `ARCHITECTURE.md` explicitly states: "The LLM is used as a zero-shot structured-output mapper. No fine-tuning. No custom training data."

---

## D-006 — Dual Safety Check in Guardrail (Part 3, 2026-08-22)

**Decision:** Guardrail checks BOTH the raw error code AND the LLM classification. The more conservative check wins.

**Reason:** Defends against LLM misclassification (e.g., classifies SUSPECTED_FRAUD as BANK_TIMEOUT). Raw error code check cannot be fooled by an LLM hallucination.

**Impact:** `guardrail_policy.py` implements two independent checks. Unit tests cover the case where raw code is safe but LLM classification is dangerous (guardrail must still veto based on raw code).

---

## D-007 — No Production Scale Claims (Phase 0 W-14, 2026-08-22)

**Decision:** Do not claim production scalability. Document the upgrade path explicitly.

**Reason:** FastAPI + SQLite is a hackathon prototype. Claiming 10,000 TPS would be dishonest and trivially debunked. Instead: state the LLM is called per-incident (not per-transaction), state the upgrade path (SQLite → Postgres, message queue for ingestion).

**Impact:** `ARCHITECTURE.md` scalability section must be honest about limits.

---

## D-008 — Build Order (Part 12, 2026-08-22)

**Decision:** Build in this order to ensure the defensible core lands first:
1. `schemas.py` + `db.py` (foundation)
2. `state_machine.py` + `guardrail_policy.py` + unit tests (the safety proof)
3. `anomaly_engine.py` (the detection layer)
4. `rail_simulator.py` (the demo environment)
5. `agent_core.py` (the LLM layer — can be stubbed if LLM key unavailable)
6. `razorpay_gateway.py` (plugin layer — can be stubbed)
7. `main.py` (API assembly)
8. `/frontend` (Next.js dashboard)
9. `generate_dataset.py` + `evaluate_benchmark.py` (evidence)
10. Documentation: `ARCHITECTURE.md`, `COMPETITIVE_ANALYSIS.md`, `BUILD_PLAN.md`, `DEMO_SCRIPT.md`, `JUDGE_QA.md`, `SCORECARD.md`, `PITCH.md`

**Reason:** The guardrail engine and state machine prove "this isn't just an LLM toy." They must be buildable, runnable, and tested before the demo is possible.

---

## D-009 — Simulation Mode for Missing API Keys (Final Rules, 2026-08-22)

**Decision:** All external API calls (Razorpay Test, LLM provider) must be behind an interface/stub. If env vars are missing, the system must run end-to-end in "simulation mode" with no external calls, and README must flag what needs a real key.

**Reason:** Demo reliability. If a judge's WiFi blocks the LLM endpoint, the demo should still run.

**Impact:** `agent_core.py` has a `SimulatedClassifier` fallback. `razorpay_gateway.py` has a `SimulatedGateway` fallback. Both are toggled by env var presence.

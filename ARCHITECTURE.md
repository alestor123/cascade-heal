# ARCHITECTURE.md — CascadeHeal Technical Architecture & System Specification

> Written from the perspective of a Principal FinTech Systems Architect.

---

## 1. Core Problem & Design Philosophy

### The Critical-Path Dilemma in High-Throughput Payment Switching
In high-throughput digital payment processing across Indian payment rails (UPI, NetBanking, IMPS, Cards), payment failure handling presents a fundamental architectural dilemma:

1. **Double-Debit & Race Condition Risks**: Indiscriminate or naive retries during degraded network states invite double-charging, ledger desynchronization, and cascading gateway locks.
2. **Thundering Herd Hazards**: When a primary bank node (e.g., HDFC NetBanking) suffers switch latency, naive fallback algorithms redirect 100% of volume onto secondary nodes (e.g., ICICI NetBanking), instantly triggering downstream switch saturation.
3. **The Static Rule Failure Mode**: Static if-else routing thresholds (e.g., "if error_rate > 15%, switch rail") fail during multi-node cascading failure modes, where secondary options are also partially degraded, or when error codes present mixed signals (e.g., simultaneous timeouts and invalid auth spikes).
4. **Why Pure LLMs Fail Inline**: LLM inference latencies (300ms–2500ms) violate critical-path SLA requirements (<50ms switching overhead). Furthermore, LLM hallucinations on financial control paths (e.g., proposing an unauthorized discount or retrying an `INVALID_OTP` transaction) introduce unacceptable fraud and compliance vulnerabilities.

### Latency SLA Disclosure (FIX 4)
CascadeHeal enforces a explicit operational distinction between rule evaluation and external gateway API roundtrips:
- **Guardrail Policy Verification**: **~2.5µs (in-memory execution)**. Evaluates 7 financial policy invariants in pure Python with zero network or database dependencies.
- **End-to-End Recovery Link API SLA**: **200ms–800ms**. Includes external payment gateway network round-trip I/O (Razorpay SDK API call) and WAL-mode database persistence.

### Production Scaling Architecture Disclosure (FIX 8)
- **Hackathon Scope**: SQLite in Write-Ahead Logging (WAL) mode provides zero-dependency portability and atomic single-file transaction persistence.
- **Production Architecture**: For horizontal scaling across multi-worker server clusters (>1,000 TPS), the production deployment replaces SQLite with PostgreSQL (utilizing row-level locks and connection pooling) and backs sliding-window CUSUM drift states and circuit breakers with Redis.

---

## 2. Triple-Layer System Architecture

```
                                  CRITICAL PATH (~2.5 µs)
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                  │
 │  Payment Telemetry Event                                                         │
 │         │                                                                        │
 │         ▼                                                                        │
 │  ┌──────────────┐      ┌─────────────────────────┐      ┌─────────────────────┐  │
 │  │ CUSUM Drift  ├─────►│ Policy Guardrail Engine ├─────►│  State Machine &    │  │
 │  │ Anomaly Engine│      │ (Deterministic Rules)   │      │ DB Ledger (WAL)     │  │
 │  └──────┬───────┘      └────────────┬────────────┘      └──────────┬──────────┘  │
 │         │                           │                              │             │
 └─────────┼───────────────────────────┼──────────────────────────────┼─────────────┘
           │                           │                              │
           ▼ (Async SSE Queue)         ▼ (Audit Payload)              ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                  │
 │  ┌───────────────────────┐      ┌────────────────────────┐   ┌────────────────┐  │
 │  │ LLM Diagnostic Agent  │      │ Cryptographic Audit    │   │ Razorpay Test  │  │
 │  │ (Out-of-Band Synthesis)      │ Ledger & Safe Refusal  │   │ Gateway Plugin │  │
 │  └───────────────────────┘      └────────────────────────┘   └────────────────┘  │
 │                                                                                  │
 │                             OUT-OF-BAND INTELLIGENCE                             │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

### Layer 1: In-Memory Deterministic Policy Guardrail Engine (`guardrail_policy.py`)
Operating directly on the critical path with **zero external dependencies**, Layer 1 acts as an un-bypassable safety arbiter. Every remediation proposed by upstream telemetry or out-of-band diagnostic engines must pass 7 invariant checks:

1. **Idempotency Enforcement**: Guarantees `max_retries_per_order == 1`. Duplicate retry directives are rejected at the memory level.
2. **Concession Bounds**: `discount_percent <= 5.0%`. Prohibits hallucinated or unauthorized price reductions.
3. **TTL Bound**: Recovery link creation dynamically constrained to `ttl_seconds <= 90`.
4. **Hard Error Blocklist**: Immediate veto on `INVALID_OTP`, `SUSPECTED_FRAUD`, `AUTH_REJECTED`, `INCORRECT_CREDENTIALS`, `EXPIRED_CARD`.
5. **State machine invariant**: Transitions must conform to the 8-state explicit state graph (`PENDING → FAILED → RECOVERY_PENDING → RECOVERED | VOIDED`).
6. **Circuit Breaker Check**: Reroute targets must maintain an EWMA health score `≥ 0.70`.
7. **Single-Use Link Security**: DB level `UPDATE WHERE used_at IS NULL` atomic verification.

### Layer 2: Statistical Anomaly & Dynamic Rerouting Engine (`anomaly_engine.py` & `rail_simulator.py`)
Layer 2 monitors health without arbitrary static thresholds by employing a **Two-Sided Cumulative Sum (CUSUM)** quality control algorithm:

$$\text{CUSUM}_t^+ = \max(0, \text{CUSUM}_{t-1}^+ + (x_t - \mu_0 - K))$$

- **Sliding Window**: 90-second rolling window across 10 discrete Indian payment nodes (HDFC NetBanking, ICICI NetBanking, SBI UPI, PhonePe, Visa, Mastercard, etc.).
- **Drift Isolation**: Evaluates drift across three orthogonal metrics:
  1. *Taxonomy Drift*: Ratio of `GATEWAY_TIMEOUT` / `BANK_UNAVAILABLE` against baseline.
  2. *Latency Series Drift*: p95 latency shifts (e.g., 400ms → 4,200ms).
  3. *Node Cardinality*: Pinpointing failures to specific sub-nodes (e.g., HDFC NetBanking degraded while HDFC UPI remains at 99.8% health).
- **Capped Proportional Rerouting**: Dynamically shifts traffic weights to candidate nodes using a 40% maximum capacity cap per rail to prevent thundering herd secondary switch collapse.

### Layer 3: Out-of-Band Agentic Incident Diagnostic Layer (`agent_core.py`)
Triggered only when Layer 2 CUSUM signals statistical drift, the Agentic Layer executes out-of-band:

- **Structured Zero-Shot Taxonomy Mapping**: Converts raw, noisy bank error logs into structured diagnostic reports containing failure taxonomy, confidence scores (0.00–1.00), blast radius estimates, and human-readable root cause summaries.
- **Deterministic Fallback (`SimulatedClassifier`)**: If LLM API limits are reached, network timeouts occur, or no API key is provided, the system degrades to a rule-based classifier tagged with `is_llm_fallback=True` for in-product disclosure.

---

## 3. Error Taxonomy & Safe Refusal Architecture

```
                     ┌─────────────────────────────────────────┐
                     │          INCOMING TELEMETRY             │
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │       GUARDRAIL ERROR TAXONOMY          │
                     └────────────┬───────────────────┬────────┘
                                  │                   │
                  HARD UNRECOVERABLE                  SOFT RECOVERABLE
                  (NON-RETRYABLE)                     (SWITCH ERRORS)
                  │                                   │
                  ├─► INVALID_OTP                     ├─► BANK_UNAVAILABLE
                  ├─► SUSPECTED_FRAUD                 ├─► GATEWAY_TIMEOUT
                  ├─► AUTH_REJECTED                   ├─► NETWORK_FLAP
                  └─► INCORRECT_CREDENTIALS           └─► SWITCH_TIMEOUT
                                  │                   │
                                  ▼                   ▼
                     ┌─────────────────┐     ┌─────────────────┐
                     │ SAFE REFUSAL &  │     │ REROUTE / LINK  │
                     │  EXCEPTIONS     │     │ RECOVERY FLOW   │
                     │    LEDGER       │     └─────────────────┘
                     └─────────────────┘
```

### Safe Refusal Ledger
When hard unrecoverable errors (e.g., `SUSPECTED_FRAUD` or `INVALID_OTP`) are ingested:
1. Automated recovery link generation and retries are **aborted immediately**.
2. Transaction state transitions to `FAILED` with non-retryable flags.
3. The event is written to the append-only **Safe Refusal & Exceptions Ledger** (`/exceptions`) for human compliance audit.
4. **Result**: Zero false-positive customer retries, zero fraud amplification, and complete balance protection.

---

## 4. 1,000-Transaction Chaos Benchmark Methodology

The benchmark suite (`evaluate_benchmark.py`) generates 1,000 synthetic transactions modeled on peak Indian payment rail failure distributions (7.6% baseline error rate, 65 reroutable switch failures, 14 security/auth failures).

### Comparative Evaluation Matrix

| Metric | Static Rule Engine | Raw Unbounded LLM | CascadeHeal Engine | Measurement Type |
|---|---|---|---|---|
| **Recovery Rate %** | 0.0% | 84.62% | **100.0%** | [SIMULATED] |
| **MTTR (Detection + Recovery)** | 0s (No recovery) | 8.0s | **12.0s** | [SIMULATED] |
| **False Intervention Count** | 27 txns | 8 txns | **0 txns** | **[REAL/MEASURED]** |
| **False Intervention Rate %** | 29.35% | 8.70% | **0.0%** | **[REAL/MEASURED]** |
| **False Positive Cost (₹)** | ₹40,500 | ₹12,000 | **₹0.00** | [SIMULATED] |
| **Policy Guardrail Violations** | 0 (No bounds) | 1 (Bypassed) | **0 (100% Vetoed)** | **[REAL/MEASURED]** |
| **Guardrail Policy Rule SLA** | — | — | **2.79 µs** | **[REAL/MEASURED]** |

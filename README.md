# CascadeHeal: Guardrail-Governed AI Payment Resilience Engine

[![Tests](https://img.shields.io/badge/Tests-107%20Passed-success)](./tests)
[![Guardrail SLA](https://img.shields.io/badge/Guardrail%20Latency-2.68%20%C2%B5s-blue)](./backend/guardrail_policy.py)
[![Gateway](https://img.shields.io/badge/Razorpay%20Integration-Test%20Mode%20SDK-purple)](./backend/razorpay_gateway.py)
[![Python](https://img.shields.io/badge/Python-3.11+-cyan)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-14+-black)](https://nextjs.org/)

CascadeHeal is a high-throughput, guardrail-governed payment resilience engine engineered specifically for Indian payment rails (UPI, NetBanking, IMPS, Cards). It solves payment failure mitigation by combining **critical-path deterministic guardrails (<3 µs execution SLA)** with **out-of-band statistical anomaly detection (CUSUM)** and **asynchronous LLM incident classification**.

---

## Technical Highlights

1. **Critical Path vs. Out-of-Band Separation**:
   - **Critical Path (In-Memory, Pure Python)**: CUSUM drift detection, State Machine validation, and Policy Guardrail verification execute synchronously in **2.68 µs**. Zero LLM or external network dependency on the critical path.
   - **Out-of-Band (Asynchronous Agent)**: Gemini/OpenAI zero-shot diagnostic classification runs out-of-band via SSE queues to analyze root causes without introducing latency into payment switching.

2. **Deterministic Policy Guardrail Layer (`guardrail_policy.py`)**:
   - Enforces 7 non-negotiable financial & security boundaries:
     * Idempotency check: `max_retries_per_order == 1`
     * Concession cap: `discount_percent <= 5.0%`
     * Expiry constraint: `ttl_seconds <= 90`
     * Hard error blocklist: `INVALID_OTP`, `SUSPECTED_FRAUD`, `AUTH_REJECTED`, `INCORRECT_CREDENTIALS`
     * Circuit breaker target threshold: `health_score >= 0.70`

3. **Multi-Dimensional Anomaly Isolation (`anomaly_engine.py`)**:
   - Two-Sided CUSUM sliding-window quality control algorithm detecting failure drift across:
     1. *Error Taxonomy*: `GATEWAY_TIMEOUT` vs. `USER_DROPPED`
     2. *Latency Series Drift*: p95 processing time spikes (400ms → 4,200ms)
     3. *Node Cardinality*: Pinpointing failures to specific sub-nodes (e.g. HDFC NetBanking degraded while HDFC UPI remains at 99.8% health).

4. **Real Razorpay Test API Integration (`razorpay_gateway.py`)**:
   - Generates genuine Razorpay Test Payment Links via official SDK (`client.payment_link.create`) with HMAC-SHA256 signature verification, single-use DB enforcement, and custom notes (`recovered_by: CascadeHeal`).
   - Includes interactive mobile modal preview rendering live Razorpay test checkout pages.

5. **Safe Refusal & Exceptions Ledger**:
   - Unrecoverable security failures (`SUSPECTED_FRAUD`, `INVALID_OTP`) trigger safe refusal—halting automated recovery and logging to the compliance audit ledger (`/exceptions`).

---

## System Architecture

```
                                  CRITICAL PATH (< 3 µs)
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

---

## 1,000-Transaction Chaos Benchmark

Results from `evaluate_benchmark.py` evaluating 1,000 synthetic payment transactions across Indian payment rail failure distributions:

| Metric | Static Rule Engine | Raw Unbounded LLM | CascadeHeal Engine | Measurement Type |
|---|---|---|---|---|
| **Recovery Rate %** | 0.0% | 90.32% | **100.0%** | [SIMULATED] |
| **MTTR (Detection + Recovery)** | 0s (No recovery) | 8.0s | **12.0s** | [SIMULATED] |
| **False Intervention Count** | 14 txns | 3 txns | **0 txns** | **[REAL/MEASURED]** |
| **False Intervention Rate %** | 18.42% | 3.95% | **0.0%** | **[REAL/MEASURED]** |
| **False Positive Cost (₹)** | ₹21,000 | ₹4,500 | **₹0.00** | [SIMULATED] |
| **Policy Guardrail Violations** | 0 (No bounds) | 2 (Bypassed) | **0 (100% Vetoed)** | **[REAL/MEASURED]** |
| **Guardrail Evaluation Latency** | — | — | **2.68 µs** | **[REAL/MEASURED]** |

---

## Repository Structure

```
cascade-heal/
├── backend/
│   ├── schemas.py              # Pydantic v2 domain models & strict enums
│   ├── db.py                   # WAL-mode SQLite, atomic state transitions, audit ledger
│   ├── state_machine.py        # Explicit 8-state transaction state graph
│   ├── guardrail_policy.py     # Deterministic Policy Guardrail Engine (Pure Python)
│   ├── anomaly_engine.py       # Two-sided CUSUM drift detection module
│   ├── rail_simulator.py       # 10-node Indian payment rail chaos generator
│   ├── agent_core.py           # Out-of-band LLM classifier & fallback engine
│   ├── razorpay_gateway.py     # Official Razorpay Test SDK integration & signed link generator
│   └── main.py                 # FastAPI application, SSE stream, chaos endpoints
├── frontend/
│   ├── app/page.tsx            # Next.js 14 real-time dashboard & benchmark interface
│   └── styles/globals.css      # Custom styling & glassmorphism system
├── tests/                      # 107 unit tests (0.19s execution)
├── evaluate_benchmark.py       # Automated 1,000-Txn comparative benchmark suite
├── ARCHITECTURE.md             # In-depth system architecture & mathematical formulation
└── README.md                   # System overview & quickstart guide
```

---

## Environment Variables

| Variable | Description | Default / Mode |
|---|---|---|
| `RAZORPAY_KEY_ID` | Razorpay Test Key ID | If set, executes real Razorpay API calls |
| `RAZORPAY_KEY_SECRET` | Razorpay Test Key Secret | Required for real Razorpay mode |
| `LLM_API_KEY` | Gemini or OpenAI API Key | If unset, uses `SimulatedClassifier` fallback |
| `LINK_SECRET` | Secret key for HMAC-SHA256 link signing | Auto-generated hex token |
| `CASCADE_DB_PATH` | Path to SQLite WAL database | `./cascade_heal.db` |

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+

### 1. Backend Server
```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic httpx razorpay google-generativeai openai aiosqlite pytest

# Run FastAPI backend
cd backend
python3 -m uvicorn main:app --reload --port 8000
```

### 2. Frontend Interface
```bash
cd frontend
npm install
npm run dev
# Dashboard opens at http://localhost:3000
```

### 3. Verification & Benchmark Execution
```bash
# Run unit test suite (107 tests in 0.19s)
python3 -m pytest tests/ -v

# Run 1,000-Transaction Benchmark Suite
python3 evaluate_benchmark.py --n 1000
```

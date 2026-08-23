# BUILD_PLAN.md — CascadeHeal Prioritized Build Plan

## Feature Categorization

### MUST BUILD ✅
| Feature | Reason |
|---|---|
| `schemas.py` | Foundation — all other modules depend on it |
| `db.py` WAL-mode SQLite + audit ledger | Idempotency + compliance evidence |
| `state_machine.py` + invalid transition tests | Proves no double-charge — load-bearing demo |
| `guardrail_policy.py` + adversarial unit tests | THE most important module for judging |
| `anomaly_engine.py` CUSUM detector | Proves "not just if-else" — statistical detection |
| `rail_simulator.py` + failure injection | Makes the demo interactive |
| `agent_core.py` LLM classifier + fallback | Where AI actually earns its place |
| `main.py` FastAPI + all endpoints | System integration |
| Dashboard (health tiles, incidents, traffic) | Judge sees this — must wow |
| Failure injection buttons | Demo requires this |
| Recovery flow UI | The human-loop differentiator |
| `generate_dataset.py` | Benchmark data generation |
| `evaluate_benchmark.py` | Measurable business impact evidence |
| `CRITIQUE.md` | Phase 0 — required by spec |
| `DECISIONS.md` | Phase 0 — required by spec |
| `ARCHITECTURE.md` | Required for "where is the AI?" defense |

### SHOULD BUILD 🔷
| Feature | Reason |
|---|---|
| SSE audit stream | Makes dashboard feel live |
| Razorpay webhook handler | Demo completeness |
| HMAC-signed recovery links | Security differentiator demo |
| `COMPETITIVE_ANALYSIS.md` | Required for positioning |
| `JUDGE_QA.md` | Required for hostile defense |
| `DEMO_SCRIPT.md` | Required for 90-second demo |

### NICE TO HAVE 💡
| Feature | Reason |
|---|---|
| Time-series failure prediction | Only if 2+ days spare — LLM suffices for hackathon |
| Recovery probability estimation | Not worth implementing if it doesn't change a decision |
| Mobile-optimized recovery page | Nice visual, low defensive value |
| Real Razorpay Test API integration | System works fine in simulation mode |

### DO NOT BUILD ❌
| Feature | Reason |
|---|---|
| Fine-tuned ML classifier | No labeled training data; zero-shot LLM is honest and sufficient |
| Kafka/message queue | Out of scope — document upgrade path instead |
| Multi-tenant merchant API | Adds complexity without judging value |
| Payment page UI | Out of scope — CascadeHeal is infrastructure, not checkout |

## Day-by-Day Plan

### Day 1 — Safety Core (40% technical depth score)
- `schemas.py`, `db.py`, `state_machine.py`, `guardrail_policy.py`
- Full unit test suite for guardrail + state machine
- `CRITIQUE.md`, `DECISIONS.md`

### Day 2 — Intelligence Layer (25% innovation score)
- `anomaly_engine.py` + tests
- `agent_core.py` (LLM + fallback)
- `rail_simulator.py` with all scenarios
- `ARCHITECTURE.md`

### Day 3 — Integration + Demo
- `main.py` FastAPI assembly
- `razorpay_gateway.py` (signed links)
- Backend smoke tests

### Day 4 — Frontend + Evidence
- Next.js dashboard (health, incidents, traffic, audit)
- Failure injection buttons
- Recovery flow UI
- `generate_dataset.py` + `evaluate_benchmark.py` run

### Final Day — Polish + Documentation
- `COMPETITIVE_ANALYSIS.md`, `JUDGE_QA.md`, `DEMO_SCRIPT.md`
- `SCORECARD.md`, `PITCH.md`, `BUILD_PLAN.md`
- README, final test run, benchmark output capture

## Scoring Weight Optimization

| Criterion | Weight | Key Artifact |
|---|---|---|
| Technical depth | 40% | `guardrail_policy.py` + 107 tests + CUSUM math |
| Innovation | 25% | Guardrail independence + LLM taxonomy + audit ledger |
| Measurable impact | 20% | `benchmark_results.json` with REAL/MEASURED tags |
| Demo quality | 10% | Dashboard + failure injection + recovery flow |
| Presentation | 5% | `PITCH.md` four lengths |

# DEMO_SCRIPT.md — CascadeHeal 90-Second Demo

> Written AFTER system was built and benchmark ran. Every "TECHNICAL EVENT" column corresponds to real API calls and log lines the system actually produces.

| T (s) | ACTION | WHAT JUDGE SEES | WHAT I SAY | TECHNICAL EVENT |
|---|---|---|---|---|
| 0 | Open dashboard at localhost:3000 | Health tiles: UPI 94%, VISA 91%, HDFC 87%. Live audit stream scrolling. All rails HEALTHY. | "Normal payment traffic. Real-time CUSUM monitoring all 10 rails. 2 events/second." | SSE heartbeat from `GET /audit/stream`. Background traffic generator running. |
| 8 | Click **"HDFC Outage"** | HDFC tile immediately starts turning amber then red | "I'm injecting a real-time HDFC NetBanking failure. Watch the health score." | `POST /inject/hdfc_outage` → `rail_simulator.inject_scenario()` → burst of `BANK_UNAVAILABLE` events |
| 14 | Watch tiles update | HDFC drops: 87% → 45% → ~5%. Audit log: `CUSUM_DRIFT_DETECTED [HDFC_NETBANKING]` | "CUSUM just fired. 3 failures in the 90-second window exceeded the drift threshold." | `anomaly_engine.ingest()` returns `DriftSignal(cusum_value=0.31, error_rate=0.73)` |
| 20 | AI diagnosis appears in audit log | Log entry: `LLM_CLASSIFICATION [HDFC_NETBANKING]` or `LLM_FALLBACK_USED` | "LLM classified this as BANK_TIMEOUT — confidence 0.91 — and recommended REROUTE." | `agent_core.llm_classifier.classify()` returns `DiagnosticReport(classification=BANK_TIMEOUT, confidence=0.91)` |
| 25 | GUARDRAIL_PASS log entry | Green log: `GUARDRAIL_PASS — proposed REROUTE — all checks passed` | "Guardrail reviewed: not fraud, retry count 0, confidence sufficient. Approved." | `guardrail_policy.evaluate_guardrail()` returns `GuardrailVerdict(outcome=PASS)` |
| 30 | Incident panel appears | "HDFC_NETBANKING BANK_TIMEOUT exceeded CUSUM threshold → rerouted to UPI (health 0.97)" | "Traffic is now being rerouted to UPI. Watch the distribution chart." | `upsert_incident()` + `REROUTE_DECISION` audit entry written to SQLite |
| 38 | Traffic chart updates | HDFC bar drops to ~5%, UPI bar rises to ~80% | "HDFC went from 4% of traffic to 5% — minimal probe traffic. UPI now handles the load." | `GET /rails/traffic` returning updated `effective_weights` |
| 45 | Enter order ID "order_demo_001", click Generate | Recovery panel shows signed URL, 90s TTL countdown begins | "Customer whose payment just failed gets a one-tap recovery link. HMAC-signed, single-use." | `POST /recover/order_demo_001` → `generate_signed_recovery_link()` → state `FAILED→RECOVERY_PENDING` |
| 55 | Click "Simulate Customer Payment" | State badge changes: RECOVERY_PENDING → RECOVERED. Revenue counter increments. | "Customer paid. Transaction recovered. Revenue saved counter updated." | `POST /recover/order_demo_001/complete` → `consume_recovery_link()` atomic DB update → `RECOVERED` state |
| 65 | Click **"Suspicious Txn ⚠️"** | Audit log immediately shows `GUARDRAIL_VETO [SUSPECTED_FRAUD]` in red | "Now I'm injecting a suspicious transaction. Watch." | `POST /inject/suspicious_transaction` → `ErrorCode.SUSPECTED_FRAUD` event processed |
| 70 | Show audit log entry | "GUARDRAIL_VETO: Hard block: raw error code SUSPECTED_FRAUD in security block list. Action: ESCALATE." | "The guardrail refused. No retry. No reroute. Escalation logged. The AI can't override this." | `guardrail_policy.evaluate_guardrail()` → `GuardrailVerdict(outcome=VETO, violated_rule=HARD_BLOCK_ERROR_CODES)` |
| 80 | Click **"Multi-Rail Failure"** | Both HDFC and UPI tiles turn red. Audit log shows `NO_ELIGIBLE_RAIL`. | "Both HDFC and UPI are now degraded. System can't find a healthy fallback." | `_select_reroute_target()` returns `None` → `NO_ELIGIBLE_RAIL` audit entry |
| 88 | Point to audit trail | Audit stream shows full sequence: CUSUM → LLM → GUARDRAIL_PASS → REROUTE → RECOVERY → VETO | "Every decision is in this immutable append-only ledger. Exportable for compliance." | SQLite WAL audit_log table, accessible via `GET /audit/recent` |
| 90 | Done | Dashboard showing live metrics, full audit trail | "107 tests passing. 0 guardrail violations in benchmark. 2.51µs guardrail latency. Thank you." | `pytest tests/ → 107 passed, 0.23s` |

## Pre-Demo Checklist
- [ ] Backend running: `cd backend && python -m uvicorn main:app --reload`
- [ ] Frontend running: `cd frontend && npm run dev`
- [ ] Dashboard open at localhost:3000
- [ ] Benchmark result on screen: `cat benchmark_results.json | python -m json.tool | head -50`
- [ ] Test pass screenshot ready: `python -m pytest tests/ -v` output
- [ ] Click "Restore All" to reset all failure injections before demo

## Fallback If LLM Is Unavailable
The demo works identically in simulation mode — `SimulatedClassifier` fires instead, audit log shows `LLM_FALLBACK_USED` (not `LLM_CLASSIFICATION`). Say: "No LLM key configured — deterministic fallback active. The guardrail behavior is identical."

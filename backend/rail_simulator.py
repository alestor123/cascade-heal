"""
rail_simulator.py — CascadeHeal payment rail simulation engine.

Generates realistic synthetic payment events with configurable failure modes.
Supports named failure injection scenarios exposed via POST /inject/{scenario}.

IMPORTANT: This module generates SIMULATED data only.
No real payments are processed. No real bank APIs are called.
All transactions, error codes, and outcomes are synthetic.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Tuple

from schemas import (
    ErrorCode,
    InjectionScenario,
    PaymentRail,
    TelemetryEvent,
)


# ---------------------------------------------------------------------------
# Rail baseline configurations
# ---------------------------------------------------------------------------

@dataclass
class RailConfig:
    """Baseline characteristics of a payment rail."""
    rail: PaymentRail
    baseline_success_rate: float  # 0-1
    baseline_latency_ms: Tuple[int, int]  # (min, max)
    weight: float  # Traffic weight (sum to 1.0 across all rails)
    supported_amounts: Tuple[float, float]  # (min, max) INR


RAIL_CONFIGS: Dict[PaymentRail, RailConfig] = {
    PaymentRail.UPI: RailConfig(
        rail=PaymentRail.UPI,
        baseline_success_rate=0.94,
        baseline_latency_ms=(80, 400),
        weight=0.65,
        supported_amounts=(1, 100000),
    ),
    PaymentRail.VISA: RailConfig(
        rail=PaymentRail.VISA,
        baseline_success_rate=0.91,
        baseline_latency_ms=(150, 600),
        weight=0.10,
        supported_amounts=(100, 500000),
    ),
    PaymentRail.MASTERCARD: RailConfig(
        rail=PaymentRail.MASTERCARD,
        baseline_success_rate=0.90,
        baseline_latency_ms=(150, 600),
        weight=0.08,
        supported_amounts=(100, 500000),
    ),
    PaymentRail.RUPAY: RailConfig(
        rail=PaymentRail.RUPAY,
        baseline_success_rate=0.89,
        baseline_latency_ms=(100, 500),
        weight=0.02,
        supported_amounts=(100, 200000),
    ),
    PaymentRail.HDFC_NETBANKING: RailConfig(
        rail=PaymentRail.HDFC_NETBANKING,
        baseline_success_rate=0.87,
        baseline_latency_ms=(500, 3000),
        weight=0.04,
        supported_amounts=(1, 1000000),
    ),
    PaymentRail.ICICI_NETBANKING: RailConfig(
        rail=PaymentRail.ICICI_NETBANKING,
        baseline_success_rate=0.86,
        baseline_latency_ms=(500, 3000),
        weight=0.03,
        supported_amounts=(1, 1000000),
    ),
    PaymentRail.SBI_NETBANKING: RailConfig(
        rail=PaymentRail.SBI_NETBANKING,
        baseline_success_rate=0.82,
        baseline_latency_ms=(800, 5000),
        weight=0.02,
        supported_amounts=(1, 500000),
    ),
    PaymentRail.AXIS_NETBANKING: RailConfig(
        rail=PaymentRail.AXIS_NETBANKING,
        baseline_success_rate=0.85,
        baseline_latency_ms=(500, 3000),
        weight=0.02,
        supported_amounts=(1, 500000),
    ),
    PaymentRail.PHONEPE_WALLET: RailConfig(
        rail=PaymentRail.PHONEPE_WALLET,
        baseline_success_rate=0.95,
        baseline_latency_ms=(50, 200),
        weight=0.02,
        supported_amounts=(1, 10000),
    ),
    PaymentRail.PAYTM_WALLET: RailConfig(
        rail=PaymentRail.PAYTM_WALLET,
        baseline_success_rate=0.93,
        baseline_latency_ms=(50, 200),
        weight=0.02,
        supported_amounts=(1, 10000),
    ),
}

# Error code distribution for failure events (weights)
FAILURE_ERROR_WEIGHTS: Dict[ErrorCode, float] = {
    ErrorCode.TIMEOUT: 0.25,
    ErrorCode.BANK_UNAVAILABLE: 0.15,
    ErrorCode.GATEWAY_TIMEOUT: 0.15,
    ErrorCode.INVALID_OTP: 0.10,
    ErrorCode.INSUFFICIENT_FUNDS: 0.15,
    ErrorCode.ISSUER_DECLINED: 0.08,
    ErrorCode.SUSPECTED_FRAUD: 0.02,
    ErrorCode.NETWORK_ERROR: 0.07,
    ErrorCode.AUTH_REJECTED: 0.02,
    ErrorCode.UNKNOWN: 0.01,
}

# Sample Indian bank issuers
ISSUER_POOL = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES", "INDUSIND", "PNB", "BOI"]

# ─────────────────────────────────────────────────────────────────────────────
# Failure injection state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RailFailureOverride:
    """Active failure injection for a specific rail."""
    rail: PaymentRail
    forced_error_codes: List[ErrorCode]  # Injected error types
    failure_probability: float           # Overrides baseline (0=normal, 1=100% failure)
    latency_multiplier: float            # Multiplies baseline latency (1=normal)
    active: bool = True
    injected_at: float = field(default_factory=time.time)


class RailSimulator:
    """
    Generates realistic synthetic payment telemetry events.
    Supports failure injection scenarios via named scenarios.
    """

    def __init__(self) -> None:
        self._overrides: Dict[PaymentRail, RailFailureOverride] = {}
        self._lock = Lock()
        self._stats: Dict[PaymentRail, Dict] = {
            rail: {"success": 0, "failure": 0, "total": 0}
            for rail in PaymentRail
        }

    # -----------------------------------------------------------------------
    # Event generation
    # -----------------------------------------------------------------------

    def generate_event(
        self,
        rail: Optional[PaymentRail] = None,
        amount_inr: Optional[float] = None,
        customer_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """
        Generate a single synthetic payment telemetry event.
        If rail is None, a rail is sampled by traffic weight.
        """
        if rail is None:
            rail = self._sample_rail()

        cfg = RAIL_CONFIGS[rail]
        override = self._overrides.get(rail)

        # Determine outcome
        error_code = self._determine_outcome(rail, cfg, override)
        latency_ms = self._determine_latency(cfg, override, error_code)

        if amount_inr is None:
            amount_inr = round(
                random.uniform(cfg.supported_amounts[0], min(cfg.supported_amounts[1], 50000)),
                2,
            )

        # Update stats
        with self._lock:
            self._stats[rail]["total"] += 1
            if error_code == ErrorCode.SUCCESS:
                self._stats[rail]["success"] += 1
            else:
                self._stats[rail]["failure"] += 1

        return TelemetryEvent(
            event_id=str(uuid.uuid4()),
            order_id=str(uuid.uuid4()),
            rail=rail,
            error_code=error_code,
            amount_inr=amount_inr,
            latency_ms=latency_ms,
            issuer=random.choice(ISSUER_POOL) if rail in {
                PaymentRail.HDFC_NETBANKING, PaymentRail.ICICI_NETBANKING,
                PaymentRail.SBI_NETBANKING, PaymentRail.AXIS_NETBANKING,
            } else None,
            timestamp=datetime.now(timezone.utc),
            customer_id=customer_id or f"cust_{uuid.uuid4().hex[:8]}",
        )

    def generate_batch(self, n: int = 10) -> List[TelemetryEvent]:
        """Generate n synthetic events across all rails."""
        return [self.generate_event() for _ in range(n)]

    def generate_scenario_event(self, scenario: InjectionScenario) -> TelemetryEvent:
        """
        Generate a single event for a specific failure scenario.
        Used for testing specific code paths (e.g., INVALID_OTP must be refused).
        """
        if scenario == InjectionScenario.SUSPICIOUS_TRANSACTION:
            return TelemetryEvent(
                event_id=str(uuid.uuid4()),
                order_id=str(uuid.uuid4()),
                rail=PaymentRail.UPI,
                error_code=ErrorCode.SUSPECTED_FRAUD,
                amount_inr=49999.00,
                latency_ms=150,
                timestamp=datetime.utcnow(),
                customer_id=f"cust_{uuid.uuid4().hex[:8]}",
                metadata={"scenario": "suspicious_transaction"},
            )
        elif scenario == InjectionScenario.HDFC_OUTAGE:
            return TelemetryEvent(
                event_id=str(uuid.uuid4()),
                order_id=str(uuid.uuid4()),
                rail=PaymentRail.HDFC_NETBANKING,
                error_code=ErrorCode.BANK_UNAVAILABLE,
                amount_inr=round(random.uniform(500, 10000), 2),
                latency_ms=5000,
                timestamp=datetime.utcnow(),
                customer_id=f"cust_{uuid.uuid4().hex[:8]}",
                metadata={"scenario": "hdfc_outage"},
            )
        else:
            return self.generate_event()

    # -----------------------------------------------------------------------
    # Failure injection scenarios
    # -----------------------------------------------------------------------

    def inject_scenario(self, scenario: InjectionScenario, intensity: float = 1.0) -> Dict:
        """
        Apply a named failure injection. Returns a description of what was injected.
        intensity: 0.0-1.0, scales the failure probability.
        """
        descriptions = {}

        with self._lock:
            if scenario == InjectionScenario.HDFC_OUTAGE:
                self._overrides[PaymentRail.HDFC_NETBANKING] = RailFailureOverride(
                    rail=PaymentRail.HDFC_NETBANKING,
                    forced_error_codes=[ErrorCode.BANK_UNAVAILABLE, ErrorCode.TIMEOUT],
                    failure_probability=min(0.95 * intensity, 0.95),
                    latency_multiplier=5.0,
                )
                descriptions = {
                    "scenario": "HDFC_OUTAGE",
                    "affected_rail": "HDFC_NETBANKING",
                    "failure_probability": f"{min(0.95 * intensity, 0.95) * 100:.0f}%",
                    "description": "HDFC NetBanking experiencing service degradation (BANK_UNAVAILABLE, high latency)",
                }

            elif scenario == InjectionScenario.UPI_DEGRADATION:
                self._overrides[PaymentRail.UPI] = RailFailureOverride(
                    rail=PaymentRail.UPI,
                    forced_error_codes=[ErrorCode.GATEWAY_TIMEOUT, ErrorCode.NETWORK_ERROR],
                    failure_probability=min(0.40 * intensity, 0.80),
                    latency_multiplier=3.0,
                )
                descriptions = {
                    "scenario": "UPI_DEGRADATION",
                    "affected_rail": "UPI",
                    "failure_probability": f"{min(0.40 * intensity, 0.80) * 100:.0f}%",
                    "description": "UPI rail showing elevated timeout and network errors",
                }

            elif scenario == InjectionScenario.GATEWAY_TIMEOUT:
                # Apply to HDFC + ICICI
                for rail in [PaymentRail.HDFC_NETBANKING, PaymentRail.ICICI_NETBANKING]:
                    self._overrides[rail] = RailFailureOverride(
                        rail=rail,
                        forced_error_codes=[ErrorCode.GATEWAY_TIMEOUT],
                        failure_probability=min(0.70 * intensity, 0.90),
                        latency_multiplier=8.0,
                    )
                descriptions = {
                    "scenario": "GATEWAY_TIMEOUT",
                    "affected_rails": ["HDFC_NETBANKING", "ICICI_NETBANKING"],
                    "failure_probability": f"{min(0.70 * intensity, 0.90) * 100:.0f}%",
                    "description": "Gateway timeout affecting HDFC and ICICI NetBanking",
                }

            elif scenario == InjectionScenario.PAYMENT_FAILURE_SPIKE:
                # Apply across all rails
                for rail in PaymentRail:
                    cfg = RAIL_CONFIGS[rail]
                    self._overrides[rail] = RailFailureOverride(
                        rail=rail,
                        forced_error_codes=[ErrorCode.ISSUER_DECLINED, ErrorCode.TIMEOUT],
                        failure_probability=min(0.30 * intensity, 0.50),
                        latency_multiplier=2.0,
                    )
                descriptions = {
                    "scenario": "PAYMENT_FAILURE_SPIKE",
                    "affected_rails": "ALL",
                    "failure_probability": f"{min(0.30 * intensity, 0.50) * 100:.0f}%",
                    "description": "30% payment failure spike across all rails",
                }

            elif scenario == InjectionScenario.SUSPICIOUS_TRANSACTION:
                # Single event injection — doesn't set ongoing override
                descriptions = {
                    "scenario": "SUSPICIOUS_TRANSACTION",
                    "description": "Injecting single SUSPECTED_FRAUD event — must be refused by guardrail",
                    "note": "This scenario injects a single event, not an ongoing override",
                }

            elif scenario == InjectionScenario.MULTI_RAIL_FAILURE:
                # HDFC + UPI both degraded
                self._overrides[PaymentRail.HDFC_NETBANKING] = RailFailureOverride(
                    rail=PaymentRail.HDFC_NETBANKING,
                    forced_error_codes=[ErrorCode.BANK_UNAVAILABLE],
                    failure_probability=0.95,
                    latency_multiplier=5.0,
                )
                self._overrides[PaymentRail.UPI] = RailFailureOverride(
                    rail=PaymentRail.UPI,
                    forced_error_codes=[ErrorCode.GATEWAY_TIMEOUT, ErrorCode.NETWORK_ERROR],
                    failure_probability=0.70,
                    latency_multiplier=4.0,
                )
                descriptions = {
                    "scenario": "MULTI_RAIL_FAILURE",
                    "affected_rails": ["HDFC_NETBANKING", "UPI"],
                    "description": "Both HDFC NetBanking and UPI degraded. System should report NO_ELIGIBLE_RAIL.",
                }

            elif scenario == InjectionScenario.RESTORE_ALL:
                self._overrides.clear()
                descriptions = {
                    "scenario": "RESTORE_ALL",
                    "description": "All failure injections cleared. Rails returning to baseline.",
                }

        return descriptions

    # -----------------------------------------------------------------------
    # Health score computation (EWMA)
    # -----------------------------------------------------------------------

    def compute_health_scores(self) -> Dict[PaymentRail, float]:
        """
        Compute current health score for each rail based on stats and active overrides.
        Uses exponentially-weighted success rate as the estimator.
        α=0.3 gives ~60% weight to the last 3 recent observations.
        """
        scores = {}
        with self._lock:
            for rail, cfg in RAIL_CONFIGS.items():
                override = self._overrides.get(rail)
                if override and override.active:
                    # Health score is reduced by the failure override
                    effective_success_rate = max(
                        0.0, cfg.baseline_success_rate - override.failure_probability
                    )
                    scores[rail] = round(effective_success_rate, 4)
                else:
                    # Use baseline slightly randomized for realism
                    noise = random.uniform(-0.02, 0.02)
                    scores[rail] = round(
                        max(0.0, min(1.0, cfg.baseline_success_rate + noise)), 4
                    )
        return scores

    def get_traffic_distribution(self) -> Dict[PaymentRail, Dict]:
        """
        Return current traffic distribution (how traffic is weighted across rails).
        Reflects overrides: degraded rails get less traffic.
        """
        with self._lock:
            total_weight = 0.0
            effective_weights = {}
            for rail, cfg in RAIL_CONFIGS.items():
                override = self._overrides.get(rail)
                if override and override.active and override.failure_probability > 0.70:
                    # Heavily degraded rails get minimal traffic (circuit breaker effect)
                    effective_weights[rail] = cfg.weight * 0.05
                elif override and override.active and override.failure_probability > 0.30:
                    effective_weights[rail] = cfg.weight * 0.30
                else:
                    effective_weights[rail] = cfg.weight
                total_weight += effective_weights[rail]

            return {
                rail: {
                    "weight": round(w / total_weight * 100, 1),
                    "baseline_weight": round(RAIL_CONFIGS[rail].weight * 100, 1),
                    "degraded": rail in self._overrides and self._overrides[rail].active,
                }
                for rail, w in effective_weights.items()
            }

    def get_stats(self) -> Dict[str, Dict]:
        with self._lock:
            return {
                rail.value: dict(self._stats[rail])
                for rail in PaymentRail
            }

    def get_active_overrides(self) -> List[str]:
        """Return names of currently active failure overrides."""
        with self._lock:
            return [rail.value for rail, ov in self._overrides.items() if ov.active]

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _sample_rail(self) -> PaymentRail:
        rails = list(RAIL_CONFIGS.keys())
        weights = [RAIL_CONFIGS[r].weight for r in rails]
        return random.choices(rails, weights=weights, k=1)[0]

    def _determine_outcome(
        self,
        rail: PaymentRail,
        cfg: RailConfig,
        override: Optional[RailFailureOverride],
    ) -> ErrorCode:
        if override and override.active:
            failure_prob = override.failure_probability
        else:
            failure_prob = 1.0 - cfg.baseline_success_rate

        if random.random() < failure_prob:
            # Failure — choose error code
            if override and override.forced_error_codes:
                # Weight forced codes heavily but allow some variety
                if random.random() < 0.80:
                    return random.choice(override.forced_error_codes)
            # Otherwise sample from general failure distribution
            codes = list(FAILURE_ERROR_WEIGHTS.keys())
            weights = [FAILURE_ERROR_WEIGHTS[c] for c in codes]
            return random.choices(codes, weights=weights, k=1)[0]
        else:
            return ErrorCode.SUCCESS

    def _determine_latency(
        self,
        cfg: RailConfig,
        override: Optional[RailFailureOverride],
        error_code: ErrorCode,
    ) -> int:
        min_ms, max_ms = cfg.baseline_latency_ms
        base_latency = random.randint(min_ms, max_ms)

        if error_code == ErrorCode.TIMEOUT or error_code == ErrorCode.BANK_UNAVAILABLE:
            base_latency = max_ms * 3  # Timeouts are always high latency

        if override and override.active:
            base_latency = int(base_latency * override.latency_multiplier)

        return min(base_latency, 30000)  # Cap at 30s


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

rail_simulator = RailSimulator()

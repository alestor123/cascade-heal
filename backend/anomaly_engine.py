"""
anomaly_engine.py — CascadeHeal CUSUM sliding-window anomaly detector.

NOT AI/ML. This is a well-established statistical process control method.
The choice of CUSUM over ML is intentional and documented in ARCHITECTURE.md:
  - No training data required
  - O(n) complexity per event
  - Fully explainable math that a judge can inspect
  - Standard in industrial quality control (Page, 1954)

CUSUM fires when the cumulative sum of error-rate deviations above a
target baseline exceeds a decision threshold h. This detects sustained
drift, not point anomalies — preventing false-positive alerts from
temporary blips.

Sliding window: events older than WINDOW_SECONDS are dropped from the
feature window, allowing the baseline to adapt to time-of-day patterns.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Dict, List, Optional, Tuple

from schemas import DriftSignal, ErrorCode, PaymentRail


# ---------------------------------------------------------------------------
# CUSUM parameters
# ---------------------------------------------------------------------------

# Observation window: keep events from the last N seconds
WINDOW_SECONDS: int = 90

# Baseline (target) error rate per rail — below this is "normal"
# In production this would be calibrated from historical data.
# For prototype: 10% is a reasonable baseline for Indian payment rails.
BASELINE_ERROR_RATE: float = 0.10

# Allowance K: typically 0.5 * expected shift magnitude.
# We want to detect shifts of ~15% (baseline 10% → 25% = shift of 0.15).
# K = 0.15 / 2 = 0.075
CUSUM_K: float = 0.075

# Decision threshold h: at h=0.3, a sustained 15% shift fires in ~4 observations.
# Higher h = fewer false positives but slower detection.
CUSUM_H: float = 0.30

# Minimum failures in window before CUSUM can fire.
# Prevents firing on tiny windows (e.g., 3 failures out of 3 transactions = 100%).
MIN_FAILURES_TO_TRIGGER: int = 3

# Minimum total events in window before CUSUM can fire.
MIN_EVENTS_TO_EVALUATE: int = 5


# ---------------------------------------------------------------------------
# Per-event record
# ---------------------------------------------------------------------------

@dataclass
class EventRecord:
    timestamp: float   # Unix time
    is_failure: bool
    error_code: ErrorCode
    latency_ms: int


# ---------------------------------------------------------------------------
# Per-rail state
# ---------------------------------------------------------------------------

@dataclass
class RailCusumState:
    """
    Maintains rolling window and CUSUM statistic for one payment rail.
    """
    rail: PaymentRail
    window: Deque[EventRecord] = field(default_factory=deque)
    cusum_plus: float = 0.0    # Upper CUSUM (detects increase in error rate)
    cusum_minus: float = 0.0   # Lower CUSUM (detects recovery — not used for alarms)
    last_drift_signal: Optional[float] = None  # Unix timestamp of last alarm
    # Cooldown: don't re-alarm on the same drift within 30s
    alarm_cooldown_seconds: float = 30.0
    lock: Lock = field(default_factory=Lock)

    def __post_init__(self):
        # dataclass doesn't deep-copy defaults safely with mutable types
        if not isinstance(self.window, deque):
            self.window = deque()

    def evict_old_events(self, now: float) -> None:
        """Remove events older than WINDOW_SECONDS from the left of the deque."""
        cutoff = now - WINDOW_SECONDS
        while self.window and self.window[0].timestamp < cutoff:
            self.window.popleft()

    def current_error_rate(self) -> float:
        if not self.window:
            return 0.0
        failures = sum(1 for e in self.window if e.is_failure)
        return failures / len(self.window)

    def current_failure_count(self) -> int:
        return sum(1 for e in self.window if e.is_failure)

    def error_type_breakdown(self) -> Dict[str, int]:
        breakdown: Dict[str, int] = {}
        for e in self.window:
            if e.is_failure:
                key = e.error_code.value
                breakdown[key] = breakdown.get(key, 0) + 1
        return breakdown

    def latency_p95(self) -> int:
        """95th percentile latency from window events."""
        latencies = sorted(e.latency_ms for e in self.window)
        if not latencies:
            return 0
        idx = int(0.95 * len(latencies))
        return latencies[min(idx, len(latencies) - 1)]


# ---------------------------------------------------------------------------
# Anomaly engine
# ---------------------------------------------------------------------------

class AnomalyEngine:
    """
    Maintains CUSUM state for all payment rails.
    Thread-safe via per-rail locks.
    """

    def __init__(self) -> None:
        self._states: Dict[PaymentRail, RailCusumState] = {
            rail: RailCusumState(rail=rail)
            for rail in PaymentRail
        }

    def ingest(
        self,
        rail: PaymentRail,
        error_code: ErrorCode,
        latency_ms: int,
    ) -> Optional[DriftSignal]:
        """
        Ingest a single telemetry event for a rail.
        Returns a DriftSignal if CUSUM crosses the threshold, otherwise None.

        CUSUM update equations (one-sided, upper CUSUM for error rate):
          x_i = current error rate observation (binary: 0 or 1 for this event)
          C+ = max(0, C+_prev + (x_i - baseline - K))

        Note: we use the *rolling error rate* as the observation, not the
        per-event binary flag — this provides a smoother signal.
        """
        state = self._states[rail]
        is_failure = error_code != ErrorCode.SUCCESS
        now = time.time()

        with state.lock:
            # 1. Add event to window
            state.window.append(
                EventRecord(
                    timestamp=now,
                    is_failure=is_failure,
                    error_code=error_code,
                    latency_ms=latency_ms,
                )
            )

            # 2. Evict old events
            state.evict_old_events(now)

            # 3. Check minimum event count
            if len(state.window) < MIN_EVENTS_TO_EVALUATE:
                return None

            # 4. Compute current error rate (rolling window observation)
            error_rate = state.current_error_rate()
            failure_count = state.current_failure_count()

            # 5. Update CUSUM+
            # x_i = error_rate, target = BASELINE_ERROR_RATE, allowance = K
            state.cusum_plus = max(
                0.0,
                state.cusum_plus + (error_rate - BASELINE_ERROR_RATE - CUSUM_K)
            )

            # 6. Update CUSUM- (tracks recovery)
            state.cusum_minus = max(
                0.0,
                state.cusum_minus + (BASELINE_ERROR_RATE - CUSUM_K - error_rate)
            )

            # 7. Check alarm condition
            if (
                state.cusum_plus >= CUSUM_H
                and failure_count >= MIN_FAILURES_TO_TRIGGER
            ):
                # Check cooldown to avoid re-alarming on the same incident
                if (
                    state.last_drift_signal is None
                    or now - state.last_drift_signal > state.alarm_cooldown_seconds
                ):
                    state.last_drift_signal = now
                    # Reset CUSUM after alarm to prevent continuous re-triggering
                    state.cusum_plus = 0.0

                    severity = self._classify_severity(state.cusum_plus, error_rate)
                    return DriftSignal(
                        rail=rail,
                        cusum_value=round(state.cusum_plus + CUSUM_H, 4),  # pre-reset value
                        error_rate=round(error_rate, 4),
                        baseline_error_rate=BASELINE_ERROR_RATE,
                        window_size=len(state.window),
                        triggered_at=datetime.now(timezone.utc),
                        severity=severity,
                        affected_error_codes=self._dominant_error_codes(state),
                    )

        return None

    def reset_rail(self, rail: PaymentRail) -> None:
        """Reset CUSUM state for a rail (used when circuit breaker closes)."""
        state = self._states[rail]
        with state.lock:
            state.window.clear()
            state.cusum_plus = 0.0
            state.cusum_minus = 0.0
            state.last_drift_signal = None

    def get_rail_summary(self, rail: PaymentRail) -> Dict:
        """Return a summary of current rail state for the health endpoint."""
        state = self._states[rail]
        with state.lock:
            state.evict_old_events(time.time())
            return {
                "rail": rail.value,
                "window_events": len(state.window),
                "error_rate": round(state.current_error_rate(), 4),
                "failure_count": state.current_failure_count(),
                "cusum_plus": round(state.cusum_plus, 4),
                "cusum_threshold": CUSUM_H,
                "latency_p95_ms": state.latency_p95(),
                "error_breakdown": state.error_type_breakdown(),
            }

    def get_all_summaries(self) -> List[Dict]:
        return [self.get_rail_summary(rail) for rail in PaymentRail]

    @staticmethod
    def _classify_severity(cusum_value: float, error_rate: float) -> str:
        if error_rate >= 0.50:
            return "HIGH"
        elif error_rate >= 0.25:
            return "MEDIUM"
        else:
            return "LOW"

    @staticmethod
    def _dominant_error_codes(state: RailCusumState) -> List[ErrorCode]:
        """Return error codes present in the window, sorted by frequency."""
        breakdown = state.error_type_breakdown()
        sorted_codes = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
        result = []
        for code_str, _ in sorted_codes[:3]:
            try:
                result.append(ErrorCode(code_str))
            except ValueError:
                pass
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

anomaly_engine = AnomalyEngine()

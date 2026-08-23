"""
schemas.py — CascadeHeal Pydantic v2 data models.

All illegal states are bound at the type level.
No external dependencies beyond pydantic and standard library.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PaymentRail(str, enum.Enum):
    UPI = "UPI"
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    RUPAY = "RUPAY"
    HDFC_NETBANKING = "HDFC_NETBANKING"
    ICICI_NETBANKING = "ICICI_NETBANKING"
    SBI_NETBANKING = "SBI_NETBANKING"
    AXIS_NETBANKING = "AXIS_NETBANKING"
    PHONEPE_WALLET = "PHONEPE_WALLET"
    PAYTM_WALLET = "PAYTM_WALLET"


class TransactionState(str, enum.Enum):
    INITIATED = "INITIATED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RECOVERED = "RECOVERED"
    RECOVERY_EXPIRED = "RECOVERY_EXPIRED"
    # Sentinel for race condition voiding
    VOIDED = "VOIDED"


class ErrorCode(str, enum.Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    BANK_UNAVAILABLE = "BANK_UNAVAILABLE"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    INVALID_OTP = "INVALID_OTP"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ISSUER_DECLINED = "ISSUER_DECLINED"
    SUSPECTED_FRAUD = "SUSPECTED_FRAUD"
    NETWORK_ERROR = "NETWORK_ERROR"
    AUTH_REJECTED = "AUTH_REJECTED"
    INCORRECT_CREDENTIALS = "INCORRECT_CREDENTIALS"
    UNKNOWN = "UNKNOWN"


class FailureClassification(str, enum.Enum):
    BANK_TIMEOUT = "BANK_TIMEOUT"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    ISSUER_DECLINE = "ISSUER_DECLINE"
    INVALID_OTP = "INVALID_OTP"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    SUSPECTED_FRAUD = "SUSPECTED_FRAUD"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


class RemediationActionType(str, enum.Enum):
    REROUTE = "REROUTE"
    RECOVER = "RECOVER"
    MONITOR = "MONITOR"
    HOLD = "HOLD"
    STOP = "STOP"
    NO_ELIGIBLE_RAIL = "NO_ELIGIBLE_RAIL"
    ESCALATE = "ESCALATE"


class RailStatus(str, enum.Enum):
    HEALTHY = "HEALTHY"       # score >= 0.80
    DEGRADED = "DEGRADED"     # 0.50 <= score < 0.80
    UNHEALTHY = "UNHEALTHY"   # score < 0.50


class GuardrailOutcome(str, enum.Enum):
    PASS = "PASS"
    VETO = "VETO"


class AuditEventType(str, enum.Enum):
    TELEMETRY_RECEIVED = "TELEMETRY_RECEIVED"
    CUSUM_DRIFT_DETECTED = "CUSUM_DRIFT_DETECTED"
    LLM_CLASSIFICATION = "LLM_CLASSIFICATION"
    LLM_FALLBACK_USED = "LLM_FALLBACK_USED"
    GUARDRAIL_PASS = "GUARDRAIL_PASS"
    GUARDRAIL_VETO = "GUARDRAIL_VETO"
    REROUTE_DECISION = "REROUTE_DECISION"
    NO_ELIGIBLE_RAIL = "NO_ELIGIBLE_RAIL"
    RECOVERY_LINK_GENERATED = "RECOVERY_LINK_GENERATED"
    RECOVERY_LINK_USED = "RECOVERY_LINK_USED"
    RECOVERY_LINK_EXPIRED = "RECOVERY_LINK_EXPIRED"
    STATE_TRANSITION = "STATE_TRANSITION"
    RACE_CONDITION_VOIDED = "RACE_CONDITION_VOIDED"
    CIRCUIT_BREAKER_OPENED = "CIRCUIT_BREAKER_OPENED"
    CIRCUIT_BREAKER_CLOSED = "CIRCUIT_BREAKER_CLOSED"
    FAILURE_INJECTION = "FAILURE_INJECTION"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class TelemetryEvent(BaseModel):
    """Single transaction outcome event."""
    event_id: str = Field(..., description="Unique event identifier")
    order_id: str = Field(..., description="Order identifier")
    rail: PaymentRail
    error_code: ErrorCode
    amount_inr: float = Field(..., gt=0, description="Transaction amount in INR")
    latency_ms: int = Field(..., ge=0, description="Gateway response latency in ms")
    issuer: Optional[str] = Field(None, description="Issuing bank code")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    customer_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    """Batch of telemetry events for bulk ingestion."""
    events: List[TelemetryEvent] = Field(..., min_length=1, max_length=1000)


class DriftSignal(BaseModel):
    """Output of CUSUM anomaly engine when drift is detected."""
    rail: PaymentRail
    cusum_value: float = Field(..., description="Current CUSUM statistic at trigger")
    error_rate: float = Field(..., ge=0.0, le=1.0, description="Current error rate in window")
    baseline_error_rate: float = Field(..., ge=0.0, le=1.0, description="Expected baseline error rate")
    window_size: int = Field(..., ge=1, description="Number of events in rolling window")
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    severity: str = Field(..., description="LOW | MEDIUM | HIGH based on cusum magnitude")
    affected_error_codes: List[ErrorCode] = Field(default_factory=list)


class DiagnosticReport(BaseModel):
    """Structured output from LLM classification call."""
    rail: PaymentRail
    classification: FailureClassification
    confidence: float = Field(..., ge=0.0, le=1.0)
    blast_radius: int = Field(..., ge=0, description="Estimated number of affected transactions")
    reasoning: str = Field(..., description="Human-readable explanation for dashboard")
    recommended_action: RemediationActionType
    is_customer_caused: bool = Field(
        ...,
        description="True if failure is caused by customer action (wrong PIN, insufficient funds)"
    )
    is_llm_fallback: bool = Field(
        default=False,
        description="True if this was generated by deterministic fallback, not LLM"
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RemediationAction(BaseModel):
    """Routing/recovery decision after guardrail check."""
    order_id: Optional[str] = None
    action_type: RemediationActionType
    source_rail: PaymentRail
    target_rail: Optional[PaymentRail] = None
    reason_string: str = Field(..., description="Human-readable explanation for dashboard")
    recovery_link: Optional[str] = None
    recovery_link_expires_at: Optional[datetime] = None


class GuardrailVerdict(BaseModel):
    """Output of guardrail policy engine."""
    outcome: GuardrailOutcome
    reason: str
    violated_rule: Optional[str] = None
    proposed_action: RemediationActionType
    # What action is allowed after guardrail (may differ from proposed)
    allowed_action: Optional[RemediationActionType] = None


class RailHealth(BaseModel):
    """Live health state of a payment rail."""
    rail: PaymentRail
    score: float = Field(..., ge=0.0, le=1.0)
    status: RailStatus
    success_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    circuit_breaker_open: bool = Field(default=False)
    consecutive_successes: int = Field(default=0)
    incident_active: bool = Field(default=False)
    incident_description: Optional[str] = None

    @classmethod
    def from_score(cls, rail: PaymentRail, score: float, **kwargs) -> "RailHealth":
        if score >= 0.80:
            status = RailStatus.HEALTHY
        elif score >= 0.50:
            status = RailStatus.DEGRADED
        else:
            status = RailStatus.UNHEALTHY
        return cls(rail=rail, score=round(score, 4), status=status, **kwargs)


class AuditEntry(BaseModel):
    """Immutable audit log entry."""
    entry_id: Optional[int] = None  # Auto-assigned by DB
    event_type: AuditEventType
    rail: Optional[PaymentRail] = None
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    guardrail_outcome: Optional[GuardrailOutcome] = None
    guardrail_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransactionRecord(BaseModel):
    """Full transaction record with state machine state."""
    order_id: str
    customer_id: Optional[str] = None
    rail: PaymentRail
    amount_inr: float = Field(..., gt=0)
    state: TransactionState
    error_code: Optional[ErrorCode] = None
    classification: Optional[FailureClassification] = None
    recovery_link_id: Optional[str] = None
    recovery_link_expires_at: Optional[datetime] = None
    recovery_link_used: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecoveryLinkPayload(BaseModel):
    """Signed payload embedded in recovery link."""
    order_id: str
    customer_id: str
    amount_inr: float = Field(..., gt=0)
    link_id: str
    expires_at: datetime

    @field_validator("amount_inr")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------

class InjectionScenario(str, enum.Enum):
    HDFC_OUTAGE = "hdfc_outage"
    UPI_DEGRADATION = "upi_degradation"
    GATEWAY_TIMEOUT = "gateway_timeout"
    PAYMENT_FAILURE_SPIKE = "payment_failure_spike"
    SUSPICIOUS_TRANSACTION = "suspicious_transaction"
    MULTI_RAIL_FAILURE = "multi_rail_failure"
    RESTORE_ALL = "restore_all"


class InjectionRequest(BaseModel):
    scenario: InjectionScenario
    intensity: float = Field(default=1.0, ge=0.0, le=1.0, description="Failure intensity 0-1")


class HealthResponse(BaseModel):
    rails: List[RailHealth]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IncidentSummary(BaseModel):
    incident_id: str
    rail: PaymentRail
    classification: FailureClassification
    confidence: float
    blast_radius: int
    description: str
    action_taken: RemediationActionType
    target_rail: Optional[PaymentRail] = None
    started_at: datetime
    resolved: bool = False


class DashboardMetrics(BaseModel):
    total_transactions: int
    success_count: int
    failure_count: int
    recovery_attempts: int
    successful_recoveries: int
    recovery_rate: float
    simulated_revenue_recovered_inr: float
    active_incidents: List[IncidentSummary]
    rail_health: List[RailHealth]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

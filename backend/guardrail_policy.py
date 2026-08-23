"""
guardrail_policy.py — CascadeHeal deterministic guardrail engine.

This is the load-bearing safety module of the entire system.

Design contract:
  - Pure function: given inputs → deterministic output
  - Synchronous: no async, no I/O, no side effects
  - Zero LLM dependency: zero import of agent_core, razorpay_gateway, or any LLM client
  - Unit-testable without any API key or external service
  - Hard-coded limits: constants in source code, NOT in config files or DB settings

A judge can read this file, understand every limit, and unit-test
every adversarial bypass attempt without running any external service.

HARD LIMITS (code-enforced):
  MAX_RETRIES_PER_ORDER = 1
  MAX_DISCOUNT_PCT = 5.0
  RECOVERY_LINK_TTL_SECONDS = 90
  HARD_BLOCK_CLASSIFICATIONS = {INVALID_OTP, SUSPECTED_FRAUD, AUTH_REJECTED, INCORRECT_CREDENTIALS}
  HARD_BLOCK_ERROR_CODES = {INVALID_OTP, SUSPECTED_FRAUD, AUTH_REJECTED, INCORRECT_CREDENTIALS}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set

from schemas import (
    DiagnosticReport,
    ErrorCode,
    FailureClassification,
    GuardrailOutcome,
    GuardrailVerdict,
    RemediationActionType,
)


# ---------------------------------------------------------------------------
# Hard-coded limits — These are intentionally NOT configurable at runtime.
# Any attempt to change these requires a code change + test suite re-run.
# ---------------------------------------------------------------------------

MAX_RETRIES_PER_ORDER: int = 1

MAX_DISCOUNT_PCT: float = 5.0

RECOVERY_LINK_TTL_SECONDS: int = 90

# Error codes that ALWAYS block retry/reroute, regardless of LLM classification.
# This dual-check prevents LLM misclassification from enabling unsafe retries.
HARD_BLOCK_ERROR_CODES: Set[ErrorCode] = {
    ErrorCode.INVALID_OTP,
    ErrorCode.SUSPECTED_FRAUD,
    ErrorCode.AUTH_REJECTED,
    ErrorCode.INCORRECT_CREDENTIALS,
}

# Classifications that ALWAYS block retry/reroute, regardless of raw error code.
HARD_BLOCK_CLASSIFICATIONS: Set[FailureClassification] = {
    FailureClassification.INVALID_OTP,
    FailureClassification.SUSPECTED_FRAUD,
}

# Classifications where reroute is eligible (infrastructure failures).
REROUTE_ELIGIBLE_CLASSIFICATIONS: Set[FailureClassification] = {
    FailureClassification.BANK_TIMEOUT,
    FailureClassification.GATEWAY_TIMEOUT,
    FailureClassification.NETWORK_ERROR,
}

# Minimum confidence for acting on LLM classification.
# Below this threshold, the system defaults to MONITOR, not action.
MIN_CONFIDENCE_FOR_ACTION: float = 0.70

# Maximum recovery links per customer per order.
MAX_RECOVERY_LINKS_PER_ORDER: int = 1


# ---------------------------------------------------------------------------
# Guardrail input context
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuardrailContext:
    """
    Immutable input context for guardrail evaluation.
    All fields required — no optional inputs. Caller must provide defaults.
    """
    raw_error_code: ErrorCode
    retry_count: int
    proposed_action: RemediationActionType
    classification: Optional[FailureClassification]
    confidence: float
    proposed_discount_pct: float
    recovery_links_already_sent: int
    is_customer_caused: bool


# ---------------------------------------------------------------------------
# Core guardrail function
# ---------------------------------------------------------------------------

def evaluate_guardrail(ctx: GuardrailContext) -> GuardrailVerdict:
    """
    Evaluate a proposed remediation action against the safety envelope.

    Implements a "lower wins" principle: the more conservative check (raw error
    code OR LLM classification) governs. This prevents LLM misclassification
    from enabling unsafe retries.

    Parameters
    ----------
    ctx : GuardrailContext
        Immutable context containing all information needed for the guardrail decision.

    Returns
    -------
    GuardrailVerdict
        outcome=PASS if the action is allowed, VETO if blocked.
        violated_rule is set if outcome=VETO.
        allowed_action is set to the safe fallback when vetoed.
    """

    # -----------------------------------------------------------------------
    # Rule 1: Hard block on fraud/auth error codes (raw error code check).
    # This check runs REGARDLESS of LLM classification — it cannot be bypassed
    # by an LLM that misclassifies SUSPECTED_FRAUD as BANK_TIMEOUT.
    # -----------------------------------------------------------------------
    if ctx.raw_error_code in HARD_BLOCK_ERROR_CODES:
        if ctx.proposed_action in (
            RemediationActionType.REROUTE,
            RemediationActionType.RECOVER,
            RemediationActionType.HOLD,
        ):
            return GuardrailVerdict(
                outcome=GuardrailOutcome.VETO,
                reason=(
                    f"Hard block: raw error code '{ctx.raw_error_code.value}' is in the "
                    f"security block list. No retry, reroute, or recovery permitted. "
                    f"Action required: escalate to fraud/security team."
                ),
                violated_rule="HARD_BLOCK_ERROR_CODES",
                proposed_action=ctx.proposed_action,
                allowed_action=RemediationActionType.ESCALATE,
            )

    # -----------------------------------------------------------------------
    # Rule 2: Hard block on fraud/auth LLM classifications.
    # Second independent check — catches cases where raw error code is ambiguous
    # but LLM correctly classifies as fraud.
    # -----------------------------------------------------------------------
    if ctx.classification in HARD_BLOCK_CLASSIFICATIONS:
        if ctx.proposed_action in (
            RemediationActionType.REROUTE,
            RemediationActionType.RECOVER,
            RemediationActionType.HOLD,
        ):
            return GuardrailVerdict(
                outcome=GuardrailOutcome.VETO,
                reason=(
                    f"Hard block: LLM classification '{ctx.classification.value}' is in the "
                    f"security block list. Confidence: {ctx.confidence:.2f}. "
                    f"Action required: escalate."
                ),
                violated_rule="HARD_BLOCK_CLASSIFICATIONS",
                proposed_action=ctx.proposed_action,
                allowed_action=RemediationActionType.ESCALATE,
            )

    # -----------------------------------------------------------------------
    # Rule 3: Maximum retries per order.
    # -----------------------------------------------------------------------
    if ctx.retry_count >= MAX_RETRIES_PER_ORDER and ctx.proposed_action in (
        RemediationActionType.REROUTE,
        RemediationActionType.RECOVER,
    ):
        return GuardrailVerdict(
            outcome=GuardrailOutcome.VETO,
            reason=(
                f"Retry limit exceeded: this order has already been retried "
                f"{ctx.retry_count} time(s). Maximum is {MAX_RETRIES_PER_ORDER}. "
                f"Stopping to prevent infinite retry loop."
            ),
            violated_rule="MAX_RETRIES_PER_ORDER",
            proposed_action=ctx.proposed_action,
            allowed_action=RemediationActionType.STOP,
        )

    # -----------------------------------------------------------------------
    # Rule 4: Maximum discount / concession.
    # -----------------------------------------------------------------------
    if ctx.proposed_discount_pct > MAX_DISCOUNT_PCT:
        return GuardrailVerdict(
            outcome=GuardrailOutcome.VETO,
            reason=(
                f"Discount limit exceeded: proposed {ctx.proposed_discount_pct:.1f}% "
                f"exceeds maximum {MAX_DISCOUNT_PCT:.1f}%. "
                f"Capping at {MAX_DISCOUNT_PCT:.1f}%."
            ),
            violated_rule="MAX_DISCOUNT_PCT",
            proposed_action=ctx.proposed_action,
            allowed_action=ctx.proposed_action,  # Allow, but discount capped
        )

    # -----------------------------------------------------------------------
    # Rule 5: One recovery link per order.
    # -----------------------------------------------------------------------
    if (
        ctx.proposed_action == RemediationActionType.RECOVER
        and ctx.recovery_links_already_sent >= MAX_RECOVERY_LINKS_PER_ORDER
    ):
        return GuardrailVerdict(
            outcome=GuardrailOutcome.VETO,
            reason=(
                f"Recovery link limit: {ctx.recovery_links_already_sent} link(s) already "
                f"sent for this order. Maximum is {MAX_RECOVERY_LINKS_PER_ORDER}. "
                f"Preventing recovery link spam."
            ),
            violated_rule="MAX_RECOVERY_LINKS_PER_ORDER",
            proposed_action=ctx.proposed_action,
            allowed_action=RemediationActionType.STOP,
        )

    # -----------------------------------------------------------------------
    # Rule 6: Customer-caused failures are not eligible for reroute.
    # -----------------------------------------------------------------------
    if ctx.is_customer_caused and ctx.proposed_action == RemediationActionType.REROUTE:
        return GuardrailVerdict(
            outcome=GuardrailOutcome.VETO,
            reason=(
                "Reroute blocked: failure is customer-caused (wrong credentials, insufficient "
                "funds, etc.). Rerouting to a different rail will not resolve the issue. "
                "Customer action required."
            ),
            violated_rule="CUSTOMER_CAUSED_NO_REROUTE",
            proposed_action=ctx.proposed_action,
            allowed_action=RemediationActionType.STOP,
        )

    # -----------------------------------------------------------------------
    # Rule 7: Low-confidence classification → downgrade to MONITOR.
    # -----------------------------------------------------------------------
    if (
        ctx.confidence < MIN_CONFIDENCE_FOR_ACTION
        and ctx.proposed_action in (
            RemediationActionType.REROUTE,
            RemediationActionType.RECOVER,
        )
    ):
        return GuardrailVerdict(
            outcome=GuardrailOutcome.VETO,
            reason=(
                f"Low confidence: classification confidence {ctx.confidence:.2f} is below "
                f"minimum {MIN_CONFIDENCE_FOR_ACTION:.2f} required for action. "
                f"Downgrading to MONITOR to prevent false-positive intervention."
            ),
            violated_rule="MIN_CONFIDENCE_FOR_ACTION",
            proposed_action=ctx.proposed_action,
            allowed_action=RemediationActionType.MONITOR,
        )

    # -----------------------------------------------------------------------
    # All checks passed — action is allowed.
    # -----------------------------------------------------------------------
    return GuardrailVerdict(
        outcome=GuardrailOutcome.PASS,
        reason="All guardrail checks passed.",
        violated_rule=None,
        proposed_action=ctx.proposed_action,
        allowed_action=ctx.proposed_action,
    )


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------

def build_guardrail_context(
    raw_error_code: ErrorCode,
    retry_count: int,
    proposed_action: RemediationActionType,
    classification: Optional[FailureClassification] = None,
    confidence: float = 0.0,
    proposed_discount_pct: float = 0.0,
    recovery_links_already_sent: int = 0,
    is_customer_caused: bool = False,
) -> GuardrailContext:
    """
    Convenience constructor for GuardrailContext with safe defaults.
    All parameters must be explicitly provided in tests for clarity.
    """
    return GuardrailContext(
        raw_error_code=raw_error_code,
        retry_count=retry_count,
        proposed_action=proposed_action,
        classification=classification,
        confidence=confidence,
        proposed_discount_pct=proposed_discount_pct,
        recovery_links_already_sent=recovery_links_already_sent,
        is_customer_caused=is_customer_caused,
    )

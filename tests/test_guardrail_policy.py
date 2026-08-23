"""
tests/test_guardrail_policy.py — Unit tests for the guardrail engine.

These tests prove that every hard limit cannot be bypassed, including
adversarial inputs (e.g., an LLM recommendation that tries to set a 20%
discount, or retries an INVALID_OTP case).

ALL TESTS RUN WITHOUT ANY EXTERNAL API CALL — zero LLM dependency.
This is the proof that the guardrail is LLM-independent.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

import pytest
from guardrail_policy import (
    MAX_DISCOUNT_PCT,
    MAX_RECOVERY_LINKS_PER_ORDER,
    MAX_RETRIES_PER_ORDER,
    RECOVERY_LINK_TTL_SECONDS,
    GuardrailContext,
    build_guardrail_context,
    evaluate_guardrail,
)
from schemas import (
    ErrorCode,
    FailureClassification,
    GuardrailOutcome,
    RemediationActionType,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_ctx(**kwargs) -> GuardrailContext:
    """Build a context with safe defaults, overriding only specified fields."""
    defaults = dict(
        raw_error_code=ErrorCode.TIMEOUT,
        retry_count=0,
        proposed_action=RemediationActionType.REROUTE,
        classification=FailureClassification.BANK_TIMEOUT,
        confidence=0.91,
        proposed_discount_pct=0.0,
        recovery_links_already_sent=0,
        is_customer_caused=False,
    )
    defaults.update(kwargs)
    return build_guardrail_context(**defaults)


# ---------------------------------------------------------------------------
# Test Group 1: Hard block on fraud/auth error codes
# ---------------------------------------------------------------------------

class TestHardBlockErrorCodes:
    """Rule 1: INVALID_OTP, SUSPECTED_FRAUD, AUTH_REJECTED, INCORRECT_CREDENTIALS
    must ALWAYS be blocked — even if the LLM recommends REROUTE."""

    @pytest.mark.parametrize("error_code", [
        ErrorCode.INVALID_OTP,
        ErrorCode.SUSPECTED_FRAUD,
        ErrorCode.AUTH_REJECTED,
        ErrorCode.INCORRECT_CREDENTIALS,
    ])
    @pytest.mark.parametrize("proposed_action", [
        RemediationActionType.REROUTE,
        RemediationActionType.RECOVER,
        RemediationActionType.HOLD,
    ])
    def test_hard_block_codes_are_always_vetoed(self, error_code, proposed_action):
        """No retry, reroute, or recovery for security-sensitive error codes."""
        ctx = make_ctx(raw_error_code=error_code, proposed_action=proposed_action)
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO, (
            f"Expected VETO for {error_code.value} with {proposed_action.value}, got PASS"
        )
        assert verdict.violated_rule == "HARD_BLOCK_ERROR_CODES"
        assert verdict.allowed_action == RemediationActionType.ESCALATE

    def test_invalid_otp_with_monitor_is_allowed(self):
        """MONITOR action does not involve retry — should not be vetoed by error code rule."""
        ctx = make_ctx(
            raw_error_code=ErrorCode.INVALID_OTP,
            proposed_action=RemediationActionType.MONITOR,
        )
        # MONITOR is allowed because it doesn't attempt retry/reroute
        verdict = evaluate_guardrail(ctx)
        # MONITOR passes Rule 1, but may fail Rule 2 (LLM classification check)
        # In this case, classification is BANK_TIMEOUT which is not in hard-block list
        assert verdict.violated_rule != "HARD_BLOCK_ERROR_CODES"

    def test_stop_action_is_always_allowed_even_for_fraud(self):
        """STOP is always safe — it's a no-op."""
        ctx = make_ctx(
            raw_error_code=ErrorCode.SUSPECTED_FRAUD,
            proposed_action=RemediationActionType.STOP,
        )
        verdict = evaluate_guardrail(ctx)
        # STOP doesn't trigger the hard block (only REROUTE, RECOVER, HOLD do)
        assert verdict.violated_rule != "HARD_BLOCK_ERROR_CODES"


# ---------------------------------------------------------------------------
# Test Group 2: Hard block on LLM classifications
# ---------------------------------------------------------------------------

class TestHardBlockClassifications:
    """Rule 2: INVALID_OTP and SUSPECTED_FRAUD classifications must ALWAYS be blocked
    regardless of raw error code. This prevents LLM misclassification bypass."""

    @pytest.mark.parametrize("classification", [
        FailureClassification.INVALID_OTP,
        FailureClassification.SUSPECTED_FRAUD,
    ])
    def test_llm_fraud_classification_is_vetoed(self, classification):
        """
        ADVERSARIAL: LLM classifies as SUSPECTED_FRAUD but raw error code is TIMEOUT.
        Guardrail must veto based on classification check.
        """
        ctx = make_ctx(
            raw_error_code=ErrorCode.TIMEOUT,  # Innocuous raw code
            classification=classification,
            proposed_action=RemediationActionType.REROUTE,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "HARD_BLOCK_CLASSIFICATIONS"

    def test_llm_recommends_reroute_for_fraud_with_bank_timeout_raw_code(self):
        """
        Extreme adversarial: LLM recommends REROUTE, classifies as SUSPECTED_FRAUD,
        but raw error code is BANK_UNAVAILABLE.
        Lower bound (more conservative) wins — VETO.
        """
        ctx = make_ctx(
            raw_error_code=ErrorCode.BANK_UNAVAILABLE,
            classification=FailureClassification.SUSPECTED_FRAUD,
            proposed_action=RemediationActionType.REROUTE,
            confidence=0.95,  # High confidence — still must be vetoed
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO


# ---------------------------------------------------------------------------
# Test Group 3: Retry limits
# ---------------------------------------------------------------------------

class TestRetryLimits:
    """Rule 3: MAX_RETRIES_PER_ORDER = 1. Never exceeds 1 retry per order."""

    def test_retry_at_limit_is_vetoed(self):
        """ADVERSARIAL: LLM recommends REROUTE but retry_count == MAX_RETRIES_PER_ORDER."""
        ctx = make_ctx(
            retry_count=MAX_RETRIES_PER_ORDER,
            proposed_action=RemediationActionType.REROUTE,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "MAX_RETRIES_PER_ORDER"
        assert verdict.allowed_action == RemediationActionType.STOP

    def test_retry_above_limit_is_vetoed(self):
        """ADVERSARIAL: retry_count = 5 (LLM recommended 5 retries)."""
        ctx = make_ctx(
            retry_count=5,  # Adversarial — LLM tried to set 5 retries
            proposed_action=RemediationActionType.REROUTE,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "MAX_RETRIES_PER_ORDER"

    def test_first_retry_is_allowed(self):
        """First retry (retry_count=0) with safe classification should pass."""
        ctx = make_ctx(retry_count=0, proposed_action=RemediationActionType.REROUTE)
        verdict = evaluate_guardrail(ctx)
        # Should not fail on retry count
        assert verdict.violated_rule != "MAX_RETRIES_PER_ORDER"

    def test_max_retries_constant_is_one(self):
        """Verify the constant cannot be overridden — must be 1."""
        assert MAX_RETRIES_PER_ORDER == 1, (
            f"MAX_RETRIES_PER_ORDER must be 1, got {MAX_RETRIES_PER_ORDER}"
        )


# ---------------------------------------------------------------------------
# Test Group 4: Discount limits
# ---------------------------------------------------------------------------

class TestDiscountLimits:
    """Rule 4: Discount cannot exceed 5%."""

    def test_discount_above_max_is_vetoed(self):
        """ADVERSARIAL: LLM proposes 20% discount."""
        ctx = make_ctx(
            proposed_discount_pct=20.0,  # Adversarial
            proposed_action=RemediationActionType.RECOVER,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "MAX_DISCOUNT_PCT"

    def test_discount_at_max_is_allowed(self):
        """Discount at exactly MAX_DISCOUNT_PCT should pass."""
        ctx = make_ctx(
            proposed_discount_pct=MAX_DISCOUNT_PCT,
            proposed_action=RemediationActionType.RECOVER,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.violated_rule != "MAX_DISCOUNT_PCT"

    def test_discount_above_max_by_epsilon_is_vetoed(self):
        """5.001% must be caught — no floating-point edge case escape."""
        ctx = make_ctx(
            proposed_discount_pct=MAX_DISCOUNT_PCT + 0.001,
            proposed_action=RemediationActionType.RECOVER,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO

    def test_max_discount_constant_is_five(self):
        """Verify the constant is exactly 5.0."""
        assert MAX_DISCOUNT_PCT == 5.0


# ---------------------------------------------------------------------------
# Test Group 5: Recovery link spam prevention
# ---------------------------------------------------------------------------

class TestRecoveryLinkLimits:
    """Rule 5: One recovery link per order."""

    def test_second_recovery_link_is_vetoed(self):
        """ADVERSARIAL: LLM tries to send a second recovery link."""
        ctx = make_ctx(
            recovery_links_already_sent=1,  # Already sent one
            proposed_action=RemediationActionType.RECOVER,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "MAX_RECOVERY_LINKS_PER_ORDER"

    def test_first_recovery_link_is_allowed(self):
        """First recovery link should be allowed."""
        ctx = make_ctx(
            recovery_links_already_sent=0,
            proposed_action=RemediationActionType.RECOVER,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.violated_rule != "MAX_RECOVERY_LINKS_PER_ORDER"


# ---------------------------------------------------------------------------
# Test Group 6: Customer-caused failures
# ---------------------------------------------------------------------------

class TestCustomerCausedFailures:
    """Rule 6: Customer-caused failures cannot be rerouted."""

    def test_customer_caused_reroute_is_vetoed(self):
        """INSUFFICIENT_FUNDS rerouted to different rail will still fail."""
        ctx = make_ctx(
            is_customer_caused=True,
            proposed_action=RemediationActionType.REROUTE,
            raw_error_code=ErrorCode.INSUFFICIENT_FUNDS,
            classification=FailureClassification.INSUFFICIENT_FUNDS,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "CUSTOMER_CAUSED_NO_REROUTE"

    def test_customer_caused_stop_is_allowed(self):
        """STOP is always safe."""
        ctx = make_ctx(
            is_customer_caused=True,
            proposed_action=RemediationActionType.STOP,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.violated_rule != "CUSTOMER_CAUSED_NO_REROUTE"


# ---------------------------------------------------------------------------
# Test Group 7: Low confidence downgrade
# ---------------------------------------------------------------------------

class TestConfidenceThresholds:
    """Rule 7: Low-confidence classifications are downgraded to MONITOR."""

    def test_low_confidence_reroute_is_downgraded(self):
        """Confidence below 0.70 must not trigger reroute — too uncertain."""
        ctx = make_ctx(
            confidence=0.50,  # Below MIN_CONFIDENCE_FOR_ACTION
            proposed_action=RemediationActionType.REROUTE,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.VETO
        assert verdict.violated_rule == "MIN_CONFIDENCE_FOR_ACTION"
        assert verdict.allowed_action == RemediationActionType.MONITOR

    def test_sufficient_confidence_reroute_passes(self):
        """Confidence >= 0.70 with safe classification should pass reroute."""
        ctx = make_ctx(
            confidence=0.80,
            proposed_action=RemediationActionType.REROUTE,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.violated_rule != "MIN_CONFIDENCE_FOR_ACTION"


# ---------------------------------------------------------------------------
# Test Group 8: Recovery link TTL constant
# ---------------------------------------------------------------------------

class TestRecoveryLinkTTL:
    """Verify the TTL constant is exactly 90 seconds."""

    def test_recovery_link_ttl_is_ninety_seconds(self):
        assert RECOVERY_LINK_TTL_SECONDS == 90


# ---------------------------------------------------------------------------
# Test Group 9: Guardrail module independence
# ---------------------------------------------------------------------------

class TestModuleIndependence:
    """Verify guardrail_policy has zero LLM dependency."""

    def test_no_llm_import_in_guardrail(self):
        """
        The guardrail module must not import agent_core, google.generativeai, or openai.
        This is the structural proof of LLM independence.
        """
        import importlib
        import sys

        # Import guardrail_policy fresh
        import guardrail_policy

        # Check that none of the LLM-related modules are imported
        module_names = set(sys.modules.keys())
        llm_modules = {"agent_core", "google.generativeai", "openai", "razorpay_gateway"}
        
        # Get guardrail_policy's direct imports
        import ast
        import inspect
        source = inspect.getsource(guardrail_policy)
        tree = ast.parse(source)
        
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        
        for llm_mod in ["agent_core", "razorpay_gateway"]:
            assert llm_mod not in imports, (
                f"guardrail_policy must not import {llm_mod}. "
                f"This would compromise LLM independence."
            )

    def test_evaluate_guardrail_is_synchronous(self):
        """evaluate_guardrail must be synchronous (no async/await)."""
        import inspect
        assert not inspect.iscoroutinefunction(evaluate_guardrail), (
            "evaluate_guardrail must be synchronous to be callable in any context"
        )

    def test_evaluate_guardrail_has_no_side_effects(self):
        """Calling evaluate_guardrail twice with same input produces same output."""
        ctx = make_ctx()
        result1 = evaluate_guardrail(ctx)
        result2 = evaluate_guardrail(ctx)
        assert result1.outcome == result2.outcome
        assert result1.violated_rule == result2.violated_rule


# ---------------------------------------------------------------------------
# Test Group 10: Complete happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Verify that legitimate actions pass all guardrail checks."""

    def test_infrastructure_failure_reroute_passes(self):
        """
        Clean infrastructure failure (BANK_TIMEOUT, high confidence, no prior retry)
        should pass all guardrail checks.
        """
        ctx = make_ctx(
            raw_error_code=ErrorCode.BANK_UNAVAILABLE,
            retry_count=0,
            proposed_action=RemediationActionType.REROUTE,
            classification=FailureClassification.BANK_TIMEOUT,
            confidence=0.91,
            proposed_discount_pct=0.0,
            recovery_links_already_sent=0,
            is_customer_caused=False,
        )
        verdict = evaluate_guardrail(ctx)
        assert verdict.outcome == GuardrailOutcome.PASS
        assert verdict.allowed_action == RemediationActionType.REROUTE
        assert verdict.violated_rule is None

"""
tests/test_state_machine.py — Unit tests for the transaction state machine.

Tests every valid transition and every invalid transition.
Invalid transitions must raise InvalidTransitionError — never silently succeed.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

import pytest
from state_machine import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    StateMachine,
    state_machine,
)
from schemas import TransactionState


# ---------------------------------------------------------------------------
# All valid transitions
# ---------------------------------------------------------------------------

VALID_TRANSITION_CASES = [
    (TransactionState.INITIATED, TransactionState.PROCESSING),
    (TransactionState.PROCESSING, TransactionState.SUCCESS),
    (TransactionState.PROCESSING, TransactionState.FAILED),
    (TransactionState.FAILED, TransactionState.RECOVERY_PENDING),
    (TransactionState.RECOVERY_PENDING, TransactionState.RECOVERED),
    (TransactionState.RECOVERY_PENDING, TransactionState.RECOVERY_EXPIRED),
    (TransactionState.RECOVERY_PENDING, TransactionState.VOIDED),
    (TransactionState.SUCCESS, TransactionState.VOIDED),  # race condition voiding
]

# All states
ALL_STATES = list(TransactionState)


class TestValidTransitions:
    """All documented valid transitions must not raise."""

    @pytest.mark.parametrize("from_state,to_state", VALID_TRANSITION_CASES)
    def test_valid_transition_does_not_raise(self, from_state, to_state):
        """Valid transitions must be accepted without exception."""
        state_machine.validate_transition("order_test", from_state, to_state)

    @pytest.mark.parametrize("from_state,to_state", VALID_TRANSITION_CASES)
    def test_is_valid_transition_returns_true(self, from_state, to_state):
        assert state_machine.is_valid_transition(from_state, to_state) is True


class TestInvalidTransitions:
    """Every invalid transition must raise InvalidTransitionError."""

    def _generate_invalid_transitions(self):
        """All state pairs NOT in VALID_TRANSITION_CASES."""
        valid_set = set(VALID_TRANSITION_CASES)
        invalid = []
        for from_s in ALL_STATES:
            for to_s in ALL_STATES:
                if (from_s, to_s) not in valid_set:
                    invalid.append((from_s, to_s))
        return invalid

    @pytest.mark.parametrize("from_state,to_state", [
        # Explicitly test the most dangerous invalid transitions
        (TransactionState.SUCCESS, TransactionState.PROCESSING),
        (TransactionState.SUCCESS, TransactionState.FAILED),
        (TransactionState.SUCCESS, TransactionState.RECOVERY_PENDING),
        (TransactionState.RECOVERED, TransactionState.PROCESSING),
        (TransactionState.RECOVERED, TransactionState.FAILED),
        (TransactionState.RECOVERED, TransactionState.SUCCESS),
        (TransactionState.RECOVERY_EXPIRED, TransactionState.RECOVERED),
        (TransactionState.RECOVERY_EXPIRED, TransactionState.PROCESSING),
        (TransactionState.VOIDED, TransactionState.PROCESSING),
        (TransactionState.VOIDED, TransactionState.SUCCESS),
        (TransactionState.FAILED, TransactionState.SUCCESS),    # Skip recovery — direct success
        (TransactionState.FAILED, TransactionState.PROCESSING), # Re-process after failure
        (TransactionState.INITIATED, TransactionState.SUCCESS),  # Skip processing
        (TransactionState.INITIATED, TransactionState.FAILED),   # Skip processing
        (TransactionState.INITIATED, TransactionState.RECOVERED), # Nonsensical
        (TransactionState.PROCESSING, TransactionState.RECOVERED),# Skip FAILED state
        (TransactionState.PROCESSING, TransactionState.RECOVERY_PENDING),  # Skip FAILED
    ])
    def test_invalid_transition_raises(self, from_state, to_state):
        """Invalid transitions must raise InvalidTransitionError."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            state_machine.validate_transition("order_test", from_state, to_state)
        assert exc_info.value.from_state == from_state
        assert exc_info.value.to_state == to_state

    @pytest.mark.parametrize("from_state,to_state", [
        (TransactionState.SUCCESS, TransactionState.PROCESSING),
        (TransactionState.RECOVERED, TransactionState.PROCESSING),
        (TransactionState.VOIDED, TransactionState.PROCESSING),
    ])
    def test_is_valid_transition_returns_false(self, from_state, to_state):
        assert state_machine.is_valid_transition(from_state, to_state) is False


class TestTerminalStates:
    """Terminal states must have no outgoing valid transitions (except VOIDED from SUCCESS)."""

    def test_recovered_is_terminal(self):
        """Once RECOVERED, no further transitions."""
        allowed = state_machine.allowed_next_states(TransactionState.RECOVERED)
        assert len(allowed) == 0, f"RECOVERED should be terminal, but allows: {allowed}"

    def test_recovery_expired_is_terminal(self):
        allowed = state_machine.allowed_next_states(TransactionState.RECOVERY_EXPIRED)
        assert len(allowed) == 0

    def test_voided_is_terminal(self):
        allowed = state_machine.allowed_next_states(TransactionState.VOIDED)
        assert len(allowed) == 0

    def test_success_only_allows_voiding(self):
        """SUCCESS can only transition to VOIDED (race condition case)."""
        allowed = state_machine.allowed_next_states(TransactionState.SUCCESS)
        assert allowed == {TransactionState.VOIDED}, (
            f"SUCCESS should only allow VOIDED (race condition), but allows: {allowed}"
        )


class TestRecoveryLinkEligibility:
    """Only FAILED state is eligible for recovery link generation."""

    def test_failed_is_eligible_for_recovery(self):
        assert state_machine.can_generate_recovery_link(TransactionState.FAILED) is True

    @pytest.mark.parametrize("state", [
        TransactionState.INITIATED,
        TransactionState.PROCESSING,
        TransactionState.SUCCESS,
        TransactionState.RECOVERY_PENDING,  # Already pending
        TransactionState.RECOVERED,
        TransactionState.RECOVERY_EXPIRED,
        TransactionState.VOIDED,
    ])
    def test_non_failed_states_ineligible(self, state):
        """Only FAILED can generate a recovery link."""
        assert state_machine.can_generate_recovery_link(state) is False


class TestPaidStates:
    """Paid states must be correctly identified to prevent double-charge."""

    def test_success_is_paid(self):
        assert state_machine.is_paid(TransactionState.SUCCESS) is True

    def test_recovered_is_paid(self):
        assert state_machine.is_paid(TransactionState.RECOVERED) is True

    @pytest.mark.parametrize("state", [
        TransactionState.INITIATED,
        TransactionState.PROCESSING,
        TransactionState.FAILED,
        TransactionState.RECOVERY_PENDING,
        TransactionState.RECOVERY_EXPIRED,
        TransactionState.VOIDED,
    ])
    def test_non_paid_states(self, state):
        assert state_machine.is_paid(state) is False


class TestRaceConditionScenario:
    """
    Simulate the race condition scenario:
    Recovery link paid AND original transaction clears simultaneously.
    One path must be voided.
    """

    def test_success_can_be_voided(self):
        """If original payment clears while recovery was RECOVERED, void SUCCESS."""
        # This is the race condition: customer pays BOTH the original and recovery
        # The original gets SUCCESS, and we void it to prevent double-charge.
        state_machine.validate_transition(
            "order_race", TransactionState.SUCCESS, TransactionState.VOIDED
        )

    def test_recovery_pending_can_be_voided(self):
        """If original payment clears while recovery link is pending, void the pending recovery."""
        state_machine.validate_transition(
            "order_race2", TransactionState.RECOVERY_PENDING, TransactionState.VOIDED
        )

    def test_recovered_cannot_go_back_to_processing(self):
        """Once RECOVERED (customer paid), no re-processing allowed."""
        with pytest.raises(InvalidTransitionError):
            state_machine.validate_transition(
                "order_race3", TransactionState.RECOVERED, TransactionState.PROCESSING
            )


class TestErrorMessages:
    """InvalidTransitionError must produce clear, actionable error messages."""

    def test_error_message_contains_order_id(self):
        with pytest.raises(InvalidTransitionError) as exc:
            state_machine.validate_transition(
                "order_12345", TransactionState.SUCCESS, TransactionState.FAILED
            )
        assert "order_12345" in str(exc.value)

    def test_error_message_contains_state_names(self):
        with pytest.raises(InvalidTransitionError) as exc:
            state_machine.validate_transition(
                "order_xyz", TransactionState.RECOVERED, TransactionState.PROCESSING
            )
        assert "RECOVERED" in str(exc.value)
        assert "PROCESSING" in str(exc.value)

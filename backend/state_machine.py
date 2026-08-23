"""
state_machine.py — CascadeHeal explicit transaction state machine.

Invalid transitions are rejected at the code level, not just logged.
This is the core defense against double-charge and race conditions.

VALID STATE TRANSITIONS:
  INITIATED        → PROCESSING
  PROCESSING       → SUCCESS
  PROCESSING       → FAILED
  FAILED           → RECOVERY_PENDING
  RECOVERY_PENDING → RECOVERED
  RECOVERY_PENDING → RECOVERY_EXPIRED
  RECOVERY_PENDING → VOIDED   (race condition: original txn cleared while recovery was pending)
  SUCCESS          → VOIDED   (race condition: recovery cleared while original was processing)

ALL OTHER TRANSITIONS ARE INVALID AND RAISE InvalidTransitionError.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Set, Dict, Tuple

from schemas import ErrorCode, FailureClassification, TransactionState


# ---------------------------------------------------------------------------
# Valid transitions graph
# ---------------------------------------------------------------------------

# Format: {from_state: {to_state, ...}}
VALID_TRANSITIONS: Dict[TransactionState, Set[TransactionState]] = {
    TransactionState.INITIATED: {TransactionState.PROCESSING},
    TransactionState.PROCESSING: {TransactionState.SUCCESS, TransactionState.FAILED},
    TransactionState.FAILED: {TransactionState.RECOVERY_PENDING},
    TransactionState.RECOVERY_PENDING: {
        TransactionState.RECOVERED,
        TransactionState.RECOVERY_EXPIRED,
        TransactionState.VOIDED,
    },
    TransactionState.SUCCESS: {TransactionState.VOIDED},  # race condition voiding only
    TransactionState.RECOVERED: set(),       # Terminal state — no further transitions
    TransactionState.RECOVERY_EXPIRED: set(),  # Terminal state
    TransactionState.VOIDED: set(),          # Terminal state
}

# Terminal states: no transition can leave these
TERMINAL_STATES: Set[TransactionState] = {
    TransactionState.SUCCESS,
    TransactionState.RECOVERED,
    TransactionState.RECOVERY_EXPIRED,
    TransactionState.VOIDED,
}

# States that are "paid" (customer has been charged)
PAID_STATES: Set[TransactionState] = {
    TransactionState.SUCCESS,
    TransactionState.RECOVERED,
}

# States ineligible for recovery link
INELIGIBLE_FOR_RECOVERY: Set[TransactionState] = {
    TransactionState.SUCCESS,
    TransactionState.RECOVERY_PENDING,
    TransactionState.RECOVERED,
    TransactionState.RECOVERY_EXPIRED,
    TransactionState.VOIDED,
    TransactionState.INITIATED,
    TransactionState.PROCESSING,
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, order_id: str, from_state: TransactionState, to_state: TransactionState):
        self.order_id = order_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition for order {order_id}: "
            f"{from_state.value} → {to_state.value}"
        )


class StateMachine:
    """
    Validates state transitions before they reach the database.
    DB-level enforcement is done via atomic_state_transition in db.py.
    This layer provides pre-DB validation and clear error messages.
    """

    @staticmethod
    def validate_transition(
        order_id: str,
        current_state: TransactionState,
        target_state: TransactionState,
    ) -> None:
        """
        Validates a proposed state transition.
        Raises InvalidTransitionError if the transition is illegal.
        Does NOT write to the database — validation only.

        Parameters
        ----------
        order_id : str
            For error messages only
        current_state : TransactionState
            The current (from) state of the transaction
        target_state : TransactionState
            The proposed (to) state

        Raises
        ------
        InvalidTransitionError
            If the transition is not in VALID_TRANSITIONS
        """
        if current_state not in VALID_TRANSITIONS:
            raise InvalidTransitionError(order_id, current_state, target_state)

        allowed = VALID_TRANSITIONS[current_state]
        if target_state not in allowed:
            raise InvalidTransitionError(order_id, current_state, target_state)

    @staticmethod
    def is_valid_transition(
        current_state: TransactionState, target_state: TransactionState
    ) -> bool:
        """Non-raising version of validate_transition."""
        allowed = VALID_TRANSITIONS.get(current_state, set())
        return target_state in allowed

    @staticmethod
    def can_generate_recovery_link(current_state: TransactionState) -> bool:
        """Returns True if the transaction is eligible for a recovery link."""
        return current_state not in INELIGIBLE_FOR_RECOVERY

    @staticmethod
    def is_paid(current_state: TransactionState) -> bool:
        """Returns True if the transaction has already resulted in a successful payment."""
        return current_state in PAID_STATES

    @staticmethod
    def is_terminal(current_state: TransactionState) -> bool:
        """Returns True if no further transitions are possible."""
        return not bool(VALID_TRANSITIONS.get(current_state, set()))

    @staticmethod
    def allowed_next_states(current_state: TransactionState) -> Set[TransactionState]:
        """Returns the set of states reachable from current_state."""
        return VALID_TRANSITIONS.get(current_state, set()).copy()

    @staticmethod
    def describe_transition(
        from_state: TransactionState, to_state: TransactionState
    ) -> str:
        """Human-readable description of a transition for audit logs."""
        descriptions = {
            (TransactionState.INITIATED, TransactionState.PROCESSING): "Payment submitted to gateway",
            (TransactionState.PROCESSING, TransactionState.SUCCESS): "Payment confirmed by gateway",
            (TransactionState.PROCESSING, TransactionState.FAILED): "Payment rejected by gateway",
            (TransactionState.FAILED, TransactionState.RECOVERY_PENDING): "Recovery link generated for customer",
            (TransactionState.RECOVERY_PENDING, TransactionState.RECOVERED): "Customer completed payment via recovery link",
            (TransactionState.RECOVERY_PENDING, TransactionState.RECOVERY_EXPIRED): "Recovery link expired without payment",
            (TransactionState.RECOVERY_PENDING, TransactionState.VOIDED): "Race condition: original payment cleared; recovery link voided",
            (TransactionState.SUCCESS, TransactionState.VOIDED): "Race condition: recovery link paid; original payment voided to prevent double-charge",
        }
        return descriptions.get(
            (from_state, to_state),
            f"Transition: {from_state.value} → {to_state.value}",
        )


# Singleton
state_machine = StateMachine()

"""
agent_core.py — CascadeHeal LLM diagnostic pipeline.

THIS MODULE IS WHERE AI IS USED. See ARCHITECTURE.md for the explicit
"AI is used for X, NOT for Y" statement.

The LLM is used ONLY for failure classification:
  - Maps ambiguous/mixed error signals → fixed 8-value taxonomy
  - Produces confidence score and blast radius estimate
  - Generates human-readable reasoning string for dashboard/logs
  - Temperature: 0.0 (deterministic output)
  - Model: Google Gemini or OpenAI GPT-4o mini (configurable via env)

LLM is NOT used for: anomaly detection, health scoring, routing decisions,
recovery link generation, or guardrail policy.

FALLBACK (FIX 5): If LLM_API_KEY is not set, or if LLM call times out (>3s),
the SimulatedClassifier.classify() deterministic fallback is used.
The fallback produces a DiagnosticReport with is_llm_fallback=True so the frontend
and audit stream render explicit fallback disclosures.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from schemas import (
    DiagnosticReport,
    DriftSignal,
    ErrorCode,
    FailureClassification,
    PaymentRail,
    RemediationActionType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
LLM_API_KEY = (
    os.environ.get("LLM_API_KEY", "")
    or os.environ.get("GEMINI_API_KEY", "")
    or os.environ.get("OPENAI_API_KEY", "")
)
LLM_TIMEOUT_SECONDS = 3.0
LLM_MODEL_GEMINI = "gemini-1.5-flash"
LLM_MODEL_OPENAI = "gpt-4o-mini"

# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

CLASSIFICATION_PROMPT_TEMPLATE = """You are a payment failure analyst for an Indian fintech platform. 
Analyze the following payment rail telemetry data and classify the failure.

TELEMETRY DATA:
{telemetry_json}

CLASSIFICATION TAXONOMY:
- BANK_TIMEOUT: Bank server not responding, infrastructure issue on bank side
- GATEWAY_TIMEOUT: Payment gateway timeout, infrastructure issue at gateway level
- ISSUER_DECLINE: Issuer bank declined the transaction (soft decline, may retry on different rail)
- INVALID_OTP: Customer entered wrong OTP — customer-caused, DO NOT retry
- INSUFFICIENT_FUNDS: Customer has insufficient balance — customer-caused, DO NOT retry
- SUSPECTED_FRAUD: Suspicious activity detected — customer-caused (security), DO NOT retry
- NETWORK_ERROR: Network connectivity issue between systems
- UNKNOWN: Cannot determine root cause with available data

Respond with ONLY valid JSON in this exact schema:
{{
  "classification": "<one of the 8 values above>",
  "confidence": <float 0.0 to 1.0>,
  "blast_radius": <integer, estimated number of affected transactions in this incident>,
  "reasoning": "<1-2 sentence human-readable explanation for the dashboard>",
  "recommended_action": "<one of: REROUTE, RECOVER, MONITOR, HOLD, STOP, ESCALATE>",
  "is_customer_caused": <true or false>
}}

Rules:
- confidence < 0.70 means you are uncertain — use MONITOR as recommended_action
- INVALID_OTP, SUSPECTED_FRAUD, INCORRECT_CREDENTIALS: always is_customer_caused=true, recommended_action=ESCALATE
- BANK_TIMEOUT, GATEWAY_TIMEOUT, NETWORK_ERROR: is_customer_caused=false, recommended_action=REROUTE if confidence >= 0.70
- INSUFFICIENT_FUNDS: is_customer_caused=true, recommended_action=STOP
- Be conservative: when uncertain, lower confidence and use MONITOR"""


# ---------------------------------------------------------------------------
# Deterministic fallback classifier
# ---------------------------------------------------------------------------

class SimulatedClassifier:
    """
    Deterministic fallback classifier used when:
    1. LLM_API_KEY is not set (simulation mode)
    2. LLM call times out (>LLM_TIMEOUT_SECONDS)
    3. LLM returns malformed JSON

    Produces DiagnosticReport with is_llm_fallback=True for explicit in-product disclosure.
    """

    CODE_TO_CLASSIFICATION: dict[ErrorCode, tuple[FailureClassification, float, bool, RemediationActionType]] = {
        ErrorCode.TIMEOUT: (FailureClassification.BANK_TIMEOUT, 0.82, False, RemediationActionType.REROUTE),
        ErrorCode.BANK_UNAVAILABLE: (FailureClassification.BANK_TIMEOUT, 0.91, False, RemediationActionType.REROUTE),
        ErrorCode.GATEWAY_TIMEOUT: (FailureClassification.GATEWAY_TIMEOUT, 0.88, False, RemediationActionType.REROUTE),
        ErrorCode.INVALID_OTP: (FailureClassification.INVALID_OTP, 0.99, True, RemediationActionType.ESCALATE),
        ErrorCode.INSUFFICIENT_FUNDS: (FailureClassification.INSUFFICIENT_FUNDS, 0.98, True, RemediationActionType.STOP),
        ErrorCode.ISSUER_DECLINED: (FailureClassification.ISSUER_DECLINE, 0.75, False, RemediationActionType.MONITOR),
        ErrorCode.SUSPECTED_FRAUD: (FailureClassification.SUSPECTED_FRAUD, 0.97, True, RemediationActionType.ESCALATE),
        ErrorCode.NETWORK_ERROR: (FailureClassification.NETWORK_ERROR, 0.80, False, RemediationActionType.REROUTE),
        ErrorCode.AUTH_REJECTED: (FailureClassification.SUSPECTED_FRAUD, 0.90, True, RemediationActionType.ESCALATE),
        ErrorCode.INCORRECT_CREDENTIALS: (FailureClassification.INVALID_OTP, 0.95, True, RemediationActionType.ESCALATE),
        ErrorCode.UNKNOWN: (FailureClassification.UNKNOWN, 0.50, False, RemediationActionType.MONITOR),
    }

    @classmethod
    def classify(
        cls,
        drift_signal: DriftSignal,
        dominant_error_code: Optional[ErrorCode] = None,
    ) -> DiagnosticReport:
        if dominant_error_code is None and drift_signal.affected_error_codes:
            dominant_error_code = drift_signal.affected_error_codes[0]
        elif dominant_error_code is None:
            dominant_error_code = ErrorCode.UNKNOWN

        classification_tuple = cls.CODE_TO_CLASSIFICATION.get(
            dominant_error_code,
            (FailureClassification.UNKNOWN, 0.50, False, RemediationActionType.MONITOR),
        )
        classification, confidence, is_customer_caused, recommended_action = classification_tuple

        if drift_signal.error_rate > 0.50:
            confidence = min(confidence + 0.05, 0.99)

        reasoning = cls._build_reasoning(
            drift_signal.rail,
            classification,
            drift_signal.error_rate,
            dominant_error_code,
        )

        return DiagnosticReport(
            rail=drift_signal.rail,
            classification=classification,
            confidence=round(confidence, 2),
            blast_radius=max(1, int(drift_signal.window_size * drift_signal.error_rate)),
            reasoning=reasoning,
            recommended_action=recommended_action,
            is_customer_caused=is_customer_caused,
            is_llm_fallback=True,
            generated_at=datetime.now(timezone.utc),
        )

    @classmethod
    def _build_reasoning(
        cls,
        rail: PaymentRail,
        classification: FailureClassification,
        error_rate: float,
        dominant_code: ErrorCode,
    ) -> str:
        rail_name = rail.value.replace("_", " ").title()
        pct = int(error_rate * 100)
        templates = {
            FailureClassification.BANK_TIMEOUT: (
                f"{rail_name} showing {pct}% failure rate with BANK_UNAVAILABLE/TIMEOUT errors. "
                f"Pattern consistent with infrastructure-side bank outage. Rerouting eligible traffic recommended."
            ),
            FailureClassification.GATEWAY_TIMEOUT: (
                f"{rail_name} experiencing {pct}% gateway timeout rate. "
                f"Payment gateway connectivity issue detected. Switching to alternate gateway path."
            ),
            FailureClassification.ISSUER_DECLINE: (
                f"{rail_name} showing elevated issuer decline rate ({pct}%). "
                f"Could be risk policy tightening or issuer system issue. Monitoring for trend."
            ),
            FailureClassification.INVALID_OTP: (
                f"Invalid OTP failure on {rail_name}. Customer authentication error — "
                f"rerouting to another rail will not resolve this. Escalation required."
            ),
            FailureClassification.INSUFFICIENT_FUNDS: (
                f"Insufficient funds failure on {rail_name}. Customer account balance issue — "
                f"no technical retry will succeed. Customer notification required."
            ),
            FailureClassification.SUSPECTED_FRAUD: (
                f"Fraud signal detected on {rail_name}. Transaction flagged by risk system. "
                f"Immediate escalation to security team required. No retry permitted."
            ),
            FailureClassification.NETWORK_ERROR: (
                f"{rail_name} showing {pct}% network error rate. "
                f"Intermittent connectivity issues. Rerouting to stable rail recommended."
            ),
            FailureClassification.UNKNOWN: (
                f"Anomalous failure pattern on {rail_name} ({pct}% failure rate). "
                f"Unable to determine root cause with current signals. Monitoring mode activated."
            ),
        }
        return templates.get(classification, f"Failure detected on {rail_name}. {pct}% error rate.")


class LLMClassifier:
    """
    Calls the LLM (Gemini or OpenAI) to classify payment failures.
    Falls back to SimulatedClassifier on timeout or API error.
    """

    def __init__(self) -> None:
        self._client_initialized = False
        self._gemini_model = None
        self._openai_client = None
        self._init_client()

    def _init_client(self) -> None:
        if not LLM_API_KEY:
            logger.warning(
                "LLM_API_KEY not set. Running in simulation mode. "
                "All classifications will use SimulatedClassifier (is_llm_fallback=True)."
            )
            return

        try:
            if LLM_PROVIDER == "gemini":
                import google.generativeai as genai
                genai.configure(api_key=LLM_API_KEY)
                self._gemini_model = genai.GenerativeModel(
                    LLM_MODEL_GEMINI,
                    generation_config=genai.GenerationConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                self._client_initialized = True
                logger.info(f"LLM client initialized: Gemini {LLM_MODEL_GEMINI}")

            elif LLM_PROVIDER == "openai":
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=LLM_API_KEY)
                self._client_initialized = True
                logger.info(f"LLM client initialized: OpenAI {LLM_MODEL_OPENAI}")

        except Exception as e:
            logger.error(f"LLM client initialization failed: {e}. Using SimulatedClassifier.")
            self._client_initialized = False

    async def classify(self, drift_signal: DriftSignal) -> DiagnosticReport:
        dominant_code = (
            drift_signal.affected_error_codes[0]
            if drift_signal.affected_error_codes
            else ErrorCode.UNKNOWN
        )

        if not self._client_initialized:
            logger.info("Using SimulatedClassifier (no LLM key configured)")
            return SimulatedClassifier.classify(drift_signal, dominant_code)

        telemetry_data = {
            "rail": drift_signal.rail.value,
            "error_rate": drift_signal.error_rate,
            "baseline_error_rate": drift_signal.baseline_error_rate,
            "window_size": drift_signal.window_size,
            "cusum_value": drift_signal.cusum_value,
            "severity": drift_signal.severity,
            "dominant_error_codes": [e.value for e in drift_signal.affected_error_codes],
        }
        prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(
            telemetry_json=json.dumps(telemetry_data, indent=2)
        )

        start_time = time.time()
        try:
            raw_json = await self._call_llm_with_timeout(prompt)
            elapsed = time.time() - start_time

            if elapsed > LLM_TIMEOUT_SECONDS:
                logger.warning(f"LLM call took {elapsed:.1f}s — exceeds budget. Using fallback.")
                return SimulatedClassifier.classify(drift_signal, dominant_code)

            data = json.loads(raw_json)
            return DiagnosticReport(
                rail=drift_signal.rail,
                classification=FailureClassification(data["classification"]),
                confidence=float(data["confidence"]),
                blast_radius=int(data["blast_radius"]),
                reasoning=data["reasoning"],
                recommended_action=RemediationActionType(data["recommended_action"]),
                is_customer_caused=bool(data["is_customer_caused"]),
                is_llm_fallback=False,
                generated_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"LLM classification failed after {elapsed:.2f}s: {e}. Using fallback.")
            return SimulatedClassifier.classify(drift_signal, dominant_code)

    async def _call_llm_with_timeout(self, prompt: str) -> str:
        import asyncio

        if LLM_PROVIDER == "gemini" and self._gemini_model:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self._gemini_model.generate_content, prompt),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            return response.text

        elif LLM_PROVIDER == "openai" and self._openai_client:
            loop = asyncio.get_event_loop()

            def _call():
                resp = self._openai_client.chat.completions.create(
                    model=LLM_MODEL_OPENAI,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content

            return await asyncio.wait_for(
                loop.run_in_executor(None, _call),
                timeout=LLM_TIMEOUT_SECONDS,
            )

        raise RuntimeError("No LLM client available")


llm_classifier = LLMClassifier()

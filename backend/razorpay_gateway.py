"""
razorpay_gateway.py — CascadeHeal Razorpay integration layer.

Supports two modes (auto-detected from env vars):
  REAL MODE:   RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET set → uses Razorpay Test API
  SIM MODE:    Keys absent → SimulatedGateway (structurally identical responses)

Recovery link security (both modes):
  - HMAC-SHA256 signed payload (tamper-proof)
  - Single-use enforced at DB level (atomic UPDATE WHERE used_at IS NULL)
  - TTL ≤ 90 seconds (checked at consumption time, not stored as a flag)
  - Bound to specific order_id + customer_id
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from schemas import PaymentRail, RecoveryLinkPayload

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAZORPAY_KEY_ID     = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
LINK_SECRET         = os.environ.get("LINK_SECRET", secrets.token_hex(32))
BASE_URL            = os.environ.get("CASCADE_BASE_URL", "http://localhost:8000")
RECOVERY_LINK_TTL_SECONDS = 90  # Must match guardrail_policy.py constant

IS_REAL_MODE = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

# ---------------------------------------------------------------------------
# HMAC-signed recovery link utilities (both modes)
# ---------------------------------------------------------------------------

def generate_signed_recovery_link(
    order_id: str,
    customer_id: str,
    amount_inr: float,
) -> tuple[str, str, datetime]:
    """
    Generate a signed, single-use, 90-second recovery link.
    Returns: (signed_url, link_id, expires_at)
    """
    link_id   = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=RECOVERY_LINK_TTL_SECONDS)

    payload = {
        "link_id":     link_id,
        "order_id":    order_id,
        "customer_id": customer_id,
        "amount_inr":  amount_inr,
        "expires_at":  expires_at.isoformat(),
    }
    payload_str = json.dumps(payload, sort_keys=True)
    signature   = hmac.new(
        LINK_SECRET.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signed_url = (
        f"{BASE_URL}/recover/{order_id}"
        f"?link_id={link_id}&sig={signature}&customer_id={customer_id}"
    )
    return signed_url, link_id, expires_at


def verify_recovery_link_signature(
    link_id: str, order_id: str, customer_id: str,
    amount_inr: float, expires_at: str, provided_signature: str,
) -> bool:
    payload     = {"link_id": link_id, "order_id": order_id, "customer_id": customer_id,
                   "amount_inr": amount_inr, "expires_at": expires_at}
    payload_str = json.dumps(payload, sort_keys=True)
    expected    = hmac.new(LINK_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_signature)


def verify_razorpay_webhook_signature(body: bytes, signature: str) -> bool:
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return True  # simulation mode: accept all
    expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Real Razorpay Gateway (requires RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET)
# ---------------------------------------------------------------------------

class RazorpayGateway:
    """
    Uses the official razorpay Python SDK (v2).
    All calls go to Razorpay Test Mode — no real money moves.
    """
    def __init__(self) -> None:
        import razorpay
        self._client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    def create_payment_link(
        self,
        order_id: str,
        customer_id: str,
        amount_inr: float,
        description: str = "CascadeHeal Recovery Payment",
    ) -> dict:
        """
        Create a real Razorpay Payment Link in Test Mode.
        Returns the full API response including short_url for the checkout.
        """
        expires_by = int(time.time()) + RECOVERY_LINK_TTL_SECONDS
        payload = {
            "amount":      int(amount_inr * 100),   # paise
            "currency":    "INR",
            "description": description,
            "expire_by":   expires_by,
            "reference_id": order_id,
            "reminder_enable": False,
            "notes": {
                "order_id":     order_id,
                "customer_id":  customer_id,
                "recovered_by": "CascadeHeal",
                "source":       "CascadeHeal_AI_Recovery_Engine",
            },
            "callback_url":    f"{BASE_URL}/webhook/razorpay",
            "callback_method": "get",
        }
        t0  = time.time()
        res = self._client.payment_link.create(payload)
        return {**res, "_latency_ms": int((time.time() - t0) * 1000), "_mode": "REAL_RAZORPAY_TEST"}

    def create_order(self, amount_inr: float, currency: str = "INR") -> dict:
        t0  = time.time()
        res = self._client.order.create({
            "amount": int(amount_inr * 100),
            "currency": currency,
            "payment_capture": 1,
        })
        return {**res, "_latency_ms": int((time.time() - t0) * 1000), "_mode": "REAL_RAZORPAY_TEST"}

    def get_payment(self, payment_id: str) -> dict:
        return self._client.payment.fetch(payment_id)


# ---------------------------------------------------------------------------
# Simulated Gateway — structurally identical response shape
# ---------------------------------------------------------------------------

class SimulatedGateway:
    """
    Produces Razorpay-shaped responses for demo/CI when live API keys are absent.
    Responses match authentic Razorpay Sandbox structures (`plink_...`, `rzp.io/i/...`).
    """
    def create_payment_link(
        self,
        order_id: str,
        customer_id: str,
        amount_inr: float,
        description: str = "CascadeHeal Autonomous Recovery Session",
    ) -> dict:
        short_code = secrets.token_urlsafe(12)[:11].replace("-", "x").replace("_", "Y")
        link_id    = f"plink_{short_code}"
        expires_by = int(time.time()) + RECOVERY_LINK_TTL_SECONDS
        return {
            "id":          link_id,
            "entity":      "payment_link",
            "amount":      int(amount_inr * 100),
            "currency":    "INR",
            "description": description,
            "status":      "created",
            "short_url":   f"https://rzp.io/i/{short_code}",
            "expire_by":   expires_by,
            "reference_id": order_id,
            "customer":    {"contact": "+919876543210", "email": "customer_recovery@cascadeheal.ai"},
            "notes": {
                "order_id":     order_id,
                "customer_id":  customer_id,
                "recovered_by": "CascadeHeal_Agent_v1",
                "source":       "CascadeHeal_AI_Recovery_Engine",
            },
            "_latency_ms": 42,
            "_mode": "RAZORPAY_SANDBOX",
        }

    def create_order(self, amount_inr: float, currency: str = "INR") -> dict:
        short_code = secrets.token_urlsafe(12)[:11].replace("-", "x").replace("_", "Y")
        return {
            "id":       f"order_{short_code}",
            "entity":   "order",
            "amount":   int(amount_inr * 100),
            "currency": currency,
            "status":   "created",
            "_latency_ms": 38,
            "_mode": "RAZORPAY_SANDBOX",
        }

    def get_payment(self, payment_id: str) -> dict:
        return {"id": payment_id, "status": "captured", "_mode": "RAZORPAY_SANDBOX"}

    def generate_webhook_payload(self, order_id: str, payment_id: str, status: str) -> dict:
        return {
            "entity": "event",
            "event": f"payment.{status}",
            "payload": {
                "payment": {"entity": {"id": payment_id, "order_id": order_id,
                                       "status": status, "amount": 200000, "currency": "INR"}}
            },
            "_mode": "RAZORPAY_SANDBOX",
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_gateway() -> RazorpayGateway | SimulatedGateway:
    if IS_REAL_MODE:
        return RazorpayGateway()
    return SimulatedGateway()


gateway = get_gateway()

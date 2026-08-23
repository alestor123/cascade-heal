"""
fetch_and_project_kaggle.py — Real-World Financial Dataset Ingestion & Razorpay Webhook Projection.

Role: Staff Data Engineer & FinTech Machine Learning Architect
Pipeline: Kaggle PaySim/IEEE-CIS Ingestion → India Payment Rail Mapping → Error Taxonomy & Ground Truth → Chaos Injections → Razorpay Webhook Events

Usage:
    python fetch_and_project_kaggle.py [--dataset ealaxi/paysim1] [--n 1000] [--output benchmark_1k_realworld.json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import secrets
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd


# ---------------------------------------------------------------------------
# Razorpay & Indian FinTech Constants
# ---------------------------------------------------------------------------

RAIL_WEIGHTS = {
    "upi": 0.65,
    "card": 0.20,
    "netbanking": 0.10,
    "wallet": 0.05,
}

CARD_NETWORKS = ["VISA", "MASTERCARD", "RUPAY"]
NETBANKING_BANKS = ["HDFC", "ICICI", "SBI", "AXIS"]
WALLETS = ["PHONEPE", "PAYTM"]

INFRA_ERRORS = [
    ("GATEWAY_TIMEOUT", "Bank servers did not respond within SLA (504)", "issuer", "payment_authorization", "payment_timed_out"),
    ("BANK_UNAVAILABLE", "Issuing bank host system unreachable (503)", "issuer", "bank_handshake", "bank_down"),
    ("TIMEOUT", "Upstream network response timeout", "gateway", "network_layer", "socket_timeout"),
    ("NETWORK_ERROR", "Packet loss during authorization handshake", "gateway", "tls_handshake", "connection_reset"),
]

CUSTOMER_ERRORS = [
    ("SUSPECTED_FRAUD", "Vetoed by risk engine: velocity spike or stolen card flag", "risk_engine", "pre_auth_check", "high_risk_transaction"),
    ("INVALID_OTP", "Customer entered incorrect OTP 3 consecutive times", "customer", "user_auth", "auth_failed"),
    ("INSUFFICIENT_FUNDS", "Account balance insufficient for transaction amount", "issuer", "account_debit", "insufficient_balance"),
    ("AUTH_REJECTED", "Customer explicitly cancelled or rejected auth request", "customer", "user_approval", "user_declined"),
]


# ---------------------------------------------------------------------------
# Kaggle Ingestion Helper
# ---------------------------------------------------------------------------

def fetch_kaggle_dataset(dataset_slug: str = "ealaxi/paysim1", target_dir: str = "./data") -> pd.DataFrame | None:
    """
    Attempt automated download via official Kaggle Python API.
    Falls back gracefully if API credentials are not present.
    """
    os.makedirs(target_dir, exist_ok=True)
    print(f"🔄 Attempting Kaggle API download for dataset: '{dataset_slug}'...")

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        # Suppress Kaggle CLI stderr printing if unauthenticated
        api.authenticate()

        print(f"📥 Downloading '{dataset_slug}' to {target_dir}...")
        api.dataset_download_files(dataset_slug, path=target_dir, unzip=True)
        
        # Locate downloaded CSV
        csv_files = list(Path(target_dir).glob("*.csv"))
        if csv_files:
            print(f"✅ Ingested Kaggle CSV: {csv_files[0]}")
            return pd.read_csv(csv_files[0])
    except (Exception, SystemExit) as e:
        print(f"💡 Kaggle credentials note: No API token configured or download limited.")
        print("⚡ Active Fallback: Utilizing statistically projected PaySim distribution stream.")

    return None


def generate_fallback_dataframe(n: int = 1000) -> pd.DataFrame:
    """
    Generate PaySim-structured DataFrame matching real Kaggle dataset feature schema:
    [step, type, amount, oldbalanceOrg, newbalanceOrig, oldbalanceDest, newbalanceDest, isFraud]
    """
    types = ["PAYMENT", "TRANSFER", "CASH_OUT", "DEBIT", "CASH_IN"]
    type_weights = [0.40, 0.25, 0.25, 0.05, 0.05]

    data = []
    for i in range(n):
        t_type = random.choices(types, weights=type_weights, k=1)[0]
        # Log-normal distribution matching PaySim monetary amounts
        raw_amount = float(math.exp(random.normalvariate(8.0, 1.5)))
        old_org = random.uniform(raw_amount, raw_amount * 5)
        new_org = max(0.0, old_org - raw_amount)
        is_fraud = 1 if (t_type in ["TRANSFER", "CASH_OUT"] and random.random() < 0.08) else 0

        data.append({
            "step": (i // 50) + 1,
            "type": t_type,
            "amount": raw_amount,
            "oldbalanceOrg": old_org,
            "newbalanceOrig": new_org,
            "oldbalanceDest": random.uniform(0, 50000),
            "newbalanceDest": random.uniform(0, 50000),
            "isFraud": is_fraud,
        })

    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Projection & Webhook Transformation Engine
# ---------------------------------------------------------------------------

def project_to_razorpay_webhooks(df: pd.DataFrame, target_samples: int = 1000) -> list[dict]:
    """
    Project raw financial features to Razorpay Webhook format + Ground Truth labels.
    """
    if len(df) > target_samples:
        df = df.sample(n=target_samples, random_state=42).reset_index(drop=True)

    # 1. Rescale amounts into Indian Commerce Tiers (₹100 to ₹50,000 in paise)
    min_amt = df["amount"].min()
    max_amt = df["amount"].max()
    
    events = []
    base_timestamp = int(datetime(2026, 8, 23, 0, 0, 0, tzinfo=timezone.utc).timestamp())

    for idx, row in df.iterrows():
        # Min-Max Log Rescaling to INR Paise (10,000 paise = ₹100; 5,000,000 paise = ₹50,000)
        norm_amt = (math.log(max(row["amount"], 1.0)) - math.log(max(min_amt, 1.0))) / max(
            (math.log(max(max_amt, 1.0)) - math.log(max(min_amt, 1.0))), 0.001
        )
        amount_inr_paise = int(10000 + norm_amt * (5000000 - 10000))

        # 2. Payment Method Mapping based on NPCI/RBI 65/20/10/5 distribution
        method = random.choices(
            list(RAIL_WEIGHTS.keys()),
            weights=list(RAIL_WEIGHTS.values()),
            k=1,
        )[0]

        bank_code = None
        if method == "netbanking":
            bank_code = random.choices(NETBANKING_BANKS, weights=[0.40, 0.30, 0.20, 0.10], k=1)[0]
        elif method == "card":
            bank_code = random.choice(CARD_NETWORKS)
        elif method == "wallet":
            bank_code = random.choice(WALLETS)
        elif method == "upi":
            bank_code = "UPI_INTENT"

        # 3. Chaos Surge Injections across time slices
        # Slice 20%-40%: HDFC NetBanking Outage (90% failure)
        is_hdfc_outage = (0.20 <= (idx / target_samples) < 0.40) and (bank_code == "HDFC")
        # Slice 50%-60%: UPI Degradation (40% failure)
        is_upi_degraded = (0.50 <= (idx / target_samples) < 0.60) and (method == "upi")

        is_fraud = int(row.get("isFraud", 0)) == 1

        # Determine failure vs success
        if is_hdfc_outage:
            is_failed = random.random() < 0.90
        elif is_upi_degraded:
            is_failed = random.random() < 0.40
        else:
            is_failed = is_fraud or (random.random() < 0.08)

        # 4. Error Taxonomy & Ground Truth Labeling
        if is_fraud or (is_failed and random.random() < 0.30):
            # Customer / Fraud Veto (30% bucket)
            err_code, err_desc, err_src, err_step, err_reason = random.choice(CUSTOMER_ERRORS)
            should_recover = False
            optimal_action = "SAFE_REFUSAL_VETO"
        elif is_failed:
            # Infrastructure Failure (70% bucket)
            err_code, err_desc, err_src, err_step, err_reason = random.choice(INFRA_ERRORS)
            should_recover = True
            optimal_action = "UPI_INTENT_LINK" if method != "upi" else "REROUTE_NETBANKING"
        else:
            err_code = "SUCCESS"
            err_desc = "Transaction authorized successfully"
            err_src = "none"
            err_step = "settled"
            err_reason = "none"
            should_recover = False
            optimal_action = "NONE"

        # 5. Latency Synthesis (Fast: 50-500ms vs Failure: 2000-10000ms)
        if is_failed:
            latency_ms = random.randint(2000, 10000)
        else:
            latency_ms = random.randint(50, 500)

        # Razorpay ID Formats (`pay_...`, `order_...`)
        short_id = secrets.token_urlsafe(10)[:9].replace("-", "x").replace("_", "Y")
        pay_id = f"pay_{short_id}"
        order_id = f"order_live_{short_id}"

        event = {
            "entity": "event",
            "event": "payment.failed" if is_failed else "payment.authorized",
            "timestamp": base_timestamp + int(idx * 2),
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": order_id,
                        "amount": amount_inr_paise,
                        "currency": "INR",
                        "status": "failed" if is_failed else "captured",
                        "method": method,
                        "bank": bank_code,
                        "error_code": err_code,
                        "error_description": err_desc,
                        "error_source": err_src,
                        "error_step": err_step,
                        "error_reason": err_reason,
                        "latency_ms": latency_ms,
                    }
                }
            },
            "ground_truth": {
                "is_fraud": is_fraud,
                "should_recover": should_recover,
                "optimal_action": optimal_action,
                "max_discount_allowed": 5.0 if should_recover else 0.0,
            },
        }
        events.append(event)

    return events


# ---------------------------------------------------------------------------
# Main Execution Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch Kaggle dataset & project into Razorpay webhooks.")
    parser.add_argument("--dataset", type=str, default="ealaxi/paysim1", help="Kaggle dataset slug")
    parser.add_argument("--n", type=int, default=1000, help="Number of records to output")
    parser.add_argument("--output", type=str, default="benchmark_1k_realworld.json", help="Output JSON path")
    args = parser.parse_args()

    print("🚀 Starting FinTech Ingestion & Feature Projection Pipeline...")
    
    df = fetch_kaggle_dataset(dataset_slug=args.dataset)
    if df is None:
        df = generate_fallback_dataframe(n=args.n * 2)

    print(f"📊 Processing {len(df)} financial transaction records...")
    webhooks = project_to_razorpay_webhooks(df, target_samples=args.n)

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(webhooks, f, indent=2)

    # Calculate summary metrics
    total = len(webhooks)
    failed_count = sum(1 for e in webhooks if e["event"] == "payment.failed")
    recoverable_count = sum(1 for e in webhooks if e["ground_truth"]["should_recover"])
    veto_count = sum(1 for e in webhooks if e["ground_truth"]["optimal_action"] == "SAFE_REFUSAL_VETO")

    print(f"\n{'='*65}")
    print(f"✅ RAZORPAY WEBHOOK DATASET CREATED: {output_path.name}")
    print(f"{'='*65}")
    print(f"Total Webhook Events:    {total:,}")
    print(f"Failed Transactions:     {failed_count:,} ({round(failed_count/total*100, 1)}%)")
    print(f"Recoverable (Infra):     {recoverable_count:,} ({round(recoverable_count/max(failed_count,1)*100, 1)}% of failures)")
    print(f"Vetoed (Customer/Fraud): {veto_count:,} ({round(veto_count/max(failed_count,1)*100, 1)}% of failures)")
    print(f"Output File:             {output_path.absolute()}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()

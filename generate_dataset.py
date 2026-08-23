"""
generate_dataset.py — Generates synthetic Indian payment transaction dataset.

Usage:
  python generate_dataset.py --n 1000 --output dataset.json
  python generate_dataset.py --n 100000 --output dataset_large.json

Distribution (INDUSTRY ASSUMPTION — sourced from NPCI/RBI public data):
  UPI: 65%, Cards: 20%, NetBanking: 10%, Wallets: 5%

All data is SYNTHETIC. No real transactions. No real customer data.
Every number produced by this script is tagged SIMULATED in outputs.
"""

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from schemas import ErrorCode, PaymentRail


# ---------------------------------------------------------------------------
# Distribution parameters
# ---------------------------------------------------------------------------

# INDUSTRY ASSUMPTION — rail distribution for Indian e-commerce
# Source: NPCI Annual Report 2023-24, RBI Payment System Indicators
RAIL_DISTRIBUTION = {
    PaymentRail.UPI: 0.65,
    PaymentRail.VISA: 0.08,
    PaymentRail.MASTERCARD: 0.07,
    PaymentRail.RUPAY: 0.05,
    PaymentRail.HDFC_NETBANKING: 0.04,
    PaymentRail.ICICI_NETBANKING: 0.03,
    PaymentRail.SBI_NETBANKING: 0.02,
    PaymentRail.AXIS_NETBANKING: 0.01,
    PaymentRail.PHONEPE_WALLET: 0.03,
    PaymentRail.PAYTM_WALLET: 0.02,
}

# Baseline failure rates per rail (INDUSTRY ASSUMPTION from payment industry benchmarks)
RAIL_BASELINE_FAILURE_RATE = {
    PaymentRail.UPI: 0.06,
    PaymentRail.VISA: 0.09,
    PaymentRail.MASTERCARD: 0.10,
    PaymentRail.RUPAY: 0.11,
    PaymentRail.HDFC_NETBANKING: 0.13,
    PaymentRail.ICICI_NETBANKING: 0.14,
    PaymentRail.SBI_NETBANKING: 0.18,
    PaymentRail.AXIS_NETBANKING: 0.15,
    PaymentRail.PHONEPE_WALLET: 0.05,
    PaymentRail.PAYTM_WALLET: 0.07,
}

# Error code distribution for failures
FAILURE_CODES = {
    "infrastructure": [
        (ErrorCode.TIMEOUT, 0.30),
        (ErrorCode.BANK_UNAVAILABLE, 0.20),
        (ErrorCode.GATEWAY_TIMEOUT, 0.20),
        (ErrorCode.NETWORK_ERROR, 0.10),
        (ErrorCode.ISSUER_DECLINED, 0.20),
    ],
    "customer": [
        (ErrorCode.INVALID_OTP, 0.35),
        (ErrorCode.INSUFFICIENT_FUNDS, 0.45),
        (ErrorCode.INCORRECT_CREDENTIALS, 0.10),
        (ErrorCode.AUTH_REJECTED, 0.05),
        (ErrorCode.SUSPECTED_FRAUD, 0.05),
    ],
}

# 70% infrastructure failures, 30% customer failures (INDUSTRY ASSUMPTION)
FAILURE_TYPE_SPLIT = {"infrastructure": 0.70, "customer": 0.30}

# Amount distribution (INR) — typical Indian e-commerce
AMOUNT_RANGES = [
    (100, 500, 0.20),      # Micro
    (500, 2000, 0.40),     # Small
    (2000, 10000, 0.30),   # Medium
    (10000, 50000, 0.10),  # Large
]


def sample_rail() -> PaymentRail:
    rails = list(RAIL_DISTRIBUTION.keys())
    weights = list(RAIL_DISTRIBUTION.values())
    return random.choices(rails, weights=weights, k=1)[0]


def sample_amount() -> float:
    range_choice = random.choices(
        [(lo, hi) for lo, hi, _ in AMOUNT_RANGES],
        weights=[w for _, _, w in AMOUNT_RANGES],
        k=1,
    )[0]
    return round(random.uniform(*range_choice), 2)


def sample_error_code(is_failure: bool, failure_type: str) -> ErrorCode:
    if not is_failure:
        return ErrorCode.SUCCESS
    codes_weights = FAILURE_CODES[failure_type]
    codes = [c for c, _ in codes_weights]
    weights = [w for _, w in codes_weights]
    return random.choices(codes, weights=weights, k=1)[0]


def generate_transaction(
    index: int,
    base_time: datetime,
    inject_hdfc_outage: bool = False,
    inject_upi_degradation: bool = False,
) -> dict:
    """Generate a single synthetic transaction record."""
    rail = sample_rail()
    amount = sample_amount()
    failure_rate = RAIL_BASELINE_FAILURE_RATE[rail]

    # Apply failure injection for benchmark scenarios
    if inject_hdfc_outage and rail == PaymentRail.HDFC_NETBANKING:
        failure_rate = 0.90  # 90% failure during outage
    if inject_upi_degradation and rail == PaymentRail.UPI:
        failure_rate = 0.40  # 40% failure during degradation

    is_failure = random.random() < failure_rate

    # Determine if this is customer-caused or infrastructure failure
    failure_type = "infrastructure"
    if is_failure:
        failure_type = random.choices(
            ["infrastructure", "customer"],
            weights=[FAILURE_TYPE_SPLIT["infrastructure"], FAILURE_TYPE_SPLIT["customer"]],
            k=1,
        )[0]

    error_code = sample_error_code(is_failure, failure_type)

    # Classify ground truth (for benchmark evaluation)
    is_customer_caused = failure_type == "customer"
    eligible_for_reroute = (
        is_failure
        and not is_customer_caused
        and error_code not in {
            ErrorCode.INVALID_OTP,
            ErrorCode.SUSPECTED_FRAUD,
            ErrorCode.AUTH_REJECTED,
            ErrorCode.INCORRECT_CREDENTIALS,
        }
    )

    # Simulated timestamp
    timestamp = base_time + timedelta(seconds=index * 1.5 + random.uniform(-0.5, 0.5))

    return {
        "transaction_id": str(uuid.uuid4()),
        "order_id": f"ord_{uuid.uuid4().hex[:12]}",
        "rail": rail.value,
        "amount_inr": amount,
        "error_code": error_code.value,
        "is_failure": is_failure,
        "is_customer_caused": is_customer_caused,
        "eligible_for_reroute": eligible_for_reroute,
        "failure_type": failure_type if is_failure else None,
        "timestamp": timestamp.isoformat(),
        "latency_ms": random.randint(50, 5000) if not is_failure else random.randint(2000, 10000),
        "data_source": "SIMULATED",  # Always tagged
    }


def generate_dataset(
    n: int = 1000,
    include_hdfc_outage: bool = True,
    include_upi_degradation: bool = False,
) -> list[dict]:
    """
    Generate n synthetic transactions.
    
    include_hdfc_outage: If True, 20% of transactions occur during a simulated HDFC outage
    include_upi_degradation: If True, 10% of transactions occur during UPI degradation
    """
    base_time = datetime(2026, 8, 22, 9, 0, 0)
    transactions = []

    for i in range(n):
        # Introduce failure windows
        hdfc_outage = include_hdfc_outage and (n // 5 <= i < n // 5 + n // 5)
        upi_degraded = include_upi_degradation and (n // 2 <= i < n // 2 + n // 10)

        txn = generate_transaction(i, base_time, hdfc_outage, upi_degraded)
        transactions.append(txn)

    return transactions


def compute_dataset_statistics(transactions: list[dict]) -> dict:
    """Compute summary statistics for the generated dataset."""
    total = len(transactions)
    failures = [t for t in transactions if t["is_failure"]]
    customer_caused = [t for t in transactions if t.get("is_customer_caused")]
    infrastructure = [t for t in transactions if t.get("is_failure") and not t.get("is_customer_caused")]
    reroutable = [t for t in transactions if t.get("eligible_for_reroute")]

    rail_breakdown = {}
    for rail in PaymentRail:
        rail_txns = [t for t in transactions if t["rail"] == rail.value]
        rail_failures = [t for t in rail_txns if t["is_failure"]]
        rail_breakdown[rail.value] = {
            "count": len(rail_txns),
            "percentage": round(len(rail_txns) / total * 100, 1),
            "failure_rate": round(len(rail_failures) / max(len(rail_txns), 1) * 100, 1),
        }

    return {
        "total_transactions": total,
        "failure_count": len(failures),
        "failure_rate_pct": round(len(failures) / total * 100, 2),
        "customer_caused_failures": len(customer_caused),
        "infrastructure_failures": len(infrastructure),
        "reroutable_failures": len(reroutable),
        "reroutable_pct_of_failures": round(len(reroutable) / max(len(failures), 1) * 100, 1),
        "rail_breakdown": rail_breakdown,
        "data_source": "SIMULATED",
        "generation_timestamp": datetime.utcnow().isoformat(),
        "notes": (
            "All statistics are SIMULATED. Rail distribution based on "
            "INDUSTRY ASSUMPTION from NPCI/RBI public data. "
            "Failure rates are representative estimates, not measured values."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic payment dataset")
    parser.add_argument("--n", type=int, default=1000, help="Number of transactions")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output file path")
    parser.add_argument("--no-hdfc-outage", action="store_true", help="Disable HDFC outage scenario")
    parser.add_argument("--upi-degradation", action="store_true", help="Include UPI degradation scenario")
    args = parser.parse_args()

    print(f"Generating {args.n} synthetic transactions...")
    transactions = generate_dataset(
        n=args.n,
        include_hdfc_outage=not args.no_hdfc_outage,
        include_upi_degradation=args.upi_degradation,
    )

    stats = compute_dataset_statistics(transactions)

    output = {
        "dataset": transactions,
        "statistics": stats,
    }

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DATASET GENERATED: {args.output}")
    print(f"{'='*60}")
    print(f"Total transactions:     {stats['total_transactions']:,}")
    print(f"Failure count:          {stats['failure_count']:,} ({stats['failure_rate_pct']}%)")
    print(f"Customer-caused:        {stats['customer_caused_failures']:,}")
    print(f"Infrastructure:         {stats['infrastructure_failures']:,}")
    print(f"Reroutable failures:    {stats['reroutable_failures']:,} ({stats['reroutable_pct_of_failures']}% of failures)")
    print(f"\nRail distribution:")
    for rail, data in stats["rail_breakdown"].items():
        print(f"  {rail:<25}: {data['percentage']:>5.1f}% | failure rate {data['failure_rate_pct']}%")
    print(f"\nAll figures: SIMULATED")
    print(f"Saved to: {output_path.absolute()}")

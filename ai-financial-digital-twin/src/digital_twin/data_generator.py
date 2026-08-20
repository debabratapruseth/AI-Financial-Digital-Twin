"""Deterministic synthetic virtual-bank dataset generation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bank_state import BankState
from .config import load_baseline, load_risk_limits


def generate_virtual_bank(seed: int = 42) -> BankState:
    """Create a compact synthetic bank. Monetary values are USD billions."""
    config = load_baseline()
    rng = np.random.default_rng(seed)
    bs = config["balance_sheet"]
    balance_sheet = pd.DataFrame([
        ("cash_reserves", "asset", bs["cash_reserves"]),
        ("securities", "asset", bs["securities"]),
        ("customer_loans", "asset", bs["customer_loans"]),
        ("retail_deposits", "liability", bs["retail_deposits"]),
        ("sme_deposits", "liability", bs["sme_deposits"]),
        ("corporate_deposits", "liability", bs["corporate_deposits"]),
        ("wholesale_funding", "liability", bs["wholesale_funding"]),
        ("other_liabilities", "liability", bs["other_liabilities"]),
        ("cet1_capital", "capital", bs["cet1_capital"]),
    ], columns=["item", "category", "amount_bn"])

    fx_exposures = pd.DataFrame([
        ("USD", 8.0, 0.55, 1.0), ("EUR", 3.5, 0.70, 1.08),
        ("GBP", -1.5, 0.80, 1.27), ("JPY", 2.0, 0.65, 0.0067),
    ], columns=["currency", "gross_exposure_bn", "hedge_ratio", "spot_to_usd"])

    customer_segments = pd.DataFrame([
        ("Retail", 42.0, 0.05, 0.7, 0.35, 0.8, 4_200_000),
        ("SME", 12.0, 0.10, 1.0, 0.55, 1.0, 180_000),
        ("Corporate", 20.0, 0.15, 1.4, 0.70, 1.3, 8_000),
        ("Private Banking", 4.0, 0.08, 1.2, 0.45, 1.1, 30_000),
    ], columns=["segment", "deposits_bn", "baseline_outflow_rate", "withdrawal_sensitivity",
                "credit_utilisation", "outage_sensitivity", "customers"])

    ratings = ["AAA", "AA", "A", "BBB", "BB", "B"]
    pd_map = {"AAA": .0005, "AA": .001, "A": .003, "BBB": .01, "BB": .035, "B": .08}
    sectors = ["Financials", "Technology", "Manufacturing", "Energy", "Property", "Retail"]
    rows = []
    for index in range(24):
        rating = ratings[index % len(ratings)]
        ead = float(rng.uniform(0.25, 1.8))
        collateral = float(rng.uniform(0.1, 0.75))
        rows.append((f"CP-{index + 1:03d}", ead, pd_map[rating], float(rng.uniform(.30, .60)),
                     rating, sectors[index % len(sectors)], collateral))
    counterparties = pd.DataFrame(rows, columns=["counterparty_id", "ead_bn", "pd", "lgd", "rating", "sector", "collateral_ratio"])

    applications = pd.DataFrame([
        ("Core Banking", "Banking", 0.99, "Primary Data Centre", "Backup Data Centre", "active-passive", 60, 100, 100, "Critical"),
        ("Domestic Payments", "Payments", 0.995, "Cloud Region A", "Cloud Region B", "warm standby", 180, 100, 70, "Critical"),
        ("Cross-Border Payments", "Payments", 0.99, "Cloud Region A", None, "none", None, 100, 0, "Critical"),
        ("Mobile Banking", "Channels", 0.98, "Primary Data Centre", "Backup Data Centre", "active-passive", 30, 100, 100, "High"),
        ("Internet Banking", "Channels", 0.98, "Primary Data Centre", "Backup Data Centre", "active-passive", 30, 100, 100, "High"),
        ("Treasury Platform", "Markets", 0.99, "Primary Data Centre", "Backup Data Centre", "warm standby", 60, 100, 90, "Critical"),
        ("Identity Service", "Security", 0.995, "Cloud Region A", "Cloud Region B", "hot standby", 30, 100, 90, "Critical"),
        ("Fraud Monitoring", "Security", 0.99, "Primary Data Centre", "Backup Data Centre", "active-passive", 30, 100, 100, "High"),
        ("Credit Risk Engine", "Risk", 0.98, "Primary Data Centre", "Backup Data Centre", "warm standby", 120, 100, 80, "High"),
        ("Liquidity Risk Platform", "Risk", 0.98, "Primary Data Centre", "Backup Data Centre", "warm standby", 120, 100, 80, "High"),
    ], columns=["application", "service", "availability_target", "primary_region", "backup_region",
                "backup_mode", "failover_time_minutes", "normal_capacity_pct", "backup_capacity_pct",
                "criticality"])
    vendors = pd.DataFrame([
        ("Cloud Provider", "Infrastructure", True), ("Payment Network", "Payments", True),
        ("Market Data Provider", "Data", False), ("Identity Provider", "Identity", True),
    ], columns=["vendor", "service", "critical"])
    infrastructure = pd.DataFrame([
        ("Cloud Region A", "cloud", 0.55, True), ("Cloud Region B", "cloud", 0.30, False),
        ("Primary Data Centre", "data_centre", 0.10, True),
        ("Backup Data Centre", "data_centre", 0.05, False),
    ], columns=["infrastructure", "type", "workload_share", "primary"])
    payment_systems = pd.DataFrame([
        ("Domestic Payments", 3.2, 0.65, 0.995), ("Cross-Border Payments", 1.8, 0.35, 0.99)
    ], columns=["system", "daily_value_bn", "critical_share", "baseline_availability"])

    edges = [
        ("Cloud Provider", "Cloud Region A", "hosts", 1.0),
        ("Cloud Region A", "Identity Service", "hosts", 1.0),
        ("Cloud Region B", "Identity Service", "backup", .5),
        ("Identity Provider", "Identity Service", "supplies", 1.0),
        ("Identity Service", "Mobile Banking", "authenticates", 1.0),
        ("Identity Service", "Internet Banking", "authenticates", 1.0),
        ("Cloud Region A", "Domestic Payments", "hosts", 1.0),
        ("Cloud Region A", "Cross-Border Payments", "hosts", 1.0),
        ("Cloud Region B", "Domestic Payments", "backup", .5),
        ("Payment Network", "Domestic Payments", "connects", 1.0),
        ("Payment Network", "Cross-Border Payments", "connects", 1.0),
        ("Market Data Provider", "Treasury Platform", "supplies", 1.0),
        ("Primary Data Centre", "Core Banking", "hosts", 1.0),
        ("Core Banking", "Domestic Payments", "supports", 1.0),
        ("Mobile Banking", "Retail", "serves", .8),
        ("Internet Banking", "Retail", "serves", .5),
        ("Internet Banking", "SME", "serves", .8),
        ("Domestic Payments", "SME", "serves", .8),
        ("Domestic Payments", "Corporate", "serves", .8),
        ("Cross-Border Payments", "Corporate", "serves", 1.0),
        ("Mobile Banking", "Private Banking", "serves", .5),
        ("Retail", "Deposit Outflows", "behaviour", .7),
        ("SME", "Deposit Outflows", "behaviour", 1.0),
        ("Corporate", "Corporate Deposits", "behaviour", 1.0),
        ("Corporate Deposits", "Deposit Outflows", "funding", 1.0),
        ("Deposit Outflows", "Liquidity Position", "reduces", 1.0),
        ("Treasury Platform", "Market P&L", "controls", 1.0),
        ("Market P&L", "Capital Position", "reduces", 1.0),
        ("Liquidity Position", "Capital Position", "funding_cost", .4),
        ("Liquidity Position", "LCR", "determines", 1.0),
        ("USD Shock", "FX Exposure", "revalues", 1.0),
        ("FX Exposure", "Market P&L", "creates", 1.0),
        ("Capital Position", "CET1 Ratio", "determines", 1.0),
        ("Volatility Shock", "Market P&L", "creates", 1.0),
        ("Major Counterparty", "Credit Loss", "defaults", 1.0),
        ("Credit Loss", "Capital Position", "reduces", 1.0),
    ]
    dependencies = pd.DataFrame(edges, columns=["source", "target", "relationship", "impact_weight"])
    return BankState(balance_sheet, fx_exposures, customer_segments, counterparties, applications,
                     vendors, infrastructure, payment_systems, dependencies,
                     load_risk_limits()["limits"], config["assumptions"], seed)

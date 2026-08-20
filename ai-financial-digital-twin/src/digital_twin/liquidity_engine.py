"""Prototype liquidity stress calculations; not a regulatory LCR implementation."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class LiquidityImpact:
    hqla_bn: float
    baseline_outflows_bn: float
    incremental_outflows_bn: float
    stressed_outflows_bn: float
    stressed_cash_bn: float
    funding_requirement_bn: float
    deposit_outflow_bn: float
    cash_consumed_bn: float
    hqla_consumed_bn: float
    facility_draw_bn: float
    asset_liquidation_bn: float
    asset_sale_proceeds_bn: float
    funding_cost_bn: float
    realised_asset_sale_loss_bn: float
    lcr: float
    detail: pd.DataFrame


def calculate_hqla(cash_bn: float, securities_bn: float, haircut: float = 0.15) -> float:
    return cash_bn + securities_bn * (1.0 - haircut)


def calculate_lcr(hqla_bn: float, net_cash_outflows_bn: float) -> float:
    return float("inf") if net_cash_outflows_bn <= 0 else hqla_bn / net_cash_outflows_bn


def calculate_liquidity(customer_segments: pd.DataFrame, cash_bn: float, securities_bn: float,
                        withdrawal_shocks: dict[str, float] | None = None, margin_call_bn: float = 0.0,
                        facility_draw_bn: float = 0.0, securities_sold_bn: float = 0.0,
                        haircut: float = 0.15, inflow_cap_bn: float = 2.0,
                        facility_annual_rate: float = 0.045, asset_sale_haircut: float = 0.02,
                        emergency_funding_annual_rate: float = 0.05) -> LiquidityImpact:
    detail = customer_segments.copy()
    shocks = withdrawal_shocks or {}
    detail["shock_rate"] = detail["segment"].map(shocks).fillna(0.0)
    detail["baseline_outflow_bn"] = detail["deposits_bn"] * detail["baseline_outflow_rate"]
    detail["incremental_outflow_bn"] = detail["deposits_bn"] * detail["shock_rate"] * detail["withdrawal_sensitivity"]
    baseline = float(detail["baseline_outflow_bn"].sum())
    incremental = float(detail["incremental_outflow_bn"].sum())
    net_outflows = max(0.0, baseline + incremental + margin_call_bn - inflow_cap_bn)
    asset_sale_proceeds = securities_sold_bn * (1.0 - asset_sale_haircut)
    realised_sale_loss = securities_sold_bn - asset_sale_proceeds
    stressed_cash = cash_bn + facility_draw_bn + asset_sale_proceeds - incremental - margin_call_bn
    remaining_securities = max(0.0, securities_bn - securities_sold_bn)
    hqla = calculate_hqla(max(0.0, stressed_cash), remaining_securities, haircut)
    funding = max(0.0, -stressed_cash)
    baseline_hqla = calculate_hqla(cash_bn, securities_bn, haircut)
    funding_cost = (facility_draw_bn * facility_annual_rate
                    + funding * emergency_funding_annual_rate) * 30.0 / 365.0
    return LiquidityImpact(
        hqla, baseline, incremental, net_outflows, stressed_cash, funding,
        incremental, incremental + margin_call_bn, max(0.0, baseline_hqla - hqla),
        facility_draw_bn, securities_sold_bn, asset_sale_proceeds, funding_cost,
        realised_sale_loss, calculate_lcr(hqla, net_outflows), detail)


def lcr_components(impact: LiquidityImpact, starting_cash_bn: float, securities_before_bn: float,
                   haircut: float, inflow_cap_bn: float, other_eligible_hqla_bn: float = 0.0,
                   wholesale_outflows_bn: float = 0.0, credit_line_drawdowns_bn: float = 0.0,
                   other_stressed_outflows_bn: float = 0.0) -> dict[str, float]:
    """Reconcile the prototype stock-over-flow LCR from an actual liquidity run.

    This is deliberately a transparent prototype bridge, not a regulatory LCR engine.
    Unmodelled components default to zero and are labelled explicitly by the caller.
    """
    segment_baseline = impact.detail.set_index("segment")["baseline_outflow_bn"].to_dict()
    segment_incremental = impact.detail.set_index("segment")["incremental_outflow_bn"].to_dict()
    margin_call_bn = impact.cash_consumed_bn - impact.deposit_outflow_bn
    remaining_securities_bn = max(0.0, securities_before_bn - impact.asset_liquidation_bn)
    securities_haircut_bn = remaining_securities_bn * haircut
    eligible_securities_bn = remaining_securities_bn - securities_haircut_bn
    eligible_cash_bn = max(0.0, impact.stressed_cash_bn)
    total_hqla_bn = eligible_cash_bn + eligible_securities_bn + other_eligible_hqla_bn
    values: dict[str, float] = {
        "starting_cash_bn": float(starting_cash_bn),
        "eligible_cash_bn": float(eligible_cash_bn),
        "securities_before_haircut_bn": float(securities_before_bn),
        "securities_haircut_bn": float(securities_haircut_bn),
        "eligible_securities_bn": float(eligible_securities_bn),
        "other_eligible_hqla_bn": float(other_eligible_hqla_bn),
        "total_eligible_hqla_bn": float(total_hqla_bn),
    }
    for segment in ("Retail", "SME", "Corporate", "Private Banking"):
        key = segment.lower().replace(" ", "_") + "_outflow_bn"
        values[key] = float(segment_baseline.get(segment, 0.0) + segment_incremental.get(segment, 0.0))
    values.update({
        "wholesale_funding_outflows_bn": float(wholesale_outflows_bn),
        "credit_line_drawdowns_bn": float(credit_line_drawdowns_bn),
        "margin_collateral_calls_bn": float(margin_call_bn),
        "other_stressed_outflows_bn": float(other_stressed_outflows_bn),
        "eligible_inflows_bn": float(inflow_cap_bn),
    })
    gross_outflows = sum(values[key] for key in (
        "retail_outflow_bn", "sme_outflow_bn", "corporate_outflow_bn", "private_banking_outflow_bn",
        "wholesale_funding_outflows_bn", "credit_line_drawdowns_bn", "margin_collateral_calls_bn",
        "other_stressed_outflows_bn",
    ))
    values["net_stressed_30d_cash_outflows_bn"] = max(0.0, gross_outflows - inflow_cap_bn)
    values["lcr"] = calculate_lcr(total_hqla_bn, values["net_stressed_30d_cash_outflows_bn"])
    return values


def build_lcr_bridge(baseline: LiquidityImpact, stressed: LiquidityImpact, starting_cash_bn: float,
                     securities_before_bn: float, haircut: float, inflow_cap_bn: float,
                     tolerance: float = 1e-10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a baseline/stress LCR bridge and machine-readable validation checks."""
    base = lcr_components(baseline, starting_cash_bn, securities_before_bn, haircut, inflow_cap_bn)
    stress_values = lcr_components(stressed, starting_cash_bn, securities_before_bn, haircut, inflow_cap_bn)
    definitions: list[tuple[str, str, str]] = [
        ("Starting cash / eligible liquid assets", "eligible_cash_bn", "Cash is floored at zero in eligible HQLA."),
        ("Securities before haircut", "securities_before_haircut_bn", "Gross synthetic securities stock."),
        ("Securities haircut", "securities_haircut_bn", "Configured haircut deducted once."),
        ("Eligible securities", "eligible_securities_bn", "Securities after configured haircut."),
        ("Other eligible HQLA", "other_eligible_hqla_bn", "Not modelled; zero."),
        ("Total eligible HQLA", "total_eligible_hqla_bn", "Eligible cash plus eligible securities and other HQLA."),
        ("Retail cash outflow", "retail_outflow_bn", "Baseline 30-day flow plus scenario increment."),
        ("SME cash outflow", "sme_outflow_bn", "Baseline 30-day flow plus scenario increment."),
        ("Corporate cash outflow", "corporate_outflow_bn", "Baseline 30-day flow plus scenario increment."),
        ("Private banking cash outflow", "private_banking_outflow_bn", "Baseline 30-day flow plus scenario increment."),
        ("Wholesale funding outflow", "wholesale_funding_outflows_bn", "Not modelled; zero."),
        ("Credit-line drawdown", "credit_line_drawdowns_bn", "Not modelled; zero."),
        ("Margin/collateral requirement", "margin_collateral_calls_bn", "Market-loss-linked margin call."),
        ("Other stressed outflows", "other_stressed_outflows_bn", "Not modelled; zero."),
        ("Eligible inflows", "eligible_inflows_bn", "Configured fixed inflow cap, deducted from gross outflows."),
        ("Net stressed 30-day cash outflow", "net_stressed_30d_cash_outflows_bn", "Gross modelled outflows less eligible inflows."),
        ("LCR", "lcr", "Total eligible HQLA divided by net stressed 30-day cash outflow."),
    ]
    bridge = pd.DataFrame([{
        "Component": label, "Baseline": base[key], "Stress Change": stress_values[key] - base[key],
        "Stressed": stress_values[key], "Explanation": explanation,
    } for label, key, explanation in definitions])
    checks = pd.DataFrame([
        {"Validation Check": "Baseline LCR = HQLA / net outflow", "Passed": abs(base["lcr"] - baseline.lcr) <= tolerance,
         "Observed": base["lcr"], "Expected": baseline.lcr},
        {"Validation Check": "Stressed LCR = HQLA / net outflow", "Passed": abs(stress_values["lcr"] - stressed.lcr) <= tolerance,
         "Observed": stress_values["lcr"], "Expected": stressed.lcr},
        {"Validation Check": "Baseline HQLA reconciles", "Passed": abs(base["total_eligible_hqla_bn"] - baseline.hqla_bn) <= tolerance,
         "Observed": base["total_eligible_hqla_bn"], "Expected": baseline.hqla_bn},
        {"Validation Check": "Stressed HQLA reconciles", "Passed": abs(stress_values["total_eligible_hqla_bn"] - stressed.hqla_bn) <= tolerance,
         "Observed": stress_values["total_eligible_hqla_bn"], "Expected": stressed.hqla_bn},
        {"Validation Check": "HQLA is non-negative", "Passed": stressed.hqla_bn >= 0.0,
         "Observed": stressed.hqla_bn, "Expected": ">= 0"},
        {"Validation Check": "Net stressed outflow is positive", "Passed": stressed.stressed_outflows_bn > 0.0,
         "Observed": stressed.stressed_outflows_bn, "Expected": "> 0"},
        {"Validation Check": "USD billion units are explicit", "Passed": True,
         "Observed": "USD bn", "Expected": "USD bn"},
    ])
    if not bool(checks["Passed"].all()):
        failures = checks.loc[~checks["Passed"], "Validation Check"].tolist()
        raise AssertionError(f"LCR bridge reconciliation failed: {failures}")
    return bridge, checks

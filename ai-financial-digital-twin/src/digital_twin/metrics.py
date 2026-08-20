"""Prototype KPI calculation and deterministic risk-limit evaluation."""

from __future__ import annotations

from typing import Any

import pandas as pd


SEVERITY_POINTS = {"Within Limit": 0, "Warning": 1, "Critical": 2}


def cet1_ratio(cet1_capital_bn: float, rwa_bn: float) -> float:
    return cet1_capital_bn / rwa_bn if rwa_bn > 0 else float("inf")


def calculate_metrics(*, cash_bn: float, hqla_bn: float, lcr: float, cet1_bn: float, rwa_bn: float,
                      market_loss_bn: float = 0.0, credit_loss_bn: float = 0.0,
                      operational_loss_bn: float = 0.0, liquidity_pnl_loss_bn: float = 0.0,
                      payment_availability: float = 1.0,
                      payment_backlog_bn: float = 0.0, customers_affected: int = 0,
                      applications_affected: int = 0, recovery_time_hours: float = 0.0,
                      deposit_outflow_bn: float = 0.0, cash_consumed_bn: float = 0.0,
                      hqla_consumed_bn: float = 0.0, emergency_funding_requirement_bn: float = 0.0,
                      funding_cost_bn: float = 0.0, asset_liquidation_bn: float = 0.0,
                      realised_asset_sale_loss_bn: float = 0.0) -> dict[str, Any]:
    total_loss = market_loss_bn + credit_loss_bn + operational_loss_bn + liquidity_pnl_loss_bn
    return {
        "total_estimated_loss_bn": total_loss, "market_loss_bn": market_loss_bn,
        "credit_loss_bn": credit_loss_bn, "operational_loss_bn": operational_loss_bn,
        "liquidity_pnl_loss_bn": liquidity_pnl_loss_bn,
        "cash_position_bn": cash_bn, "hqla_bn": hqla_bn, "lcr": lcr,
        "cet1_capital_bn": cet1_bn, "risk_weighted_assets_bn": rwa_bn,
        "cet1_ratio": cet1_ratio(cet1_bn, rwa_bn), "payment_availability": payment_availability,
        "payment_backlog_bn": payment_backlog_bn, "customers_affected": customers_affected,
        "applications_affected": applications_affected, "recovery_time_hours": recovery_time_hours,
        "deposit_outflow_bn": deposit_outflow_bn, "cash_consumed_bn": cash_consumed_bn,
        "hqla_consumed_bn": hqla_consumed_bn,
        "emergency_funding_requirement_bn": emergency_funding_requirement_bn,
        "funding_cost_bn": funding_cost_bn, "asset_liquidation_bn": asset_liquidation_bn,
        "realised_asset_sale_loss_bn": realised_asset_sale_loss_bn,
    }


def evaluate_risk_limits(metrics: dict[str, Any], limits: dict[str, Any]) -> list[dict[str, Any]]:
    breaches = []
    for metric, rule in limits.items():
        if metric not in metrics:
            continue
        value = float(metrics[metric])
        direction = rule["direction"]
        critical = value < rule["critical"] if direction == "min" else value > rule["critical"]
        warning = value < rule["warning"] if direction == "min" else value > rule["warning"]
        if critical or warning:
            level = "critical" if critical else "warning"
            breaches.append({"metric": metric, "value": value, "level": level,
                             "threshold": float(rule[level]), "direction": direction})
    return breaches


def classify_risk_severity(value: float, rule: dict[str, Any]) -> str:
    """Return one mutually exclusive management severity classification."""
    if rule["direction"] == "min":
        return "Critical" if value < rule["critical"] else ("Warning" if value < rule["warning"] else "Within Limit")
    return "Critical" if value > rule["critical"] else ("Warning" if value > rule["warning"] else "Within Limit")


def risk_threshold_table(metrics: dict[str, Any], limits: dict[str, Any]) -> pd.DataFrame:
    """Expose configured thresholds, severity, and signed distance to the healthy boundary."""
    rows = []
    for metric, rule in limits.items():
        if metric not in metrics:
            continue
        value = float(metrics[metric])
        warning = float(rule["warning"])
        distance = value - warning if rule["direction"] == "min" else warning - value
        rows.append({
            "Metric": metric, "Current Value": value, "Warning Threshold": warning,
            "Critical Threshold": float(rule["critical"]),
            "Direction": rule["direction"], "Severity": classify_risk_severity(value, rule),
            "Distance to Warning Threshold / Healthy Boundary": distance,
        })
    return pd.DataFrame(rows)


def severity_distribution(results: dict[str, Any], limits: dict[str, Any]) -> pd.DataFrame:
    """Count mutually exclusive configured metric severities for each strategy."""
    rows = []
    for severity in ("Within Limit", "Warning", "Critical"):
        row = {"Severity": severity}
        for label, result in results.items():
            statuses = risk_threshold_table(result.metrics, limits)["Severity"]
            row[label] = int((statuses == severity).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def prototype_risk_severity_scores(results: dict[str, Any], limits: dict[str, Any]) -> pd.DataFrame:
    """Calculate a transparent non-regulatory 0/1/2 management severity score."""
    rows = []
    no_action_score = None
    for label, result in results.items():
        statuses = risk_threshold_table(result.metrics, limits)["Severity"]
        score = int(statuses.map(SEVERITY_POINTS).sum())
        if label == "No Action":
            no_action_score = score
        rows.append({"Strategy": label, "Prototype Risk Severity Score": score})
    if no_action_score is None:
        raise ValueError("results must include a 'No Action' strategy")
    for row in rows:
        row["Severity Score Improvement vs No Action"] = no_action_score - row["Prototype Risk Severity Score"]
    return pd.DataFrame(rows)

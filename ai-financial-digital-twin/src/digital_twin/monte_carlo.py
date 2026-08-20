"""Efficient reproducible uncertainty simulation around the deterministic engine."""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from .scenario_engine import ScenarioEngine


def run_monte_carlo(engine: ScenarioEngine, scenario: str | dict = "combined_stress", runs: int = 1000,
                    seed: int = 42, actions: list[str] | None = None) -> pd.DataFrame:
    if runs not in {100, 500, 1000}:
        raise ValueError("runs must be one of 100, 500, or 1000")
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for run in range(runs):
        overrides = {
            "fx": {"USD": float(np.clip(rng.normal(-.10, .025), -.20, -.02))},
            "volatility_multiplier": float(np.clip(rng.lognormal(np.log(2.0), .15), 1.0, 3.5)),
            "withdrawal_rates": {
                "Retail": float(np.clip(rng.normal(.08, .015), 0, .2)),
                "SME": float(np.clip(rng.normal(.12, .025), 0, .3)),
                "Corporate": float(np.clip(rng.normal(.20, .04), 0, .4)),
            },
            "operational": {"recovery_time_hours": float(np.clip(rng.gamma(4.0, 1.0), .5, 12.0))},
            "credit": {"default_loss_multiplier": float(np.clip(rng.normal(1.0, .15), .5, 1.5))},
        }
        result = engine.run(scenario, actions=actions, overrides=overrides)
        m = result.metrics
        rows.append({"run": run + 1, "total_loss_bn": m["total_estimated_loss_bn"],
                     "lowest_cash_bn": m["cash_position_bn"], "lcr": m["lcr"],
                     "cet1_ratio": m["cet1_ratio"], "payment_backlog_bn": m["payment_backlog_bn"],
                     "payment_availability": m["payment_availability"],
                     "recovery_time_hours": m["recovery_time_hours"],
                     "customers_affected": m["customers_affected"], "risk_limit_breach": bool(result.risk_limit_breaches)})
    return pd.DataFrame(rows)


def summarize_monte_carlo(results: pd.DataFrame) -> pd.DataFrame:
    numeric = [c for c in results.columns if c not in {"run", "risk_limit_breach"}]
    rows = [{"metric": c, "mean": results[c].mean(), "median": results[c].median(),
             "p05": results[c].quantile(.05), "p95": results[c].quantile(.95)} for c in numeric]
    summary = pd.DataFrame(rows)
    summary.attrs["probability_risk_limit_breach"] = float(results["risk_limit_breach"].mean())
    return summary


def metric_percentiles(results: pd.DataFrame) -> pd.DataFrame:
    """Return decision-oriented P5/median/P95 ranges for major outcome metrics."""
    metrics = [
        "total_loss_bn", "lowest_cash_bn", "lcr", "cet1_ratio",
        "payment_availability", "payment_backlog_bn", "recovery_time_hours", "customers_affected",
    ]
    return pd.DataFrame([{
        "Risk Metric": metric,
        "P5": float(results[metric].quantile(.05)),
        "Median": float(results[metric].median()),
        "P95": float(results[metric].quantile(.95)),
    } for metric in metrics])


def breach_probability_table(results: pd.DataFrame, risk_limits: dict[str, Any]) -> pd.DataFrame:
    """Calculate separate empirical breach probabilities without changing assumptions."""
    lcr = risk_limits["lcr"]
    cet1 = risk_limits["cet1_ratio"]
    availability = risk_limits["payment_availability"]
    loss = risk_limits["total_estimated_loss_bn"]
    recovery = risk_limits["recovery_time_hours"]
    definitions = [
        ("LCR warning", "lcr", "<", float(lcr["warning"]), "warning"),
        ("LCR critical", "lcr", "<", float(lcr["critical"]), "critical"),
        ("Negative cash", "lowest_cash_bn", "<", 0.0, "critical"),
        ("CET1 warning", "cet1_ratio", "<", float(cet1["warning"]), "warning"),
        ("CET1 critical", "cet1_ratio", "<", float(cet1["critical"]), "critical"),
        ("Payment availability warning", "payment_availability", "<", float(availability["warning"]), "warning"),
        ("Payment availability critical", "payment_availability", "<", float(availability["critical"]), "critical"),
        ("Severe total loss", "total_loss_bn", ">", float(loss["critical"]), "severe"),
        ("Recovery-time threshold", "recovery_time_hours", ">", float(recovery["warning"]), "warning"),
    ]
    rows = []
    for label, column, operator, threshold, severity in definitions:
        breached = results[column] < threshold if operator == "<" else results[column] > threshold
        probability = float(breached.mean())
        rows.append({
            "Risk Metric": label, "Threshold": f"{operator} {threshold:g}",
            "Probability of Breach": probability, "Severity": severity,
            "Breach Count": int(breached.sum()), "Simulation Runs": int(len(results)),
        })
    return pd.DataFrame(rows)


def explain_probability_extremes(results: pd.DataFrame, breach_table: pd.DataFrame) -> pd.DataFrame:
    """Diagnose 0%/100% results from observed ranges, without retuning distributions."""
    column_map = {
        "LCR warning": "lcr", "LCR critical": "lcr", "Negative cash": "lowest_cash_bn",
        "CET1 warning": "cet1_ratio", "CET1 critical": "cet1_ratio",
        "Payment availability warning": "payment_availability",
        "Payment availability critical": "payment_availability", "Severe total loss": "total_loss_bn",
        "Recovery-time threshold": "recovery_time_hours",
    }
    rows = []
    for record in breach_table.to_dict("records"):
        probability = record["Probability of Breach"]
        if probability not in {0.0, 1.0}:
            continue
        column = column_map[record["Risk Metric"]]
        unique = int(results[column].nunique())
        cause = "metric is deterministic across runs" if unique == 1 else (
            "threshold is exceeded by every sampled outcome" if probability == 1.0
            else "threshold is not exceeded by any sampled outcome")
        rows.append({
            "Risk Metric": record["Risk Metric"], "Probability of Breach": probability,
            "Observed Minimum": float(results[column].min()), "Observed Maximum": float(results[column].max()),
            "Unique Outcomes": unique, "Explanation": cause,
        })
    return pd.DataFrame(rows)


def operational_breach_diagnostics(results: pd.DataFrame, risk_limits: dict[str, Any]) -> pd.DataFrame:
    """Explain operational breach outcomes from observed simulations without retuning them."""
    definitions = [
        ("Payment availability warning", "payment_availability", "<",
         float(risk_limits["payment_availability"]["warning"]),
         "Sampled recovery duration; fixed outage start, backup delay and backup capacity"),
        ("Payment availability critical", "payment_availability", "<",
         float(risk_limits["payment_availability"]["critical"]),
         "Sampled recovery duration; fixed outage start, backup delay and backup capacity"),
        ("Recovery-time threshold", "recovery_time_hours", ">",
         float(risk_limits["recovery_time_hours"]["warning"]),
         "Sampled recovery duration plus simulated backlog-clearance time"),
    ]
    rows = []
    for metric, column, operator, threshold, driver in definitions:
        series = results[column]
        breached = series < threshold if operator == "<" else series > threshold
        probability = float(breached.mean())
        stochastic = int(series.nunique()) > 1
        if probability == 1.0:
            classification = ("B. Correct because stochastic range never crosses threshold" if stochastic
                              else "A. Correct because scenario deterministically guarantees breach")
        elif not stochastic:
            classification = "C. Monte Carlo variable is not actually connected to metric"
        else:
            classification = "Observed stochastic breach probability"
        rows.append({
            "Metric": metric, "Threshold": f"{operator} {threshold:g}",
            "Min": float(series.min()), "P5": float(series.quantile(.05)),
            "Median": float(series.median()), "P95": float(series.quantile(.95)),
            "Max": float(series.max()), "Breach Probability": probability,
            "Primary Driver": driver, "Deterministic or Stochastic?": "Stochastic" if stochastic else "Deterministic",
            "Unique Outcomes": int(series.nunique()), "Classification": classification,
        })
    return pd.DataFrame(rows)

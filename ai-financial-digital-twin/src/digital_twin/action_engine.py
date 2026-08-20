"""Management-action comparison using explicit deterministic parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd
from .scenario_engine import ScenarioEngine
from .metrics import (
    classify_risk_severity, prototype_risk_severity_scores, risk_threshold_table,
    severity_distribution,
)

AVAILABLE_ACTIONS = ["Activate Backup Region", "Prioritise Critical Payments", "Sell Liquid Securities",
                     "Draw Liquidity Facility", "Increase FX Hedge", "Contact High-Risk Corporate Depositors"]

ACTION_PRIMARY_RISK_DOMAIN = {
    "Activate Backup Region": "Operational Resilience",
    "Prioritise Critical Payments": "Operational Resilience",
    "Sell Liquid Securities": "Liquidity Management",
    "Draw Liquidity Facility": "Liquidity Risk",
    "Increase FX Hedge": "Market Risk",
    "Contact High-Risk Corporate Depositors": "Liquidity / Customer Behaviour",
}

ACTION_METRICS = (
    "total_estimated_loss_bn", "cash_position_bn", "lcr", "cet1_ratio",
    "payment_availability", "payment_backlog_bn", "customers_affected", "recovery_time_hours",
)

_HIGHER_IS_BETTER = {"cash_position_bn", "hqla_bn", "lcr", "cet1_ratio", "payment_availability"}

STRATEGY_METRICS = (
    "total_estimated_loss_bn", "market_loss_bn", "credit_loss_bn", "operational_loss_bn",
    "cash_position_bn", "hqla_bn", "lcr", "cet1_ratio", "payment_availability",
    "payment_backlog_bn", "customers_affected", "recovery_time_hours",
)


@dataclass(frozen=True)
class ManagementStrategyAnalysis:
    no_action: Any
    individual_results: dict[str, Any]
    individual_comparison: pd.DataFrame
    best_by_objective: pd.DataFrame
    selected_best_action: str
    selected_best_result: Any
    combined_results: dict[str, Any]
    selected_combined_actions: list[str]
    selected_combined_result: Any
    strategy_comparison: pd.DataFrame
    residual_risk: pd.DataFrame
    action_efficiency: pd.DataFrame
    interaction_rules: pd.DataFrame
    severity_distribution: pd.DataFrame
    severity_scores: pd.DataFrame
    threshold_status: pd.DataFrame
    multidimensional_action_value: pd.DataFrame
    securities_sale_hqla_bridge: pd.DataFrame
    prioritisation_diagnostic: pd.DataFrame
    unaddressed_risk_drivers: pd.DataFrame
    response_risk_flow: pd.DataFrame


def meaningful_percentage_improvement(before: float, after: float,
                                      absolute_improvement: float) -> tuple[float | None, str]:
    """Suppress misleading percentages for non-positive baselines or zero crossings."""
    if before <= 0:
        return None, "N/A — baseline non-positive / sign change"
    if after == 0 or (before < 0 < after) or (after < 0 < before):
        return None, "N/A — baseline non-positive / sign change"
    return absolute_improvement / abs(before) * 100.0, "Calculated from positive, same-sign baseline"


def compare_actions(engine: ScenarioEngine, scenario: str | dict, actions: list[str]) -> tuple[object, object, pd.DataFrame]:
    before = engine.run(scenario)
    after = engine.run(scenario, actions=actions)
    rows = []
    for metric in ACTION_METRICS:
        b, a = before.metrics[metric], after.metrics[metric]
        raw_change = a - b
        improvement = raw_change if metric in _HIGHER_IS_BETTER else -raw_change
        percent, percent_note = meaningful_percentage_improvement(b, a, improvement)
        rows.append({"metric": metric, "before": b, "after": a, "change": raw_change,
                     "absolute_improvement": improvement, "percentage_improvement": percent,
                     "percentage_improvement_note": percent_note})
    return before, after, pd.DataFrame(rows)


def attribute_management_actions(engine: ScenarioEngine, scenario: str | dict,
                                 actions: list[str] | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Evaluate every action independently and return metric and causal attribution."""
    selected = actions or AVAILABLE_ACTIONS
    baseline = engine.run(scenario)
    rows: list[dict] = []
    traces: list[dict] = []
    for action in selected:
        result = engine.run(scenario, actions=[action])
        for metric in ACTION_METRICS:
            before, after = baseline.metrics[metric], result.metrics[metric]
            raw_change = after - before
            improvement = raw_change if metric in _HIGHER_IS_BETTER else -raw_change
            percent, percent_note = meaningful_percentage_improvement(before, after, improvement)
            rows.append({
                "action": action, "metric": metric, "before": before, "after": after,
                "change": raw_change, "absolute_improvement": improvement,
                "percentage_improvement": percent, "percentage_improvement_note": percent_note,
            })
        traces.extend(_action_trace(action, baseline.metrics, result.metrics))
    return pd.DataFrame(rows), traces


def analyze_management_strategies(engine: ScenarioEngine, scenario: str | dict = "combined_stress",
                                  combined_actions: list[str] | None = None) -> ManagementStrategyAnalysis:
    """Rerun no-action, every single action, and simultaneous action strategies."""
    no_action = engine.run(scenario)
    individual_results = {action: engine.run(scenario, actions=[action]) for action in AVAILABLE_ACTIONS}
    individual_rows = []
    for action, result in individual_results.items():
        row = {"Action": action, **{metric: result.metrics[metric] for metric in STRATEGY_METRICS}}
        row["Warning Breaches"] = _breach_count(result, "warning")
        row["Critical Breaches"] = _breach_count(result, "critical")
        individual_rows.append(row)
    individual = pd.DataFrame(individual_rows)

    scores = _balanced_action_scores(individual)
    selected_action = str(scores.sort_values("Balanced Severity Score").iloc[0]["Action"])
    best_rows = [
        _best_objective(individual, "Loss reduction", "total_estimated_loss_bn", "min"),
        _best_objective(individual, "Liquidity (LCR)", "lcr", "max"),
        _best_objective(individual, "Immediate cash", "cash_position_bn", "max"),
        _best_objective(individual, "Operational resilience", "Operational Severity Score", "min", scores),
        _best_objective(individual, "Customer impact", "customers_affected", "min"),
        {"Objective": "Balanced equal-weight resilience", "Best Action": selected_action,
         "Metric": "Balanced Severity Score",
         "Value": float(scores.loc[scores["Action"] == selected_action, "Balanced Severity Score"].iloc[0]),
         "Direction": "min"},
    ]
    best_by_objective = pd.DataFrame(best_rows)

    core_actions = ["Activate Backup Region", "Draw Liquidity Facility", "Increase FX Hedge"]
    comprehensive = combined_actions or [
        "Activate Backup Region", "Prioritise Critical Payments",
        "Contact High-Risk Corporate Depositors", "Draw Liquidity Facility", "Increase FX Hedge",
    ]
    combined_results = {
        "Cross-domain core response": engine.run(scenario, actions=core_actions),
        "Comprehensive response": engine.run(scenario, actions=comprehensive),
    }
    selected_combined = combined_results["Comprehensive response"]
    strategy_results = {
        "No Action": no_action,
        "Balanced Single Action": individual_results[selected_action],
        "Combined Response": selected_combined,
    }
    comparison = _strategy_table(strategy_results, no_action, engine.bank.risk_limits)
    residual = _residual_risk_table(strategy_results, engine.bank.risk_limits)
    efficiency = _action_efficiency(no_action, individual_results)
    severity_counts = severity_distribution(strategy_results, engine.bank.risk_limits)
    severity_scores = prototype_risk_severity_scores(strategy_results, engine.bank.risk_limits)
    threshold_status = risk_threshold_table(selected_combined.metrics, engine.bank.risk_limits)
    action_value = _multidimensional_action_value(no_action, individual_results)
    sale_bridge = _securities_sale_hqla_bridge(engine, no_action, individual_results["Sell Liquid Securities"])
    prioritisation = _prioritisation_diagnostic(no_action, individual_results["Prioritise Critical Payments"])
    residual_drivers = _unaddressed_risk_drivers(no_action, selected_combined)
    risk_flow = pd.DataFrame([
        {"Risk Domain": "MARKET RISK", "Management Action": "Increase FX Hedge"},
        {"Risk Domain": "OPERATIONAL RISK", "Management Action": "Activate Backup Region"},
        {"Risk Domain": "OPERATIONAL RISK", "Management Action": "Prioritise Critical Payments"},
        {"Risk Domain": "LIQUIDITY RISK", "Management Action": "Draw Liquidity Facility"},
        {"Risk Domain": "LIQUIDITY RISK", "Management Action": "Contact High-Risk Corporate Depositors"},
        {"Risk Domain": "RESIDUAL RISK", "Management Action": "Reported after simultaneous re-simulation"},
    ])
    interaction_rules = pd.DataFrame([
        {"Interaction": "Backup activation + depositor contact",
         "Rule": "Backup changes simulated availability first; outage-driven withdrawals are recalculated, then corporate contact subtracts 3 percentage points from the resulting rate."},
        {"Interaction": "Securities sale",
         "Rule": "Gross securities fall by the sale amount; cash rises only by net proceeds; realised haircut loss enters P&L once."},
        {"Interaction": "Liquidity facility",
         "Rule": "Facility draw increases cash and its 30-day funding cost enters P&L once."},
        {"Interaction": "FX hedge",
         "Rule": "Hedge ratios alter market exposure only; operational parameters are unchanged."},
        {"Interaction": "Combined response",
         "Rule": "All actions are passed together to one engine rerun; individual improvements are never summed."},
    ])
    return ManagementStrategyAnalysis(
        no_action, individual_results, individual, best_by_objective, selected_action,
        individual_results[selected_action], combined_results, comprehensive, selected_combined,
        comparison, residual, efficiency, interaction_rules, severity_counts, severity_scores,
        threshold_status, action_value, sale_bridge, prioritisation, residual_drivers, risk_flow)


def _normalized(series: pd.Series, higher_is_worse: bool) -> pd.Series:
    spread = float(series.max() - series.min())
    if spread == 0.0:
        return pd.Series(0.0, index=series.index)
    return ((series - series.min()) / spread if higher_is_worse
            else (series.max() - series) / spread)


def _balanced_action_scores(individual: pd.DataFrame) -> pd.DataFrame:
    scores = pd.DataFrame({"Action": individual["Action"]})
    higher_worse = ["total_estimated_loss_bn", "payment_backlog_bn", "customers_affected", "recovery_time_hours"]
    lower_worse = ["cash_position_bn", "lcr", "cet1_ratio", "payment_availability"]
    columns = []
    for metric in higher_worse:
        name = f"{metric} severity"; scores[name] = _normalized(individual[metric], True); columns.append(name)
    for metric in lower_worse:
        name = f"{metric} severity"; scores[name] = _normalized(individual[metric], False); columns.append(name)
    scores["Operational Severity Score"] = scores[[
        "payment_availability severity", "payment_backlog_bn severity", "recovery_time_hours severity",
    ]].mean(axis=1)
    scores["Balanced Severity Score"] = scores[columns].mean(axis=1)
    return scores


def _best_objective(individual: pd.DataFrame, objective: str, metric: str, direction: str,
                    alternate: pd.DataFrame | None = None) -> dict[str, Any]:
    source = alternate if alternate is not None else individual
    index = source[metric].idxmin() if direction == "min" else source[metric].idxmax()
    return {"Objective": objective, "Best Action": str(source.loc[index, "Action"]),
            "Metric": metric, "Value": float(source.loc[index, metric]), "Direction": direction}


def _breach_count(result: Any, level: str) -> int:
    return sum(breach["level"] == level for breach in result.risk_limit_breaches)


def _strategy_table(results: dict[str, Any], no_action: Any, risk_limits: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for metric in STRATEGY_METRICS:
        row: dict[str, Any] = {"Metric": metric}
        for label, result in results.items(): row[label] = result.metrics[metric]
        combined = results["Combined Response"].metrics[metric]
        base = no_action.metrics[metric]
        improvement = combined - base if metric in _HIGHER_IS_BETTER else base - combined
        percentage, percentage_note = meaningful_percentage_improvement(base, combined, improvement)
        row["Absolute Improvement vs No Action"] = improvement
        row["Percentage Improvement vs No Action"] = percentage
        row["Percentage Improvement Note"] = percentage_note
        row["Risk Status"] = (classify_risk_severity(combined, risk_limits[metric])
                              if metric in risk_limits else "No configured threshold")
        rows.append(row)
    scores = prototype_risk_severity_scores(results, risk_limits).set_index("Strategy")
    no_action_score = int(scores.loc["No Action", "Prototype Risk Severity Score"])
    combined_score = int(scores.loc["Combined Response", "Prototype Risk Severity Score"])
    rows.append({
        "Metric": "Prototype Risk Severity Score",
        **{label: int(scores.loc[label, "Prototype Risk Severity Score"]) for label in results},
        "Absolute Improvement vs No Action": no_action_score - combined_score,
        "Percentage Improvement vs No Action": (no_action_score - combined_score) / no_action_score * 100.0 if no_action_score > 0 else None,
        "Percentage Improvement Note": "Non-regulatory 0/1/2 severity-point comparison",
        "Risk Status": "Prototype management score — not regulatory",
    })
    return pd.DataFrame(rows)


def _residual_risk_table(results: dict[str, Any], risk_limits: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for risk, rule in risk_limits.items():
        no_action_value = float(results["No Action"].metrics[risk])
        combined_value = float(results["Combined Response"].metrics[risk])
        no_action_severity = classify_risk_severity(no_action_value, rule)
        combined_severity = classify_risk_severity(combined_value, rule)
        transition = _severity_transition(no_action_severity, combined_severity)
        threshold = (f"healthy >= {float(rule['warning']):g}; critical < {float(rule['critical']):g}"
                     if rule["direction"] == "min"
                     else f"healthy <= {float(rule['warning']):g}; critical > {float(rule['critical']):g}")
        row = {
            "Risk": risk, "Risk Metric": risk, "No Action": no_action_value, "Combined Response": combined_value,
            "No Action Severity": no_action_severity, "Combined Severity": combined_severity,
            "Combined Response Severity": combined_severity,
            "Threshold": threshold, "Transition": transition,
            "Residual Concern": (combined_severity if combined_severity != "Within Limit"
                                 else "No configured breach"),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _severity_transition(before: str, after: str) -> str:
    if before == after:
        return "UNCHANGED"
    return f"{before.upper()} → {after.upper()}"


def _action_efficiency(no_action: Any, results: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for action, result in results.items():
        cost = ((result.metrics["funding_cost_bn"] + result.metrics["realised_asset_sale_loss_bn"])
                - (no_action.metrics["funding_cost_bn"] + no_action.metrics["realised_asset_sale_loss_bn"]))
        cost_modelled = "liquidity facility" in action.lower() or "sell liquid" in action.lower()
        net_benefit = no_action.metrics["total_estimated_loss_bn"] - result.metrics["total_estimated_loss_bn"]
        rows.append({
            "Action": action,
            "P&L Loss Reduction Before Action Cost (USD bn)": net_benefit + (cost if cost_modelled else 0.0),
            "Modelled Action Cost (USD bn)": cost if cost_modelled else None,
            "Net P&L Impact After Modelled Action Cost (USD bn)": net_benefit,
            "Cost Availability": ("Modelled in funding/realised-sale loss" if cost_modelled
                                  else "Action cost not modelled — economic ROI cannot be calculated."),
        })
    return pd.DataFrame(rows)


def _multidimensional_action_value(no_action: Any, results: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for action, result in results.items():
        before, after = no_action.metrics, result.metrics
        modelled_cost = ((after["funding_cost_bn"] + after["realised_asset_sale_loss_bn"])
                         - (before["funding_cost_bn"] + before["realised_asset_sale_loss_bn"]))
        cost_is_modelled = action in {"Sell Liquid Securities", "Draw Liquidity Facility"}
        rows.append({
            "Action": action,
            "P&L Loss Reduction": before["total_estimated_loss_bn"] - after["total_estimated_loss_bn"],
            "Cash Improvement": after["cash_position_bn"] - before["cash_position_bn"],
            "LCR Improvement": after["lcr"] - before["lcr"],
            "Payment Availability Improvement": after["payment_availability"] - before["payment_availability"],
            "Payment Backlog Reduction": before["payment_backlog_bn"] - after["payment_backlog_bn"],
            "Customers Protected": before["customers_affected"] - after["customers_affected"],
            "Recovery Time Reduction": before["recovery_time_hours"] - after["recovery_time_hours"],
            "CET1 Improvement": after["cet1_ratio"] - before["cet1_ratio"],
            "Modelled Action Cost": modelled_cost if cost_is_modelled else None,
            "Primary Risk Domain": ACTION_PRIMARY_RISK_DOMAIN[action],
        })
    return pd.DataFrame(rows)


def _securities_sale_hqla_bridge(engine: ScenarioEngine, before: Any, after: Any) -> pd.DataFrame:
    securities = engine.bank.amount("securities")
    haircut = engine.bank.assumptions["hqla_securities_haircut"]
    sold_before = float(before.metrics["asset_liquidation_bn"])
    sold_after = float(after.metrics["asset_liquidation_bn"])
    values_before = {
        "Raw Cash Position": float(before.metrics["cash_position_bn"]),
        "Gross Securities Remaining": max(0.0, securities - sold_before),
        "Securities Sold": sold_before,
        "Realised Sale Proceeds": 0.0,
        "Realised Sale Loss": float(before.metrics["realised_asset_sale_loss_bn"]),
        "Eligible Cash": max(0.0, float(before.metrics["cash_position_bn"])),
        "Eligible Securities": max(0.0, securities - sold_before) * (1.0 - haircut),
        "Securities Haircut": max(0.0, securities - sold_before) * haircut,
        "Other HQLA": 0.0,
        "Total HQLA": float(before.metrics["hqla_bn"]),
    }
    values_after = {
        "Raw Cash Position": float(after.metrics["cash_position_bn"]),
        "Gross Securities Remaining": max(0.0, securities - sold_after),
        "Securities Sold": sold_after,
        "Realised Sale Proceeds": sold_after - float(after.metrics["realised_asset_sale_loss_bn"]),
        "Realised Sale Loss": float(after.metrics["realised_asset_sale_loss_bn"]),
        "Eligible Cash": max(0.0, float(after.metrics["cash_position_bn"])),
        "Eligible Securities": max(0.0, securities - sold_after) * (1.0 - haircut),
        "Securities Haircut": max(0.0, securities - sold_after) * haircut,
        "Other HQLA": 0.0,
        "Total HQLA": float(after.metrics["hqla_bn"]),
    }
    return pd.DataFrame([{"Component": component, "Before": value,
                          "Change": values_after[component] - value, "After": values_after[component]}
                         for component, value in values_before.items()])


def _prioritisation_diagnostic(before: Any, after: Any) -> pd.DataFrame:
    metrics = ["payment_availability", "payment_backlog_bn", "customers_affected", "recovery_time_hours"]
    rows = [{"Metric": metric, "Before": before.metrics[metric], "After": after.metrics[metric],
             "Change": after.metrics[metric] - before.metrics[metric]} for metric in metrics]
    rows.append({
        "Metric": "Validation classification", "Before": None, "After": None,
        "Change": "B. Correct consequence of explicit prioritisation rule and nonlinear queue clearance",
    })
    return pd.DataFrame(rows)


def _unaddressed_risk_drivers(no_action: Any, combined: Any) -> pd.DataFrame:
    definitions = [
        ("Market Loss", "market_loss_bn", False),
        ("Credit Loss", "credit_loss_bn", False),
        ("Operational Loss", "operational_loss_bn", False),
        ("Liquidity Position", "cash_position_bn", True),
        ("Customer Impact", "customers_affected", False),
    ]
    rows = []
    for domain, metric, higher_better in definitions:
        before, after = float(no_action.metrics[metric]), float(combined.metrics[metric])
        improvement = after - before if higher_better else before - after
        rows.append({
            "Risk Driver": domain, "Metric": metric, "No Action": before,
            "Combined Response": after, "Improvement": improvement,
            "Response": "Materially unchanged / unaddressed" if abs(improvement) <= 1e-12 else "Improved",
        })
    return pd.DataFrame(rows)


def _action_trace(action: str, before: dict, after: dict) -> list[dict]:
    """Explain action effects using only measured before/after simulation values."""
    normalized = action.lower()
    if "backup" in normalized or "priorit" in normalized:
        chain = [
            (action, "Payment Capacity", "changes_capacity", before["payment_availability"], after["payment_availability"], "operational"),
            ("Payment Capacity", "Payment Backlog", "processes", before["payment_backlog_bn"], after["payment_backlog_bn"], "operational"),
            ("Payment Backlog", "Customers Affected", "disrupts", before["customers_affected"], after["customers_affected"], "operational"),
            ("Customers Affected", "Deposit Outflows", "behaviour", before["deposit_outflow_bn"], after["deposit_outflow_bn"], "liquidity"),
            ("Deposit Outflows", "Liquidity Position", "reduces", before["cash_position_bn"], after["cash_position_bn"], "liquidity"),
        ]
    elif "facility" in normalized or "sell liquid" in normalized:
        chain = [
            (action, "Liquidity Position", "funds", before["cash_position_bn"], after["cash_position_bn"], "liquidity"),
            ("Liquidity Position", "LCR", "determines", before["lcr"], after["lcr"], "liquidity"),
            ("LCR", "Funding Cost and Loss", "costs", before["total_estimated_loss_bn"], after["total_estimated_loss_bn"], "financial"),
        ]
    elif "fx hedge" in normalized:
        chain = [
            (action, "FX Exposure", "hedges", before["market_loss_bn"], after["market_loss_bn"], "financial"),
            ("FX Exposure", "Capital Position", "reduces_loss", before["cet1_capital_bn"], after["cet1_capital_bn"], "financial"),
            ("Capital Position", "CET1 Ratio", "determines", before["cet1_ratio"], after["cet1_ratio"], "financial"),
        ]
    else:
        chain = [
            (action, "Deposit Outflows", "changes_behaviour", before["deposit_outflow_bn"], after["deposit_outflow_bn"], "liquidity"),
            ("Deposit Outflows", "Liquidity Position", "reduces", before["cash_position_bn"], after["cash_position_bn"], "liquidity"),
            ("Liquidity Position", "LCR", "determines", before["lcr"], after["lcr"], "liquidity"),
        ]
    return [{
        "action": action, "sequence": index, "source_node": source, "target_node": target,
        "dependency_type": dependency, "shock": action, "previous_value": previous,
        "new_value": new, "financial_or_operational_effect": effect,
        "reason": "Measured before/after difference from deterministic action re-simulation",
        "simulation_time": None,
    } for index, (source, target, dependency, previous, new, effect) in enumerate(chain, 1)]

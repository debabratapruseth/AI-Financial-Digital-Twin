"""Optional LLM narrative over validated simulation output only."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from .dependency_graph import top_propagation_paths


def validated_payload(result: Any) -> dict[str, Any]:
    payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    required = {"scenario", "metrics", "risk_limit_breaches"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(f"Simulation output missing fields: {sorted(missing)}")
    json.dumps(payload, allow_nan=False)
    return payload


def deterministic_summary(result: Any) -> str:
    data = validated_payload(result)
    m = data["metrics"]
    drivers = sorted((("market", m["market_loss_bn"]), ("credit", m["credit_loss_bn"]),
                      ("operational", m["operational_loss_bn"])), key=lambda x: x[1], reverse=True)
    breach_text = ", ".join(f"{b['metric']} ({b['level']})" for b in data["risk_limit_breaches"]) or "none"
    return (f"{data['scenario']}: estimated loss is ${m['total_estimated_loss_bn']:.3f}bn. "
            f"Prototype LCR is {m['lcr']:.2f}, CET1 ratio is {m['cet1_ratio']:.1%}, and payment availability is {m['payment_availability']:.1%}. "
            f"The largest quantified driver is {drivers[0][0]} loss (${drivers[0][1]:.3f}bn). "
            f"Recorded risk-limit breaches: {breach_text}. All figures come from the deterministic simulation.")


def explain_results(result: Any, question: str | None = None, model: str | None = None) -> str:
    full_payload = validated_payload(result)
    if not os.getenv("OPENAI_API_KEY"):
        return deterministic_summary(full_payload)
    payload = compact_result_context(full_payload)
    from openai import OpenAI
    client = OpenAI()
    instruction = ("Explain only the supplied synthetic simulation output. Do not calculate new values, invent exposures, "
                   "override limits, or assert unsupported causal links. State that all ratios are prototype approximations.")
    prompt = question or "Give a CEO summary, top three drivers, causal chain, action explanation, and remaining vulnerabilities."
    request_text = f"Question: {prompt}\nValidated compact JSON:\n{json.dumps(payload)}"
    _validate_request_size(request_text)
    response = client.responses.create(model=model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=instruction, input=request_text)
    return response.output_text


def answer_question(engine: Any, result: Any, question: str, overrides: dict | None = None) -> str:
    """Rerun first when a caller supplies new numerical assumptions."""
    target = engine.run(result.scenario, overrides=overrides) if overrides else result
    return explain_results(target, question)


def build_executive_context(result: Any, monte_carlo_percentiles: pd.DataFrame,
                            breach_probabilities: pd.DataFrame,
                            management_action_comparison: pd.DataFrame,
                            material_assumptions: dict[str, Any], top_n_paths: int = 5,
                            *, lcr_bridge: pd.DataFrame | None = None,
                            operational_monte_carlo_diagnostics: pd.DataFrame | None = None,
                            management_strategy_analysis: Any | None = None) -> dict[str, Any]:
    """Build the only compact, validated payload intended for executive LLM use."""
    payload = validated_payload(result)
    metrics = payload["metrics"]
    loss_drivers = [
        {"driver": "market_loss_bn", "value": float(metrics["market_loss_bn"])},
        {"driver": "credit_loss_bn", "value": float(metrics["credit_loss_bn"])},
        {"driver": "operational_loss_bn", "value": float(metrics["operational_loss_bn"])},
        {"driver": "liquidity_pnl_loss_bn", "value": float(metrics.get("liquidity_pnl_loss_bn", 0.0))},
    ]
    loss_drivers.sort(key=lambda item: item["value"], reverse=True)
    context = {
        "scenario": payload["scenario"],
        "baseline_metrics": payload["baseline"],
        "stressed_metrics": metrics,
        "risk_breaches": payload["risk_limit_breaches"],
        "top_risk_drivers": loss_drivers,
        "top_propagation_paths": [
            {key: value for key, value in path.items() if key != "events"}
            for path in top_propagation_paths(payload.get("propagation_trace", []), top_n_paths)
        ],
        "monte_carlo_percentiles": _records(monte_carlo_percentiles),
        "breach_probabilities": _records(breach_probabilities),
        "management_action_comparison": _records(management_action_comparison),
        "material_assumptions": material_assumptions,
    }
    if lcr_bridge is not None:
        context["lcr_bridge"] = _records(lcr_bridge)
    if operational_monte_carlo_diagnostics is not None:
        context["operational_monte_carlo_diagnostics"] = _records(operational_monte_carlo_diagnostics)
    if management_strategy_analysis is not None:
        analysis = management_strategy_analysis
        context["management_strategies"] = {
            "no_action": analysis.no_action.metrics,
            "individual_actions": _records(analysis.individual_comparison),
            "best_single_actions_by_objective": _records(analysis.best_by_objective),
            "balanced_single_action_choice": analysis.selected_best_action,
            "combined_response_actions": analysis.selected_combined_actions,
            "combined_response": analysis.selected_combined_result.metrics,
            "severity_distribution": _records(analysis.severity_distribution),
            "prototype_risk_severity_scores": _records(analysis.severity_scores),
            "configured_threshold_status": _records(analysis.threshold_status),
            "multidimensional_action_value": _records(analysis.multidimensional_action_value),
            "residual_risks": _records(analysis.residual_risk),
            "unaddressed_risk_drivers": _records(analysis.unaddressed_risk_drivers),
            "action_cost_limitations": _records(analysis.action_efficiency),
            "interpretation_constraints": {
                "no_universal_best_action": True,
                "severity_score_is_non_regulatory": True,
                "economic_roi_available": False,
                "combined_response_is_single_simulation_rerun": True,
            },
        }
    json.dumps(context, allow_nan=False)
    return context


def payload_size_comparison(raw_simulation_payload: Any, executive_context: dict[str, Any]) -> dict[str, int | float]:
    raw_json = json.dumps(raw_simulation_payload, default=_json_default, allow_nan=False)
    context_json = json.dumps(executive_context, default=_json_default, allow_nan=False)
    return {
        "raw_simulation_payload_bytes": len(raw_json.encode("utf-8")),
        "executive_context_payload_bytes": len(context_json.encode("utf-8")),
        "reduction_percent": 100.0 * (1.0 - len(context_json) / max(1, len(raw_json))),
    }


def explain_executive_context(executive_context: dict[str, Any], model: str | None = None) -> str:
    """Explain validated decision context; never send raw simulation data."""
    json.dumps(executive_context, allow_nan=False)
    if not os.getenv("OPENAI_API_KEY"):
        scenario = executive_context["scenario"]
        stressed = executive_context["stressed_metrics"]
        return (f"{scenario}: total estimated loss is ${stressed['total_estimated_loss_bn']:.3f}bn, "
                f"prototype LCR is {stressed['lcr']:.2f}, and CET1 ratio is {stressed['cet1_ratio']:.1%}. "
                "Set OPENAI_API_KEY to generate the expanded decision-intelligence narrative.")
    from openai import OpenAI
    request_text = (
        "Answer: WHAT HAPPENED? WHAT WAS AFFECTED? HOW DID THE SHOCK PROPAGATE? "
        "HOW BAD COULD IT GET? WHAT SHOULD MANAGEMENT DO? Explain that no universal best action exists; distinguish "
        "objective-specific winners from the balanced choice; describe critical-to-warning/within-limit transitions, "
        "residual warnings, unaddressed drivers, and incomplete action costs. Do not claim economic ROI. "
        "Cite only supplied figures and classifications.\n"
        + json.dumps(executive_context)
    )
    _validate_request_size(request_text)
    response = OpenAI().responses.create(
        model=model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=(
            "Explain only the validated executive context. Never invent dependencies or numbers, recalculate ratios, "
            "override deterministic limits, or characterize this prototype as a regulatory model."
        ),
        input=request_text,
    )
    return response.output_text


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records"))


def compact_result_context(result: Any) -> dict[str, Any]:
    """Strip detailed records and time series from a validated scenario for Q&A."""
    payload = validated_payload(result)
    liquidity = payload.get("impacts", {}).get("liquidity_impact", {})
    context = {
        "scenario": payload["scenario"],
        "baseline_metrics": payload["baseline"],
        "stressed_metrics": payload["metrics"],
        "risk_breaches": payload["risk_limit_breaches"],
        "top_propagation_paths": [
            {key: value for key, value in path.items() if key != "events"}
            for path in top_propagation_paths(payload.get("propagation_trace", []), 5)
        ],
        "liquidity_impact": liquidity,
        "management_actions": payload.get("management_actions", []),
    }
    json.dumps(context, allow_nan=False)
    return context


def _validate_request_size(request_text: str, maximum_bytes: int = 60_000) -> None:
    """Conservative preflight guard for models with smaller context windows."""
    size = len(request_text.encode("utf-8"))
    if size > maximum_bytes:
        raise ValueError(
            f"OpenAI request payload is {size:,} bytes, above the {maximum_bytes:,}-byte safety limit. "
            "Use build_executive_context() or compact_result_context() before calling the LLM."
        )


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.DataFrame):
        return _records(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")

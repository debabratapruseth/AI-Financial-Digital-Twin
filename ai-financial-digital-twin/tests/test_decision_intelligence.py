import pandas as pd

from digital_twin.action_engine import ACTION_METRICS, attribute_management_actions
from digital_twin.ai_explainer import build_executive_context, compact_result_context, payload_size_comparison
from digital_twin.data_generator import generate_virtual_bank
from digital_twin.monte_carlo import breach_probability_table, metric_percentiles, run_monte_carlo
from digital_twin.scenario_engine import ScenarioEngine


def test_per_metric_breach_probabilities():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    results = run_monte_carlo(engine, "combined_stress", runs=100, seed=42)
    table = breach_probability_table(results, engine.bank.risk_limits)
    assert len(table) == 9
    assert table["Risk Metric"].tolist() == [
        "LCR warning", "LCR critical", "Negative cash", "CET1 warning", "CET1 critical",
        "Payment availability warning", "Payment availability critical", "Severe total loss",
        "Recovery-time threshold",
    ]
    assert table["Probability of Breach"].between(0, 1).all()


def test_management_action_attribution_has_all_requested_metrics_and_trace():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    frame, trace = attribute_management_actions(engine, "combined_stress", ["Activate Backup Region"])
    assert set(frame["metric"]) == set(ACTION_METRICS)
    assert {"before", "after", "absolute_improvement", "percentage_improvement"}.issubset(frame.columns)
    assert trace and all(event["action"] == "Activate Backup Region" for event in trace)
    availability = frame.loc[frame["metric"] == "payment_availability"].iloc[0]
    assert availability["after"] > availability["before"]


def test_compact_executive_context_excludes_raw_timeseries():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    result = engine.run("combined_stress")
    mc = run_monte_carlo(engine, "combined_stress", runs=100, seed=42)
    percentiles = metric_percentiles(mc)
    probabilities = breach_probability_table(mc, engine.bank.risk_limits)
    actions, _ = attribute_management_actions(engine, "combined_stress", ["Activate Backup Region"])
    context = build_executive_context(result, percentiles, probabilities, actions,
                                      {"prototype": True, "units": "USD billions"})
    assert set(context) == {"scenario", "baseline_metrics", "stressed_metrics", "risk_breaches",
                            "top_risk_drivers", "top_propagation_paths", "monte_carlo_percentiles",
                            "breach_probabilities", "management_action_comparison", "material_assumptions"}
    assert "operational_timeseries" not in str(context)
    raw = {"scenario": result.to_dict(include_timeseries=True), "monte_carlo": mc.to_dict("records")}
    sizes = payload_size_comparison(raw, context)
    assert sizes["executive_context_payload_bytes"] < sizes["raw_simulation_payload_bytes"]


def test_interactive_question_context_is_compact():
    result = ScenarioEngine(generate_virtual_bank(seed=42)).run("combined_stress")
    compact = compact_result_context(result)
    assert set(compact) == {"scenario", "baseline_metrics", "stressed_metrics", "risk_breaches",
                            "top_propagation_paths", "liquidity_impact", "management_actions"}
    assert "market_detail" not in str(compact)
    assert "credit_detail" not in str(compact)

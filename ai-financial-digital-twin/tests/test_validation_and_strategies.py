import pandas as pd
import pytest

from digital_twin.action_engine import (
    AVAILABLE_ACTIONS, analyze_management_strategies, meaningful_percentage_improvement,
)
from digital_twin.data_generator import generate_virtual_bank
from digital_twin.metrics import classify_risk_severity
from digital_twin.monte_carlo import operational_breach_diagnostics, run_monte_carlo
from digital_twin.scenario_engine import ScenarioEngine


@pytest.fixture(scope="module")
def engine():
    return ScenarioEngine(generate_virtual_bank(seed=42))


def test_lcr_numerator_denominator_and_bridge_reconcile(engine):
    result = engine.run("combined_stress")
    bridge = pd.DataFrame(result.impacts["lcr_bridge"]).set_index("Component")
    hqla = bridge.loc["Total eligible HQLA", "Stressed"]
    net_outflow = bridge.loc["Net stressed 30-day cash outflow", "Stressed"]
    assert hqla == pytest.approx(result.metrics["hqla_bn"])
    assert net_outflow > 0
    assert hqla / net_outflow == pytest.approx(result.metrics["lcr"])
    assert pd.DataFrame(result.impacts["lcr_validation_checks"])["Passed"].all()


def test_liquidity_stock_and_flow_are_not_counted_as_pnl(engine):
    result = engine.run("combined_stress")
    metrics = result.metrics
    assert metrics["deposit_outflow_bn"] == pytest.approx(10.223333333333334)
    assert metrics["hqla_consumed_bn"] == pytest.approx(
        result.baseline["hqla_bn"] - metrics["hqla_bn"])
    assert metrics["total_estimated_loss_bn"] == pytest.approx(
        metrics["market_loss_bn"] + metrics["credit_loss_bn"]
        + metrics["operational_loss_bn"] + metrics["liquidity_pnl_loss_bn"])
    assert metrics["deposit_outflow_bn"] not in [metrics["total_estimated_loss_bn"]]


def test_operational_random_variable_propagates_to_both_metrics(engine):
    results = run_monte_carlo(engine, "combined_stress", runs=100, seed=42)
    assert results["payment_availability"].nunique() > 1
    assert results["recovery_time_hours"].nunique() > 1
    assert results[["payment_availability", "recovery_time_hours"]].corr().iloc[0, 1] < -0.9
    diagnostics = operational_breach_diagnostics(results, engine.bank.risk_limits)
    assert (diagnostics["Breach Probability"] == 1.0).all()
    assert diagnostics["Classification"].str.startswith("B.").all()


def test_no_action_and_every_single_action_are_real_reruns(engine):
    analysis = analyze_management_strategies(engine)
    control = engine.run("combined_stress")
    assert analysis.no_action.metrics == control.metrics
    assert set(analysis.individual_results) == set(AVAILABLE_ACTIONS)
    for action, result in analysis.individual_results.items():
        assert result.management_actions == [action]


def test_multiple_actions_are_simulated_together_not_summed(engine):
    actions = ["Activate Backup Region", "Draw Liquidity Facility", "Increase FX Hedge"]
    analysis = analyze_management_strategies(engine)
    simultaneous = analysis.combined_results["Cross-domain core response"]
    direct = engine.run("combined_stress", actions=actions)
    assert simultaneous.metrics == direct.metrics
    independent_loss_improvements = sum(
        analysis.no_action.metrics["total_estimated_loss_bn"]
        - analysis.individual_results[action].metrics["total_estimated_loss_bn"]
        for action in actions
    )
    simultaneous_improvement = (
        analysis.no_action.metrics["total_estimated_loss_bn"]
        - simultaneous.metrics["total_estimated_loss_bn"]
    )
    assert simultaneous_improvement != pytest.approx(independent_loss_improvements)


def test_action_interactions_and_residual_risk_are_explicit(engine):
    analysis = analyze_management_strategies(engine)
    combined = analysis.selected_combined_result
    contact_only = analysis.individual_results["Contact High-Risk Corporate Depositors"]
    backup_only = analysis.individual_results["Activate Backup Region"]
    assert combined.metrics["deposit_outflow_bn"] < contact_only.metrics["deposit_outflow_bn"]
    assert combined.metrics["deposit_outflow_bn"] < backup_only.metrics["deposit_outflow_bn"]
    assert set(analysis.residual_risk["Risk"]) == set(engine.bank.risk_limits)
    assert "Combined Response Severity" in analysis.residual_risk
    assert not analysis.interaction_rules.empty


def test_risk_severity_is_mutually_exclusive_and_scores_reconcile(engine):
    analysis = analyze_management_strategies(engine)
    distribution = analysis.severity_distribution.set_index("Severity")
    assert distribution["No Action"].sum() == len(engine.bank.risk_limits)
    assert distribution["Combined Response"].sum() == len(engine.bank.risk_limits)
    scores = analysis.severity_scores.set_index("Strategy")
    assert scores.loc["No Action", "Prototype Risk Severity Score"] == 7
    assert scores.loc["Combined Response", "Prototype Risk Severity Score"] == 2
    assert scores.loc["Combined Response", "Severity Score Improvement vs No Action"] == 5
    assert classify_risk_severity(1.0, {"direction": "min", "warning": 1.1, "critical": .9}) == "Warning"


def test_threshold_table_uses_bank_configuration(engine):
    analysis = analyze_management_strategies(engine)
    table = analysis.threshold_status.set_index("Metric")
    for metric, rule in engine.bank.risk_limits.items():
        assert table.loc[metric, "Warning Threshold"] == pytest.approx(rule["warning"])
        assert table.loc[metric, "Critical Threshold"] == pytest.approx(rule["critical"])


def test_percentage_improvement_suppression_and_valid_calculation():
    assert meaningful_percentage_improvement(-.25, 3.75, 4.0)[0] is None
    assert meaningful_percentage_improvement(2.0, -1.0, -3.0)[0] is None
    percent, note = meaningful_percentage_improvement(10.0, 12.0, 2.0)
    assert percent == pytest.approx(20.0)
    assert "positive" in note


def test_action_value_terminology_domains_and_objective_winners_are_calculated(engine):
    analysis = analyze_management_strategies(engine)
    assert "P&L Loss Reduction Before Action Cost (USD bn)" in analysis.action_efficiency
    assert "Net P&L Impact After Modelled Action Cost (USD bn)" in analysis.action_efficiency
    assert not any("Benefit before" in column for column in analysis.action_efficiency)
    assert set(analysis.multidimensional_action_value["Action"]) == set(AVAILABLE_ACTIONS)
    assert analysis.multidimensional_action_value["Primary Risk Domain"].notna().all()
    assert set(analysis.best_by_objective["Objective"]) == {
        "Loss reduction", "Liquidity (LCR)", "Immediate cash", "Operational resilience",
        "Customer impact", "Balanced equal-weight resilience",
    }
    assert analysis.selected_best_action in AVAILABLE_ACTIONS


def test_prioritisation_recovery_is_queue_driven_and_availability_unchanged(engine):
    analysis = analyze_management_strategies(engine)
    before = analysis.no_action
    prioritised = analysis.individual_results["Prioritise Critical Payments"]
    assert prioritised.metrics["payment_backlog_bn"] < before.metrics["payment_backlog_bn"]
    assert prioritised.metrics["recovery_time_hours"] < before.metrics["recovery_time_hours"]
    assert prioritised.metrics["payment_availability"] == before.metrics["payment_availability"]
    assert prioritised.metrics["customers_affected"] == before.metrics["customers_affected"]
    assert analysis.prioritisation_diagnostic.iloc[-1]["Change"].startswith("B.")


def test_sell_securities_hqla_reconciles_without_double_counting(engine):
    analysis = analyze_management_strategies(engine)
    bridge = analysis.securities_sale_hqla_bridge.set_index("Component")
    assert bridge.loc["Total HQLA", "Before"] == pytest.approx(
        bridge.loc["Eligible Cash", "Before"] + bridge.loc["Eligible Securities", "Before"])
    assert bridge.loc["Total HQLA", "After"] == pytest.approx(
        bridge.loc["Eligible Cash", "After"] + bridge.loc["Eligible Securities", "After"])
    assert bridge.loc["Eligible Securities", "Change"] == pytest.approx(-1.7)
    assert bridge.loc["Total HQLA", "Change"] == pytest.approx(0.017466666666665853)


def test_residual_transitions_and_unaddressed_credit_are_visible(engine):
    analysis = analyze_management_strategies(engine)
    residual = analysis.residual_risk.set_index("Risk Metric")
    assert residual.loc["cash_position_bn", "Transition"] == "CRITICAL → WARNING"
    assert residual.loc["recovery_time_hours", "Transition"] == "CRITICAL → WITHIN LIMIT"
    drivers = analysis.unaddressed_risk_drivers.set_index("Risk Driver")
    assert drivers.loc["Credit Loss", "Response"] == "Materially unchanged / unaddressed"
    assert drivers.loc["Credit Loss", "Improvement"] == pytest.approx(0.0)

import pytest

from digital_twin.config import load_scenario
from digital_twin.data_generator import generate_virtual_bank
from digital_twin.dependency_graph import blast_radius_by_type
from digital_twin.operational_simulator import simulate_payments
from digital_twin.scenario_engine import ScenarioEngine


def test_cloud_scenario_contains_infrastructure_parameters_only():
    operational = load_scenario("cloud_region_a_8hr")["shocks"]["operational"]
    assert operational == {
        "enabled": True,
        "failed_region": "Cloud Region A",
        "outage_duration_hours": 8,
        "backup_region": "Cloud Region B",
        "backup_activation_delay_hours": 3,
        "backup_capacity_pct": .70,
        "post_recovery_capacity_pct": 1.25,
        "simulation_horizon_hours": 24,
    }


def test_cloud_outage_timeline_and_backlog_clearance():
    impact = simulate_payments(
        duration_hours=24, outage_start_hour=0, recovery_time_hours=8,
        impaired_capacity_fraction=0, backup_activation_hours=3,
        backup_capacity_fraction=.70, post_recovery_capacity_fraction=1.25, seed=42)
    timeline = impact.timeseries.set_index("hour")
    assert (timeline.loc[0:2, "capacity_fraction"] == 0).all()
    assert timeline.loc[3:7, "capacity_fraction"].tolist() == pytest.approx([.70] * 5)
    assert timeline.loc[8, "capacity_fraction"] == pytest.approx(1.25)
    assert timeline.loc[0, "event"] == "Primary region failed"
    assert timeline.loc[3, "event"] == "Backup region activated"
    assert "Primary region recovered" in timeline.loc[8, "event"]
    assert impact.primary_recovery_time_hours == 8
    assert impact.backlog_cleared
    assert impact.backlog_clearance_time_hours > 8
    assert impact.ending_backlog_bn == pytest.approx(0.0)


def test_blast_radius_and_faster_backup_are_model_derived():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    standard = engine.run("cloud_region_a_8hr")
    faster = engine.run("cloud_region_a_8hr", overrides={
        "operational": {"backup_activation_delay_hours": 1}})
    expected = blast_radius_by_type(engine.graph, "Cloud Region A")
    impact = standard.impacts["operational_impact"]
    expected_applications = sorted(
        set().union(*expected.values()) & set(engine.bank.applications["application"]))
    assert impact["applications_affected"] == expected_applications
    assert impact["business_services_affected"] == expected["Business Service"]
    assert impact["customer_segments_affected"] == expected["Customer Segment"]
    assert impact["financial_risk_nodes_affected"] == expected["Financial Position / Risk Metric"]
    assert faster.metrics["payment_backlog_bn"] < standard.metrics["payment_backlog_bn"]
    assert faster.metrics["customers_affected"] < standard.metrics["customers_affected"]
    assert faster.metrics["deposit_outflow_bn"] < standard.metrics["deposit_outflow_bn"]
    assert faster.metrics["recovery_time_hours"] < standard.metrics["recovery_time_hours"]

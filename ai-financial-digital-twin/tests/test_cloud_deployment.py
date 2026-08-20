import pandas as pd

from digital_twin.data_generator import generate_virtual_bank
from digital_twin.dependency_graph import cloud_concentration_metrics
from digital_twin.scenario_engine import ScenarioEngine
from digital_twin.visualizations import cloud_deployment_view_data


REQUIRED_DEPLOYMENT_COLUMNS = {
    "application", "primary_region", "backup_region", "backup_mode", "failover_time_minutes",
    "normal_capacity_pct", "backup_capacity_pct", "criticality",
}


def test_application_region_mapping_matches_dependency_graph():
    bank = generate_virtual_bank(seed=42)
    engine = ScenarioEngine(bank)
    assert REQUIRED_DEPLOYMENT_COLUMNS.issubset(bank.applications.columns)
    cloud_apps = bank.applications.loc[bank.applications["primary_region"] == "Cloud Region A"]
    for row in cloud_apps.itertuples(index=False):
        assert engine.graph.has_edge("Cloud Region A", row.application)
        assert engine.graph.has_edge("Cloud Region B", row.application) == pd.notna(row.backup_region)


def test_backup_availability_and_hour_three_failover_state():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    result = engine.run("cloud_region_a_8hr")
    states = pd.DataFrame(result.impacts["operational_impact"]["application_failover_states"]["backup_activation"])
    indexed = states.set_index("application")
    assert indexed.loc["Domestic Payments", "application_status"] == "Recovered degraded"
    assert indexed.loc["Identity Service", "application_status"] == "Recovered degraded"
    assert indexed.loc["Domestic Payments", "active_region"] == "Cloud Region B"
    assert indexed.loc["Identity Service", "effective_capacity_pct"] == 70
    assert indexed.loc["Cross-Border Payments", "application_status"] == "No backup / unavailable"
    assert indexed.loc["Cross-Border Payments", "effective_capacity_pct"] == 0


def test_no_backup_and_deployment_view_are_data_driven():
    bank = generate_virtual_bank(seed=42)
    result = ScenarioEngine(bank).run("cloud_region_a_8hr")
    states = pd.DataFrame(result.impacts["operational_impact"]["application_failover_states"]["hour_0"])
    view = cloud_deployment_view_data(bank.applications, states)
    no_backup = view.loc[view["status"] == "No backup / unavailable", "application"].tolist()
    assert no_backup == bank.applications.loc[
        (bank.applications["primary_region"] == "Cloud Region A") & bank.applications["backup_region"].isna(),
        "application"].tolist()
    assert "Cross-Border Payments" in no_backup


def test_cloud_concentration_and_blast_radius():
    bank = generate_virtual_bank(seed=42)
    engine = ScenarioEngine(bank)
    concentration = cloud_concentration_metrics(bank, engine.graph)
    assert concentration["applications_by_region"]["Cloud Region A"] == [
        "Cross-Border Payments", "Domestic Payments", "Identity Service"]
    assert concentration["applications_by_region"]["Cloud Region B"] == [
        "Domestic Payments", "Identity Service"]
    assert concentration["applications_without_backup"] == ["Cross-Border Payments"]
    assert concentration["applications_solely_region_a"] == ["Cross-Border Payments"]
    result = engine.run("cloud_region_a_8hr")
    assert result.impacts["operational_impact"]["applications_affected"] == [
        "Cross-Border Payments", "Domestic Payments", "Identity Service", "Internet Banking", "Mobile Banking"]


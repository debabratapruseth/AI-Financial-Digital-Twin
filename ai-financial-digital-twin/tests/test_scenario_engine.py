from digital_twin.config import load_scenario
from digital_twin.data_generator import generate_virtual_bank
from digital_twin.scenario_engine import ScenarioEngine
from digital_twin.dependency_graph import top_propagation_paths


def test_scenario_loading():
    assert load_scenario("combined_stress")["name"] == "Flagship combined stress"


def test_combined_scenario_is_deterministic_and_stressed():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    first = engine.run("combined_stress")
    second = engine.run("combined_stress")
    assert first.metrics == second.metrics
    assert first.metrics["total_estimated_loss_bn"] > 0
    assert first.metrics["cash_position_bn"] < first.baseline["cash_position_bn"]
    assert first.audit_log and first.propagation_paths
    required = {"source_node", "target_node", "dependency_type", "shock", "previous_value",
                "new_value", "financial_or_operational_effect", "reason", "simulation_time"}
    assert first.propagation_trace
    assert all(required.issubset(event) for event in first.propagation_trace)
    paths = top_propagation_paths(first.propagation_trace, top_n=3)
    assert paths and all(" → " in path["path"] for path in paths)
    assert any(path["nodes"][-1] == "LCR" for path in paths)

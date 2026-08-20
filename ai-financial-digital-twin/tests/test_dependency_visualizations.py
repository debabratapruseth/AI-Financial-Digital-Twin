import networkx as nx

from digital_twin.data_generator import generate_virtual_bank
from digital_twin.dependency_graph import impacted_graph_elements, scenario_propagation_subgraph
from digital_twin.scenario_engine import ScenarioEngine
from digital_twin.visualizations import interactive_dependency_graph, scenario_propagation_graph_figure


def _node_text_by_status(figure):
    return {trace.name: set(trace.text or []) for trace in figure.data if trace.mode == "markers+text"}


def test_visualization_uses_actual_networkx_graph_without_mutation():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    graph = engine.graph
    nodes_before = {node: dict(attributes) for node, attributes in graph.nodes(data=True)}
    edges_before = {(source, target): dict(attributes) for source, target, attributes in graph.edges(data=True)}

    figure = interactive_dependency_graph(graph)

    displayed_nodes = set().union(*_node_text_by_status(figure).values())
    assert displayed_nodes == set(graph.nodes)
    assert nodes_before == {node: dict(attributes) for node, attributes in graph.nodes(data=True)}
    assert edges_before == {(source, target): dict(attributes) for source, target, attributes in graph.edges(data=True)}


def test_cloud_failure_marks_failed_and_impacted_nodes_from_trace():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    result = engine.run("cloud_failure")
    impacted_nodes, _ = impacted_graph_elements(engine.graph, result.propagation_trace)

    figure = interactive_dependency_graph(
        engine.graph, result.propagation_trace, failed_nodes={"Cloud Region A"})
    statuses = _node_text_by_status(figure)

    assert "Cloud Region A" in statuses["Failed / shocked"]
    displayed_impacted = statuses["Failed / shocked"] | statuses["Downstream impacted"]
    assert displayed_impacted == impacted_nodes


def test_focused_scenario_graph_contains_only_real_propagation_edges():
    engine = ScenarioEngine(generate_virtual_bank(seed=42))
    result = engine.run("combined_stress")
    _, expected_edges = impacted_graph_elements(engine.graph, result.propagation_trace)

    focused = scenario_propagation_subgraph(engine.graph, result.propagation_trace)
    figure = scenario_propagation_graph_figure(engine.graph, result.propagation_trace)

    assert set(focused.edges) == expected_edges
    assert set(focused.nodes) == {node for edge in expected_edges for node in edge}
    displayed_nodes = set().union(*_node_text_by_status(figure).values())
    assert displayed_nodes == set(focused.nodes)
    assert all(engine.graph.has_edge(source, target) for source, target in focused.edges)
    assert isinstance(focused, nx.DiGraph)


import pandas as pd
from digital_twin.dependency_graph import build_dependency_graph, downstream_impacts, trace_propagation_paths


def test_dependency_propagation():
    edges = pd.DataFrame([("A", "B", "x", 1), ("B", "C", "x", 1)],
                         columns=["source", "target", "relationship", "impact_weight"])
    graph = build_dependency_graph(edges)
    assert downstream_impacts(graph, "A") == ["B", "C"]
    assert trace_propagation_paths(graph, "A", ["C"]) == [["A", "B", "C"]]


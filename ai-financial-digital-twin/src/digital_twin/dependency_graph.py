"""Directed operational and financial dependency graph analysis."""

from __future__ import annotations

from typing import Any, Iterable
import networkx as nx
import pandas as pd


def build_dependency_graph(dependencies: pd.DataFrame,
                           node_metadata: dict[str, dict[str, Any]] | None = None) -> nx.DiGraph:
    graph = nx.DiGraph()
    for row in dependencies.itertuples(index=False):
        graph.add_edge(row.source, row.target, relationship=row.relationship,
                       impact_weight=float(row.impact_weight))
    if node_metadata:
        for node, attributes in node_metadata.items():
            if node in graph:
                graph.nodes[node].update(attributes)
    return graph


def bank_node_metadata(bank: Any) -> dict[str, dict[str, Any]]:
    """Derive node categories from the existing synthetic bank datasets."""
    metadata: dict[str, dict[str, Any]] = {}
    for row in bank.infrastructure.itertuples(index=False):
        category = "Cloud Region" if row.type == "cloud" else "Infrastructure"
        metadata[row.infrastructure] = {"node_type": category, "source_dataset": "infrastructure"}
    for row in bank.vendors.itertuples(index=False):
        metadata[row.vendor] = {"node_type": "Vendor", "source_dataset": "vendors",
                                "configured_critical": bool(row.critical)}
    for row in bank.applications.itertuples(index=False):
        metadata[row.application] = {"node_type": "Application", "source_dataset": "applications",
                                     "availability_target": float(row.availability_target),
                                     "primary_region": row.primary_region, "backup_region": row.backup_region,
                                     "backup_mode": row.backup_mode,
                                     "failover_time_minutes": row.failover_time_minutes,
                                     "normal_capacity_pct": float(row.normal_capacity_pct),
                                     "backup_capacity_pct": float(row.backup_capacity_pct),
                                     "application_criticality": row.criticality}
    for row in bank.payment_systems.itertuples(index=False):
        metadata.setdefault(row.system, {}).update({
            "node_type": "Business Service", "source_dataset": "applications+payment_systems",
            "baseline_availability": float(row.baseline_availability)})
    for row in bank.customer_segments.itertuples(index=False):
        metadata[row.segment] = {"node_type": "Customer Segment", "source_dataset": "customer_segments",
                                 "customers": int(row.customers)}
    financial_nodes = {
        "Corporate Deposits", "Deposit Outflows", "Liquidity Position", "LCR", "FX Exposure",
        "Market P&L", "Credit Loss", "Capital Position", "CET1 Ratio",
    }
    shock_nodes = {"USD Shock", "Volatility Shock", "Major Counterparty"}
    for node in financial_nodes:
        metadata[node] = {"node_type": "Financial Position / Risk Metric", "source_dataset": "dependency_rules"}
    for node in shock_nodes:
        metadata[node] = {"node_type": "Scenario Shock", "source_dataset": "scenario_rules"}
    return metadata


def annotate_graph_importance(graph: nx.DiGraph, critical_count: int = 5) -> nx.DiGraph:
    """Return a copy annotated with betweenness, downstream reach, and criticality."""
    annotated = graph.copy()
    betweenness = nx.betweenness_centrality(annotated)
    ranked = sorted(annotated.nodes, key=lambda node: (betweenness[node], len(nx.descendants(annotated, node))),
                    reverse=True)
    critical = set(ranked[:critical_count])
    for node in annotated.nodes:
        annotated.nodes[node].update({
            "betweenness_centrality": float(betweenness[node]),
            "downstream_count": len(nx.descendants(annotated, node)),
            "critical": node in critical or bool(annotated.nodes[node].get("configured_critical", False)),
            "node_type": annotated.nodes[node].get("node_type", "Business Service"),
        })
    return annotated


def shock_origin_nodes(propagation_trace: list[dict[str, Any]]) -> set[str]:
    """Return scenario origins exactly as emitted by first events in each trace path."""
    return {str(event["source_node"]) for event in propagation_trace if int(event.get("sequence", 0)) == 1}


def impacted_graph_elements(graph: nx.DiGraph, propagation_trace: list[dict[str, Any]]) -> tuple[set[str], set[tuple[str, str]]]:
    """Match simulation trace events to edges that actually exist in the dependency graph."""
    edges = {
        (str(event["source_node"]), str(event["target_node"]))
        for event in propagation_trace
        if graph.has_edge(str(event["source_node"]), str(event["target_node"]))
    }
    nodes = {node for edge in edges for node in edge}
    return nodes, edges


def scenario_propagation_subgraph(graph: nx.DiGraph, propagation_trace: list[dict[str, Any]]) -> nx.DiGraph:
    """Return a copy containing only real graph nodes/edges used by the scenario trace."""
    nodes, edges = impacted_graph_elements(graph, propagation_trace)
    focused = nx.DiGraph()
    for node in nodes:
        focused.add_node(node, **dict(graph.nodes[node]))
    for source, target in edges:
        focused.add_edge(source, target, **dict(graph[source][target]))
    return focused


def blast_radius_by_type(graph: nx.DiGraph, source: str) -> dict[str, list[str]]:
    """Group downstream nodes by graph-derived node type for an infrastructure shock."""
    if source not in graph:
        return {}
    grouped: dict[str, list[str]] = {}
    for node in nx.descendants(graph, source):
        node_type = str(graph.nodes[node].get("node_type", "Business Service"))
        grouped.setdefault(node_type, []).append(str(node))
    return {node_type: sorted(nodes) for node_type, nodes in sorted(grouped.items())}


def cloud_concentration_metrics(bank: Any, graph: nx.DiGraph,
                                regions: tuple[str, str] = ("Cloud Region A", "Cloud Region B")) -> dict[str, Any]:
    """Calculate deployment and dependency concentration from bank data and NetworkX."""
    applications = bank.applications
    deployments: dict[str, list[str]] = {}
    critical: dict[str, list[str]] = {}
    for region in regions:
        deployed = applications.loc[
            (applications["primary_region"] == region) | (applications["backup_region"] == region), "application"
        ].tolist()
        critical_apps = applications.loc[
            ((applications["primary_region"] == region) | (applications["backup_region"] == region))
            & (applications["criticality"] == "Critical"), "application"
        ].tolist()
        deployments[region] = sorted(deployed)
        critical[region] = sorted(critical_apps)
    no_backup = sorted(applications.loc[applications["backup_region"].isna(), "application"].tolist())
    solely_region_a = sorted(applications.loc[
        (applications["primary_region"] == regions[0]) & applications["backup_region"].isna(), "application"
    ].tolist())
    region_a_descendants = nx.descendants(graph, regions[0]) if regions[0] in graph else set()
    region_b_descendants = nx.descendants(graph, regions[1]) if regions[1] in graph else set()
    sole_a_services = sorted(
        node for node in region_a_descendants - region_b_descendants
        if graph.nodes[node].get("node_type") == "Business Service"
    )
    exposed_segments = sorted(
        node for node in region_a_descendants
        if graph.nodes[node].get("node_type") == "Customer Segment"
    )
    return {
        "applications_by_region": deployments,
        "critical_applications_by_region": critical,
        "applications_without_backup": no_backup,
        "applications_solely_region_a": solely_region_a,
        "business_services_solely_region_a": sole_a_services,
        "customer_segments_exposed_to_region_a": exposed_segments,
        "single_points_of_failure": single_points_of_failure(graph),
    }


def downstream_impacts(graph: nx.DiGraph, node: str) -> list[str]:
    if node not in graph:
        return []
    return sorted(nx.descendants(graph, node))


def centrality_table(graph: nx.DiGraph) -> pd.DataFrame:
    degree = nx.degree_centrality(graph)
    between = nx.betweenness_centrality(graph)
    return pd.DataFrame([
        {"node": node, "degree_centrality": degree[node], "betweenness_centrality": between[node],
         "downstream_count": len(nx.descendants(graph, node))}
        for node in graph.nodes
    ]).sort_values(["betweenness_centrality", "downstream_count"], ascending=False).reset_index(drop=True)


def critical_nodes(graph: nx.DiGraph, top_n: int = 5) -> list[str]:
    return centrality_table(graph).head(top_n)["node"].tolist()


def single_points_of_failure(graph: nx.DiGraph) -> list[str]:
    """Nodes whose removal disconnects at least one currently reachable source/target pair."""
    undirected_articulation = set(nx.articulation_points(graph.to_undirected()))
    return sorted(node for node in undirected_articulation if graph.out_degree(node) > 0)


def trace_propagation_paths(graph: nx.DiGraph, source: str,
                            targets: Iterable[str] | None = None, cutoff: int = 8) -> list[list[str]]:
    if source not in graph:
        return []
    destinations = list(targets or [n for n in graph if graph.out_degree(n) == 0])
    paths: list[list[str]] = []
    for target in destinations:
        if target in graph and nx.has_path(graph, source, target):
            paths.extend(list(nx.all_simple_paths(graph, source, target, cutoff=cutoff)))
    return paths


def propagated_impact(graph: nx.DiGraph, source: str, initial_impact: float = 1.0) -> dict[str, float]:
    impacts = {source: initial_impact}
    if source not in graph:
        return {}
    for node in nx.topological_sort(graph):
        if node not in impacts:
            continue
        for successor in graph.successors(node):
            weight = float(graph[node][successor].get("impact_weight", 1.0))
            impacts[successor] = max(impacts.get(successor, 0.0), impacts[node] * weight)
    return impacts


def top_propagation_paths(propagation_trace: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    """Rank explicit simulation paths by material numeric effect, then path length.

    Events are grouped by their ``path_id``. The function never infers new edges;
    it only summarizes paths emitted by the deterministic scenario engine.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in propagation_trace:
        grouped.setdefault(str(event.get("path_id", "unclassified")), []).append(event)
    ranked = []
    for path_id, events in grouped.items():
        ordered = sorted(events, key=lambda event: int(event.get("sequence", 0)))
        nodes = [ordered[0]["source_node"]] + [event["target_node"] for event in ordered]
        numeric_changes = [
            abs(float(event["new_value"]) - float(event["previous_value"]))
            for event in ordered
            if isinstance(event.get("new_value"), (int, float))
            and isinstance(event.get("previous_value"), (int, float))
        ]
        ranked.append({
            "path_id": path_id,
            "nodes": nodes,
            "path": " → ".join(nodes),
            "material_effect": max(numeric_changes, default=0.0),
            "events": ordered,
        })
    ordered = sorted(ranked, key=lambda item: (item["material_effect"], len(item["nodes"])), reverse=True)
    selected: list[dict[str, Any]] = []
    represented_domains: set[str] = set()
    for item in ordered:
        path_id = item["path_id"]
        domain = "liquidity" if path_id.endswith("_liquidity") else path_id.split("_to_")[0]
        if domain not in represented_domains:
            selected.append(item)
            represented_domains.add(domain)
        if len(selected) == top_n:
            return selected
    for item in ordered:
        if item not in selected:
            selected.append(item)
        if len(selected) == top_n:
            break
    return selected

"""Plotly figure factories. Functions return figures and never display them."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .dependency_graph import (
    annotate_graph_importance,
    impacted_graph_elements,
    scenario_propagation_subgraph,
    shock_origin_nodes,
)


def bank_health_dashboard(metrics: dict) -> go.Figure:
    keys = ["lcr", "cet1_ratio", "cash_position_bn", "payment_availability"]
    fig = go.Figure()
    for index, key in enumerate(keys):
        fig.add_trace(go.Indicator(mode="number", value=float(metrics[key]), title={"text": key.replace("_", " ").title()},
                                   domain={"row": index // 2, "column": index % 2}))
    fig.update_layout(grid={"rows": 2, "columns": 2, "pattern": "independent"}, title="Bank Health (Prototype KPIs)")
    return fig


def baseline_vs_stressed(baseline: dict, stressed: dict) -> go.Figure:
    keys = ["cash_position_bn", "hqla_bn", "lcr", "cet1_ratio", "payment_availability"]
    frame = pd.DataFrame([{"metric": k, "Baseline": baseline[k], "Stressed": stressed[k]} for k in keys])
    return px.bar(frame.melt("metric", var_name="state", value_name="value"), x="metric", y="value", color="state", barmode="group")


def dependency_graph_figure(graph: nx.DiGraph) -> go.Figure:
    return interactive_dependency_graph(
        graph, title="DIGITAL TWIN DEPENDENCY MAP — BASELINE (size = betweenness centrality)")


def impacted_dependency_graph_figure(graph: nx.DiGraph, propagation_trace: list[dict]) -> go.Figure:
    """Backward-compatible full graph with deterministic scenario highlighting."""
    return interactive_dependency_graph(
        graph, propagation_trace=propagation_trace,
        title="DIGITAL TWIN — IMPACTED DEPENDENCY GRAPH (size = betweenness centrality)")


def scenario_propagation_graph_figure(graph: nx.DiGraph, propagation_trace: list[dict],
                                      failed_nodes: set[str] | list[str] | None = None,
                                      title: str = "SCENARIO PROPAGATION GRAPH") -> go.Figure:
    """Render only actual graph elements used in the current simulation trace."""
    focused = scenario_propagation_subgraph(graph, propagation_trace)
    return interactive_dependency_graph(
        focused, propagation_trace=propagation_trace, failed_nodes=failed_nodes,
        title=f"{title} (focused; size = betweenness centrality)")


def interactive_dependency_graph(graph: nx.DiGraph, propagation_trace: list[dict] | None = None,
                                 failed_nodes: set[str] | list[str] | None = None,
                                 title: str = "DIGITAL TWIN DEPENDENCY GRAPH") -> go.Figure:
    """Create a pure-Python, deterministic, accessible layered Plotly graph.

    The input graph is copied. No visualization edge is invented: scenario edges
    are included only when they exist in the supplied NetworkX graph.
    """
    display_graph = annotate_graph_importance(graph)
    positions = _layered_positions(display_graph)
    trace_events = propagation_trace or []
    impacted_nodes, impacted_edges = impacted_graph_elements(display_graph, trace_events)
    origins = shock_origin_nodes(trace_events)
    failed = set(failed_nodes or origins)
    has_scenario = propagation_trace is not None
    figure = go.Figure()

    for source, target, attributes in display_graph.edges(data=True):
        impacted = (source, target) in impacted_edges
        weight = float(attributes.get("impact_weight", 1.0))
        x0, y0 = positions[source]; x1, y1 = positions[target]
        figure.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line={"color": "#dc2626" if impacted else "#94a3b8",
                  "width": (2.0 + 2.0 * weight) if impacted else (.7 + weight)},
            opacity=1.0 if impacted else .45,
            hovertemplate=(f"{source} → {target}<br>Dependency: {attributes.get('relationship', 'depends_on')}"
                           f"<br>Strength: {weight:.2f}<br>Scenario path: {'Yes' if impacted else 'No'}<extra></extra>"),
            showlegend=False,
        ))

    statuses: dict[str, list[str]] = {name: [] for name in ("Failed / shocked", "Downstream impacted", "Critical", "Unaffected", "Normal")}
    for node in display_graph.nodes:
        attrs = display_graph.nodes[node]
        if node in failed:
            status = "Failed / shocked"
        elif node in impacted_nodes:
            status = "Downstream impacted"
        elif attrs.get("critical"):
            status = "Critical"
        elif has_scenario:
            status = "Unaffected"
        else:
            status = "Normal"
        statuses[status].append(node)

    style = {
        "Failed / shocked": {"color": "#b91c1c", "symbol": "x", "line": "#111827"},
        "Downstream impacted": {"color": "#f97316", "symbol": "triangle-down", "line": "#7c2d12"},
        "Critical": {"color": "#7c3aed", "symbol": "diamond", "line": "#111827"},
        "Unaffected": {"color": "#e2e8f0", "symbol": "circle-open", "line": "#64748b"},
        "Normal": {"color": "#2563eb", "symbol": "circle", "line": "#1e3a8a"},
    }
    max_centrality = max((display_graph.nodes[node]["betweenness_centrality"] for node in display_graph), default=1.0) or 1.0
    for status, nodes in statuses.items():
        if not nodes:
            continue
        hover = [_node_hover(display_graph, node, status, trace_events) for node in nodes]
        sizes = [14.0 + 24.0 * display_graph.nodes[node]["betweenness_centrality"] / max_centrality for node in nodes]
        border_width = [3 if display_graph.nodes[node].get("critical") else 1.5 for node in nodes]
        figure.add_trace(go.Scatter(
            x=[positions[node][0] for node in nodes], y=[positions[node][1] for node in nodes],
            mode="markers+text", text=nodes, textposition="middle right", name=status,
            hovertext=hover, hovertemplate="%{hovertext}<extra></extra>",
            marker={"size": sizes, "color": style[status]["color"], "symbol": style[status]["symbol"],
                    "line": {"color": style[status]["line"], "width": border_width}},
        ))
    figure.update_layout(
        title=title, template="plotly_white", height=max(650, 90 * len(set(y for _, y in positions.values()))),
        hovermode="closest", legend={"orientation": "h", "y": 1.08, "x": 0},
        xaxis={"visible": False}, yaxis={"visible": False}, margin={"l": 30, "r": 180, "t": 120, "b": 30},
        annotations=[{"text": "Top → bottom follows causal dependency depth. Node size reflects betweenness centrality; thick borders mark critical nodes.",
                      "xref": "paper", "yref": "paper", "x": 0, "y": 1.02, "showarrow": False, "xanchor": "left"}],
    )
    return figure


def _layered_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Place DAG generations in deterministic horizontal layers."""
    if not graph.nodes:
        return {}
    if nx.is_directed_acyclic_graph(graph):
        generations = [sorted(generation) for generation in nx.topological_generations(graph)]
    else:
        generations = [sorted(graph.nodes)]
    positions: dict[str, tuple[float, float]] = {}
    max_layer = max(1, len(generations) - 1)
    for layer, nodes in enumerate(generations):
        count = len(nodes)
        for index, node in enumerate(nodes):
            x = 0.0 if count == 1 else -1.0 + 2.0 * index / (count - 1)
            positions[node] = (x, float(max_layer - layer))
    return positions


def _node_hover(graph: nx.DiGraph, node: str, status: str, propagation_trace: list[dict]) -> str:
    attrs = graph.nodes[node]
    dependencies = sorted(graph.predecessors(node))
    dependents = sorted(graph.successors(node))
    downstream = sorted(nx.descendants(graph, node))
    impacts = []
    for event in propagation_trace:
        if node not in {event.get("source_node"), event.get("target_node")}:
            continue
        value = event.get("new_value")
        if isinstance(value, (int, float)):
            impacts.append(f"{event.get('financial_or_operational_effect')}: {value:.4g}")
    details = [
        f"<b>{node}</b>", f"Type: {attrs.get('node_type', 'Business Service')}",
        f"Criticality: {'Critical' if attrs.get('critical') else 'Standard'}",
        f"Operational status: {'Failed / shocked' if status == 'Failed / shocked' else 'Operational'}",
        f"Scenario impact: {status}", f"Betweenness centrality: {attrs.get('betweenness_centrality', 0.0):.4f}",
        f"Immediate dependencies: {', '.join(dependencies) or 'None'}",
        f"Immediate dependents: {', '.join(dependents) or 'None'}",
        f"Downstream dependents: {len(downstream)}",
    ]
    if "customers" in attrs:
        details.append(f"Configured customers: {attrs['customers']:,}")
    if impacts:
        details.append("Validated scenario values: " + "; ".join(dict.fromkeys(impacts)))
    return "<br>".join(details)


def breach_probability_figure(frame: pd.DataFrame) -> go.Figure:
    return px.bar(frame, x="Probability of Breach", y="Risk Metric", color="Severity",
                  orientation="h", range_x=[0, 1], title="Monte Carlo Breach Probabilities")


def distribution_figure(results: pd.DataFrame, column: str, title: str | None = None) -> go.Figure:
    return px.histogram(results, x=column, nbins=40, marginal="box", title=title or f"{column} distribution")


def threshold_distribution_figure(results: pd.DataFrame, column: str, thresholds: dict[str, float],
                                  title: str) -> go.Figure:
    """Plot an empirical metric distribution with configured risk-limit lines."""
    figure = distribution_figure(results, column, title)
    colors = {"warning": "#d97706", "critical": "#b91c1c"}
    for label, threshold in thresholds.items():
        figure.add_vline(x=float(threshold), line_width=3, line_dash="dash",
                         line_color=colors.get(label, "#334155"),
                         annotation_text=f"{label.title()}: {threshold:g}")
    return figure


def loss_distribution(results: pd.DataFrame) -> go.Figure: return distribution_figure(results, "total_loss_bn", "Total Loss Distribution")
def lcr_distribution(results: pd.DataFrame) -> go.Figure: return distribution_figure(results, "lcr", "Prototype LCR Distribution")
def monte_carlo_histogram(results: pd.DataFrame, metric: str = "total_loss_bn") -> go.Figure: return distribution_figure(results, metric)


def payment_backlog_over_time(timeseries: pd.DataFrame) -> go.Figure:
    return px.line(timeseries, x="hour", y="backlog_bn", title="Payment Backlog Over Time")


def cloud_outage_timeline_figure(timeseries: pd.DataFrame, outage_duration_hours: float,
                                 backup_activation_delay_hours: float) -> go.Figure:
    """Show capacity, backlog, and model-emitted outage lifecycle events."""
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(go.Scatter(
        x=timeseries["hour"], y=timeseries["backlog_bn"], mode="lines+markers",
        name="Payment backlog (USD bn)", line={"width": 3, "color": "#b91c1c"}), secondary_y=False)
    figure.add_trace(go.Scatter(
        x=timeseries["hour"], y=timeseries["capacity_fraction"] * 100.0,
        mode="lines+markers", name="Processing capacity (%)",
        line={"width": 3, "dash": "dash", "color": "#2563eb"}), secondary_y=True)
    if "customers_affected" in timeseries:
        figure.add_trace(go.Scatter(
            x=timeseries["hour"], y=timeseries["customers_affected"], mode="lines",
            name="Customers affected", yaxis="y3", line={"width": 2, "color": "#7c3aed"}))
    figure.add_vrect(x0=0, x1=backup_activation_delay_hours, fillcolor="#fecaca", opacity=.35,
                     line_width=0, annotation_text="Primary failed; backup unavailable")
    figure.add_vrect(x0=backup_activation_delay_hours, x1=outage_duration_hours,
                     fillcolor="#fed7aa", opacity=.3, line_width=0, annotation_text="Backup degraded")
    clearance_rows = timeseries.loc[timeseries["event"].str.contains("Backlog cleared", na=False), "hour"]
    clearance_hour = float(clearance_rows.iloc[0] + 1) if not clearance_rows.empty else float(timeseries["hour"].max() + 1)
    figure.add_vrect(x0=outage_duration_hours, x1=clearance_hour, fillcolor="#bfdbfe", opacity=.25,
                     line_width=0, annotation_text="Primary recovered; backlog clearance")
    for label, hour in (("Failure", 0.0), ("Backup activation", backup_activation_delay_hours),
                        ("Primary recovery", outage_duration_hours), ("Backlog cleared", clearance_hour)):
        figure.add_vline(x=hour, line_width=2, line_dash="dot", line_color="#334155",
                         annotation_text=f"{label}: h{hour:g}", annotation_position="top")
    figure.update_yaxes(title_text="Backlog (USD bn)", secondary_y=False)
    figure.update_yaxes(title_text="Processing capacity (%)", secondary_y=True)
    figure.update_xaxes(title_text="Simulation hour", dtick=1)
    figure.update_layout(title="Cloud Failure Timeline — Capacity, Degradation, Recovery, and Backlog Clearance",
                         template="plotly_white", hovermode="x unified", height=600,
                         legend={"orientation": "h", "y": 1.12},
                         yaxis3={"title": "Customers affected", "overlaying": "y", "side": "right",
                                 "anchor": "free", "position": .93, "showgrid": False})
    return figure


def cloud_deployment_view_data(applications: pd.DataFrame, application_states: pd.DataFrame | None = None,
                               regions: tuple[str, str] = ("Cloud Region A", "Cloud Region B")) -> pd.DataFrame:
    """Build region deployment records exclusively from the application table and calculated states."""
    states = application_states.set_index("application") if application_states is not None else None
    records = []
    for row in applications.itertuples(index=False):
        if row.primary_region not in regions and row.backup_region not in regions:
            continue
        state = states.loc[row.application] if states is not None and row.application in states.index else None
        primary_status = "Primary / Active"
        primary_capacity = float(row.normal_capacity_pct)
        if state is not None and bool(state["directly_hosted_in_failed_region"]):
            primary_status = "Primary recovered" if state["application_status"] == "Primary recovered" else "Failed"
            primary_capacity = float(row.normal_capacity_pct) if primary_status == "Primary recovered" else 0.0
        records.append(_deployment_record(row, row.primary_region, "Primary", primary_status,
                                          primary_capacity))
        if pd.notna(row.backup_region):
            backup_status, capacity = "Standby", float(row.backup_capacity_pct)
            if state is not None and bool(state["directly_hosted_in_failed_region"]):
                status = str(state["application_status"])
                if status == "Waiting for failover": backup_status, capacity = status, 0.0
                elif status in {"Recovered", "Recovered degraded"}:
                    backup_status, capacity = status, float(state["effective_capacity_pct"])
                elif status == "Primary recovered": backup_status = "Standby"
            records.append(_deployment_record(row, row.backup_region, "Backup", backup_status, capacity))
        elif row.primary_region == regions[0]:
            records.append(_deployment_record(row, regions[1], "No backup", "No backup / unavailable", 0.0))
    return pd.DataFrame(records)


def cloud_deployment_map_figure(applications: pd.DataFrame, application_states: pd.DataFrame | None = None,
                                title: str = "CLOUD DEPLOYMENT MAP") -> go.Figure:
    """Render side-by-side Region A/Region B deployments and calculated failover states."""
    view = cloud_deployment_view_data(applications, application_states)
    applications_order = sorted(view["application"].unique())
    y_map = {application: index for index, application in enumerate(applications_order)}
    styles = {
        "Primary / Active": ("#2563eb", "circle"), "Standby": ("#64748b", "circle-open"),
        "Failed": ("#b91c1c", "x"), "Waiting for failover": ("#d97706", "hourglass"),
        "Recovered": ("#15803d", "diamond"), "Recovered degraded": ("#65a30d", "diamond-open"),
        "Primary recovered": ("#15803d", "star"), "No backup / unavailable": ("#111827", "x-open"),
    }
    figure = go.Figure()
    for status, rows in view.groupby("status", sort=False):
        color, symbol = styles.get(status, ("#7c3aed", "square"))
        figure.add_trace(go.Scatter(
            x=rows["region"],
            y=[y_map[application] for application in rows["application"]],
            mode="markers+text", text=rows["application"], textposition="middle right", name=status,
            marker={"size": 20, "color": color, "symbol": symbol, "line": {"width": 2, "color": "#111827"}},
            customdata=rows[["role", "criticality", "backup_mode", "failover_time_minutes",
                             "configured_backup_capacity_pct", "effective_capacity_pct"]].to_numpy(),
            hovertemplate=("<b>%{text}</b><br>Region: %{x}<br>Role: %{customdata[0]}"
                           "<br>Criticality: %{customdata[1]}<br>Backup mode: %{customdata[2]}"
                           "<br>Failover: %{customdata[3]} minutes<br>Configured backup capacity: %{customdata[4]}%"
                           "<br>Effective capacity: %{customdata[5]}%<extra></extra>"),
        ))
    figure.update_xaxes(categoryorder="array", categoryarray=["Cloud Region A", "Cloud Region B"], side="top")
    figure.update_yaxes(visible=False, range=[-1, len(applications_order)])
    figure.update_layout(title=title, template="plotly_white", height=max(450, 90 * len(applications_order)),
                         legend={"orientation": "h", "y": 1.15}, margin={"l": 40, "r": 220, "t": 130, "b": 40})
    return figure


def cloud_concentration_figure(concentration: dict) -> go.Figure:
    regions = list(concentration["applications_by_region"])
    frame = pd.DataFrame({
        "Region": regions,
        "Applications": [len(concentration["applications_by_region"][region]) for region in regions],
        "Critical applications": [len(concentration["critical_applications_by_region"][region]) for region in regions],
    }).melt("Region", var_name="Measure", value_name="Count")
    return px.bar(frame, x="Region", y="Count", color="Measure", barmode="group",
                  title="Cloud Deployment Concentration Risk")


def _deployment_record(row: object, region: str, role: str, status: str, capacity: float) -> dict:
    return {
        "application": row.application, "region": region, "role": role, "status": status,
        "criticality": row.criticality, "backup_mode": row.backup_mode,
        "failover_time_minutes": row.failover_time_minutes,
        "configured_backup_capacity_pct": float(row.backup_capacity_pct),
        "effective_capacity_pct": capacity,
    }


def scenario_comparison(frame: pd.DataFrame) -> go.Figure:
    return px.bar(frame, x="scenario", y="total_estimated_loss_bn", color="lcr", title="Scenario Comparison")


def management_action_comparison(frame: pd.DataFrame) -> go.Figure:
    return px.bar(frame.melt("metric", value_vars=["before", "after"], var_name="state"), x="metric", y="value", color="state", barmode="group")


def management_strategy_figure(strategy_comparison: pd.DataFrame, metrics: list[str] | None = None) -> go.Figure:
    """Compare no action, selected single action, and combined response on chosen metrics."""
    selected = metrics or ["total_estimated_loss_bn", "cash_position_bn", "lcr", "payment_availability",
                           "customers_affected", "recovery_time_hours"]
    frame = strategy_comparison.loc[strategy_comparison["Metric"].isin(selected)]
    long = frame.melt("Metric", value_vars=["No Action", "Balanced Single Action", "Combined Response"],
                      var_name="Strategy", value_name="Value")
    return px.bar(long, x="Metric", y="Value", color="Strategy", barmode="group",
                  facet_col="Metric", facet_col_wrap=3, title="MANAGEMENT RESPONSE DECISION LAB")


def severity_distribution_figure(frame: pd.DataFrame) -> go.Figure:
    long = frame.melt("Severity", var_name="Strategy", value_name="Configured Risk Metrics")
    return px.bar(long, x="Strategy", y="Configured Risk Metrics", color="Severity", barmode="stack",
                  category_orders={"Severity": ["Within Limit", "Warning", "Critical"]},
                  color_discrete_map={"Within Limit": "#15803d", "Warning": "#d97706", "Critical": "#b91c1c"},
                  title="Mutually Exclusive Risk-Severity Distribution")


def management_response_flow_figure(flow: pd.DataFrame, selected_actions: list[str]) -> go.Figure:
    """Show deterministic risk-domain-to-action-to-residual-risk routing."""
    selected = flow.loc[flow["Management Action"].isin(selected_actions)]
    domains = list(dict.fromkeys(selected["Risk Domain"].tolist()))
    actions = list(dict.fromkeys(selected["Management Action"].tolist()))
    labels = domains + actions + ["RESIDUAL RISK"]
    index = {label: position for position, label in enumerate(labels)}
    sources = [index[row["Risk Domain"]] for _, row in selected.iterrows()]
    targets = [index[row["Management Action"]] for _, row in selected.iterrows()]
    values = [1] * len(selected)
    sources += [index[action] for action in actions]
    targets += [index["RESIDUAL RISK"]] * len(actions)
    values += [1] * len(actions)
    figure = go.Figure(go.Sankey(node={"label": labels, "pad": 20, "thickness": 18},
                                  link={"source": sources, "target": targets, "value": values}))
    figure.update_layout(title="Combined Management Response — Risk Channels and Residual Risk", template="plotly_white")
    return figure


def risk_heatmap(frame: pd.DataFrame) -> go.Figure:
    return px.imshow(frame.select_dtypes("number").T, aspect="auto", color_continuous_scale="RdYlGn_r", title="Risk Heatmap")

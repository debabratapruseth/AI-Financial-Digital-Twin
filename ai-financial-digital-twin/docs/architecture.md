# Architecture

`BankState` contains compact pandas datasets for the balance sheet, FX, customer cohorts, counterparties, applications, vendors, infrastructure, payments, and dependency edges. All amounts use USD billions.

The flow is configuration → synthetic state → dependency graph → scenario orchestration → financial and operational engines → metrics/limits → visualization/export/explanation. `ScenarioEngine` owns orchestration to avoid circular imports. Engine functions are small and deterministic; plotting functions return figures without side effects. `ScenarioResult` is the audit boundary and contains baseline metrics, applied shocks, detailed impacts, paths, limit breaches, and event records.

The master notebook locates `src` from one `PROJECT_ROOT`, making the same code usable locally and from a Drive-mounted Colab session.

The dependency-map visualization renders the same directed NetworkX graph used by `ScenarioEngine`. Node categories are derived from the synthetic bank datasets, causal depth determines a deterministic layered layout, and node size represents betweenness centrality. Scenario views match emitted propagation events back to existing graph edges; focused views contain no unrelated or visualization-invented edges.

Application records also contain primary/backup placement, backup mode, failover time, normal and backup capacity, and criticality. Cloud deployment maps, hour-specific failover states, and concentration measures read those records directly. Application blast radius remains graph-derived, including downstream applications that are disrupted through a failed dependency rather than direct hosting.

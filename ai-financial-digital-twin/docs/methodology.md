# Methodology

## Deterministic calculations

- FX P&L = gross exposure × (1 − hedge ratio) × configured currency shock.
- Volatility loss = excess volatility multiplier × configured sensitivity.
- Expected loss = PD × LGD × EAD; default loss = LGD × EAD.
- Segment incremental outflow = deposits × shock rate × withdrawal sensitivity.
- Prototype LCR = haircut-adjusted HQLA / stressed 30-day net cash outflows.
- Prototype CET1 ratio = CET1 after modeled losses / loans × risk-weight density.

These are explanatory approximations, not official regulatory calculations.

Deposit withdrawals are modeled first as liquidity usage, not accounting loss. Results separately report deposit outflow, cash and HQLA consumption, emergency funding, asset liquidation, funding cost, and realized liquidation loss. Only the last two enter P&L and capital.

## Dependencies and operations

NetworkX represents directed infrastructure-to-financial dependencies. Reachability, degree/betweenness centrality, articulation points, paths, and weighted downstream impact are reported. SimPy advances payment arrivals and processing hourly. During an outage, capacity falls, backup capacity activates, and recovery restores normal processing; backlog is carried forward.

Infrastructure-only cloud scenarios use the failed graph node as the sole impact origin. Applications, business services, customer segments, and financial/risk nodes are selected from NetworkX descendants. SimPy records primary failure, backup activation, degraded capacity, primary recovery, temporary recovery capacity, and the first hour in which backlog is fully cleared.

Every scenario also emits edge-level causal events containing source, target, dependency type, shock, before/after values, effect class, reason, and simulation time where applicable. Top-path reporting ranks these deterministic traces while retaining domain diversity across operational, liquidity, market, and credit propagation.

## Monte Carlo and management actions

Monte Carlo samples bounded FX, volatility, withdrawal, recovery, and default-severity variables with a seeded NumPy generator. Each draw reruns the same deterministic engine. Results report distribution percentiles and empirical breach probability. Actions alter declared capacity, timing, funding, asset sale, hedge, or depositor-response parameters; benefits are differences between re-simulations.

Threshold probabilities are reported separately for LCR, cash, CET1, payment availability, severe loss, and recovery time. A diagnostic table explains 0% and 100% outcomes from the observed simulation range; distributions are not tuned to force visually varied probabilities.

## ML and LLM responsibilities

No ML model is needed for this prototype. The optional LLM is a narrative layer over validated JSON. It cannot create input data, calculate authoritative figures, change causal paths, or override deterministic thresholds.

The executive LLM receives a compact context rather than raw paths or time series. Payload sizes are reported to make that boundary auditable.

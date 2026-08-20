"""Central, configuration-driven scenario orchestration."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from .bank_state import AuditEvent, BankState, ScenarioResult
from .config import load_scenario
from .credit_engine import calculate_credit_impact
from .dependency_graph import (
    bank_node_metadata, blast_radius_by_type, build_dependency_graph,
    propagated_impact, trace_propagation_paths,
)
from .liquidity_engine import build_lcr_bridge, calculate_liquidity
from .market_engine import calculate_market_impact
from .metrics import calculate_metrics, evaluate_risk_limits
from .operational_simulator import application_failover_states, simulate_payments


class ScenarioEngine:
    """Run reproducible financial and operational shocks from YAML definitions."""

    def __init__(self, bank: BankState):
        self.bank = bank
        self.graph = build_dependency_graph(bank.dependencies, bank_node_metadata(bank))

    def baseline_metrics(self) -> dict[str, Any]:
        liquidity = calculate_liquidity(
            self.bank.customer_segments, self.bank.amount("cash_reserves"), self.bank.amount("securities"),
            haircut=self.bank.assumptions["hqla_securities_haircut"],
            inflow_cap_bn=self.bank.assumptions["inflow_cap_bn"])
        rwa = self.bank.amount("customer_loans") * self.bank.assumptions["risk_weight_density"]
        return calculate_metrics(cash_bn=self.bank.amount("cash_reserves"), hqla_bn=liquidity.hqla_bn,
                                 lcr=liquidity.lcr, cet1_bn=self.bank.amount("cet1_capital"), rwa_bn=rwa)

    def run(self, scenario: str | dict[str, Any], actions: list[str] | None = None,
            overrides: dict[str, Any] | None = None) -> ScenarioResult:
        config = load_scenario(scenario) if isinstance(scenario, str) else dict(scenario)
        shocks = _deep_merge(config.get("shocks", {}), overrides or {})
        actions = actions or []
        action_params = _action_parameters(actions)
        baseline = self.baseline_metrics()
        name = str(config.get("name", "custom_scenario"))
        audit: list[dict[str, Any]] = []

        fx_shocks = dict(shocks.get("fx", {}))
        if action_params["fx_hedge_increase"]:
            exposures = self.bank.fx_exposures.copy()
            exposures["hedge_ratio"] = (exposures["hedge_ratio"] + action_params["fx_hedge_increase"]).clip(upper=.95)
        else:
            exposures = self.bank.fx_exposures
        market = calculate_market_impact(exposures, fx_shocks, float(shocks.get("volatility_multiplier", 1.0)),
                                         self.bank.assumptions["volatility_loss_sensitivity"])
        audit.append(asdict(AuditEvent("market", "market shock", {"fx": fx_shocks, "volatility": shocks.get("volatility_multiplier", 1)},
                                            0.0, market.total_market_loss_bn, "Hedged exposure revaluation plus configured volatility sensitivity", name)))

        operational_cfg = shocks.get("operational", {})
        outage = bool(operational_cfg.get("enabled", False))
        source = str(operational_cfg.get("failed_region", operational_cfg.get("source", "Cloud Region A")))
        recovery = float(operational_cfg.get("outage_duration_hours",
                                             operational_cfg.get("recovery_time_hours", 0.0)))
        blast_radius = blast_radius_by_type(self.graph, source) if outage else {}
        downstream_nodes = set().union(*blast_radius.values()) if blast_radius else set()
        application_names = set(self.bank.applications["application"])
        affected_applications = sorted(downstream_nodes & application_names)
        affected_services = blast_radius.get("Business Service", [])
        affected_segments = blast_radius.get("Customer Segment", [])
        affected_financial_nodes = blast_radius.get("Financial Position / Risk Metric", [])
        segment_customers = self.bank.customer_segments.set_index("segment")["customers"].to_dict()
        customer_population = sum(int(segment_customers.get(segment, 0)) for segment in affected_segments)
        if action_params["activate_backup"]:
            configured_backup_hours = float(operational_cfg.get(
                "backup_activation_delay_hours", operational_cfg.get("backup_activation_hours", 2.0)))
            backup_hours = min(configured_backup_hours, .5)
            backup_capacity = max(float(operational_cfg.get(
                "backup_capacity_pct", operational_cfg.get("backup_capacity_fraction", .7))), .9)
            recovery = max(0.5, recovery * .65)
        else:
            backup_hours = float(operational_cfg.get(
                "backup_activation_delay_hours", operational_cfg.get("backup_activation_hours", 2.0)))
            backup_capacity = float(operational_cfg.get(
                "backup_capacity_pct", operational_cfg.get("backup_capacity_fraction", .7)))
        outage_start = float(operational_cfg.get("outage_start_hour", 0.0 if "failed_region" in operational_cfg else 2.0))
        impaired_capacity = float(operational_cfg.get(
            "impaired_capacity_fraction", 0.0 if "failed_region" in operational_cfg else .1))
        post_recovery_capacity = float(operational_cfg.get("post_recovery_capacity_pct", 1.0))
        simulation_horizon = int(operational_cfg.get("simulation_horizon_hours", 24))
        operational = simulate_payments(
            duration_hours=simulation_horizon,
            outage_start_hour=outage_start if outage else 99.0,
            recovery_time_hours=recovery if outage else 0.0,
            impaired_capacity_fraction=impaired_capacity,
            backup_capacity_fraction=backup_capacity, backup_activation_hours=backup_hours,
            post_recovery_capacity_fraction=post_recovery_capacity,
            prioritisation_factor=action_params["prioritisation_factor"],
            customers=customer_population, applications_affected=len(affected_applications), seed=self.bank.seed)
        backup_region = str(operational_cfg.get("backup_region", "Cloud Region B"))
        application_states = {
            "hour_0": json.loads(application_failover_states(
                self.bank.applications, affected_applications, source, backup_region, 0.0, recovery,
                backup_hours, backup_capacity).to_json(orient="records")),
            "backup_activation": json.loads(application_failover_states(
                self.bank.applications, affected_applications, source, backup_region, backup_hours, recovery,
                backup_hours, backup_capacity).to_json(orient="records")),
            "primary_recovery": json.loads(application_failover_states(
                self.bank.applications, affected_applications, source, backup_region, recovery, recovery,
                backup_hours, backup_capacity).to_json(orient="records")),
        } if outage else {}
        operational_loss = recovery * self.bank.assumptions["outage_loss_per_hour_bn"]
        operational_loss += operational.peak_backlog_bn * self.bank.assumptions["payment_backlog_loss_per_bn"]
        operational_loss += operational.customers_affected * self.bank.assumptions["customer_impact_cost_bn"]

        withdrawals = dict(shocks.get("withdrawal_rates", {}))
        if outage:
            impacts = propagated_impact(self.graph, source)
            outage_severity = 1.0 - operational.payment_availability
            for segment in ("Retail", "SME", "Corporate", "Private Banking"):
                if segment in impacts:
                    row = self.bank.customer_segments.set_index("segment").loc[segment]
                    withdrawals[segment] = withdrawals.get(segment, 0.0) + (
                        self.bank.assumptions["outage_withdrawal_response_rate"]
                        * outage_severity * impacts[segment] * row["outage_sensitivity"])
        if action_params["depositor_contact"]:
            withdrawals["Corporate"] = max(0.0, withdrawals.get("Corporate", 0.0) - .03)
        margin_call = market.total_market_loss_bn * self.bank.assumptions["margin_pressure_multiplier"]
        liquidity = calculate_liquidity(
            self.bank.customer_segments, self.bank.amount("cash_reserves"), self.bank.amount("securities"),
            withdrawals, margin_call, action_params["facility_draw_bn"], action_params["securities_sold_bn"],
            self.bank.assumptions["hqla_securities_haircut"], self.bank.assumptions["inflow_cap_bn"],
            self.bank.assumptions["liquidity_facility_annual_rate"], self.bank.assumptions["asset_sale_haircut"],
            self.bank.assumptions["emergency_funding_annual_rate"])
        baseline_liquidity = calculate_liquidity(
            self.bank.customer_segments, self.bank.amount("cash_reserves"), self.bank.amount("securities"),
            haircut=self.bank.assumptions["hqla_securities_haircut"],
            inflow_cap_bn=self.bank.assumptions["inflow_cap_bn"])
        lcr_bridge, lcr_validation = build_lcr_bridge(
            baseline_liquidity, liquidity, self.bank.amount("cash_reserves"),
            self.bank.amount("securities"), self.bank.assumptions["hqla_securities_haircut"],
            self.bank.assumptions["inflow_cap_bn"])

        credit_cfg = shocks.get("credit", {})
        credit = calculate_credit_impact(self.bank.counterparties, float(credit_cfg.get("pd_multiplier", 1.0)),
                                         credit_cfg.get("default_counterparty"),
                                         float(credit_cfg.get("default_loss_multiplier", 1.0)))
        credit_loss = credit.incremental_credit_loss_bn + credit.default_loss_bn
        liquidity_pnl_loss = liquidity.funding_cost_bn + liquidity.realised_asset_sale_loss_bn
        total_loss = market.total_market_loss_bn + credit_loss + operational_loss + liquidity_pnl_loss
        cet1 = max(0.0, self.bank.amount("cet1_capital") - total_loss)
        rwa = self.bank.amount("customer_loans") * self.bank.assumptions["risk_weight_density"]
        metrics = calculate_metrics(cash_bn=liquidity.stressed_cash_bn, hqla_bn=liquidity.hqla_bn,
            lcr=liquidity.lcr, cet1_bn=cet1, rwa_bn=rwa, market_loss_bn=market.total_market_loss_bn,
            credit_loss_bn=credit_loss, operational_loss_bn=operational_loss,
            liquidity_pnl_loss_bn=liquidity_pnl_loss,
            payment_availability=operational.payment_availability,
            payment_backlog_bn=operational.peak_backlog_bn, customers_affected=operational.customers_affected,
            applications_affected=operational.applications_affected, recovery_time_hours=operational.recovery_time_hours,
            deposit_outflow_bn=liquidity.deposit_outflow_bn, cash_consumed_bn=liquidity.cash_consumed_bn,
            hqla_consumed_bn=liquidity.hqla_consumed_bn,
            emergency_funding_requirement_bn=liquidity.funding_requirement_bn,
            funding_cost_bn=liquidity.funding_cost_bn, asset_liquidation_bn=liquidity.asset_liquidation_bn,
            realised_asset_sale_loss_bn=liquidity.realised_asset_sale_loss_bn)
        breaches = evaluate_risk_limits(metrics, self.bank.risk_limits)
        paths = trace_propagation_paths(self.graph, source, ["Liquidity Position", "Capital Position"]) if outage else []
        audit.extend([
            asdict(AuditEvent("liquidity", "deposit and margin stress", withdrawals, baseline["cash_position_bn"],
                              liquidity.stressed_cash_bn, "Segment deposits × shock × withdrawal sensitivity", name)),
            asdict(AuditEvent("credit", "credit stress", credit_cfg, 0.0, credit_loss,
                              "Incremental expected loss plus configured default loss", name)),
            asdict(AuditEvent("capital", "loss absorption", total_loss, baseline["cet1_capital_bn"], cet1,
                              "Prototype losses deducted from CET1", name)),
        ])
        trace = _build_propagation_trace(
            self.graph, name, shocks, baseline, metrics, market, liquidity, credit_loss,
            operational, withdrawals, operational_cfg, action_params)
        return ScenarioResult(
            scenario=name, baseline=baseline, metrics=metrics, shocks=shocks,
            impacts={
                "market_detail": market.detail.to_dict("records"),
                "liquidity_detail": liquidity.detail.to_dict("records"),
                "credit_detail": credit.detail.to_dict("records"),
                "margin_call_bn": margin_call,
                "liquidity_impact": {
                    "deposit_outflow_bn": liquidity.deposit_outflow_bn,
                    "cash_consumed_bn": liquidity.cash_consumed_bn,
                    "hqla_consumed_bn": liquidity.hqla_consumed_bn,
                    "lcr_deterioration": baseline["lcr"] - liquidity.lcr,
                    "emergency_funding_requirement_bn": liquidity.funding_requirement_bn,
                    "funding_cost_bn": liquidity.funding_cost_bn,
                    "asset_liquidation_bn": liquidity.asset_liquidation_bn,
                    "realised_asset_sale_loss_bn": liquidity.realised_asset_sale_loss_bn,
                    "liquidity_impact_is_not_pnl": True,
                    "liquidity_pnl_loss_bn": liquidity_pnl_loss,
                },
                "lcr_bridge": lcr_bridge.to_dict("records"),
                "lcr_validation_checks": lcr_validation.to_dict("records"),
                "operational_impact": {
                    "failed_region": source if outage else None,
                    "backup_region": operational_cfg.get("backup_region"),
                    "applications_affected": affected_applications,
                    "business_services_affected": affected_services,
                    "customer_segments_affected": affected_segments,
                    "financial_risk_nodes_affected": affected_financial_nodes,
                    "primary_recovery_time_hours": operational.primary_recovery_time_hours,
                    "backlog_clearance_time_hours": operational.backlog_clearance_time_hours,
                    "backlog_cleared": operational.backlog_cleared,
                    "application_failover_states": application_states,
                },
            },
            risk_limit_breaches=breaches, audit_log=audit, propagation_paths=paths,
            operational_timeseries=operational.timeseries, management_actions=actions,
            propagation_trace=trace)


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in updates.items():
        result[key] = _deep_merge(result.get(key, {}), value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def _action_parameters(actions: list[str]) -> dict[str, Any]:
    params = {"activate_backup": False, "prioritisation_factor": 1.0, "facility_draw_bn": 0.0,
              "securities_sold_bn": 0.0, "fx_hedge_increase": 0.0, "depositor_contact": False}
    for action in actions:
        normalized = action.lower().replace("_", " ")
        if "backup" in normalized: params["activate_backup"] = True
        elif "prioritise" in normalized or "prioritize" in normalized: params["prioritisation_factor"] = 1.25
        elif "liquidity facility" in normalized: params["facility_draw_bn"] += 3.0
        elif "sell liquid" in normalized: params["securities_sold_bn"] += 2.0
        elif "fx hedge" in normalized: params["fx_hedge_increase"] += .15
        elif "depositor" in normalized: params["depositor_contact"] = True
    return params


def _trace_event(path_id: str, sequence: int, source: str, target: str, dependency_type: str,
                 shock: Any, previous: Any, new: Any, effect: str, reason: str,
                 simulation_time: float | None = None) -> dict[str, Any]:
    return {
        "path_id": path_id, "sequence": sequence, "source_node": source,
        "target_node": target, "dependency_type": dependency_type, "shock": shock,
        "previous_value": previous, "new_value": new,
        "financial_or_operational_effect": effect, "reason": reason,
        "simulation_time": simulation_time,
    }


def _build_propagation_trace(graph: Any, scenario: str, shocks: dict[str, Any], baseline: dict[str, Any],
                             metrics: dict[str, Any], market: Any, liquidity: Any, credit_loss: float,
                             operational: Any, withdrawals: dict[str, float], operational_cfg: dict[str, Any],
                             action_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Create explicit events only for graph edges or deterministic calculation rules."""
    events: list[dict[str, Any]] = []
    fx_shock = float(shocks.get("fx", {}).get("USD", 0.0))
    if fx_shock:
        net_usd = float(market.detail.loc[market.detail["currency"] == "USD", "net_exposure_bn"].sum())
        market_path = [
            ("USD Shock", "FX Exposure", "revalues", 0.0, fx_shock, "USD spot shock applied"),
            ("FX Exposure", "Market P&L", "creates", 0.0, market.total_market_loss_bn, "Unhedged FX exposure creates market loss"),
            ("Market P&L", "Capital Position", "reduces", baseline["cet1_capital_bn"], metrics["cet1_capital_bn"], "Losses are absorbed by prototype CET1"),
            ("Capital Position", "CET1 Ratio", "determines", baseline["cet1_ratio"], metrics["cet1_ratio"], "CET1 divided by unchanged prototype RWA"),
        ]
        for seq, (source, target, dependency, previous, new, reason) in enumerate(market_path, 1):
            shock = {"usd_shock": fx_shock, "net_usd_exposure_bn": net_usd}
            events.append(_trace_event("market_to_capital", seq, source, target, dependency, shock,
                                       previous, new, "financial", reason))

    if float(shocks.get("volatility_multiplier", 1.0)) != 1.0:
        events.append(_trace_event("volatility_to_capital", 1, "Volatility Shock", "Market P&L", "creates",
            shocks["volatility_multiplier"], 0.0, market.volatility_loss_bn, "financial",
            "Configured volatility sensitivity creates deterministic market loss"))
        events.append(_trace_event("volatility_to_capital", 2, "Market P&L", "Capital Position", "reduces",
            shocks["volatility_multiplier"], baseline["cet1_capital_bn"], metrics["cet1_capital_bn"], "financial",
            "Total modeled losses reduce prototype CET1"))
        events.append(_trace_event("volatility_to_capital", 3, "Capital Position", "CET1 Ratio", "determines",
            shocks["volatility_multiplier"], baseline["cet1_ratio"], metrics["cet1_ratio"], "financial",
            "CET1 ratio follows calculated capital"))

    if withdrawals:
        detail = liquidity.detail.set_index("segment")
        for segment, rate in withdrawals.items():
            if segment not in detail.index or float(detail.loc[segment, "incremental_outflow_bn"]) <= 0:
                continue
            outflow = float(detail.loc[segment, "incremental_outflow_bn"])
            source = "Corporate Deposits" if segment == "Corporate" else segment
            events.append(_trace_event(f"{segment.lower().replace(' ', '_')}_liquidity", 1, source,
                "Deposit Outflows", "behaviour", rate, 0.0, outflow, "liquidity",
                "Segment deposits × withdrawal shock × configured sensitivity"))
            events.append(_trace_event(f"{segment.lower().replace(' ', '_')}_liquidity", 2, "Deposit Outflows",
                "Liquidity Position", "reduces", rate, baseline["cash_position_bn"], metrics["cash_position_bn"],
                "liquidity", "Incremental deposit outflows and margin calls consume cash"))
            events.append(_trace_event(f"{segment.lower().replace(' ', '_')}_liquidity", 3, "Liquidity Position",
                "LCR", "determines", rate, baseline["lcr"], metrics["lcr"], "liquidity",
                "Stressed HQLA divided by stressed net cash outflows"))

    if operational_cfg.get("enabled"):
        source = str(operational_cfg.get("failed_region", operational_cfg.get("source", "Cloud Region A")))
        graph_paths = trace_propagation_paths(graph, source, ["LCR"])
        if graph_paths:
            corporate_paths = [path for path in graph_paths if "Corporate" in path]
            path = min(corporate_paths or graph_paths, key=len)
            for seq, (left, right) in enumerate(zip(path, path[1:]), 1):
                dependency = graph[left][right].get("relationship", "depends_on")
                if right == "LCR": previous, new, effect = baseline["lcr"], metrics["lcr"], "liquidity"
                elif right == "Liquidity Position": previous, new, effect = baseline["cash_position_bn"], metrics["cash_position_bn"], "liquidity"
                elif right == "Deposit Outflows": previous, new, effect = 0.0, metrics["deposit_outflow_bn"], "liquidity"
                elif right in {"Retail", "SME", "Corporate", "Private Banking"}: previous, new, effect = 0, operational.customers_affected, "operational"
                else: previous, new, effect = 1.0, operational.payment_availability, "operational"
                events.append(_trace_event("operations_to_liquidity", seq, left, right, dependency,
                    operational_cfg, previous, new, effect, "Configured dependency edge transmits the operational shock",
                    float(operational_cfg.get("outage_start_hour", 0.0)) if seq == 1 else None))

    if credit_loss > 0:
        events.extend([
            _trace_event("credit_to_capital", 1, "Major Counterparty", "Credit Loss", "defaults",
                         shocks.get("credit", {}), 0.0, credit_loss, "financial", "PD stress and/or EAD × LGD default loss"),
            _trace_event("credit_to_capital", 2, "Credit Loss", "Capital Position", "reduces",
                         shocks.get("credit", {}), baseline["cet1_capital_bn"], metrics["cet1_capital_bn"],
                         "financial", "Credit loss is absorbed by prototype CET1"),
            _trace_event("credit_to_capital", 3, "Capital Position", "CET1 Ratio", "determines",
                         shocks.get("credit", {}), baseline["cet1_ratio"], metrics["cet1_ratio"],
                         "financial", "CET1 ratio follows calculated capital"),
        ])

    if not events:
        events.append(_trace_event("no_material_shock", 1, "Scenario Input", "Bank State", "evaluates",
                                   shocks, baseline["total_estimated_loss_bn"], metrics["total_estimated_loss_bn"],
                                   "financial_or_operational", "Scenario evaluated with no material configured shock"))
    return events

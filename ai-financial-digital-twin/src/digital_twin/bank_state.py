"""Core state and result containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class BankState:
    """Synthetic bank datasets and scalar assumptions, all in USD billions."""

    balance_sheet: pd.DataFrame
    fx_exposures: pd.DataFrame
    customer_segments: pd.DataFrame
    counterparties: pd.DataFrame
    applications: pd.DataFrame
    vendors: pd.DataFrame
    infrastructure: pd.DataFrame
    payment_systems: pd.DataFrame
    dependencies: pd.DataFrame
    risk_limits: dict[str, Any]
    assumptions: dict[str, Any]
    seed: int = 42

    def clone(self) -> "BankState":
        return BankState(
            **{name: getattr(self, name).copy(deep=True) for name in (
                "balance_sheet", "fx_exposures", "customer_segments", "counterparties",
                "applications", "vendors", "infrastructure", "payment_systems", "dependencies"
            )},
            risk_limits=dict(self.risk_limits),
            assumptions=dict(self.assumptions),
            seed=self.seed,
        )

    def amount(self, item: str) -> float:
        rows = self.balance_sheet.loc[self.balance_sheet["item"] == item, "amount_bn"]
        if rows.empty:
            raise KeyError(item)
        return float(rows.iloc[0])


@dataclass
class AuditEvent:
    component: str
    event: str
    input: Any
    previous_value: Any
    new_value: Any
    reason: str
    scenario: str
    timestamp: str = "T+0"


@dataclass
class ScenarioResult:
    scenario: str
    baseline: dict[str, float]
    metrics: dict[str, Any]
    shocks: dict[str, Any]
    impacts: dict[str, Any]
    risk_limit_breaches: list[dict[str, Any]]
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    propagation_paths: list[list[str]] = field(default_factory=list)
    operational_timeseries: pd.DataFrame = field(default_factory=pd.DataFrame)
    management_actions: list[str] = field(default_factory=list)
    propagation_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        output = {
            "scenario": self.scenario, "baseline": self.baseline, "metrics": self.metrics,
            "shocks": self.shocks, "impacts": self.impacts,
            "risk_limit_breaches": self.risk_limit_breaches, "audit_log": self.audit_log,
            "propagation_paths": self.propagation_paths,
            "propagation_trace": self.propagation_trace,
            "management_actions": self.management_actions,
        }
        if include_timeseries:
            output["operational_timeseries"] = self.operational_timeseries.to_dict(orient="records")
        return output

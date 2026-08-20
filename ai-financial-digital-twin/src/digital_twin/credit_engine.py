"""Simplified credit expected-loss and default-loss calculations."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class CreditImpact:
    baseline_expected_loss_bn: float
    stressed_expected_loss_bn: float
    incremental_credit_loss_bn: float
    default_loss_bn: float
    detail: pd.DataFrame


def expected_loss(ead_bn: float, pd_value: float, lgd: float) -> float:
    return ead_bn * pd_value * lgd


def calculate_credit_impact(counterparties: pd.DataFrame, pd_multiplier: float = 1.0,
                            default_counterparty: str | None = None,
                            default_loss_multiplier: float = 1.0) -> CreditImpact:
    detail = counterparties.copy()
    detail["baseline_el_bn"] = detail["ead_bn"] * detail["pd"] * detail["lgd"]
    detail["stressed_pd"] = (detail["pd"] * pd_multiplier).clip(upper=1.0)
    detail["stressed_el_bn"] = detail["ead_bn"] * detail["stressed_pd"] * detail["lgd"]
    baseline = float(detail["baseline_el_bn"].sum())
    stressed = float(detail["stressed_el_bn"].sum())
    default_loss = 0.0
    if default_counterparty:
        target = detail[detail["counterparty_id"] == default_counterparty]
        if target.empty:
            raise ValueError(f"Unknown counterparty: {default_counterparty}")
        default_loss = float((target["ead_bn"] * target["lgd"]).iloc[0]) * default_loss_multiplier
    return CreditImpact(baseline, stressed, max(0.0, stressed - baseline), default_loss, detail)

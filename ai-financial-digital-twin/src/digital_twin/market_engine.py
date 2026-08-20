"""Simplified deterministic market-risk calculations."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class MarketImpact:
    fx_pnl_bn: float
    volatility_loss_bn: float
    total_market_loss_bn: float
    detail: pd.DataFrame


def revalue_fx(exposures: pd.DataFrame, shocks: dict[str, float]) -> tuple[float, pd.DataFrame]:
    detail = exposures.copy()
    detail["shock"] = detail["currency"].map(shocks).fillna(0.0)
    detail["net_exposure_bn"] = detail["gross_exposure_bn"] * (1.0 - detail["hedge_ratio"])
    detail["pnl_bn"] = detail["net_exposure_bn"] * detail["shock"]
    return float(detail["pnl_bn"].sum()), detail


def calculate_market_impact(exposures: pd.DataFrame, fx_shocks: dict[str, float] | None = None,
                            volatility_multiplier: float = 1.0,
                            volatility_sensitivity: float = 0.12) -> MarketImpact:
    pnl, detail = revalue_fx(exposures, fx_shocks or {})
    volatility_loss = max(0.0, volatility_multiplier - 1.0) * volatility_sensitivity
    total_loss = max(0.0, -pnl) + volatility_loss
    return MarketImpact(pnl, volatility_loss, total_loss, detail)


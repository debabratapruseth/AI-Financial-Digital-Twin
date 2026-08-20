import pandas as pd
import pytest
from digital_twin.liquidity_engine import calculate_lcr, calculate_liquidity


def test_lcr_formula():
    assert calculate_lcr(12, 10) == pytest.approx(1.2)


def test_segment_deposit_stress():
    segments = pd.DataFrame([{"segment": "Retail", "deposits_bn": 10, "baseline_outflow_rate": .05,
                              "withdrawal_sensitivity": .5}])
    result = calculate_liquidity(segments, 2, 5, {"Retail": .10}, inflow_cap_bn=0)
    assert result.incremental_outflows_bn == pytest.approx(.5)
    assert result.stressed_cash_bn == pytest.approx(1.5)
    assert result.deposit_outflow_bn == pytest.approx(.5)
    assert result.cash_consumed_bn == pytest.approx(.5)
    assert result.hqla_consumed_bn == pytest.approx(.5)
    assert result.funding_cost_bn == 0
    assert result.realised_asset_sale_loss_bn == 0


def test_asset_sale_reports_liquidity_and_pnl_separately():
    segments = pd.DataFrame([{"segment": "Retail", "deposits_bn": 10, "baseline_outflow_rate": .05,
                              "withdrawal_sensitivity": .5}])
    result = calculate_liquidity(segments, 2, 5, {"Retail": .10}, securities_sold_bn=1,
                                 inflow_cap_bn=0, asset_sale_haircut=.02)
    assert result.asset_liquidation_bn == 1
    assert result.asset_sale_proceeds_bn == pytest.approx(.98)
    assert result.realised_asset_sale_loss_bn == pytest.approx(.02)

import pandas as pd
import pytest
from digital_twin.market_engine import revalue_fx


def test_fx_shock_respects_hedge():
    frame = pd.DataFrame([{"currency": "USD", "gross_exposure_bn": 10.0, "hedge_ratio": .6}])
    pnl, detail = revalue_fx(frame, {"USD": -.10})
    assert pnl == pytest.approx(-.4)
    assert detail.iloc[0]["net_exposure_bn"] == pytest.approx(4.0)


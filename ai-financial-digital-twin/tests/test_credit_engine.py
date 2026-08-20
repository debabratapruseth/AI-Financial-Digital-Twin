import pandas as pd
import pytest
from digital_twin.credit_engine import calculate_credit_impact, expected_loss


def test_expected_and_default_loss():
    assert expected_loss(10, .02, .4) == pytest.approx(.08)
    cp = pd.DataFrame([{"counterparty_id": "X", "ead_bn": 2, "pd": .01, "lgd": .5}])
    impact = calculate_credit_impact(cp, default_counterparty="X")
    assert impact.default_loss_bn == pytest.approx(1.0)


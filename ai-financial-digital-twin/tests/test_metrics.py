from digital_twin.metrics import evaluate_risk_limits


def test_risk_limit_breaches_both_directions():
    limits = {"lcr": {"warning": 1.1, "critical": 1.0, "direction": "min"},
              "loss": {"warning": 1.0, "critical": 2.0, "direction": "max"}}
    breaches = evaluate_risk_limits({"lcr": .9, "loss": 1.5}, limits)
    assert [(b["metric"], b["level"]) for b in breaches] == [("lcr", "critical"), ("loss", "warning")]


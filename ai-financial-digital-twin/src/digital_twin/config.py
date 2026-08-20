"""Configuration loading with repository-relative defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_yaml(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = project_root() / resolved
    if not resolved.exists():
        raise FileNotFoundError(f"Configuration not found: {resolved}")
    with resolved.open(encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    if not isinstance(content, dict):
        raise ValueError(f"Expected a YAML mapping in {resolved}")
    return content


def load_baseline(path: str | Path = "configs/baseline_bank.yaml") -> dict[str, Any]:
    return load_yaml(path)


def load_risk_limits(path: str | Path = "configs/risk_limits.yaml") -> dict[str, Any]:
    return load_yaml(path)


def load_scenario(name_or_path: str | Path) -> dict[str, Any]:
    path = Path(name_or_path)
    if path.suffix not in {".yaml", ".yml"}:
        path = Path("configs/scenarios") / f"{path}.yaml"
    return load_yaml(path)


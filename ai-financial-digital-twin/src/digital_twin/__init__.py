"""AI Financial Digital Twin: synthetic bank stress-testing prototype."""

from .bank_state import BankState, ScenarioResult
from .data_generator import generate_virtual_bank
from .scenario_engine import ScenarioEngine

__all__ = ["BankState", "ScenarioResult", "ScenarioEngine", "generate_virtual_bank"]
__version__ = "0.1.0"


from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True, frozen=True)
class ActionPolicy:
    action: str
    risk: RiskLevel
    confirmation_required: bool


class SecurityPolicy:
    """Ponto central para autorizações antes de ações externas."""

    _DEFAULTS = {
        "open_app": RiskLevel.LOW,
        "open_url": RiskLevel.LOW,
        "open_path": RiskLevel.MEDIUM,
        "web_search": RiskLevel.LOW,
        "read_file": RiskLevel.LOW,
        "list_files": RiskLevel.LOW,
        "write_file": RiskLevel.MEDIUM,
        "run_python": RiskLevel.MEDIUM,
        "code_workspace": RiskLevel.MEDIUM,
        "run_tests": RiskLevel.MEDIUM,
        "file_manager": RiskLevel.MEDIUM,
        "scheduler": RiskLevel.MEDIUM,
        "system_control": RiskLevel.HIGH,
    }

    def assess(self, action: str) -> ActionPolicy:
        risk = self._DEFAULTS.get(action, RiskLevel.HIGH)
        return ActionPolicy(
            action=action,
            risk=risk,
            confirmation_required=risk in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )

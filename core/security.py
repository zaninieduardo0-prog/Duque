from __future__ import annotations

import os
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
        "write_file": RiskLevel.HIGH,
        "delete_file": RiskLevel.HIGH,
        "run_python": RiskLevel.MEDIUM,
        "ui_click": RiskLevel.MEDIUM,
        "screen_click_text": RiskLevel.MEDIUM,
        "ui_type_text": RiskLevel.MEDIUM,
        "ui_press": RiskLevel.MEDIUM,
        "ui_hotkey": RiskLevel.MEDIUM,
        "screenshot": RiskLevel.LOW,
        "screen_snapshot": RiskLevel.LOW,
        "screen_find": RiskLevel.LOW,
        "screen_contains_text": RiskLevel.LOW,
        "code_workspace": RiskLevel.MEDIUM,
        "run_tests": RiskLevel.MEDIUM,
        "file_manager": RiskLevel.MEDIUM,
        "scheduler": RiskLevel.MEDIUM,
        "schedule_task": RiskLevel.MEDIUM,
        "reminder": RiskLevel.MEDIUM,
        "system_control": RiskLevel.HIGH,
    }

    def assess(self, action: str) -> ActionPolicy:
        # Auto-modificação só pode ocorrer quando o usuário habilitou
        # explicitamente o modo de desenvolvimento autônomo.
        if action == "write_file" and os.getenv("DUQUE_ALLOW_SELF_MODIFICATION", "0").casefold() in {"1", "true", "yes", "on"}:
            risk = RiskLevel.MEDIUM
        else:
            # Ferramentas sem classificação explícita recebem risco médio.
            risk = self._DEFAULTS.get(action, RiskLevel.MEDIUM)
        return ActionPolicy(
            action=action,
            risk=risk,
            confirmation_required=risk in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )

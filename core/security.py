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
        "open_search_result": RiskLevel.LOW,
        "read_file": RiskLevel.LOW,
        "list_files": RiskLevel.LOW,
        "write_file": RiskLevel.MEDIUM,
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
        "git_push": RiskLevel.HIGH,
        "git_commit": RiskLevel.MEDIUM,
        "git_pull": RiskLevel.MEDIUM,
        "git_fetch": RiskLevel.LOW,
        "git_log": RiskLevel.LOW,
        "system_info": RiskLevel.LOW,
        "environment": RiskLevel.LOW,
        "list_directory": RiskLevel.LOW,
        "read_any_file": RiskLevel.LOW,
        "write_any_file": RiskLevel.HIGH,
        "delete_any_file": RiskLevel.HIGH,
        "copy_path": RiskLevel.HIGH,
        "move_path": RiskLevel.HIGH,
        "run_command": RiskLevel.HIGH,
        "list_processes": RiskLevel.LOW,
        "kill_process": RiskLevel.HIGH,
    }

    def assess(self, action: str) -> ActionPolicy:
        # Ferramentas registradas que ainda não possuem uma classificação
        # explícita recebem risco médio. A confirmação fica reservada às
        # ações realmente classificadas como HIGH/CRITICAL.
        risk = self._DEFAULTS.get(action, RiskLevel.MEDIUM)
        return ActionPolicy(
            action=action,
            risk=risk,
            confirmation_required=risk in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )

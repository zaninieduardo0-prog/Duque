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
        "close_app": RiskLevel.MEDIUM,
        "is_app_running": RiskLevel.LOW,
        "open_url": RiskLevel.LOW,
        "open_path": RiskLevel.MEDIUM,
        "web_search": RiskLevel.LOW,
        "open_search_result": RiskLevel.LOW,
        "read_file": RiskLevel.LOW,
        "read_many_files": RiskLevel.LOW,
        "list_files": RiskLevel.LOW,
        "inspect_workspace": RiskLevel.LOW,
        "write_file": RiskLevel.MEDIUM,
        "delete_file": RiskLevel.HIGH,
        # Executa código arbitrário do workspace.
        "run_python": RiskLevel.HIGH,
        "run_tests": RiskLevel.MEDIUM,
        "ui_click": RiskLevel.MEDIUM,
        "screen_click_text": RiskLevel.MEDIUM,
        "ui_type_text": RiskLevel.MEDIUM,
        "ui_press": RiskLevel.MEDIUM,
        "ui_hotkey": RiskLevel.MEDIUM,
        "screenshot": RiskLevel.LOW,
        "screen_snapshot": RiskLevel.LOW,
        "screen_find": RiskLevel.LOW,
        "screen_contains_text": RiskLevel.LOW,
        "schedule_task": RiskLevel.MEDIUM,
        "schedule_reminder": RiskLevel.LOW,
        "list_scheduled_jobs": RiskLevel.LOW,
        "cancel_scheduled_job": RiskLevel.MEDIUM,
        "git_status": RiskLevel.LOW,
        "git_diff": RiskLevel.LOW,
        "git_log": RiskLevel.LOW,
        "git_fetch": RiskLevel.LOW,
        "git_pull": RiskLevel.HIGH,
        "git_commit": RiskLevel.HIGH,
        "git_push": RiskLevel.HIGH,
        "system_info": RiskLevel.LOW,
        "environment": RiskLevel.LOW,
        "list_directory": RiskLevel.LOW,
        "read_any_file": RiskLevel.MEDIUM,
        "write_any_file": RiskLevel.HIGH,
        "delete_any_file": RiskLevel.HIGH,
        "copy_path": RiskLevel.HIGH,
        "move_path": RiskLevel.HIGH,
        "run_command": RiskLevel.HIGH,
        "list_processes": RiskLevel.LOW,
        "kill_process": RiskLevel.HIGH,
        # Ferramentas da Forja: só atuam na cópia isolada (worktree) do projeto.
        "edit_file": RiskLevel.MEDIUM,
        "search_code": RiskLevel.LOW,
        "run_checks": RiskLevel.MEDIUM,
        "show_diff": RiskLevel.LOW,
    }

    def __init__(self, default: RiskLevel = RiskLevel.HIGH) -> None:
        self.default = default

    def assess(self, action: str) -> ActionPolicy:
        # Ferramenta sem classificação explícita exige confirmação: uma
        # ferramenta nova nunca nasce liberada por esquecimento.
        risk = self._DEFAULTS.get(action, self.default)
        return ActionPolicy(
            action=action,
            risk=risk,
            confirmation_required=risk in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )

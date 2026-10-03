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
        # Commits na instalação ao vivo exigem confirmação; o caminho normal de
        # auto-desenvolvimento é a Forja (cópia isolada + CI + rollback).
        "git_commit": RiskLevel.HIGH,
        "apply_code_change": RiskLevel.HIGH,
        "forge_improve": RiskLevel.MEDIUM,
        "forge_status": RiskLevel.LOW,
        # ferramentas do dia a dia
        "current_time": RiskLevel.LOW,
        "weather": RiskLevel.LOW,
        "calculate": RiskLevel.LOW,
        "note_add": RiskLevel.LOW,
        "notes_list": RiskLevel.LOW,
        "note_delete": RiskLevel.MEDIUM,
        "timer_set": RiskLevel.LOW,
        "timers_list": RiskLevel.LOW,
        "timer_cancel": RiskLevel.LOW,
        "media": RiskLevel.LOW,
        "volume": RiskLevel.LOW,
        "clipboard_read": RiskLevel.LOW,
        "clipboard_write": RiskLevel.MEDIUM,
        "lock_screen": RiskLevel.MEDIUM,
        "system_status": RiskLevel.LOW,
        "open_folder": RiskLevel.LOW,
        "find_files": RiskLevel.LOW,
        "youtube": RiskLevel.LOW,
        "spotify": RiskLevel.LOW,
        "maps": RiskLevel.LOW,
        "reminder_at": RiskLevel.LOW,
        "reminders_list": RiskLevel.LOW,
        "reminder_cancel": RiskLevel.LOW,
        "focus_mode": RiskLevel.LOW,
        "describe_screen": RiskLevel.LOW,
        "routine_run": RiskLevel.LOW,
        "routine_save": RiskLevel.LOW,
        "routines_list": RiskLevel.LOW,
        "routine_delete": RiskLevel.LOW,
        "contact_save": RiskLevel.LOW,
        "contacts_list": RiskLevel.LOW,
        "whatsapp_message": RiskLevel.LOW,
        "day_summary": RiskLevel.LOW,
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

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
        # Web (computer/web_tools.py): leitura com bloqueio de endereços internos.
        "read_webpage": RiskLevel.LOW,
        "page_links": RiskLevel.LOW,
        "check_url": RiskLevel.LOW,
        "download_file": RiskLevel.MEDIUM,
        # Rascunhos (computer/compose_links.py): só abrem prontos; o Du confere e envia.
        "email_compose": RiskLevel.LOW,
        "calendar_event": RiskLevel.LOW,
        "share_text": RiskLevel.LOW,
        "whatsapp_read": RiskLevel.LOW,
        "open_app": RiskLevel.LOW,
        "close_app": RiskLevel.MEDIUM,
        "is_app_running": RiskLevel.LOW,
        "open_url": RiskLevel.LOW,
        # Abrir um caminho qualquer equivale a executar (.exe, .bat, .lnk...).
        "open_path": RiskLevel.HIGH,
        "web_search": RiskLevel.LOW,
        "google_search": RiskLevel.LOW,
        "open_search_result": RiskLevel.LOW,
        "read_file": RiskLevel.LOW,
        "read_many_files": RiskLevel.LOW,
        "inspect_workspace": RiskLevel.LOW,
        "list_files": RiskLevel.LOW,
        "write_file": RiskLevel.MEDIUM,
        "delete_file": RiskLevel.HIGH,
        # Executa código arbitrário (o modelo pode escrevê-lo antes com write_file).
        "run_python": RiskLevel.HIGH,
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
        "set_voice": RiskLevel.LOW,
        "list_voices": RiskLevel.LOW,
        # Atualiza o código da instalação ao vivo (o caminho seguro é a Forja).
        "git_pull": RiskLevel.HIGH,
        "git_fetch": RiskLevel.LOW,
        "git_log": RiskLevel.LOW,
        "git_status": RiskLevel.LOW,
        "git_diff": RiskLevel.LOW,
        "system_info": RiskLevel.LOW,
        "environment": RiskLevel.LOW,
        "list_directory": RiskLevel.LOW,
        # Lê qualquer arquivo do PC (inclusive credenciais); fica registrado como médio.
        "read_any_file": RiskLevel.MEDIUM,
        "write_any_file": RiskLevel.HIGH,
        "delete_any_file": RiskLevel.HIGH,
        "copy_path": RiskLevel.HIGH,
        "move_path": RiskLevel.HIGH,
        "run_command": RiskLevel.HIGH,
        "list_processes": RiskLevel.LOW,
        "kill_process": RiskLevel.HIGH,
        "click_on": RiskLevel.MEDIUM,
        "volume_set": RiskLevel.LOW,
        "whatsapp_web_open": RiskLevel.LOW,
        "wait": RiskLevel.LOW,
        "chrome_profiles": RiskLevel.LOW,
        "youtube_play": RiskLevel.LOW,
        "notepad_write": RiskLevel.LOW,
        "compose_text": RiskLevel.LOW,
        "whatsapp_send": RiskLevel.MEDIUM,
    }

    def __init__(self, default: RiskLevel = RiskLevel.MEDIUM) -> None:
        # Risco de uma ferramenta sem classificação explícita. O padrão continua
        # MEDIUM (sem confirmação) por compatibilidade; o AgentLoop deve usar
        # SecurityPolicy(default=RiskLevel.HIGH) para que uma ferramenta nova
        # nunca nasça liberada por esquecimento.
        self.default = default

    def known(self, action: str) -> bool:
        return action in self._DEFAULTS

    @classmethod
    def declare(cls, risks: dict[str, str]) -> None:
        """Risco declarado por um módulo de ferramentas ("low"/"medium"/"high").

        Fica na tabela da classe (vale para toda política criada depois) e nunca
        rebaixa uma classificação já definida aqui.
        """
        for name, level in risks.items():
            cls._DEFAULTS.setdefault(name, RiskLevel(str(level).casefold()))

    def assess(self, action: str) -> ActionPolicy:
        risk = self._DEFAULTS.get(action, self.default)
        return ActionPolicy(
            action=action,
            risk=risk,
            confirmation_required=risk in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )

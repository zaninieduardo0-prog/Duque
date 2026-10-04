from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.task_engine import StepResult, TaskEngine
from core.tasks import Task


@dataclass(slots=True)
class CorrectionReport:
    success: bool
    attempts: int
    results: list[StepResult]
    last_error: str | None = None
    # Etapas da última tentativa (as que realmente rodaram), para retomar uma
    # confirmação exatamente do ponto em que parou, sem refazer o que já deu certo.
    last_steps: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


# Ações com efeito visível (abrir app, site, mensagem): repetir depois de uma
# falha abria a mesma coisa várias vezes. Elas rodam uma vez só.
NO_RETRY_TOOLS = frozenset({
    "open_app", "open_url", "open_path", "open_folder", "google_search", "open_search_result",
    "whatsapp_message", "whatsapp_send", "whatsapp_web_open", "media_control", "play_media", "spotify_play",
    "youtube_play", "spotify", "maps", "media", "volume", "close_app", "kill_process", "lock_screen",
    "notepad_write", "note_add", "timer_set", "reminder_at", "schedule_task", "routine_run",
    "focus_mode", "forge_improve", "click_on", "clipboard_write",
})
# Abrem janelas/abas ou mexem na tela: se uma delas já rodou nesta tentativa, um plano
# novo do modelo quase sempre a repetiria com outro nome ("Chrome" x "chrome").
VISIBLE_TOOLS = frozenset({
    "open_app", "open_url", "open_path", "open_folder", "google_search", "open_search_result",
    "whatsapp_message", "whatsapp_send", "whatsapp_web_open", "youtube_play", "spotify", "maps",
    "notepad_write", "click_on",
})
# Ferramentas de interface: mesmo "falhando" na verificação (a tela não mudou),
# o clique/digitação aconteceu; repetir duplica texto e cliques.
UI_TOOLS = frozenset({"ui_click", "ui_type_text", "ui_press", "ui_hotkey", "screen_click_text"})
# Comandos que rodaram e devolveram um resultado (ex.: testes falhando) já são a
# resposta; repeti-los só gasta tempo e repete efeitos colaterais.
COMMAND_TOOLS = frozenset({"run_tests", "run_python", "run_command"})


def step_key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
    return tool, repr(sorted((arguments or {}).items()))


def _ran(tool: str, result: Any) -> bool:
    """A ferramenta chegou a agir (mesmo que o resultado final seja uma falha)?"""
    if result.success:
        return True
    if tool in UI_TOOLS and result.verification is not None:
        return True
    return False


class SelfCorrection:
    """Laço simples de executar -> observar erro -> pedir nova tentativa."""

    def __init__(self, task_engine: TaskEngine) -> None:
        self.task_engine = task_engine

    def run(
        self,
        task: Task,
        steps_factory: Callable[[str | None, int], list[tuple[str, dict[str, Any]]]],
        *,
        max_attempts: int = 3,
        confirmed: bool = False,
    ) -> CorrectionReport:
        error: str | None = None
        all_results: list[StepResult] = []
        attempts_limit = max(1, max_attempts)
        # Etapas que já deram certo numa tentativa anterior: não rodam de novo
        # (reabrir apps, redigitar texto e duplicar notas era o "Duque perdido").
        done: set[tuple[str, str]] = set()

        for attempt in range(1, attempts_limit + 1):
            planned = steps_factory(error, attempt)
            steps = [(tool, arguments) for tool, arguments in planned if step_key(tool, arguments) not in done]
            if not steps:
                if attempt > 1:
                    return CorrectionReport(False, attempt, all_results, error)
                return CorrectionReport(False, attempt, all_results, "O plano não contém etapas executáveis")

            # A confirmação do usuário vale só para o plano que ele aprovou; um
            # plano corrigido pelo modelo precisa pedir confirmação de novo.
            results = self.task_engine.run(task, steps, confirmed=confirmed and attempt == 1)
            all_results.extend(results)
            for item, (tool, arguments) in zip(results, steps):
                if item.result.success:
                    done.add(step_key(tool, arguments))

            if self.task_engine.succeeded(results):
                return CorrectionReport(True, attempt, all_results, last_steps=steps)

            failed = next((item for item in reversed(results) if not item.result.success), None)
            error = failed.result.error if failed else "Falha sem detalhes"

            if failed is None:
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)
            if failed.result.confirmation_required:
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)
            if failed.tool in NO_RETRY_TOOLS or (failed.tool in UI_TOOLS and _ran(failed.tool, failed.result)):
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)
            if failed.tool in COMMAND_TOOLS and failed.result.value is not None:
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)
            if any(item.tool in VISIBLE_TOOLS | UI_TOOLS for item in results if item is not failed):
                # Uma etapa com efeito visível já rodou nesta tentativa; um plano novo
                # quase sempre a repetiria (outra janela, outra mensagem).
                return CorrectionReport(False, attempt, all_results, error, last_steps=steps)

        return CorrectionReport(False, attempts_limit, all_results, error)

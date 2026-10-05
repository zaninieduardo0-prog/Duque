"""Pequenas garantias de estabilidade na camada de interação.

Este módulo só normaliza a resposta final de sequências quando o usuário
explicitamente pede uma confirmação curta. A execução das etapas continua
sendo responsabilidade do AgentLoop original.
"""
from __future__ import annotations

import re
from typing import Any


def _wants_short_confirmation(text: str) -> bool:
    normalized = " ".join((text or "").casefold().split())
    return bool(re.search(
        r"\b(?:apenas|s[oó]|somente)\s+(?:me\s+)?(?:confirme|informe|diga)\b|"
        r"\b(?:s[oó]|somente)\s+(?:me\s+)?(?:confirme|informe|diga)\s+(?:se|que)\b",
        normalized,
    ))


def _sequence_succeeded(text: str) -> bool:
    normalized = " ".join((text or "").casefold().split())
    return not re.search(
        r"\b(?:na etapa|não consegui|nao consegui|não consigo|nao consigo|pulei a etapa)\b",
        normalized,
    )


def install() -> None:
    from .agent_loop import AgentLoop, AgentResult

    if getattr(AgentLoop, "_duque_stability_patch", False):
        return

    original = AgentLoop._handle_sequence

    def handle_sequence(self: Any, steps: list[str], *, confirmed: bool, max_attempts: int):
        # O método original continua responsável por executar e verificar tudo.
        result = original(self, steps, confirmed=confirmed, max_attempts=max_attempts)
        if (
            result.execution is not None
            and result.execution.success
            and _wants_short_confirmation(" ".join(steps))
            and _sequence_succeeded(result.text)
        ):
            return AgentResult("Tarefa finalizada.", result.task_id, result.execution, result.attempts)
        return result

    AgentLoop._handle_sequence = handle_sequence
    AgentLoop._duque_stability_patch = True

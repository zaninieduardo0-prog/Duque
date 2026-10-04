from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .verification import Verification
from .verified_ui import VerifiedScreenActions


@dataclass(slots=True, frozen=True)
class VisualStep:
    """Uma etapa de automação guiada pela tela."""

    action: str
    target: str | None = None
    value: str | None = None
    min_confidence: float = 0.65


@dataclass(slots=True, frozen=True)
class VisualStepResult:
    index: int
    step: VisualStep
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class VisualWorkflow:
    """Executa sequências pequenas de ações visuais com falha explícita."""

    def __init__(self, actions: VerifiedScreenActions, verification: Verification) -> None:
        self.actions = actions
        self.verification = verification

    def run(
        self,
        steps: list[VisualStep],
        *,
        on_step: Callable[[VisualStepResult], Any] | None = None,
    ) -> list[VisualStepResult]:
        results: list[VisualStepResult] = []
        for index, step in enumerate(steps, start=1):
            try:
                result = self._run_step(step)
                item = VisualStepResult(index, step, True, result=result)
            except Exception as exc:
                item = VisualStepResult(index, step, False, error=f"{type(exc).__name__}: {exc}")
                results.append(item)
                if on_step:
                    on_step(item)
                break
            results.append(item)
            if on_step:
                on_step(item)
        return results

    def _run_step(self, step: VisualStep) -> dict[str, Any]:
        if step.action == "click_text":
            if not step.target:
                raise ValueError("click_text exige target")
            result = self.actions.click_text(step.target, step.min_confidence)
            # click_text não levanta depois de clicar (evita clique em dobro); aqui a
            # sequência para quando o clique visivelmente não fez nada.
            status = str((result.get("verification") or {}).get("status", ""))
            if status in {"not_changed", "failed"}:
                raise RuntimeError(str(result["verification"].get("reason") or "O clique não teve efeito visível"))
            return result
        if step.action == "type_text":
            if step.value is None:
                raise ValueError("type_text exige value")
            self.actions.controller.type_text(step.value)
            return {"typed": True, "length": len(step.value)}
        if step.action == "press":
            if not step.target:
                raise ValueError("press exige target")
            self.actions.controller.press(step.target)
            return {"pressed": step.target}
        raise ValueError(f"Ação visual não suportada: {step.action}")

    @staticmethod
    def succeeded(results: list[VisualStepResult]) -> bool:
        return bool(results) and all(item.success for item in results)

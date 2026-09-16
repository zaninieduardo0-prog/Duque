from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class ObservationContext:
    """Estado observado do ambiente durante uma tarefa."""

    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentContext:
    """Contexto de execução que acompanha uma meta do início ao fim."""

    goal: str
    task_id: str
    observations: list[ObservationContext] = field(default_factory=list)
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)

    def observe(self, data: dict[str, Any]) -> ObservationContext:
        observation = ObservationContext(data=data)
        self.observations.append(observation)
        return observation

    def record_step(self, **data: Any) -> None:
        self.completed_steps.append(data)

    def record_failure(self, error: str) -> None:
        self.failures.append(error)

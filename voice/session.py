from __future__ import annotations

from threading import Lock
from typing import Any

FAREWELLS = (
    "até mais duque", "até logo duque", "tchau duque", "pode dormir duque",
    "até mais, duque", "até logo, duque", "tchau, duque", "pode dormir, duque",
)

# Erros do Realtime que só dizem "não havia resposta para cancelar/criar":
# acontecem em toda interrupção e não significam que a sessão quebrou.
BENIGN_ERROR_CODES = frozenset({
    "response_cancel_not_active",
    "conversation_already_has_active_response",
    "input_audio_buffer_commit_empty",
    "item_truncate_invalid_item_id",
    "invalid_item_id",
})
BENIGN_ERROR_MESSAGES = (
    "no active response",
    "already has an active response",
    "cancellation failed",
    "buffer too small",
)

# Erros que tornam a sessão inútil. Falhas de transporte (WebSocket caiu) não
# chegam como evento "error": o SDK as levanta ao iterar a sessão.
FATAL_ERROR_CODES = frozenset({
    "session_expired",
    "invalid_api_key",
    "insufficient_quota",
    "model_not_found",
})
FATAL_ERROR_TYPES = frozenset({"authentication_error", "permission_error"})
FATAL_ERROR_MESSAGES = (
    "session expired",
    "maximum duration",
    "connection closed",
)


class PlaybackFence:
    """Barreira de sessão: áudio de uma sessão encerrada nunca toca na próxima.

    Cada sessão recebe uma geração; callbacks atrasados carregam a geração
    antiga e são descartados.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._generation = 0
        self._active = False

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def new_session(self) -> int:
        with self._lock:
            self._generation += 1
            self._active = True
            return self._generation

    def accepts(self, generation: int) -> bool:
        with self._lock:
            return self._active and generation == self._generation

    def close(self) -> None:
        with self._lock:
            self._active = False


def is_farewell(text: str) -> bool:
    normalized = " ".join((text or "").casefold().split())
    return any(phrase in normalized for phrase in FAREWELLS)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def error_details(error: Any) -> tuple[str, str, str]:
    """Extrai (tipo, código, mensagem) de um erro do Realtime, aninhado ou não."""
    kind = code = message = ""
    current = error
    for _ in range(4):
        if current is None or isinstance(current, (str, bytes)):
            break
        kind = str(_field(current, "type") or kind)
        code = str(_field(current, "code") or code)
        message = str(_field(current, "message") or message)
        current = _field(current, "error")
    if not message:
        message = str(error or "")
    return kind, code, message


def is_benign_error(error: Any) -> bool:
    _kind, code, message = error_details(error)
    if code in BENIGN_ERROR_CODES:
        return True
    lowered = message.casefold()
    return any(fragment in lowered for fragment in BENIGN_ERROR_MESSAGES)


def is_fatal_error(error: Any) -> bool:
    """Só erros de sessão/credencial encerram a conversa.

    Os demais (requisição inválida, falha de uma resposta, erro interno do SDK
    numa ferramenta) afetam um evento, não a sessão.
    """
    if is_benign_error(error):
        return False
    kind, code, message = error_details(error)
    if code in FATAL_ERROR_CODES or kind in FATAL_ERROR_TYPES:
        return True
    lowered = message.casefold()
    return any(fragment in lowered for fragment in FATAL_ERROR_MESSAGES)

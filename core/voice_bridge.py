"""Ponte entre o núcleo (servidor/AgentLoop) e o runtime de voz.

Os dois rodam no mesmo processo quando o Duque é iniciado pelo duque.py, mas
um não importa o outro: cada lado se registra aqui. Isso mantém o servidor
testável sem microfone e a voz funcionando mesmo se o servidor mudar.
"""

from __future__ import annotations

import json
import urllib.request
from threading import RLock
from typing import Any, Callable

SERVER = "http://127.0.0.1:5000"


class VoiceBridge:
    def __init__(self) -> None:
        self._lock = RLock()
        self._send_text: Callable[[str], bool] | None = None
        self._stop_speech: Callable[[], None] | None = None
        self._executor: Callable[[str], str] | None = None
        self._recorder: Callable[[str, str, str], Any] | None = None
        self._context: Callable[[], str] | None = None
        self._memories: Callable[[], str] | None = None
        self._voice: Callable[[], str] | None = None

    # lado da voz ------------------------------------------------------------
    def attach_session(self, send_text: Callable[[str], bool], stop_speech: Callable[[], None] | None = None) -> None:
        with self._lock:
            self._send_text = send_text
            self._stop_speech = stop_speech

    def detach_session(self) -> None:
        with self._lock:
            self._send_text = None
            self._stop_speech = None

    @property
    def voice_active(self) -> bool:
        with self._lock:
            return self._send_text is not None

    def stop_speech(self) -> bool:
        """Interrompe a fala da conversa de voz ("stop" digitado no HUD)."""
        with self._lock:
            stopper = self._stop_speech
        if stopper is None:
            return False
        try:
            stopper()
            return True
        except Exception:
            return False

    def send_to_voice(self, text: str) -> bool:
        """Entrega texto digitado à sessão de voz ativa (resposta sai falada nela)."""
        with self._lock:
            sender = self._send_text
        if sender is None:
            return False
        try:
            return bool(sender(text))
        except Exception:
            return False

    # lado do núcleo -----------------------------------------------------------
    def attach_core(
        self,
        *,
        executor: Callable[[str], str],
        recorder: Callable[[str, str, str], Any],
        context: Callable[[], str],
        memories: Callable[[], str] | None = None,
        voice: Callable[[], str] | None = None,
    ) -> None:
        with self._lock:
            self._executor = executor
            self._recorder = recorder
            self._context = context
            self._memories = memories
            self._voice = voice

    def execute(self, request: str) -> str:
        """Executa um pedido pelo cérebro do Duque (usado pelas ferramentas da voz)."""
        with self._lock:
            executor = self._executor
        if executor is not None:
            return executor(request)
        data = _post("/api/comando", {"text": request, "canal": "voz", "registrar": False}, timeout=180)
        return str(data.get("text") or data.get("erro") or "Sem resposta do núcleo.")

    def record(self, role: str, text: str, channel: str = "voz") -> None:
        with self._lock:
            recorder = self._recorder
        if recorder is not None:
            recorder(role, text, channel)
            return
        try:
            _post("/api/conversa", {"role": role, "text": text, "canal": channel}, timeout=2)
        except Exception:
            pass

    def context(self) -> str:
        with self._lock:
            provider = self._context
        if provider is not None:
            return provider()
        try:
            request = urllib.request.Request(f"{SERVER}/api/conversa?formato=texto")
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.loads(response.read().decode("utf-8")).get("texto", "")
        except Exception:
            return ""


    def voice(self, default: str = "") -> str:
        """Voz escolhida pelo Du (a mesma do TTS do HUD)."""
        with self._lock:
            provider = self._voice
        try:
            if provider is not None:
                return provider() or default
            request = urllib.request.Request(f"{SERVER}/api/voz")
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.loads(response.read().decode("utf-8")).get("atual") or default
        except Exception:
            return default

    def memories(self) -> str:
        with self._lock:
            provider = self._memories
        if provider is not None:
            return provider()
        try:
            request = urllib.request.Request(f"{SERVER}/api/memoria?formato=texto")
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.loads(response.read().decode("utf-8")).get("texto", "")
        except Exception:
            return ""


def _post(path: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    return data if isinstance(data, dict) else {}


bridge = VoiceBridge()

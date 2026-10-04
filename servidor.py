from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, jsonify, request, stream_with_context
from openai import OpenAI

from brain.agent_loop import AgentLoop
from core.events import Event, EventType
from core.state import DuqueState

ROOT = Path(__file__).resolve().parent
INTERFACE = ROOT / "interface" / "index.html"
ALLOWED_HOSTS = {"127.0.0.1:5000", "localhost:5000"}
# Token por execução: só o HUD servido por este processo e a voz (mesmo
# processo) conseguem mandar comandos. Bloqueia páginas maliciosas no
# navegador que tentem falar com 127.0.0.1:5000 (inclusive DNS rebinding).
API_TOKEN = os.environ.setdefault("DUQUE_API_TOKEN", uuid4().hex)

app = Flask(__name__)

agent = AgentLoop()
openai_client = OpenAI(timeout=60.0, max_retries=1) if os.getenv("OPENAI_API_KEY") else None
state_lock = threading.Lock()
hud_streams = 0

estado_duque: dict[str, object] = {
    "estado": "standby",
    "tarefa": "",
    "atividade": "Sistema online",
    "resposta": "",
    "coerencia": 100,
    "ultima_atualizacao": None,
    "modo": "texto",
    "voz_ativa": False,
    "lembrete": None,
}


def _snapshot_to_dict(snapshot) -> dict[str, object]:
    return {
        "estado": snapshot.state.value,
        "tarefa": snapshot.task,
        "atividade": snapshot.activity,
        "coerencia": snapshot.coherence,
        "ultima_atualizacao": datetime.fromtimestamp(snapshot.updated_at).isoformat(timespec="milliseconds"),
    }


def _set_state(estado: DuqueState, *, tarefa: str = "", atividade: str = "", coerencia: int = 100) -> None:
    # O HUD só exibe o que está acontecendo; estados vêm de fontes diferentes
    # (texto, voz, agenda) e nunca podem ser recusados com erro.
    agent.engine.transition(estado, task=tarefa, activity=atividade, coherence=coerencia, force=True)


def _handle_event(event: Event) -> None:
    if event.type == EventType.STATE_CHANGED:
        snapshot = event.data.get("snapshot")
        if snapshot is not None:
            with state_lock:
                estado_duque.update(_snapshot_to_dict(snapshot))
        return

    if event.type == EventType.TASK_STARTED:
        tool = str(event.data.get("tool", ""))
        step = event.data.get("step", "")
        _set_state(DuqueState.EXECUTING, tarefa=f"Etapa {step}: {tool}"[:120], atividade=f"Executando {tool}"[:120])
    elif event.type == EventType.TASK_FINISHED:
        tool = str(event.data.get("tool", ""))
        if tool:
            _set_state(DuqueState.EXECUTING, tarefa=f"Concluído: {tool}"[:120], atividade="Resultado recebido")
        else:
            _set_state(DuqueState.STANDBY, atividade="Sistema online")
    elif event.type == EventType.TASK_FAILED:
        _set_state(DuqueState.ERROR, atividade=str(event.data.get("error", "Falha na tarefa"))[:120])
    elif event.type == EventType.OBSERVATION_STARTED:
        _set_state(DuqueState.EXECUTING, atividade="Observando a tela")
    elif event.type == EventType.VERIFICATION_STARTED:
        _set_state(DuqueState.EXECUTING, atividade="Verificando resultado")
    elif event.type == EventType.RESPONSE_STARTED:
        _set_state(DuqueState.SPEAKING, atividade="Gerando resposta")
    elif event.type == EventType.RESPONSE_FINISHED:
        _set_state(DuqueState.STANDBY, atividade="Sistema online")
    elif event.type == EventType.MEMORY_UPDATED and event.data.get("kind") == "reminder_due":
        texto = f"Lembrete: {event.data.get('description', '')}"
        with state_lock:
            estado_duque["lembrete"] = {"id": uuid4().hex, "texto": texto}
            estado_duque["resposta"] = texto


agent.engine.events.subscribe(None, _handle_event)
# A agenda só começa depois de o HUD estar inscrito nos eventos.
agent.start_background()


@app.before_request
def _proteger():
    if request.host not in ALLOWED_HOSTS:
        return jsonify({"erro": "Host não permitido."}), 403
    if request.method == "POST" and request.headers.get("X-Duque-Token") != API_TOKEN:
        return jsonify({"erro": "Token inválido."}), 403
    return None


@app.route("/")
def inicio():
    if not INTERFACE.exists():
        return Response("Erro: interface/index.html não encontrado.", status=500, mimetype="text/plain")
    html = INTERFACE.read_text(encoding="utf-8").replace("__DUQUE_TOKEN__", API_TOKEN)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.route("/api/hud/stream")
def hud_stream():
    """Conexão aberta enquanto existir uma aba do HUD (o launcher não abre outra)."""

    def eventos():
        global hud_streams
        with state_lock:
            hud_streams += 1
        try:
            yield "retry: 2000\n\n"
            while True:
                time.sleep(15)
                yield ": ping\n\n"
        finally:
            with state_lock:
                hud_streams -= 1

    return Response(stream_with_context(eventos()), mimetype="text/event-stream", headers={"Cache-Control": "no-store"})


def hud_conectada() -> bool:
    with state_lock:
        return hud_streams > 0


@app.route("/api/fala", methods=["POST"])
def gerar_fala():
    dados = request.get_json(silent=True) or {}
    texto = dados.get("text")
    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "O texto para fala não pode ser vazio."}), 400
    if openai_client is None:
        return jsonify({"erro": "OPENAI_API_KEY não configurada."}), 503
    try:
        audio = openai_client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=os.getenv("DUQUE_VOICE", "cedar"),
            input=texto.strip()[:4000],
            instructions=(
                "Fale em português do Brasil. "
                "Voz masculina, grave e encorpada, com timbre mais baixo, natural, calma e confiante, "
                "como um assistente pessoal futurista. Fale em ritmo controlado, com presença e autoridade, "
                "sem soar robótico ou exagerado. "
                "Não leia símbolos de formatação nem descreva a instrução."
            ),
            response_format="mp3",
            speed=float(os.getenv("DUQUE_VOICE_SPEED", "0.96")),
        )
        return Response(audio.content, mimetype="audio/mpeg")
    except Exception as exc:
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/estado", methods=["GET"])
def obter_estado():
    with state_lock:
        return jsonify(dict(estado_duque))


@app.route("/api/estado", methods=["POST"])
def alterar_estado():
    dados = request.get_json(silent=True) or {}
    novo_estado = dados.get("estado")
    estados = {state.value for state in DuqueState}
    if not isinstance(novo_estado, str) or novo_estado not in estados:
        return jsonify({"erro": f"Estado inválido: {novo_estado}", "estados_permitidos": sorted(estados)}), 400

    coerencia = dados.get("coerencia")
    if coerencia is not None and (isinstance(coerencia, bool) or not isinstance(coerencia, (int, float))):
        return jsonify({"erro": "coerencia deve ser um número."}), 400
    modo = dados.get("modo")
    if modo is not None and modo not in {"texto", "voz"}:
        return jsonify({"erro": "modo deve ser 'texto' ou 'voz'."}), 400

    atual = agent.engine.state.snapshot()
    tarefa = dados.get("tarefa")
    atividade = dados.get("atividade")
    _set_state(
        DuqueState(novo_estado),
        tarefa=atual.task if not isinstance(tarefa, str) else tarefa,
        atividade=atual.activity if not isinstance(atividade, str) else atividade,
        coerencia=int(atual.coherence if coerencia is None else coerencia),
    )
    if modo is not None:
        with state_lock:
            estado_duque["modo"] = modo
            estado_duque["voz_ativa"] = modo == "voz"
    return obter_estado()


@app.route("/api/comando", methods=["POST"])
def executar_comando():
    dados = request.get_json(silent=True) or {}
    texto = dados.get("text")
    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "O comando não pode ser vazio."}), 400

    try:
        _set_state(DuqueState.PROCESSING, tarefa="Interpretando comando", atividade="Processamento")
        resultado = agent.handle(texto.strip())
        with state_lock:
            estado_duque["resposta"] = resultado.text or ""

        sucesso = resultado.execution is None or resultado.execution.success
        if resultado.awaiting_confirmation:
            _set_state(DuqueState.STANDBY, tarefa="Aguardando confirmação", atividade="Confirmação necessária")
        elif not sucesso and resultado.execution is not None:
            _set_state(DuqueState.ERROR, atividade=(resultado.execution.error or "Falha na execução")[:120])
        else:
            _set_state(DuqueState.STANDBY, atividade="Resposta pronta")

        return jsonify({
            "ok": sucesso or resultado.awaiting_confirmation,
            "text": resultado.text,
            "resposta": resultado.text,
            "task_id": resultado.task_id,
            "attempts": resultado.attempts,
            "aguardando_confirmacao": resultado.awaiting_confirmation,
            "execution": (
                {
                    "success": resultado.execution.success,
                    "error": resultado.execution.error,
                    "confirmation_required": resultado.execution.confirmation_required,
                }
                if resultado.execution is not None
                else None
            ),
        })
    except Exception as exc:
        _set_state(DuqueState.ERROR, atividade=f"{type(exc).__name__}: {exc}"[:120])
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/status", methods=["GET"])
def status():
    with state_lock:
        dados: dict[str, object] = {
            "estado": estado_duque["estado"],
            "atividade": estado_duque["atividade"],
            "tarefa": estado_duque["tarefa"],
        }
    dados["hud_conectada"] = hud_conectada()
    return jsonify(dados)

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, Response
from openai import OpenAI

from brain.agent_loop import AgentLoop
from core.events import Event, EventType
from core.state import DuqueState

app = Flask(__name__)

agent = AgentLoop()
openai_client = OpenAI() if __import__('os').getenv('OPENAI_API_KEY') else None
state_lock = Lock()
# Momento da última consulta de estado feita por uma aba do HUD. Serve para o
# launcher saber se já existe uma interface aberta e não abrir outra. A folga
# é longa porque o navegador desacelera os timers de abas em segundo plano.
ultimo_contato_hud: float | None = None
HUD_TIMEOUT = 75.0

estado_duque = {
    "estado": "standby",
    "tarefa": "",
    "atividade": "Sistema online",
    "resposta": "",
    "coerencia": 100,
    "ultima_atualizacao": None,
    "modo": "texto",
}


def _snapshot_to_dict(snapshot) -> dict[str, object]:
    return {
        "estado": snapshot.state.value,
        "tarefa": snapshot.task,
        "atividade": snapshot.activity,
        "coerencia": snapshot.coherence,
        "ultima_atualizacao": datetime.fromtimestamp(
            snapshot.updated_at
        ).isoformat(timespec="milliseconds"),
    }


def _set_state(
    estado: DuqueState,
    *,
    tarefa: str = "",
    atividade: str = "",
    coerencia: int = 100,
    force: bool = False,
) -> None:
    snapshot = agent.engine.transition(
        estado,
        task=tarefa,
        activity=atividade,
        coherence=coerencia,
        force=force,
    )
    with state_lock:
        estado_duque.update(_snapshot_to_dict(snapshot))


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
        _set_state(
            DuqueState.EXECUTING,
            tarefa=f"Etapa {step}: {tool}"[:120],
            atividade=f"Executando {tool}"[:120],
        )
        return

    if event.type == EventType.TASK_FINISHED and event.data.get("tool"):
        tool = str(event.data.get("tool", ""))
        _set_state(
            DuqueState.EXECUTING,
            tarefa=f"Concluído: {tool}"[:120],
            atividade="Resultado recebido",
        )
        return

    if event.type == EventType.TASK_FAILED:
        error = str(event.data.get("error", "Falha na tarefa"))
        _set_state(
            DuqueState.ERROR,
            atividade=error[:120],
        )
        return

    if event.type == EventType.OBSERVATION_STARTED:
        _set_state(
            DuqueState.EXECUTING,
            atividade="Observando a tela",
        )
        return

    if event.type == EventType.VERIFICATION_STARTED:
        _set_state(
            DuqueState.EXECUTING,
            atividade="Verificando resultado",
        )
        return

    if event.type == EventType.RESPONSE_STARTED:
        # Forçar transição visual para SPEAKING mesmo que o estado atual tenha sido
        # alterado por outro evento (evita InvalidTransition quando race ocorrer).
        try:
            _set_state(
                DuqueState.SPEAKING,
                atividade="Gerando resposta",
            )
        except Exception:
            _set_state(
                DuqueState.SPEAKING,
                atividade="Gerando resposta",
                force=True,
            )
        return

    if event.type == EventType.RESPONSE_FINISHED:
        _set_state(
            DuqueState.STANDBY,
            atividade="Sistema online",
        )


agent.engine.events.subscribe(None, _handle_event)


def atualizar_estado(
    estado: str,
    tarefa: str | None = None,
    atividade: str | None = None,
    coerencia: int | None = None,
    modo: str | None = None,
) -> bool:
    try:
        target = DuqueState(estado)
    except ValueError:
        return False

    current = agent.engine.state.snapshot()
    _set_state(
        target,
        tarefa=current.task if tarefa is None else tarefa,
        atividade=current.activity if atividade is None else atividade,
        coerencia=current.coherence if coerencia is None else coerencia,
    )
    return True


@app.route("/")
def inicio():
    caminho = Path("interface/index.html")

    if not caminho.exists():
        return Response(
            "Erro: interface/index.html não encontrado.",
            status=500,
            mimetype="text/plain",
        )

    html = caminho.read_text(encoding="utf-8")

    # A própria HUD já sincroniza estado e envia comandos pela API.
    # Mantemos esta rota simples para evitar injetar JavaScript duplicado.
    return Response(html, mimetype="text/html")


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
            voice="cedar",
            input=texto.strip(),
            instructions=(
                "Fale em português do Brasil. "
                "Voz masculina, grave e encorpada, com timbre mais baixo, natural, calma e confiante, "
                "como um assistente pessoal futurista. Fale em ritmo controlado, com presença e autoridade, "
                "sem soar robótico ou exagerado. "
                "Não leia símbolos de formatação nem descreva a instrução."
            ),
            response_format="mp3",
            speed=0.96,
        )
        return Response(audio.content, mimetype="audio/mpeg")
    except Exception as exc:
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 500


def obter_estado():
    with state_lock:
        return jsonify(dict(estado_duque))


@app.route("/api/estado", methods=["GET"])
def consultar_estado():
    global ultimo_contato_hud
    ultimo_contato_hud = time.monotonic()
    return obter_estado()


def hud_conectada() -> bool:
    contato = ultimo_contato_hud
    return contato is not None and time.monotonic() - contato < HUD_TIMEOUT


@app.route("/api/estado", methods=["POST"])
def alterar_estado():
    dados = request.get_json(silent=True) or {}
    novo_estado = dados.get("estado")

    if not isinstance(novo_estado, str) or novo_estado not in {
        state.value for state in DuqueState
    }:
        return jsonify({
            "erro": f"Estado inválido: {novo_estado}",
            "estados_permitidos": [state.value for state in DuqueState],
        }), 400

    try:
        atualizar_estado(
            novo_estado,
            tarefa=dados.get("tarefa"),
            atividade=dados.get("atividade"),
            coerencia=dados.get("coerencia"),
            modo=dados.get("modo"),
        )
    except Exception as exc:
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 500

    return obter_estado()


@app.route("/api/comando", methods=["POST"])
def executar_comando():
    dados = request.get_json(silent=True) or {}
    texto = dados.get("text")

    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "O comando não pode ser vazio."}), 400

    try:
        _set_state(
            DuqueState.PROCESSING,
            tarefa="Interpretando comando",
            atividade="Processamento",
        )
        with state_lock:
            estado_duque["modo"] = "texto"

        resultado = agent.handle(texto.strip())

        with state_lock:
            estado_duque["resposta"] = resultado.text or ""

        if agent._pending_confirmation is not None:
            try:
                _set_state(
                    DuqueState.SPEAKING,
                    tarefa="Aguardando confirmação",
                    atividade="Confirmação necessária",
                )
            except Exception:
                _set_state(
                    DuqueState.SPEAKING,
                    tarefa="Aguardando confirmação",
                    atividade="Confirmação necessária",
                    force=True,
                )
        elif resultado.execution is not None and not resultado.execution.success:
            _set_state(
                DuqueState.ERROR,
                tarefa="",
                atividade=resultado.execution.error or "Falha na execução",
            )
        else:
            _set_state(
                DuqueState.STANDBY,
                tarefa="",
                atividade="Resposta pronta",
            )

        return jsonify({
            "ok": True,
            "text": resultado.text,
            "resposta": resultado.text,
            "task_id": resultado.task_id,
            "attempts": resultado.attempts,
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
        _set_state(
            DuqueState.ERROR,
            atividade=f"{type(exc).__name__}: {exc}"[:120],
        )
        return jsonify({
            "ok": False,
            "erro": f"{type(exc).__name__}: {exc}",
        }), 500


@app.route("/estado/<novo_estado>", methods=["GET"])
def estado_compatibilidade(novo_estado: str):
    if novo_estado not in {state.value for state in DuqueState}:
        return jsonify({"erro": "Estado inválido."}), 400

    atualizar_estado(novo_estado)
    return obter_estado()


@app.route("/status", methods=["GET"])
def status():
    with state_lock:
        return jsonify({
            "estado": estado_duque["estado"],
            "atividade": estado_duque["atividade"],
            "tarefa": estado_duque["tarefa"],
            "hud_conectada": hud_conectada(),
        })


if __name__ == "__main__":
    print()
    print("=" * 60)
    print("DUQUE - SERVIDOR CENTRAL")
    print("=" * 60)
    print()
    print("Interface:")
    print("http://127.0.0.1:5000")
    print()
    print("API de estado:")
    print("http://127.0.0.1:5000/api/estado")
    print()
    print("API de comando:")
    print("POST http://127.0.0.1:5000/api/comando")
    print()
    print("HUD: sincronização automática ativa")
    print("AgentLoop: conectado")
    print()
    print("=" * 60)
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
    )

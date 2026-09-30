from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock, Timer

from flask import Flask, jsonify, request, Response

from brain.agent_loop import AgentLoop
from brain.model import NullModel, OpenAIResponsesModel
from core.events import Event, EventType
from core.state import DuqueState

app = Flask(__name__)

def _create_agent() -> AgentLoop:
    autonomous = os.getenv("DUQUE_AUTONOMOUS_AGENT", "0").casefold() in {"1", "true", "yes", "on"}
    api_key = os.getenv("OPENAI_API_KEY")

    if autonomous and api_key:
        return AgentLoop(model=OpenAIResponsesModel())

    # Sem chave, o servidor continua abrindo a interface para diagnóstico.
    # As tarefas que exigem raciocínio de modelo ficam indisponíveis até a chave
    # ser configurada, em vez de derrubar o servidor inteiro na inicialização.
    return AgentLoop(model=NullModel())


agent = _create_agent()
state_lock = Lock()
command_lock = Lock()

estado_duque = {
    "estado": "standby",
    "tarefa": "",
    "atividade": "Sistema online",
    "resposta": "",
    "coerencia": 100,
    "ultima_atualizacao": None,
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


def _return_to_standby(delay: float = 2.5) -> None:
    def reset():
        try:
            _set_state(
                DuqueState.STANDBY,
                tarefa="",
                atividade="Sistema online",
            )
        except Exception:
            pass

    Timer(delay, reset).start()
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
        _set_state(
            DuqueState.EXECUTING,
            atividade=f"Executando {event.data.get('tool', 'etapa')}",
        )
        return

    # TASK_FINISHED descreve uma etapa concluída; a próxima etapa pode começar
    # imediatamente, então não forçamos standby aqui.
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
        _set_state(
            DuqueState.SPEAKING,
            atividade="Gerando resposta",
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


@app.route("/api/estado", methods=["GET"])
def obter_estado():
    with state_lock:
        return jsonify(dict(estado_duque))


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

        if (
            os.getenv("DUQUE_AUTONOMOUS_AGENT", "0").casefold() in {"1", "true", "yes", "on"}
            and not os.getenv("OPENAI_API_KEY")
        ):
            _set_state(
                DuqueState.ERROR,
                tarefa="Configuração necessária",
                atividade="OPENAI_API_KEY não configurada",
            )
            return jsonify({
                "ok": False,
                "erro": "OPENAI_API_KEY não configurada no ambiente do Duque.",
            }), 503

        with command_lock:
            resultado = agent.handle(texto.strip())

        with state_lock:
            estado_duque["resposta"] = resultado.text or ""

        if (
            agent._pending_confirmation is not None
            or agent._pending_autonomous_confirmation is not None
        ):
            _set_state(
                DuqueState.SPEAKING,
                tarefa="Aguardando confirmação",
                atividade="Confirmação necessária",
            )

        elif resultado.execution is not None and not resultado.execution.success:
            _set_state(
                DuqueState.ERROR,
                tarefa="",
                atividade=resultado.execution.error or "Falha na execução",
            )

        else:
            _set_state(
                DuqueState.SPEAKING,
                tarefa=(resultado.text or "")[:120],
                atividade="Resposta pronta",
            )

            _return_to_standby()

        return jsonify({
            "ok": True,
            "text": resultado.text,
            "task_id": resultado.task_id,
            "attempts": resultado.attempts,
            "autonomous": agent.autonomous_enabled(),
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

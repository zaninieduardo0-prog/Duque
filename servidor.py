from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, Response
import os
import subprocess
from core.auth import require_auth, check_api_token
from core.auth_roles import require_role
import json
import tempfile
from voice.voz_local import LocalTTS
from voice.stt_vosk import transcribe_wav
from pathlib import Path
import shutil
from openai import OpenAI

from brain.agent_loop import AgentLoop
from core.events import Event, EventType
from core.state import DuqueState

app = Flask(__name__)

agent = AgentLoop()
openai_client = OpenAI() if __import__('os').getenv('OPENAI_API_KEY') else None
state_lock = Lock()

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


def _check_api_token() -> bool:
    """Verifica token simples de API via DUQUE_API_TOKEN. Se não configurado, permite por padrão."""
    token = os.getenv("DUQUE_API_TOKEN")
    if not token:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        provided = auth.split(" ", 1)[1]
    else:
        provided = request.args.get("token") or request.form.get("token") or ""
    return provided == token


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

    # Primeiro tenta TTS local se disponível
    try:
        if os.getenv('DUQUE_USE_LOCAL_TTS', '1') == '1':
            try:
                tts = LocalTTS()
                # grava em arquivo temporário WAV e retorna conteúdo
                import io
                import base64
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                path = tmp.name
                tmp.close()
                res = tts.speak_to_file(texto.strip(), path)
                if res.get('success'):
                    data = open(path, 'rb').read()
                    return Response(data, mimetype='audio/wav')
                # fallback para cloud TTS
            except Exception:
                pass

        if openai_client is None:
            return jsonify({"erro": "OPENAI_API_KEY não configurada e TTS local indisponível."}), 503

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


@app.route('/api/workspace/inspect', methods=['GET'])
def api_inspect_workspace():
    try:
        info = agent.self_development.inspect()
        return jsonify({"ok": True, "info": info})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/workspace/read_many', methods=['POST'])
def api_read_many():
    dados = request.get_json(silent=True) or {}
    paths = dados.get('paths')
    if not isinstance(paths, list):
        return jsonify({"ok": False, "erro": "paths deve ser uma lista"}), 400
    try:
        result = agent.self_development.read_many(paths)
        return jsonify({"ok": True, "files": result})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/workspace/apply_change', methods=['POST'])
@require_auth
def api_apply_change():
    dados = request.get_json(silent=True) or {}
    path = dados.get('path')
    content = dados.get('content')
    if not isinstance(path, str) or not isinstance(content, str):
        return jsonify({"ok": False, "erro": "path e content devem ser strings"}), 400
    try:
        result = agent.self_development.apply_change(path, content)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/workspace/propose_change', methods=['POST'])
@require_auth
def api_propose_change():
    dados = request.get_json(silent=True) or {}
    path = dados.get('path')
    content = dados.get('content')
    branch = dados.get('branch')
    message = dados.get('message')
    if not isinstance(path, str) or not isinstance(content, str):
        return jsonify({"ok": False, "erro": "path e content devem ser strings"}), 400
    try:
        result = agent.self_development.tools.propose_change(path, content, branch=branch, message=message)
        # opcional: criar PR remoto se GH_TOKEN estiver configurado e param create_pr=true
        create_pr = bool(dados.get('create_pr'))
        if create_pr:
            # chamamos o script que faz push e cria PR via GH API
            branch_name = result.get('branch')
            if branch_name:
                try:
                    pr_proc = subprocess.run([sys.executable, 'scripts/gh_pr_create.py', '--branch', branch_name, '--title', f"Proposta: {path}", '--body', message or "Gerado pelo Duque"], cwd=str(Path('.').resolve()), capture_output=True, text=True, shell=False)
                    if pr_proc.returncode == 0:
                        try:
                            pr_json = json.loads(pr_proc.stdout)
                        except Exception:
                            pr_json = {'raw': pr_proc.stdout}
                        return jsonify({"ok": True, "result": result, "pr": pr_json})
                    return jsonify({"ok": False, "error": "Falha ao criar PR", "stdout": pr_proc.stdout, "stderr": pr_proc.stderr}), 500
                except Exception as exc:
                    return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/workspace/approve_change', methods=['POST'])
@require_auth
def api_approve_change():
    dados = request.get_json(silent=True) or {}
    branch = dados.get('branch')
    target = dados.get('target')
    if not isinstance(branch, str) or not branch.strip():
        return jsonify({"ok": False, "erro": "branch é obrigatório"}), 400
    try:
        # require admin role for approve if JWT roles are configured
        if os.getenv('DUQUE_JWT_SECRET'):
            # use role-based check
            from core.auth_roles import require_role

            @require_role('admin')
            def _merge():
                return agent.self_development.tools.merge_branch(branch, target=target)

            result = _merge()
        else:
            result = agent.self_development.tools.merge_branch(branch, target=target)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/workspace/list_proposals', methods=['GET'])
@require_auth
def api_list_proposals():
    try:
        proc = subprocess.run(["git", "branch", "--list", "duque/autogen/*"], cwd='.', capture_output=True, text=True, shell=False)
        if proc.returncode != 0:
            return jsonify({"ok": False, "erro": proc.stderr}), 500
        lines = [l.strip().lstrip('* ').strip() for l in proc.stdout.splitlines() if l.strip()]
        return jsonify({"ok": True, "branches": lines})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route('/api/stt', methods=['POST'])
@require_auth
def api_stt():
    # Recebe um upload de arquivo WAV no campo 'file' e retorna transcrição via VOSK
    if 'file' not in request.files:
        return jsonify({"ok": False, "erro": "Arquivo WAV não enviado no campo 'file'"}), 400
    f = request.files['file']
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    try:
        f.save(tmp.name)
        # Primeiro tente VOSK
        res = transcribe_wav(tmp.name)
        if not res.get('success'):
            # Fallback: se whisper_infer.py disponível, chame-o
            whisper = Path('scripts/whisper_infer.py')
            if whisper.exists():
                proc = subprocess.run([sys.executable, str(whisper), tmp.name], capture_output=True, text=True, shell=False)
                try:
                    res2 = json.loads(proc.stdout)
                    return jsonify({"ok": True, "result": res2})
                except Exception:
                    pass
        return jsonify({"ok": True, "result": res})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500
    finally:
        try:
            tmp.close()
        except Exception:
            pass


@app.route('/api/git/commit', methods=['POST'])
def api_git_commit():
    dados = request.get_json(silent=True) or {}
    message = dados.get('message')
    if not isinstance(message, str) or not message.strip():
        return jsonify({"ok": False, "erro": "message é obrigatório"}), 400
    try:
        git_tool = agent.executor.tools.get('git_commit')
        if git_tool is None:
            return jsonify({"ok": False, "erro": "git_commit não está disponível"}), 503
        result = git_tool(message=message)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}), 500


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

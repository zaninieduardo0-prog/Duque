from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, request, Response
from openai import OpenAI

from brain.agent_loop import AgentLoop, AgentResult
from core.executor import ExecutionResult
from core.events import Event, EventType
from brain.voice_style import SAMPLE as VOICE_SAMPLE
from brain.voice_style import TTS_INSTRUCTIONS, TTS_SPEED, VOICES, current_voice, set_voice
from core.emergency import describe as describe_pause
from core.emergency import is_pause_command, is_resume_command, is_shutdown_command, shutdown_soon
from core.voice_bridge import bridge
from core.security import RiskLevel, SecurityPolicy
from core.state import DuqueState
from core.tasks import TaskStatus
from memory.memory import MemoryLayer
from voice import local_tts
from voice.gate import addressed, is_sleep

app = Flask(__name__)

agent = AgentLoop()
# Ferramenta sem risco definido em core/security.py pede confirmação (antes
# nascia liberada por esquecimento). Todas as atuais estão classificadas.
agent.executor.security = SecurityPolicy(default=RiskLevel.HIGH)
# Tarefas agendadas e pedidos (HUD, voz) usam o mesmo cérebro: nunca ao mesmo tempo.
agent.scheduled_runner.lock = agent._handle_lock
openai_client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
state_lock = Lock()

INTERFACE = Path(__file__).resolve().parent / "interface" / "index.html"

# Só o próprio PC conversa com o TELEX. Sem isto, qualquer página aberta no
# navegador (ou um domínio que aponte para 127.0.0.1, "DNS rebinding") podia
# mandar comandos — inclusive um "sim" para uma ação de alto risco pendente.
_HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1"}


def _host_local(valor: str | None) -> bool:
    if not valor:
        return False
    host = urlparse(valor if "//" in valor else f"//{valor}").hostname or ""
    return host.casefold() in _HOSTS_LOCAIS


@app.before_request
def _somente_local():
    if not _host_local(request.host):
        return jsonify({"erro": "Host não permitido."}), 403
    origem = request.headers.get("Origin")
    if origem is not None and request.method not in {"GET", "HEAD", "OPTIONS"} and not _host_local(origem):
        return jsonify({"erro": "Origem não permitida."}), 403
    # Navegadores marcam pedidos vindos de outros sites; só a abertura do HUD
    # ("/") pode vir de fora (um link/favorito). Clientes Python não mandam o cabeçalho.
    site = request.headers.get("Sec-Fetch-Site", "").casefold()
    if site in {"cross-site", "same-site"} and not (request.method == "GET" and request.path == "/"):
        return jsonify({"erro": "Pedido de outro site bloqueado."}), 403
    return None

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
    force: bool = True,
) -> None:
    # Este estado só alimenta o HUD. Ele nunca pode derrubar uma ação real:
    # a voz, por exemplo, executa ferramentas a partir de "ouvindo", e a
    # transição ouvindo -> executando não existe na máquina de estados.
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
        _set_state(DuqueState.SPEAKING, atividade="Gerando resposta")
        return

    if event.type == EventType.RESPONSE_FINISHED:
        _set_state(
            DuqueState.STANDBY,
            atividade="Sistema online",
        )


def _safe_handle_event(event: Event) -> None:
    """Falha ao atualizar o HUD nunca interrompe a tarefa que emitiu o evento."""
    try:
        _handle_event(event)
    except Exception as exc:
        print(f"[HUD] evento {event.type.value} ignorado: {type(exc).__name__}: {exc}", flush=True)


agent.engine.events.subscribe(None, _safe_handle_event)


# Núcleo novo (pasta telex/): uma IA com ferramentas confiáveis (WhatsApp Web e
# sites pelo navegador do TELEX). DUQUE_NUCLEO=antigo volta ao cérebro anterior.
NUCLEO_NOVO = os.getenv("DUQUE_NUCLEO", "novo").strip().casefold() != "antigo"
_telex = None


def _telex_agent():
    global _telex
    if _telex is None:
        from telex.agent import TelexAgent

        _telex = TelexAgent(legacy_tools=agent.executor.tools.get)
    return _telex


def processar(texto: str, canal: str = "texto", registrar: bool = True) -> AgentResult:
    """Ponto único dos pedidos (HUD e voz)."""
    if not NUCLEO_NOVO:
        return agent.handle(texto, channel=canal, record=registrar)
    with agent._handle_lock:  # nunca junto com uma tarefa agendada
        if registrar:
            agent.conversation.add("user", texto, canal)
        resposta = _telex_agent().handle(texto)
        if registrar:
            agent.conversation.add("assistant", resposta.text, canal)
    execucao = ExecutionResult(success=not resposta.failed, value={"ferramentas": resposta.tools_used},
                               error=resposta.text if resposta.failed else None)
    return AgentResult(resposta.text, None, execucao, max(1, resposta.steps))


def _execute_for_voice(pedido: str) -> str:
    """Ferramenta da voz: executa pelo mesmo cérebro, sem duplicar o turno na conversa."""
    return processar(pedido, canal="voz", registrar=False).text


bridge.attach_core(
    executor=_execute_for_voice,
    recorder=lambda role, text, channel: agent.conversation.add(role, text, channel),
    context=lambda: agent.conversation.transcript(12),
    memories=agent.memory_digest,
    voice=lambda: current_voice(agent.memory),
)


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
    try:
        coerencia = None if coerencia is None else int(coerencia)
    except (TypeError, ValueError):
        coerencia = None

    current = agent.engine.state.snapshot()
    _set_state(
        target,
        tarefa=current.task if tarefa is None else str(tarefa)[:200],
        atividade=current.activity if atividade is None else str(atividade)[:200],
        coerencia=current.coherence if coerencia is None else coerencia,
    )
    if modo in {"texto", "voz"}:
        with state_lock:
            estado_duque["modo"] = modo
    return True


@app.route("/")
def inicio():
    caminho = INTERFACE

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


_local_speaker: Any = None
_local_speaker_lock = Lock()


def _voz_local_forcada() -> bool:
    return os.getenv("DUQUE_VOICE", "auto").strip().casefold() == "local"


def _falar_local(texto: str) -> Response | None:
    """Fala do HUD com a voz local (Piper ou Windows), em WAV; None se não houver voz local."""
    global _local_speaker
    with _local_speaker_lock:  # duas falas ao mesmo tempo não carregam o modelo duas vezes
        if _local_speaker is None:
            _local_speaker = local_tts.load(print) or False
    if not _local_speaker:
        return None
    try:
        audio = _local_speaker.synthesize(texto[:4000])
    except Exception as exc:
        print(f"[TTS] voz local falhou: {type(exc).__name__}: {exc}")
        return None
    if not audio.pcm:
        return None
    return Response(audio.to_wav(), mimetype="audio/wav", headers={"Cache-Control": "no-store"})


@app.route("/api/fala", methods=["GET"])
def falar_em_streaming():
    """Fala do HUD em streaming: o navegador começa a tocar enquanto o áudio chega.

    Antes o HUD esperava o MP3 inteiro (1–3 s de silêncio antes de cada resposta).
    """
    texto = (request.args.get("text") or "").strip()
    if not texto:
        return jsonify({"erro": "O texto para fala não pode ser vazio."}), 400
    if openai_client is None or _voz_local_forcada():
        local = _falar_local(texto)
        if local is not None:
            return local
        return jsonify({"erro": "Sem voz: configure OPENAI_API_KEY ou instale a voz local (preparar_local.bat)."}), 503
    pedida = request.args.get("voz")
    voz: Any = pedida if pedida in VOICES else current_voice(agent.memory)
    client = openai_client

    def gerar():
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice=voz,
            input=texto[:4000],
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
            speed=TTS_SPEED,
        ) as resposta:
            yield from resposta.iter_bytes(4096)

    stream = gerar()
    try:
        first = next(stream)  # a OpenAI recusa (sem créditos, sem rede) já no primeiro pedaço
    except StopIteration:
        first = b""
    except Exception as exc:
        local = _falar_local(texto)
        if local is not None:
            print(f"[TTS] OpenAI falhou ({type(exc).__name__}); falando com a voz local.")
            return local
        raise

    def chunks():
        yield first
        yield from stream

    return Response(chunks(), mimetype="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.route("/api/fala", methods=["POST"])
def gerar_fala():
    dados = request.get_json(silent=True) or {}
    texto = dados.get("text")

    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "O texto para fala não pode ser vazio."}), 400

    if openai_client is None or _voz_local_forcada():
        local = _falar_local(texto.strip())
        if local is not None:
            return local
        return jsonify({"erro": "Sem voz: configure OPENAI_API_KEY ou instale a voz local (preparar_local.bat)."}), 503

    voz: Any = str(dados["voz"]) if dados.get("voz") in VOICES else current_voice(agent.memory)
    try:
        audio = openai_client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voz,
            input=texto.strip(),
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
            speed=TTS_SPEED,
        )
        return Response(audio.content, mimetype="audio/mpeg")
    except Exception as exc:
        local = _falar_local(texto.strip())  # sem créditos/rede: fala com a voz local
        if local is not None:
            return local
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/voz", methods=["GET"])
def voz_status():
    return jsonify({"atual": current_voice(agent.memory), "vozes": VOICES, "amostra": VOICE_SAMPLE})


@app.route("/api/voz", methods=["POST"])
def voz_escolher():
    dados = request.get_json(silent=True) or {}
    resultado = set_voice(agent.memory, str(dados.get("voz", "")))
    return jsonify(resultado), (400 if resultado.get("success") is False else 200)


def _versao_atual() -> str:
    """Identifica a versão rodando (commit + início do processo) para o HUD se recarregar."""
    import subprocess

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        commit = ""
    return f"{commit or 'local'}-{int(_INICIO)}"


_INICIO = time.time()
_VERSAO: dict[str, str] = {}


@app.route("/api/versao", methods=["GET"])
def versao():
    if "v" not in _VERSAO:
        _VERSAO["v"] = _versao_atual()
    return jsonify({"versao": _VERSAO["v"], "inicio": _INICIO})


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


_ID_COMANDO = re.compile(r"[A-Za-z0-9_-]{8,64}")
_comandos_lock = Lock()


def _comando_repetido(comando_id: Any) -> bool:
    """O HUD reenvia um comando quando a conexão cai; o mesmo id nunca roda duas vezes.

    Sem isto, um pedido que já tinha sido executado (e derrubado/reiniciado o
    servidor no meio da resposta) era executado de novo: janelas e abas em dobro.
    Fica no banco para valer também depois de um reinício.
    """
    if not isinstance(comando_id, str) or not _ID_COMANDO.fullmatch(comando_id):
        return False
    chave = f"hud:cmd:{comando_id}"
    with _comandos_lock:
        if agent.memory.recall(MemoryLayer.OPERATIONAL, chave) is not None:
            return True
        agent.memory.remember(MemoryLayer.OPERATIONAL, chave, time.time())
    return False


@app.route("/api/comando", methods=["POST"])
def executar_comando():
    dados = request.get_json(silent=True) or {}
    texto = dados.get("text")
    canal = str(dados.get("canal")) if dados.get("canal") in {"texto", "voz"} else "texto"
    registrar = dados.get("registrar", True) is not False

    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "O comando não pode ser vazio."}), 400

    if _comando_repetido(dados.get("id")):
        return jsonify({"ok": True, "duplicado": True, "text": "", "resposta": ""})

    # Pausa de emergência, retomada e "Repousar, Telex" valem sempre e não
    # passam pelo cérebro (que pode estar parado esperando a retomada).
    controle = _comando_de_controle(texto.strip(), canal, registrar)
    if controle is not None:
        return jsonify(controle)

    # Conversa por voz em andamento: o texto digitado entra na mesma sessão e a
    # resposta sai falada por ela, mantendo um único fluxo de conversa.
    if canal == "texto" and registrar and bridge.voice_active:
        agent.conversation.add("user", texto.strip(), "texto")
        if bridge.send_to_voice(texto.strip()):
            return jsonify({"ok": True, "via": "voz", "text": "", "resposta": ""})
        # A fala do usuário já foi registrada acima; não registrar de novo.
        registrar = False

    try:
        # Estado visual: um comando novo sempre pode começar, mesmo vindo de
        # "dormindo" ou "erro" (antes isso gerava InvalidTransition e erro 500).
        _set_state(
            DuqueState.PROCESSING,
            tarefa="Interpretando comando",
            atividade="Processamento",
            force=True,
        )
        with state_lock:
            estado_duque["modo"] = "texto"

        resultado = processar(texto.strip(), canal=canal, registrar=registrar)

        with state_lock:
            estado_duque["resposta"] = resultado.text or ""

        if agent._pending_confirmation is not None:
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
        import traceback

        print(f"[COMANDO] falhou em {texto!r}:\n{traceback.format_exc()}", flush=True)
        try:
            _set_state(
                DuqueState.ERROR,
                atividade=f"{type(exc).__name__}: {exc}"[:120],
            )
        except Exception:
            pass
        return jsonify({
            "ok": False,
            "erro": f"Não consegui processar: {type(exc).__name__}: {exc}",
        }), 500


now_playing = agent.now_playing
_SAUDACAO_CHAVE = "hud:saudacao"


def _ultima_saudacao_salva() -> float:
    try:
        return float(agent.memory.recall(MemoryLayer.OPERATIONAL, _SAUDACAO_CHAVE, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# Lida do banco: cada reinício (Forja, queda) recarrega o HUD, que pede a
# saudação de novo; antes ela era repetida a cada reinício.
_ultima_saudacao = {"em": _ultima_saudacao_salva()}
_saudacao_lock = Lock()


@app.route("/api/saudacao", methods=["POST"])
def saudacao():
    """Resumo de início (hora, clima, pendências). No máximo uma vez a cada 30 min."""
    if os.getenv("DUQUE_GREETING", "1").casefold() in {"0", "false", "off", "no", "nao", "não"}:
        return jsonify({"ok": False, "motivo": "desativada"})
    with _saudacao_lock:  # dois HUDs abertos não saúdam duas vezes
        agora = time.time()
        if agora - _ultima_saudacao["em"] < 1800:
            return jsonify({"ok": False, "motivo": "recente"})
        _ultima_saudacao["em"] = agora
    agent.memory.remember(MemoryLayer.OPERATIONAL, _SAUDACAO_CHAVE, agora)
    try:
        texto = agent.greeting()
    except Exception as exc:
        print(f"[SAUDAÇÃO] falhou: {type(exc).__name__}: {exc}", flush=True)
        return jsonify({"ok": False, "motivo": "erro"})
    agent.announce(texto)
    return jsonify({"ok": True, "text": texto})


@app.route("/api/memoria", methods=["GET"])
def memoria():
    if request.args.get("formato") == "texto":
        return jsonify({"texto": agent.memory_digest()})
    return jsonify({
        "notas": agent.assistant_tools.notes_list().get("notes", []),
        "timers": agent.assistant_tools.timers_list().get("timers", []),
        "lembretes": agent.reminders_list().get("reminders", []),
        "rotinas": {nome: valor.get("commands", []) for nome, valor in agent.routines.routines_list().get("routines", {}).items()},
        "contatos": [contato["name"] for contato in agent.messaging.contacts_list().get("contacts", [])],
        "foco_ate": agent._focus_until if agent.focus_active() else None,
        "turnos": agent.conversation.last_id(),
    })


@app.route("/api/memoria/notas", methods=["POST"])
def memoria_adicionar():
    dados = request.get_json(silent=True) or {}
    resultado = agent.assistant_tools.note_add(str(dados.get("texto", "")))
    return jsonify(resultado), (400 if resultado.get("success") is False else 200)


@app.route("/api/memoria/notas/<int:indice>", methods=["DELETE"])
def memoria_apagar(indice: int):
    resultado = agent.assistant_tools.note_delete(indice)
    return jsonify(resultado), (404 if resultado.get("success") is False else 200)


_clima_cache: dict[str, Any] = {"em": 0.0, "dados": None}
_clima_lock = Lock()


@app.route("/api/clima", methods=["GET"])
def clima():
    """Clima do painel do HUD na cidade do DUQUE_CITY (cache de 10 min)."""
    with _clima_lock:
        if _clima_cache["dados"] is not None and time.time() - _clima_cache["em"] < 600:
            return jsonify(_clima_cache["dados"])
        try:
            resultado = agent.assistant_tools.weather()
        except Exception as exc:
            return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 503
        if resultado.get("success") is False:
            return jsonify({"erro": resultado.get("error", "sem clima")}), 503
        atual = resultado.get("current") or {}
        dados = {
            "cidade": resultado.get("city"),
            "temperatura": atual.get("temperature_2m"),
            "codigo": atual.get("weather_code"),
        }
        _clima_cache.update(em=time.time(), dados=dados)
        return jsonify(dados)


@app.route("/api/midia", methods=["GET"])
def midia_status():
    return jsonify(now_playing.get())


@app.route("/api/midia", methods=["POST"])
def midia_controle():
    dados = request.get_json(silent=True) or {}
    acao = str(dados.get("acao", ""))
    if acao not in {"play_pause", "next", "previous"}:
        return jsonify({"erro": "Ação inválida: use play_pause, next ou previous."}), 400
    try:
        resultado = agent.assistant_tools.media(acao)
    except Exception as exc:
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 503
    now_playing.invalidate()
    return jsonify({"ok": True, **resultado})


@app.route("/api/parar", methods=["POST"])
def parar_fala():
    """ "Stop" pelo HUD: corta a fala da conversa de voz na hora."""
    return jsonify({"ok": True, "voz": bridge.stop_speech()})


HUD_APPS = {"whatsapp", "instagram", "spotify", "youtube", "chrome", "gmail", "discord"}


@app.route("/api/abrir", methods=["POST"])
def abrir_app():
    """Ícones do HUD: abre o app (ou o site no Chrome do Du) sem passar pela conversa."""
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("app", "")).casefold().strip()
    if nome not in HUD_APPS:
        return jsonify({"erro": f"App não disponível no HUD: {nome}"}), 400
    from computer.tools import ComputerTools

    try:
        resultado = ComputerTools().open_app(nome)
    except Exception as exc:
        return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 503
    return jsonify({"ok": True, **{k: v for k, v in resultado.items() if k != "command"}})


@app.route("/api/conversa", methods=["GET"])
def conversa():
    if request.args.get("formato") == "texto":
        return jsonify({"texto": agent.conversation.transcript(12)})
    try:
        desde = int(request.args.get("desde", "0"))
    except ValueError:
        desde = 0
    turnos = agent.conversation.since(desde) if desde else agent.conversation.recent(30)
    return jsonify({
        "turnos": [turno.to_dict() for turno in turnos],
        "ultimo": agent.conversation.last_id(),
        "voz_ativa": bridge.voice_active,
    })


@app.route("/api/conversa", methods=["POST"])
def registrar_conversa():
    dados = request.get_json(silent=True) or {}
    # Canal fechado: um "aviso" vindo de fora seria lido em voz alta pelo HUD.
    canal = str(dados.get("canal", "voz")) if dados.get("canal", "voz") in {"texto", "voz"} else "voz"
    turno = agent.conversation.add(str(dados.get("role", "")), str(dados.get("text", "")), canal)
    if turno is None:
        return jsonify({"erro": "Turno inválido."}), 400
    return jsonify({"ok": True, "id": turno.id})


def _avisar(texto: str) -> None:
    """Fala do TELEX que entra na conversa (o HUD lê em voz alta).

    Com a conversa de voz ativa o HUD fica calado (para não falar junto com a
    voz); então a própria sessão de voz fala o aviso.
    """
    agent.conversation.add("assistant", texto, "aviso")
    if bridge.voice_active:
        bridge.announce(texto)


def _pausar(origem: str = "hud") -> dict[str, Any]:
    status = agent.pause.pause(f"pedido por {origem}")
    bridge.end_voice("pausa de emergência")
    _set_state(DuqueState.STANDBY, tarefa="Pausa de emergência", atividade="Tudo parado onde estava")
    _avisar("Pausa de emergência. Tudo parado onde estava; diga ou clique em retomar quando quiser.")
    return status


def _retomar(origem: str = "hud") -> dict[str, Any]:
    if not agent.pause.paused:
        return {"pausado": False, "texto": "Não estou em pausa."}
    status = agent.pause.resume()
    texto = "Retomando. " + describe_pause(status)
    _set_state(DuqueState.STANDBY, tarefa="", atividade="Sistema online")
    _avisar(texto)
    return {**status, "pausado": False, "texto": texto, "origem": origem}


def _desligar(origem: str) -> dict[str, Any]:
    print(f"[TELEX] desligado por {origem}", flush=True)
    _avisar("Desligando. Até logo, Du.")
    bridge.end_voice("desligar")
    shutdown_soon()
    return {"ok": True, "via": "desligar", "text": "", "resposta": "", "desligando": True}


def _comando_de_controle(texto: str, canal: str, registrar: bool) -> dict[str, Any] | None:
    if is_shutdown_command(texto):
        if registrar:
            agent.conversation.add("user", texto, canal)
        return _desligar(canal)
    if is_pause_command(texto):
        if registrar:
            agent.conversation.add("user", texto, canal)
        _pausar(canal)
        return {"ok": True, "via": "emergencia", "text": "", "resposta": "", "pausado": True}
    if agent.pause.paused:
        if registrar:
            agent.conversation.add("user", texto, canal)
        if is_resume_command(texto):
            _retomar(canal)
            return {"ok": True, "via": "emergencia", "text": "", "resposta": "", "pausado": False}
        aviso = 'Estou em pausa de emergência. Diga "retomar" (ou clique em Retomar) para eu continuar de onde parei.'
        _avisar(aviso)
        return {"ok": True, "via": "emergencia", "text": aviso, "resposta": aviso, "pausado": True}
    if is_sleep(texto) and addressed(texto):
        if registrar:
            agent.conversation.add("user", texto, canal)
        encerrou = bridge.end_voice("repousar")
        _set_state(DuqueState.STANDBY, tarefa="", atividade="Em repouso")
        _avisar("Em repouso." if encerrou else "Em repouso. Me chame quando precisar.")
        return {"ok": True, "via": "repouso", "text": "", "resposta": ""}
    return None


@app.route("/api/desligar", methods=["POST"])
def desligar():
    return jsonify(_desligar("hud"))


@app.route("/api/emergencia", methods=["GET"])
def emergencia_status():
    return jsonify(agent.pause.status())


@app.route("/api/emergencia", methods=["POST"])
def emergencia():
    dados = request.get_json(silent=True) or {}
    acao = str(dados.get("acao", "")).casefold()
    origem = str(dados.get("origem", "hud"))[:20]
    if acao == "pausar":
        return jsonify({"ok": True, **_pausar(origem)})
    if acao == "retomar":
        return jsonify({"ok": True, **_retomar(origem)})
    if acao == "alternar":
        return jsonify({"ok": True, **(_retomar(origem) if agent.pause.paused else _pausar(origem))})
    return jsonify({"erro": "Ação inválida: use pausar, retomar ou alternar."}), 400


@app.route("/api/tarefas", methods=["GET"])
def tarefas():
    """Painel de trabalhos longos do HUD: Forja, tarefas rodando e a pausa."""
    agora = time.time()
    rodando = []
    for tarefa in agent.tasks.list(TaskStatus.RUNNING)[-5:]:
        inicio = tarefa.started_at or tarefa.created_at
        rodando.append({
            "id": tarefa.id[:8],
            "descricao": tarefa.description[:90],
            "segundos": int(max(0.0, agora - inicio)),
        })
    forja: dict[str, Any] = {"ativa": agent.forge_service is not None}
    if agent.forge_service is not None:
        forja.update(agent.forge_service.status())
        atual = forja.get("current")
        if atual and atual.get("started_at"):
            atual["segundos"] = int(max(0.0, agora - float(atual["started_at"])))
    return jsonify({"pausa": agent.pause.status(), "forja": forja, "tarefas": rodando})


@app.route("/api/forja", methods=["GET"])
def forja_status():
    if agent.forge_service is None:
        return jsonify({"ativa": False, "motivo": "Forja desligada: configure ANTHROPIC_API_KEY (ou OPENAI_API_KEY)."})
    return jsonify({"ativa": True, **agent.forge_service.status()})


@app.route("/api/forja", methods=["POST"])
def forja_enviar():
    if agent.forge_service is None:
        return jsonify({"erro": "Forja desligada."}), 503
    dados = request.get_json(silent=True) or {}
    objetivo = dados.get("objetivo") or dados.get("goal")
    if not isinstance(objetivo, str) or not objetivo.strip():
        return jsonify({"erro": "Informe o objetivo."}), 400
    return jsonify({"ok": True, **agent.forge_service.submit(objetivo)})


@app.route("/estado/<novo_estado>", methods=["GET"])
def estado_compatibilidade(novo_estado: str):
    if novo_estado not in {state.value for state in DuqueState}:
        return jsonify({"erro": "Estado inválido."}), 400

    atualizar_estado(novo_estado)
    return obter_estado()


# Presença do HUD ---------------------------------------------------------------
# Cada aba do HUD mantém uma conexão SSE aberta (EventSource continua conectado
# mesmo com a aba em segundo plano, ao contrário dos timers). O launcher e a voz
# só abrem uma interface nova quando nenhuma está conectada: antes cada início,
# reinício (Forja, queda) ou segunda abertura criava mais uma aba.
_hud_lock = Lock()
_hud = {"conectados": 0, "visto": 0.0}
HUD_PING_SECONDS = 5.0


def hud_conectados() -> int:
    with _hud_lock:
        return _hud["conectados"]


def _hud_eventos(ping: float = HUD_PING_SECONDS, limite: int | None = None):
    with _hud_lock:
        _hud["conectados"] += 1
        _hud["visto"] = time.time()
    try:
        yield "retry: 3000\n\n"
        enviados = 0
        while limite is None or enviados < limite:
            with _hud_lock:
                _hud["visto"] = time.time()
            dados = json.dumps({"versao": _VERSAO.get("v", ""), "inicio": _INICIO})
            yield f"event: ping\ndata: {dados}\n\n"
            enviados += 1
            # Uma aba fechada só é notada na próxima escrita: ping curto.
            time.sleep(ping)
    finally:
        with _hud_lock:
            _hud["conectados"] = max(0, _hud["conectados"] - 1)


@app.route("/api/hud/stream", methods=["GET"])
def hud_stream():
    return Response(
        _hud_eventos(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.route("/api/hud", methods=["GET"])
def hud_status():
    with _hud_lock:
        return jsonify({"conectados": _hud["conectados"], "visto": _hud["visto"] or None})


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

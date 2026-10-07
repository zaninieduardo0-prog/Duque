"""O núcleo novo do TELEX: uma IA, um conjunto pequeno de ferramentas confiáveis.

Fluxo: pedido -> IA (Claude ou OpenAI) escolhe ferramentas -> o TELEX executa
e devolve o resultado -> a IA confere e responde. Sem roteador por regex, sem
planejador paralelo, sem operador "às cegas".
"""

from __future__ import annotations

import json
import threading
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any

from . import browser as web
from . import whatsapp
from .browser import Browser
from .llm import History, Reply, Tool, ToolOutput, make_brain
from .pc import Screen, notepad

SYSTEM = """Você é o TELEX, assistente pessoal por voz do Du (Eduardo), no PC Windows dele. Responda sempre em português do Brasil.

Como agir:
- Faça o que o Du pediu usando as ferramentas; não peça confirmação para pedidos claros. Pergunte só quando faltar algo essencial (ex.: para quem enviar) ou antes de algo irreversível que ele não pediu explicitamente.
- WhatsApp: SEMPRE pelas ferramentas whatsapp_* (WhatsApp Web no navegador do TELEX). Nunca abra o app do WhatsApp, nunca pesquise contatos no Google. Se a ferramenta disser que não achou o contato, diga os nomes que apareceram e pergunte qual é.
- Sites e pesquisas: use abrir_site / pesquisar_google. Para agir dentro de uma página: elementos_da_pagina (numera o que dá para clicar/preencher), depois clicar_elemento / digitar_no_elemento. Para saber o que está escrito: ler_pagina.
- Programas do Windows: abrir_programa / fechar_programa. Só use ver_tela + clicar_na_tela + digitar_texto + apertar_teclas quando nenhuma outra ferramenta servir (programas fora do navegador). Depois de clicar, capture a tela de novo para conferir.
- Textos (poema, mensagem, resumo): escreva você mesmo e passe o texto pronto para a ferramenta (bloco_de_notas, whatsapp_enviar, salvar_arquivo...).
- Confira o resultado de cada ferramenta. Nunca diga que fez algo se a ferramenta falhou: diga o que deu errado em uma frase.
- A resposta final é falada: curta (1 a 2 frases), natural, sem listas nem markdown, sem repetir o pedido."""


_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


class TelexAgent:
    def __init__(
        self,
        *,
        brain: Any = None,
        browser: Browser | None = None,
        screen: Screen | None = None,
        legacy_tools: Callable[[str], Callable[..., Any] | None] | None = None,
        history_size: int = 6,
    ) -> None:
        self._brain = brain
        self.browser = browser or Browser()
        self.screen = screen or Screen()
        self.legacy_tools = legacy_tools  # ferramentas do núcleo antigo reaproveitadas (lembretes, clima...)
        self.history: History = []
        self.history_size = history_size
        self._lock = threading.Lock()
        self.tools = self._build_tools()

    @property
    def brain(self) -> Any:
        if self._brain is None:
            self._brain = make_brain()
        return self._brain

    # ferramentas ------------------------------------------------------------------
    def _legacy(self, name: str) -> Callable[..., Any]:
        def call(**kwargs: Any) -> Any:
            function = self.legacy_tools(name) if self.legacy_tools else None
            if function is None:
                raise RuntimeError(f"A ferramenta {name} não está disponível agora.")
            return function(**kwargs)
        return call

    def _open_program(self, nome: str) -> Any:
        if "whatsapp" in nome.casefold() or "zap" in nome.casefold():
            return self.browser.call(lambda b: web._summary(b.page_for(whatsapp.HOST, whatsapp.URL)))
        from computer.tools import ComputerTools

        return ComputerTools().open_app(nome)

    def _close_program(self, nome: str) -> Any:
        from computer.tools import ComputerTools

        return ComputerTools().close_app(nome)

    def _capture(self) -> ToolOutput:
        image, note = self.screen.capture()
        return ToolOutput(note, image_png=image)

    def _save_file(self, nome: str, conteudo: str, pasta: str = "documentos") -> Any:
        from computer.file_tools import FileTools

        return FileTools().save_text_file(nome, conteudo, folder=pasta, overwrite=True)

    def _read_file(self, nome: str, pasta: str = "documentos") -> Any:
        from computer.file_tools import FileTools

        return FileTools().read_text_file(nome, folder=pasta)

    def _recent_files(self, pasta: str = "downloads") -> Any:
        from computer.file_tools import FileTools

        return FileTools().recent_files(folder=pasta)

    def _compose(self, kind: str, **kwargs: Any) -> Any:
        from computer.compose_links import ComposeLinks

        links = ComposeLinks(open_url=lambda url: self.browser.call(web.open_site, url))
        return links.email_compose(**kwargs) if kind == "email" else links.calendar_event(**kwargs)

    def _build_tools(self) -> list[Tool]:
        s, i, b = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}

        def tool(name: str, description: str, function: Callable[..., Any], required: tuple[str, ...] = (), **properties: Any) -> Tool:
            return Tool(name, description, properties, required, function)

        folder = {"type": "string", "description": "documentos, downloads, área de trabalho, imagens..."}
        return [
            # WhatsApp Web
            tool("whatsapp_enviar", "Envia uma mensagem no WhatsApp Web para um contato ou grupo (pelo nome como aparece no WhatsApp). Pesquisa pela busca do WhatsApp e confere o envio.",
                 lambda contato, mensagem: self.browser.call(whatsapp.send_message, contato, mensagem), ("contato", "mensagem"), contato=s, mensagem=s),
            tool("whatsapp_abrir_conversa", "Abre a conversa de um contato ou grupo no WhatsApp Web (sem enviar nada).",
                 lambda contato: self.browser.call(whatsapp.open_chat, contato), ("contato",), contato=s),
            tool("whatsapp_ler", "Lê as últimas mensagens de uma conversa do WhatsApp Web.",
                 lambda contato, quantidade=10: self.browser.call(whatsapp.read_messages, contato, quantidade), ("contato",), contato=s, quantidade=i),
            tool("whatsapp_conversas_recentes", "Lista as conversas mais recentes do WhatsApp Web (com prévia e não lidas).",
                 lambda quantidade=10: self.browser.call(whatsapp.recent_chats, quantidade), (), quantidade=i),
            # Navegador
            tool("abrir_site", "Abre um site no navegador do TELEX (endereço ou nome do site, ex.: 'youtube.com').",
                 lambda endereco: self.browser.call(web.open_site, endereco), ("endereco",), endereco=s),
            tool("pesquisar_google", "Pesquisa no Google e devolve os primeiros resultados (título e link).",
                 lambda pesquisa: self.browser.call(web.google_search, pesquisa), ("pesquisa",), pesquisa=s),
            tool("ler_pagina", "Lê o texto da aba atual do navegador do TELEX.",
                 lambda maximo=6000: self.browser.call(web.read_page, maximo), (), maximo=i),
            tool("elementos_da_pagina", "Lista e numera os botões, links e campos visíveis da aba atual.",
                 lambda: self.browser.call(web.list_elements)),
            tool("clicar_elemento", "Clica no elemento de número N (de elementos_da_pagina).",
                 lambda numero: self.browser.call(web.click_element, numero), ("numero",), numero=i),
            tool("digitar_no_elemento", "Digita um texto no campo de número N (de elementos_da_pagina); enter=true aperta Enter depois.",
                 lambda numero, texto, enter=False: self.browser.call(web.type_into, numero, texto, enter), ("numero", "texto"), numero=i, texto=s, enter=b),
            tool("tecla_na_pagina", "Aperta uma tecla na página (ex.: Enter, Escape, PageDown, Control+F).",
                 lambda tecla: self.browser.call(web.press_key, tecla), ("tecla",), tecla=s),
            tool("voltar_pagina", "Volta para a página anterior.", lambda: self.browser.call(web.go_back)),
            tool("abas", "Lista as abas abertas no navegador do TELEX.", lambda: self.browser.call(web.list_tabs)),
            tool("trocar_aba", "Vai para a aba de número N (de abas).", lambda numero: self.browser.call(web.switch_tab, numero), ("numero",), numero=i),
            tool("fechar_aba", "Fecha a aba atual.", lambda: self.browser.call(web.close_tab)),
            # PC
            tool("abrir_programa", "Abre um programa do Windows pelo nome (ex.: calculadora, Excel, Spotify).", self._open_program, ("nome",), nome=s),
            tool("fechar_programa", "Fecha um programa do Windows pelo nome.", self._close_program, ("nome",), nome=s),
            tool("bloco_de_notas", "Escreve um texto pronto num arquivo e abre no Bloco de Notas.",
                 lambda texto, titulo="": notepad(texto, titulo), ("texto",), texto=s, titulo=s),
            tool("salvar_arquivo", "Salva um texto num arquivo .txt numa pasta do Du.", self._save_file, ("nome", "conteudo"), nome=s, conteudo=s, pasta=folder),
            tool("ler_arquivo", "Lê um arquivo de texto (nome numa pasta do Du, ou caminho completo).", self._read_file, ("nome",), nome=s, pasta=folder),
            tool("arquivos_recentes", "Lista os arquivos mais recentes de uma pasta (padrão: downloads).", self._recent_files, (), pasta=folder),
            tool("ver_tela", "Captura a tela do PC para você ver (use antes de clicar_na_tela).", self._capture),
            tool("clicar_na_tela", "Clica no ponto (x, y) da última captura de tela.",
                 lambda x, y, duplo=False: self.screen.click(x, y, duplo), ("x", "y"), x=i, y=i, duplo=b),
            tool("digitar_texto", "Digita um texto na janela em foco do Windows.", lambda texto: self.screen.type_text(texto), ("texto",), texto=s),
            tool("apertar_teclas", "Aperta uma tecla ou atalho no Windows (ex.: enter, ctrl+s, alt+tab).", lambda teclas: self.screen.keys(teclas), ("teclas",), teclas=s),
            # Rascunhos (abrem prontos no navegador; o Du confere e envia)
            tool("rascunho_email", "Abre um e-mail pronto (Gmail) para o Du conferir e enviar.",
                 lambda para="", assunto="", texto="": self._compose("email", to=para, subject=assunto, body=texto), (), para=s, assunto=s, texto=s),
            tool("evento_agenda", "Abre um evento pronto no Google Agenda (título e quando, ex.: 'amanhã às 15h').",
                 lambda titulo, quando: self._compose("agenda", title=titulo, when=quando), ("titulo", "quando"), titulo=s, quando=s),
            # Do dia a dia (núcleo antigo, já testado)
            tool("lembrete", "Cria um lembrete (quando: 'amanhã às 9h', 'daqui a 20 minutos').",
                 lambda quando, texto="": self._legacy("reminder_at")(when=quando, text=texto), ("quando",), quando=s, texto=s),
            tool("lembretes", "Lista os lembretes agendados.", lambda: self._legacy("reminders_list")()),
            tool("cancelar_lembrete", "Cancela o lembrete de número N (0 = todos).", lambda numero: self._legacy("reminder_cancel")(index=numero), ("numero",), numero=i),
            tool("timer", "Cria um timer em segundos.", lambda segundos, nome="": self._legacy("timer_set")(seconds=segundos, label=nome), ("segundos",), segundos=i, nome=s),
            tool("clima", "Previsão do tempo (cidade opcional).", lambda cidade="": self._legacy("weather")(city=cidade), (), cidade=s),
            tool("volume", "Define o volume do PC em porcentagem.", lambda porcentagem: self._legacy("volume_set")(percent=porcentagem), ("porcentagem",), porcentagem=i),
            tool("midia", "Controla a música/vídeo: play_pause, next, previous, stop ou mute.", lambda acao: self._legacy("media")(action=acao), ("acao",), acao=s),
            tool("copiar", "Copia um texto para a área de transferência.", lambda texto: self._legacy("clipboard_write")(text=texto), ("texto",), texto=s),
        ]

    def _run_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        tool = next((item for item in self.tools if item.name == name), None)
        if tool is None or tool.function is None:
            return ToolOutput(f"Ferramenta desconhecida: {name}", is_error=True)
        try:
            result = tool.function(**arguments)
        except TypeError as exc:
            return ToolOutput(f"Argumentos inválidos para {name}: {exc}", is_error=True)
        except Exception as exc:  # noqa: BLE001 - o erro vira resposta para a IA
            print(f"[TELEX] ferramenta {name} falhou:\n{traceback.format_exc()}", flush=True)
            return ToolOutput(f"Falhou: {exc}", is_error=True)
        if isinstance(result, ToolOutput):
            return result
        failed = isinstance(result, dict) and (result.get("ok") is False or result.get("success") is False)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        return ToolOutput(text[:12000], is_error=failed)

    def handle(self, text: str) -> Reply:
        with self._lock:
            now = datetime.now()
            # A hora vai no pedido, não nas instruções: assim as instruções ficam em cache.
            request = f"{text.strip()}\n\n(Agora: {_WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M})"
            try:
                reply = self.brain.run(SYSTEM, list(self.history), request, self.tools, self._run_tool)
            except Exception as exc:  # noqa: BLE001
                print(f"[TELEX] a IA falhou:\n{traceback.format_exc()}", flush=True)
                return Reply(f"Não consegui falar com a IA agora ({type(exc).__name__}).", failed=True)
            if not reply.text:
                reply.text = "Pronto." if not reply.failed else "Não consegui terminar."
            self.history.append((text.strip(), reply.text))
            del self.history[: -self.history_size]
            return reply

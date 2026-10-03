from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from computer.apps import find_app_in_text

_UNITS = {"segundo": 1, "segundos": 1, "minuto": 60, "minutos": 60, "hora": 3600, "horas": 3600}
_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(segundos?|minutos?|horas?)")


class StepKind(str, Enum):
    THINK = "think"
    TOOL = "tool"
    RESPOND = "respond"


@dataclass(slots=True)
class PlanStep:
    description: str
    kind: StepKind = StepKind.THINK
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)


class Planner:
    """Planejador heurístico determinístico para ações operacionais comuns."""

    @staticmethod
    def _app_name(goal: str) -> str:
        value = goal.strip()
        lowered = value.casefold()
        if lowered.startswith("duque,"):
            value = value[len("duque,"):].strip()
            lowered = value.casefold()
        prefixes = (
            "abrir o aplicativo ", "abrir aplicativo ", "abrir a aplicação ",
            "abrir aplicação ", "abrir o ", "abrir a ", "abrir ",
            "abra o aplicativo ", "abra aplicativo ", "abra o ", "abra a ",
            "abra ", "abre o aplicativo ", "abre aplicativo ", "abre o ", "abre a ",
            "abre ", "inicie o ", "inicie a ", "inicie ",
        )
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return value[len(prefix):].strip().rstrip(".,!?")
        return value.rstrip(".,!?")

    @staticmethod
    def _extract_path(goal: str, markers: tuple[str, ...]) -> str:
        lowered = goal.casefold()
        for marker in markers:
            index = lowered.find(marker)
            if index >= 0:
                return goal[index + len(marker):].strip().rstrip(".,!?")
        return ""

    def build(
        self,
        goal: str,
        intent: str = "chat",
        available_tools: set[str] | None = None,
        context_app: str | None = None,
    ) -> Plan:
        def tool_available(name: str) -> bool:
            return available_tools is None or name in available_tools

        if intent == "open_app":
            app_name = find_app_in_text(goal) or ""
            if not app_name and context_app and re.search(r"\b(?:novamente|de novo|outra vez|ele|ela|isso)\b", goal.casefold()):
                app_name = context_app
            app_name = app_name or self._app_name(goal)
            if not tool_available("open_app"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Abrir o aplicativo solicitado: {app_name}",
                StepKind.TOOL, "open_app", {"name": app_name},
            )])

        if intent == "close_app":
            lowered = goal.casefold()
            names = (
                ("chrome", "chrome"), ("navegador", "chrome"), ("browser", "chrome"),
                ("edge", "edge"), ("whatsapp", "whatsapp"),
                ("bloco de notas", "bloco de notas"), ("notepad", "notepad"),
                ("calculadora", "calculadora"), ("paint", "paint"),
            )
            app_name = next((name for marker_text, name in names if marker_text in lowered), "")
            if not app_name:
                app_name = find_app_in_text(goal) or self._app_name(goal)
            if not tool_available("close_app"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Fechar o aplicativo solicitado: {app_name}",
                StepKind.TOOL, "close_app", {"name": app_name},
            )])

        if intent == "check_app":
            lowered = goal.casefold()
            names = (
                ("chrome", "chrome"), ("navegador", "chrome"),
                ("edge", "edge"), ("whatsapp", "whatsapp"),
                ("bloco de notas", "bloco de notas"), ("notepad", "notepad"),
                ("calculadora", "calculadora"), ("paint", "paint"),
            )
            app_name = next((name for marker_text, name in names if marker_text in lowered), "")
            if not app_name:
                app_name = find_app_in_text(goal) or context_app or self._app_name(goal)
            if not tool_available("is_app_running"):
                return Plan(goal)
            return Plan(goal, [PlanStep(
                f"Verificar se o aplicativo está em execução: {app_name}",
                StepKind.TOOL, "is_app_running", {"name": app_name},
            )])

        if intent == "open_search_result":
            if not tool_available("open_search_result"):
                return Plan(goal)
            lowered = goal.casefold()
            index = 1
            for marker in ("resultado ", "resultado número ", "resultado numero "):
                position = lowered.find(marker)
                if position >= 0:
                    remainder = goal[position + len(marker):].strip()
                    digits = ""
                    for char in remainder:
                        if char.isdigit():
                            digits += char
                        else:
                            break
                    if digits:
                        index = int(digits)
                    break
            return Plan(goal, [PlanStep(
                f"Abrir o resultado de pesquisa {index}",
                StepKind.TOOL, "open_search_result", {"index": index},
            )])

        if intent == "search":
            query = self.search_query(goal)
            lowered = goal.casefold()
            wants_browser = any(word in lowered for word in ("google", "navegador", "página", "pagina", "chrome", "abra", "abre", "abrir"))
            tool = "google_search" if wants_browser and tool_available("google_search") else "web_search"
            if not tool_available(tool):
                return Plan(goal)
            return Plan(goal, [PlanStep(f"Pesquisar: {query}", StepKind.TOOL, tool, {"query": query})])

        if intent == "file_operation":
            lowered = goal.casefold()
            folder_plan = self._folder_or_search_plan(goal, tool_available)
            if folder_plan is not None:
                return folder_plan
            if any(marker in lowered for marker in (
                "liste os arquivos", "listar os arquivos", "liste os ficheiros",
                "listar arquivos", "mostre os arquivos", "mostra os arquivos",
                "mostre os ficheiros", "listar a pasta", "mostre a pasta",
            )):
                if tool_available("list_files"):
                    return Plan(goal, [PlanStep(
                        "Listar os arquivos do workspace", StepKind.TOOL, "list_files", {}
                    )])
                if tool_available("inspect_workspace"):
                    return Plan(goal, [PlanStep(
                        "Inspecionar o workspace", StepKind.TOOL, "inspect_workspace", {}
                    )])

            path = self._extract_path(goal, (
                "leia o arquivo ", "ler o arquivo ", "abra o arquivo ",
                "leia arquivo ", "ler arquivo ", "abra arquivo ",
                "analise o arquivo ", "analisa o arquivo ",
                "analise arquivo ", "analisa arquivo ",
                "mostre o conteúdo de ", "mostre o conteudo de ",
            ))
            if path and tool_available("read_file"):
                return Plan(goal, [PlanStep(
                    f"Ler o arquivo solicitado: {path}",
                    StepKind.TOOL, "read_file", {"path": path},
                )])

            if any(marker in lowered for marker in (
                "analise o projeto", "analisa o projeto", "verifique o projeto",
                "verifica o projeto", "inspecione o projeto", "inspeciona o projeto",
                "estrutura do projeto", "estrutura do repositório",
            )):
                if tool_available("inspect_workspace"):
                    return Plan(goal, [PlanStep(
                        "Inspecionar o workspace", StepKind.TOOL, "inspect_workspace", {}
                    )])

            path = self._extract_path(goal, (
                "apague o arquivo ", "delete o arquivo ", "exclua o arquivo ",
                "apague arquivo ", "delete arquivo ", "exclua arquivo ",
            ))
            if path and tool_available("delete_file"):
                return Plan(goal, [PlanStep(
                    f"Excluir o arquivo solicitado: {path}",
                    StepKind.TOOL, "delete_file", {"path": path},
                )])

            for marker_text in ("crie o arquivo ", "criar o arquivo ", "escreva o arquivo ", "salve o arquivo "):
                if marker_text in lowered and tool_available("write_file"):
                    remainder = goal[lowered.index(marker_text) + len(marker_text):].strip()
                    separator = " com conteúdo "
                    if separator in remainder.casefold():
                        split_at = remainder.casefold().index(separator)
                        path = remainder[:split_at].strip()
                        content = remainder[split_at + len(separator):]
                        if path and content:
                            return Plan(goal, [PlanStep(
                                f"Criar o arquivo solicitado: {path}",
                                StepKind.TOOL, "write_file",
                                {"path": path, "content": content},
                            )])
            return Plan(goal)

        if intent == "code":
            steps = [PlanStep("Entender o objetivo e os requisitos", StepKind.THINK)]
            if tool_available("list_files"):
                steps.append(PlanStep("Listar o workspace antes da alteração", StepKind.TOOL, "list_files"))
            steps.extend([
                PlanStep("Escrever ou modificar o código", StepKind.THINK),
                PlanStep("Executar a verificação disponível", StepKind.THINK),
                PlanStep("Relatar o resultado", StepKind.RESPOND),
            ])
            return Plan(goal, steps)

        assistant_plan = self._assistant_plan(goal, intent, tool_available)
        if assistant_plan is not None:
            return assistant_plan

        if intent in {"reminder", "system"}:
            return Plan(goal)

        return Plan(goal, [PlanStep("Responder à solicitação", StepKind.RESPOND)])

    @staticmethod
    def search_query(goal: str) -> str:
        """Tira o pedido em volta e deixa só o que pesquisar."""
        text = goal.strip()
        match = re.search(r"\b(?:pesquis[ae]r?|procur[ae]r?|busc[ae]r?)\b\s*(?:no google|na internet|na web|sobre|por)?\s*[:,]?\s*(.+)$", text, flags=re.IGNORECASE)
        if match:
            text = match.group(1)
        text = re.sub(r"\s*(?:no google|na internet|na web|no navegador|por aqui mesmo)\s*", " ", text, flags=re.IGNORECASE)
        return text.strip(" .,!?") or goal.strip()

    @staticmethod
    def parse_duration(text: str) -> float | None:
        """Soma durações como "1 hora e 30 minutos" em segundos."""
        total = 0.0
        for amount, unit in _DURATION.findall(text.casefold()):
            total += float(amount.replace(",", ".")) * _UNITS[unit]
        return total or None

    @staticmethod
    def _folder_or_search_plan(goal: str, tool_available) -> Plan | None:
        """"abre a pasta downloads" e "procura arquivos chamados X" no computador do Du."""
        from computer.assistant_tools import KNOWN_FOLDERS

        lowered = " ".join(goal.casefold().split())
        if re.search(r"\b(?:abr[ae]|abrir|mostr[ae])\b", lowered) and "pasta" in lowered and tool_available("open_folder"):
            for name in sorted(KNOWN_FOLDERS, key=len, reverse=True):
                if re.search(rf"\b{re.escape(name)}\b", lowered):
                    return Plan(goal, [PlanStep(f"Abrir a pasta {name}", StepKind.TOOL, "open_folder", {"name": name})])
        if re.search(r"\b(?:procur[ae]|procurar|encontr[ae]|encontrar|ach[ae]|localiz[ae])\b", lowered) and "arquivo" in lowered and tool_available("find_files"):
            quoted = re.search(r"[\"'“]([^\"'”]+)[\"'”]", goal)
            named = re.search(r"(?:chamad[oa]s?|com o nome|nomead[oa]s?|de nome)\s+(.+?)(?:\s+na pasta.*)?[?.!]*$", goal, flags=re.IGNORECASE)
            name = (quoted.group(1) if quoted else named.group(1) if named else "").strip()
            if name:
                return Plan(goal, [PlanStep(f"Procurar arquivos: {name}", StepKind.TOOL, "find_files", {"name": name})])
        return None

    @staticmethod
    def _shortcut_plan(goal: str, lowered: str, single) -> Plan | None:
        social = Planner._social_plan(goal, lowered, single)
        if social is not None:
            return social
        if re.search(r"bloque(?:ie|ia|ar)", lowered):
            return single("Bloquear a tela", "lock_screen", {})
        if re.search(r"\btela\b|o que você (?:vê|ve)|o que voce (?:vê|ve)", lowered):
            return single("Olhar a tela", "describe_screen", {"question": goal})
        if "foco" in lowered or "pomodoro" in lowered:
            if re.search(r"\b(?:sair|sai|encerr\w*|termin\w*|desativ\w*|deslig\w*)\b|\bpar[ae] (?:o |do )?(?:modo )?foco\b", lowered):
                return single("Encerrar o modo foco", "focus_mode", {"action": "stop"})
            minutes = (Planner.parse_duration(goal) or 25 * 60) / 60
            return single("Ativar o modo foco", "focus_mode", {"action": "start", "minutes": minutes})
        if "lembrete" in lowered or "agenda" in lowered or "agendado" in lowered or "marcado" in lowered:
            if re.search(r"cancel(?:a|e|ar)", lowered):
                number = re.search(r"\b(\d+)\b", lowered)
                return single("Cancelar lembrete", "reminder_cancel", {"index": int(number.group(1)) if number else 0})
            return single("Ver a agenda", "reminders_list", {})
        verbs = r"(?:toca|toque|tocar|coloca|coloque|bota|abre|abra|abrir|pesquise|pesquisa|procure|procura|busque|busca|ache|acha)"
        for service in ("youtube", "spotify"):
            match = re.search(rf"{verbs}\s+(.+?)\s+no {service}\b", goal, flags=re.IGNORECASE)
            if match:
                return single(f"Abrir {service}", service, {"query": match.group(1).strip(" \"'")})
        match = re.search(r"(?:como (?:chego|chegar|vou)|rota|mapa)\s+(?:para|até|ate|em|no|na|ao|à|de|do|da)\s+(.+?)[?.!]*$", goal, flags=re.IGNORECASE)
        if match:
            return single("Abrir o mapa", "maps", {"destination": match.group(1).strip()})
        if re.search(r"(?:computador|pc|notebook|sistema|cpu|memória|memoria|bateria)", lowered) and not re.search(r"cop(?:ie|ia|iar)", lowered):
            return single("Ver o estado do computador", "system_status", {})
        match = re.search(r"cop(?:ie|ia|iar)\s+[\"“'](.+?)[\"”'](?:\s|$)", goal, flags=re.IGNORECASE)
        if match:
            return single("Copiar texto", "clipboard_write", {"text": match.group(1)})
        if re.search(r"(?:área|area) de transfer", lowered):
            return single("Ler a área de transferência", "clipboard_read", {})
        if re.search(r"bloque(?:ie|ia|ar)", lowered):
            return single("Bloquear a tela", "lock_screen", {})
        if re.search(r"cancel(?:a|e|ar)", lowered):
            return single("Cancelar timers", "timer_cancel", {})
        if "timer" in lowered:
            return single("Listar timers", "timers_list", {})
        return None

    @staticmethod
    def _social_plan(goal: str, lowered: str, single) -> Plan | None:
        """WhatsApp, contatos, rotinas e resumo do dia."""
        text = goal.strip()
        if "voz" in lowered or "vozes" in lowered:
            from .voice_style import VOICES

            chosen = next((name for name in VOICES if re.search(rf"\b{name}\b", lowered)), None)
            if chosen and re.search(r"\b(?:mud|troc|us|coloqu?|alter|escolh)\w*", lowered):
                return single("Trocar a voz", "set_voice", {"name": chosen})
            return single("Listar vozes", "list_voices", {})
        if re.search(r"\b(?:mand[ae]|envi[ae]|escrev[ae])\b[^.?!]*\b(?:mensagem|msg|zap|whatsapp)\b", lowered):
            match = re.search(
                r"\b(?:para|pro|pra|ao|à)\s+(?:o |a )?(.+?)(?:\s+(?:no|pelo) (?:whatsapp|zap))?(?:\s+(?:dizendo(?: que)?|falando(?: que)?|escrito|com o texto|que)\s+|\s*:\s*)(.+)$",
                text, flags=re.IGNORECASE,
            )
            if match:
                contact = re.sub(r"\s+(?:no|pelo) (?:whatsapp|zap)$", "", match.group(1), flags=re.IGNORECASE).strip()
                return single("Preparar mensagem no WhatsApp", "whatsapp_message", {"contact": contact, "text": match.group(2).strip()})
            body = re.search(r"(?:dizendo|falando|escrito|com o texto|:)\s*(.+)$", text, flags=re.IGNORECASE)
            if body:
                return single("Preparar mensagem no WhatsApp", "whatsapp_message", {"contact": "", "text": body.group(1).strip()})
            return None
        if "meus contatos" in lowered:
            return single("Listar contatos", "contacts_list", {})
        if "contato" in lowered:
            match = re.search(r"contato\s+(.+?)\s+(\+?\d[\d\s().-]{8,})\s*$", text, flags=re.IGNORECASE)
            if match:
                return single("Salvar contato", "contact_save", {"name": match.group(1).strip(), "phone": match.group(2).strip()})
            return None
        if "minhas rotinas" in lowered:
            return single("Listar rotinas", "routines_list", {})
        if "rotina" in lowered:
            if re.search(r"\b(?:cri[ae]|salv[ae]|nova)\b", lowered):
                match = re.search(r"rotina\s+([\wÀ-ú]+)\s*(?:com|:|-|=|que faz|que)?\s*(.+)$", text, flags=re.IGNORECASE)
                if match:
                    return single("Salvar rotina", "routine_save", {"name": match.group(1), "commands": match.group(2)})
                return None
            name = re.search(r"rotina\s+(?:de\s+|do\s+|da\s+)?([\wÀ-ú]+)", text, flags=re.IGNORECASE)
            if not name:
                return None
            if re.search(r"\b(?:apag|exclu|remov)\w*", lowered):
                return single("Apagar rotina", "routine_delete", {"name": name.group(1)})
            return single("Rodar rotina", "routine_run", {"name": name.group(1)})
        mode = re.search(r"modo\s+([\wÀ-ú]+)\s*$", lowered)
        if mode and mode.group(1) != "foco":
            return single("Rodar rotina", "routine_run", {"name": mode.group(1)})
        if re.search(r"resumo do (?:meu )?dia|como foi (?:o )?meu dia|o que (?:eu )?fiz hoje", lowered):
            return single("Resumo do dia", "day_summary", {})
        return None

    def _assistant_plan(self, goal: str, intent: str, tool_available) -> Plan | None:
        """Planos determinísticos para as ferramentas do dia a dia."""
        lowered = " ".join(goal.casefold().split())

        def single(description: str, tool: str, arguments: dict[str, Any]) -> Plan | None:
            if not tool_available(tool):
                return None
            return Plan(goal, [PlanStep(description, StepKind.TOOL, tool, arguments)])

        if intent == "shortcut":
            return self._shortcut_plan(goal, lowered, single)
        if intent == "time":
            return single("Consultar data e hora", "current_time", {})
        if intent == "weather":
            match = re.search(r"\b(?:em|de|para)\s+([a-zà-ú][a-zà-ú\s]+?)(?:\?|$|\s+(?:hoje|agora|amanhã|amanha))", lowered)
            city = match.group(1).strip() if match and match.group(1).strip() not in {"hoje", "agora"} else ""
            return single("Consultar o clima", "weather", {"city": city} if city else {})
        if intent == "media":
            if any(word in lowered for word in ("próxima", "proxima", "pula")):
                action = "next"
            elif any(word in lowered for word in ("anterior", "volta a")):
                action = "previous"
            else:
                action = "play_pause"
            return single("Controlar a mídia", "media", {"action": action})
        if intent == "note":
            if any(word in lowered for word in ("minhas notas", "minhas anotações", "minhas anotacoes", "leia as notas", "sabe sobre mim", "lembra de mim")):
                return single("Listar notas", "notes_list", {})
            text = re.sub(r"^(?:duque[,!]?\s+)?(?:anote|anota|faça uma nota|faz uma nota|lembre|lembra|guarde|guarda|memorize|memoriza)\s*(?:que|:)?\s*", "", goal.strip(), flags=re.IGNORECASE)
            return single("Guardar nota", "note_add", {"text": text or goal})
        if intent == "calc":
            expression = re.sub(r"^(?:duque[,!]?\s+)?(?:quanto é|quanto e|calcule|calcula)\s*", "", goal.strip(), flags=re.IGNORECASE).rstrip("?! ")
            return single("Calcular", "calculate", {"expression": expression})
        if intent == "reminder":
            seconds = self.parse_duration(goal)
            if seconds:
                label = re.sub(r"\b(?:em|daqui a|daqui)\s+\d+.*$", "", goal, flags=re.IGNORECASE)
                label = re.sub(r"^(?:duque[,!]?\s+)?(?:me lembre|me lembra|me avise|me avisa|crie um timer|cria um timer|timer)\s*(?:de|para|que)?\s*", "", label.strip(), flags=re.IGNORECASE)
                arguments: dict[str, Any] = {"seconds": seconds}
                if label.strip(" .,!?"):
                    arguments["label"] = label.strip(" .,!?")
                return single("Criar timer", "timer_set", arguments)
            from .when import parse_when

            when = parse_when(goal)
            if when is not None:
                return single("Agendar lembrete", "reminder_at", {"when": goal, "text": when.rest})
            return None
        if intent == "system":
            if any(word in lowered for word in ("aumente o volume", "aumentar o volume", "aumenta o volume", "sobe o volume")):
                return single("Aumentar volume", "volume", {"direction": "up"})
            if any(word in lowered for word in ("diminua o volume", "diminuir o volume", "diminui o volume", "abaixa o volume", "abaixe o volume")):
                return single("Diminuir volume", "volume", {"direction": "down"})
            if any(word in lowered for word in ("mute", "mutar", "desative o som", "ative o som", "silencie")):
                return single("Alternar mudo", "volume", {"direction": "mute"})
            if any(word in lowered for word in ("bloqueie", "bloquear", "bloqueia")) and "tela" in lowered:
                return single("Bloquear a tela", "lock_screen", {})
        return None

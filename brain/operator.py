"""Operador: o TELEX usando o computador sozinho para cumprir um pedido.

Entra quando não existe ferramenta pronta para o pedido (ou quando o caminho
pronto falhou): avalia se é possível, age uma etapa por vez (ferramentas
diretas primeiro; tela, clique e teclado quando precisa), confere cada passo
olhando a tela e termina com evidência — ou diz com honestidade que não
consegue e o que faltaria.

Limites: 30 ações e 6 minutos por pedido. Ações de risco alto (apagar,
mover, rodar comandos no sistema) continuam pedindo confirmação.
"""

from __future__ import annotations

import re

OPERATOR_SYSTEM = (
    "Você é o TELEX operando o computador Windows do Du para cumprir o pedido dele, com autonomia e honestidade.\n"
    "1) Primeiro avalie se é possível com as ferramentas disponíveis. Se não for (precisa de senha que você não tem, "
    "pagamento, algo fora do computador, ou falta uma ferramenta), responda "
    '{"action":"cannot","message":"por que não dá e o que faltaria"} — sem tentar à toa.\n'
    "2) Prefira ferramentas diretas (open_app, open_url, youtube_play, whatsapp_send, notepad_write, find_files, "
    "read_any_file, write_any_file, run_command, chrome_profiles...) a mexer na tela.\n"
    "3) Para usar janelas: describe_screen para ver o que há na tela; click_on com uma descrição clara do elemento "
    "(ex.: 'botão azul Enviar no canto inferior direito'); ui_type_text para digitar; ui_hotkey/ui_press para atalhos; "
    "wait para esperar carregar.\n"
    "4) Depois de cada ação que muda a tela, confira com describe_screen antes de seguir. Nunca diga que fez sem evidência.\n"
    "5) Não faça compras nem pagamentos, não apague nada e não envie mensagens que ele não pediu.\n"
    "Uma ação por resposta. Responda SOMENTE JSON: "
    '{"action":"tool","tool":"nome","arguments":{},"reason":"por que esta ação"} | '
    '{"action":"finish","message":"o que foi feito e qual a evidência"} | '
    '{"action":"cannot","message":"por que não dá"}.'
)

# Pedidos que mandam fazer algo (e não perguntas ou conversa).
ACTION_REQUEST = re.compile(
    r"^(?:telex[\s,!.:-]+)?(?:por favor[,]?\s+)?(?:(?:você )?(?:pode|consegue|poderia)\s+)?(?:me\s+)?"
    r"(?:abr|fech|cliqu|clic|entr[ae]\b|acess|baix|instal|desinstal|configur|ativ|desativ|mud|troqu|troc|cri[ae]|"
    r"fa[cç]a|faz\b|coloqu|coloc|ponha|procur|pesquis|ach[ae]|encontr|envi|mand|organiz|renomei|mov|copi|limp|"
    r"atualiz|verifiqu|verific|confir|lig[ue]|deslig|preench|respond|compartilh|imprim|salv|edit|escrev|digit|"
    r"toqu|toc|selecion|marqu|desmarqu|rol[ae]|minimiz|maximiz|feche|agend)\w*",
    re.IGNORECASE,
)


def looks_like_action(text: str) -> bool:
    value = " ".join((text or "").split())
    return bool(value) and not value.endswith("?") and bool(ACTION_REQUEST.match(value))

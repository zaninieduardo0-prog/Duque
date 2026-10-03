"""Escrever no Bloco de Notas de um jeito confiável.

Em vez de digitar tecla por tecla numa janela (que perde foco, acentos e
quebras de linha), o TELEX grava o texto num arquivo .txt em
Documentos/TELEX e abre esse arquivo no Bloco de Notas. Depois confere no
disco se o conteúdo está lá — a regra da casa: só diz que fez com evidência.

Pedidos de criação ("um poema sobre o mar", "uma lista de compras para
churrasco") são escritos pelo modelo; texto ditado ("escreva: oi, tudo bem")
vai literalmente.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

COMPOSE_WORDS = re.compile(
    r"^(?:um|uma|uns|umas|o|a|meu|minha)?\s*(?:pequen[oa]s?\s+|curt[oa]s?\s+|bel[oa]s?\s+|nov[oa]s?\s+)?"
    r"(?:poema|poesia|soneto|haicai|texto|carta|hist[oó]ria|conto|lista|reda[cç][aã]o|mensagem|resumo|piada|"
    r"receita|e-?mail|par[aá]grafo|frase|discurso|roteiro|plano|cronograma|ideias|dicas|letra|post|legenda|bilhete|"
    r"artigo|cr[oô]nica|pensamento|reflex[aã]o|agenda|checklist)\b",
    re.IGNORECASE,
)

COMPOSE_PROMPT = (
    "Escreva somente o conteúdo pedido, em português do Brasil, pronto para colar num arquivo de texto. "
    "Sem título de explicação, sem comentários antes ou depois, sem markdown. Pedido: {request}"
)


def needs_composing(request: str) -> bool:
    text = request.strip()
    if not text or text[0] in "\"“'":
        return False
    return bool(COMPOSE_WORDS.match(text))


def slug(text: str, limit: int = 32) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]+", plain)
    stop = {"um", "uma", "o", "a", "de", "do", "da", "sobre", "para", "com", "e"}
    useful = [word for word in words if word not in stop][:4] or ["texto"]
    return "-".join(useful)[:limit].strip("-") or "texto"


def default_folder() -> Path:
    custom = os.getenv("DUQUE_NOTES_DIR", "").strip()
    if custom:
        return Path(custom)
    return Path.home() / "Documents" / "TELEX"


def _open_in_notepad(path: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["notepad.exe", str(path)])
    else:  # fora do Windows (testes, desenvolvimento): só registra
        print(f"[notepad] abriria {path}")


class NotepadWriter:
    def __init__(
        self,
        compose: Callable[[str], str] | None = None,
        *,
        folder: Path | None = None,
        opener: Callable[[Path], Any] = _open_in_notepad,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.compose = compose
        self.folder = folder
        self.opener = opener
        self.clock = clock

    def notepad_write(self, request: str) -> dict[str, Any]:
        request = (request or "").strip()
        if not request:
            return {"success": False, "error": "Não sei o que escrever no Bloco de Notas."}
        composed = needs_composing(request) and self.compose is not None
        if composed:
            assert self.compose is not None
            try:
                content = self.compose(COMPOSE_PROMPT.format(request=request)).strip()
            except Exception as exc:
                return {"success": False, "error": f"Não consegui escrever o texto: {type(exc).__name__}: {exc}"}
        else:
            content = request.strip("\"“”'")
        if not content:
            return {"success": False, "error": "O texto ficou vazio."}

        folder = self.folder or default_folder()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = self.clock().strftime("%Y-%m-%d_%H%M%S")
        path = folder / f"{slug(request)}_{stamp}.txt"
        path.write_text(content + "\n", encoding="utf-8")

        # Evidência real antes de abrir: o arquivo existe e tem o texto.
        if path.read_text(encoding="utf-8").strip() != content.strip():
            return {"success": False, "error": "O arquivo não ficou com o texto esperado."}
        try:
            self.opener(path)
        except OSError as exc:
            return {"success": False, "error": f"Escrevi em {path}, mas o Bloco de Notas não abriu: {exc}"}
        what = "Escrevi" if composed else "Coloquei o texto"
        return {
            "message": f"{what} no Bloco de Notas ({len(content.split())} palavras). Arquivo salvo em Documentos/TELEX/{path.name}.",
            "path": str(path),
            "words": len(content.split()),
            "composed": composed,
        }

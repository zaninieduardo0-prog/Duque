"""Mensagens pelo WhatsApp com confirmação humana.

O Duque abre a conversa com o texto já escrito; quem envia é o Du (Enter).
Nada é enviado sozinho. Contatos ficam na memória local do Duque.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any, Callable

from memory.memory import Memory, MemoryLayer

KEY = "contatos"


def _key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def normalize_phone(phone: str, default_country: str = "55") -> str | None:
    digits = re.sub(r"\D", "", phone)
    if len(digits) in (10, 11):  # DDD + número, sem país
        digits = default_country + digits
    if not 12 <= len(digits) <= 15:
        return None
    return digits


class Messaging:
    def __init__(self, memory: Memory, open_target: Callable[[str], None]) -> None:
        self.memory = memory
        self.open_target = open_target

    def _contacts(self) -> dict[str, dict[str, str]]:
        data = self.memory.recall(MemoryLayer.PERSONAL, KEY, {})
        return data if isinstance(data, dict) else {}

    def contact_save(self, name: str, phone: str) -> dict[str, Any]:
        number = normalize_phone(phone)
        if number is None:
            return {"success": False, "error": f"Número inválido: {phone}. Use DDD + número, ex.: 19 99999-9999."}
        contacts = self._contacts()
        contacts[_key(name)] = {"name": name.strip(), "phone": number}
        self.memory.remember(MemoryLayer.PERSONAL, KEY, contacts)
        return {"message": f"Contato {name.strip()} salvo.", "phone": number}

    def contacts_list(self) -> dict[str, Any]:
        contacts = self._contacts()
        if not contacts:
            return {"message": "Nenhum contato salvo.", "contacts": []}
        items = sorted(contacts.values(), key=lambda item: item["name"].casefold())
        return {"message": "Contatos: " + ", ".join(item["name"] for item in items), "contacts": items}

    def whatsapp_message(self, contact: str, text: str) -> dict[str, Any]:
        if not text.strip():
            return {"success": False, "error": "A mensagem está vazia."}
        found = self._contacts().get(_key(contact)) if contact.strip() else None
        query = {"text": text.strip()}
        if found:
            query["phone"] = found["phone"]
        url = "whatsapp://send?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
        self.open_target(url)
        if found:
            message = f"Abri o WhatsApp com a mensagem pronta para {found['name']}. É só conferir e apertar Enter."
        else:
            message = (
                f"Não tenho o número de '{contact}'. Abri o WhatsApp com a mensagem pronta para você escolher o contato. "
                "Para eu saber da próxima vez: 'salve o contato Nome 19 99999-9999'."
            ) if contact.strip() else "Abri o WhatsApp com a mensagem pronta para você escolher o contato."
        return {"message": message, "url": url, "contact_found": bool(found)}

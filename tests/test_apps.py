from __future__ import annotations

from computer.apps import resolve_app


def test_resolve_whatsapp_uses_explicit_protocol_launcher() -> None:
    command = resolve_app("WhatsApp")
    assert command is not None
    assert command[:3] == ["cmd.exe", "/c", "start"]
    assert command[-1] == "whatsapp:"


def test_resolve_unknown_app_does_not_invent_command() -> None:
    assert resolve_app("definitely-not-a-real-duque-app") is None

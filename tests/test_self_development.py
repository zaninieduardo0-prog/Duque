from __future__ import annotations

from brain.self_development import SelfDevelopment
from computer.workspace import Workspace


def test_self_development_is_read_only_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DUQUE_ALLOW_SELF_MODIFICATION", raising=False)
    development = SelfDevelopment(Workspace(str(tmp_path)))

    result = development.apply_change("example.py", "print('x')")

    assert result["success"] is False
    assert "DUQUE_ALLOW_SELF_MODIFICATION" in result["error"]
    assert not (tmp_path / "example.py").exists()


def test_self_development_can_write_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DUQUE_ALLOW_SELF_MODIFICATION", "1")
    development = SelfDevelopment(Workspace(str(tmp_path)))

    result = development.apply_change("example.py", "print('x')")

    assert result["changed"] is True
    assert (tmp_path / "example.py").read_text(encoding="utf-8") == "print('x')"

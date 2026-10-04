from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Arquivos que formam os "freios" do sistema. Uma alteração neles nunca é
# aplicada automaticamente: o PR fica aberto aguardando aprovação humana.
DEFAULT_PROTECTED = (
    "core/security.py",
    "forge/*",
    ".github/*",
    "duque_supervisor.py",
    "Duque.vbs",
    "iniciar_duque.bat",
    "pyproject.toml",
    # configuração que muda como os testes rodam (ou o que é ignorado)
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
    "conftest.py",
    "*/conftest.py",
    "sitecustomize.py",
    "*/sitecustomize.py",
    "usercustomize.py",
    "*/usercustomize.py",
    ".gitignore",
    ".gitattributes",
)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def parse_github_slug(url: str) -> str | None:
    """Extrai 'dono/repo' de URLs https ou ssh do GitHub."""
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


@dataclass(slots=True)
class ForgeConfig:
    repo_root: Path
    forge_dir: Path
    remote: str = "origin"
    base_branch: str = "main"
    branch_prefix: str = "duque/forja-"
    protected: tuple[str, ...] = DEFAULT_PROTECTED
    auto_merge: bool = True
    require_ci: bool = True
    max_rounds: int = 3
    agent_max_steps: int = 80
    ci_timeout_seconds: int = 1200
    ci_poll_seconds: int = 20
    ci_grace_seconds: int = 180
    checks: tuple[str, ...] = ("compile", "imports", "pytest", "ruff")
    github_slug: str | None = None
    github_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, repo_root: str | Path | None = None) -> ForgeConfig:
        root = Path(repo_root or os.getenv("DUQUE_WORKSPACE_ROOT", ".")).resolve()
        forge_dir = Path(os.getenv("DUQUE_FORGE_DIR", str(root / "duque_data" / "forja"))).resolve()
        checks = tuple(
            item.strip()
            for item in os.getenv("DUQUE_FORGE_CHECKS", "compile,imports,pytest,ruff").split(",")
            if item.strip()
        )
        return cls(
            repo_root=root,
            forge_dir=forge_dir,
            remote=os.getenv("DUQUE_FORGE_REMOTE", "origin"),
            base_branch=os.getenv("DUQUE_FORGE_BASE", "main"),
            auto_merge=_env_flag("DUQUE_FORGE_AUTO_MERGE", True),
            require_ci=_env_flag("DUQUE_FORGE_REQUIRE_CI", True),
            max_rounds=int(os.getenv("DUQUE_FORGE_MAX_ROUNDS", "3")),
            agent_max_steps=int(os.getenv("DUQUE_FORGE_MAX_STEPS", "80")),
            ci_timeout_seconds=int(os.getenv("DUQUE_FORGE_CI_TIMEOUT", "1200")),
            checks=checks,
            github_slug=os.getenv("DUQUE_GITHUB_REPO") or None,
            github_token=os.getenv("DUQUE_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or None,
        )

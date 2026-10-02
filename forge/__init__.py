"""Forja: o Duque desenvolvendo a si mesmo com segurança.

Fluxo: cópia isolada (git worktree) -> agente programador -> portão de
qualidade independente -> commit/push em branch -> PR -> CI -> merge
fast-forward no main -> atualização da instalação ao vivo com rollback.

A cópia em execução nunca é editada diretamente pelo agente.
"""

from .config import ForgeConfig
from .forge import Forge, ForgeReport, ForgeStatus

__all__ = ["Forge", "ForgeConfig", "ForgeReport", "ForgeStatus"]

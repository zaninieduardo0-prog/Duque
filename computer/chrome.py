"""Abre links no Chrome com o perfil do Du (sem a tela de escolher conta).

O perfil é procurado no arquivo "Local State" do Chrome pelo nome ou e-mail
(padrão: "zaninieduardo0"; troque com a variável DUQUE_CHROME_PROFILE, que
também aceita o nome da pasta, ex.: "Profile 1").
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PROFILE = "zaninieduardo0"


def wanted_profile(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("DUQUE_CHROME_PROFILE") or DEFAULT_PROFILE).strip()


def user_data_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def chrome_executable(env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    candidates = [
        Path(env.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def find_profile(local_state: dict[str, Any], wanted: str, *, strict: bool = False) -> str | None:
    """Pasta do perfil (ex.: "Profile 2") cujo nome/e-mail bate com `wanted`.

    Com ``strict``, não cai no último perfil usado quando nada bate.
    """
    profile = local_state.get("profile") or {}
    cache = profile.get("info_cache") or {}
    target = wanted.casefold().strip()
    if target and isinstance(cache, dict):
        for directory in cache:
            if directory.casefold() == target:
                return directory
        for directory, info in cache.items():
            if not isinstance(info, dict):
                continue
            fields = (info.get(key) for key in ("user_name", "name", "gaia_name", "gaia_given_name", "shortcut_name"))
            if any(target in str(value).casefold() for value in fields if value):
                return directory
    if strict:
        return None
    last_used = profile.get("last_used")
    return str(last_used) if last_used else None


def resolve_profile(env: Mapping[str, str] | None = None) -> str | None:
    path = user_data_dir(env) / "Local State"
    try:
        local_state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Só força um perfil quando ele foi encontrado pelo nome/e-mail. Forçar o
    # "último usado" abria uma janela nova (às vezes sem carregar o site);
    # sem perfil, o link vira uma aba nova no Chrome que já está aberto.
    return find_profile(local_state, wanted_profile(env), strict=True)


def chrome_command(url: str | None = None, env: Mapping[str, str] | None = None) -> list[str] | None:
    executable = chrome_executable(env)
    if not executable:
        return None
    command = [executable]
    profile = resolve_profile(env)
    if profile:
        command.append(f"--profile-directory={profile}")
    if url:
        command.append(url)
    return command


def open_in_chrome(url: str | None = None) -> bool:
    """Abre no Chrome do Du. Retorna False se não for Windows ou não achar o Chrome."""
    if platform.system() != "Windows":
        return False
    command = chrome_command(url)
    if not command:
        return False
    subprocess.Popen(command, shell=False)
    return True

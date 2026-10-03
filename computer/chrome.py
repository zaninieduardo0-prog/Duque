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


def _plain(text: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip()


def list_profiles(env: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """Perfis do Chrome deste Windows: pasta, nome mostrado e e-mail."""
    path = user_data_dir(env) / "Local State"
    try:
        local_state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    cache = (local_state.get("profile") or {}).get("info_cache") or {}
    profiles = []
    for directory, info in cache.items():
        if isinstance(info, dict):
            profiles.append({
                "dir": str(directory),
                "name": str(info.get("name") or info.get("shortcut_name") or directory),
                "email": str(info.get("user_name") or ""),
                "account": str(info.get("gaia_name") or info.get("gaia_given_name") or ""),
            })
    return profiles


def match_profile(spoken: str, profiles: list[dict[str, str]]) -> dict[str, str] | None:
    """Perfil citado pelo Du ("perfil Embralan", "conta do trabalho", "Profile 2")."""
    wanted = _plain(spoken)
    for prefix in ("perfil ", "conta ", "do ", "da ", "de "):
        if wanted.startswith(prefix):
            wanted = wanted[len(prefix):].strip()
    if not wanted:
        return None
    for profile in profiles:  # nome exato primeiro
        if wanted in {_plain(profile["name"]), _plain(profile["dir"])}:
            return profile
    for profile in profiles:
        fields = (profile["name"], profile["email"], profile["account"], profile["dir"])
        if any(wanted in _plain(value) or (_plain(value) and _plain(value) in wanted) for value in fields if value):
            return profile
    return None


def chrome_command(
    url: str | None = None, env: Mapping[str, str] | None = None, *, profile_dir: str | None = None,
) -> list[str] | None:
    executable = chrome_executable(env)
    if not executable:
        return None
    command = [executable]
    profile = profile_dir or resolve_profile(env)
    if profile:
        command.append(f"--profile-directory={profile}")
    if url:
        command.append(url)
    return command


def open_in_chrome(url: str | None = None, profile_dir: str | None = None) -> bool:
    """Abre no Chrome do Du (num perfil específico, se pedido). False fora do Windows/sem Chrome."""
    if platform.system() != "Windows":
        return False
    command = chrome_command(url, profile_dir=profile_dir)
    if not command:
        return False
    subprocess.Popen(command, shell=False)
    return True

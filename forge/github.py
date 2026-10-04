from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

API = "https://api.github.com"
OK_CONCLUSIONS = {"success", "neutral", "skipped"}


# Erros que não melhoram esperando: token sem permissão Checks: read, repositório
# privado sem token ou slug errado.
NO_ACCESS = {401, 403, 404}


@dataclass(slots=True)
class CIStatus:
    state: str  # success | failure | pending | none
    failures: list[str] = field(default_factory=list)
    reason: str = ""
    final: bool = False  # True: não adianta continuar consultando


@dataclass(slots=True)
class PullRequest:
    number: int
    url: str


class CodeHost(Protocol):
    def create_pull(self, head: str, base: str, title: str, body: str) -> PullRequest | None: ...

    def wait_for_checks(self, sha: str, *, timeout: int, poll: int, grace: int) -> CIStatus: ...


class GitHubClient:
    """Cliente mínimo da API REST do GitHub (sem dependências externas).

    Leitura de checks funciona sem token em repositório público; criar PR
    exige token (DUQUE_GITHUB_TOKEN ou GITHUB_TOKEN).
    """

    def __init__(self, slug: str | None, token: str | None = None, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.slug = slug
        self.token = token
        self.sleep = sleep

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{API}{path}", data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "duque-forja")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else None

    def create_pull(self, head: str, base: str, title: str, body: str) -> PullRequest | None:
        if not self.slug or not self.token:
            return None
        try:
            data = self._request("POST", f"/repos/{self.slug}/pulls", {"title": title, "head": head, "base": base, "body": body})
            return PullRequest(int(data["number"]), str(data["html_url"]))
        except (OSError, ValueError, KeyError, TypeError):
            # URLError/HTTPError/timeout são OSError; JSON inválido é ValueError.
            return None

    def commit_checks(self, sha: str) -> CIStatus:
        if not self.slug:
            return CIStatus("none", reason="repositório do GitHub desconhecido", final=True)
        try:
            data = self._request("GET", f"/repos/{self.slug}/commits/{sha}/check-runs?per_page=100")
        except urllib.error.HTTPError as exc:
            if exc.code in NO_ACCESS:
                return CIStatus(
                    "none",
                    reason=f"sem acesso aos checks (HTTP {exc.code}); o token precisa de Checks: read",
                    final=True,
                )
            return CIStatus("none", reason=f"GitHub respondeu HTTP {exc.code}")
        except (OSError, ValueError) as exc:
            return CIStatus("none", reason=f"falha de rede ao consultar o CI: {exc}")
        runs = data.get("check_runs", []) if isinstance(data, dict) else []
        if not runs:
            return CIStatus("none")
        if any(run.get("status") != "completed" for run in runs):
            return CIStatus("pending")
        failed = [run for run in runs if run.get("conclusion") not in OK_CONCLUSIONS]
        if not failed:
            return CIStatus("success")
        failures: list[str] = []
        for run in failed:
            failures.append(f"check '{run.get('name')}' terminou como {run.get('conclusion')}")
            try:
                annotations = self._request("GET", f"/repos/{self.slug}/check-runs/{run['id']}/annotations?per_page=50")
            except (OSError, ValueError, KeyError):
                continue
            for item in annotations if isinstance(annotations, list) else []:
                message = str(item.get("message", ""))
                if "Node.js" in message or message.startswith("Process completed"):
                    continue
                failures.append(f"{item.get('path')}:{item.get('start_line')} {message}")
        return CIStatus("failure", failures)

    def wait_for_checks(self, sha: str, *, timeout: int, poll: int, grace: int) -> CIStatus:
        """Espera o CI terminar. 'none' se nenhum check aparecer dentro de `grace`."""
        waited = 0
        status = CIStatus("none")
        while waited <= timeout:
            status = self.commit_checks(sha)
            if status.state in {"success", "failure"} or status.final:
                return status
            if status.state == "none" and waited >= grace:
                return status
            self.sleep(poll)
            waited += poll
        return CIStatus("pending", [f"CI não terminou em {timeout}s"])

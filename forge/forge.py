from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable

from core.tasks import TaskManager

from .config import ForgeConfig, parse_github_slug
from .developer import Developer, SandboxTools
from .git import Git, GitError
from .github import CodeHost, GitHubClient
from .guard import check_changes, touches_workflows
from .quality import QualityGate
from .sandbox import ForgeSandbox


class ForgeStatus(str, Enum):
    MERGED = "merged"                        # aplicado no main
    AWAITING_APPROVAL = "awaiting_approval"  # PR/branch aguardando humano
    NO_CHANGES = "no_changes"
    FAILED = "failed"


@dataclass(slots=True)
class ForgeReport:
    id: str
    goal: str
    status: ForgeStatus = ForgeStatus.FAILED
    branch: str = ""
    commit: str | None = None
    pr_url: str | None = None
    rounds: int = 0
    checks: str = ""
    ci: str = ""
    changed_files: list[str] = field(default_factory=list)
    approval_reasons: list[str] = field(default_factory=list)
    message: str = ""
    error: str | None = None
    log: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def note(self, text: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {text}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    def summary(self) -> str:
        labels = {
            ForgeStatus.MERGED: "Melhoria aplicada no main",
            ForgeStatus.AWAITING_APPROVAL: "Pronto, aguardando sua aprovação",
            ForgeStatus.NO_CHANGES: "Nada precisou ser alterado",
            ForgeStatus.FAILED: "Não consegui concluir",
        }
        parts = [f"{labels[self.status]}: {self.goal}"]
        if self.message:
            parts.append(self.message)
        if self.pr_url:
            parts.append(f"PR: {self.pr_url}")
        if self.approval_reasons:
            parts.append("Motivo: " + "; ".join(self.approval_reasons))
        if self.error:
            parts.append(f"Erro: {self.error}")
        return "\n".join(parts)


class Forge:
    """Orquestra o ciclo completo de auto-desenvolvimento do Duque."""

    def __init__(
        self,
        config: ForgeConfig,
        developer: Developer,
        *,
        gate: QualityGate | None = None,
        host: CodeHost | None = None,
        on_merged: Callable[[ForgeReport], Any] | None = None,
        progress: Callable[[ForgeReport, str], Any] | None = None,
    ) -> None:
        self.config = config
        self.developer = developer
        self.gate = gate or QualityGate(config.checks, strict=config.require_ci)
        if host is None:
            slug = config.github_slug
            if slug is None:
                try:
                    slug = parse_github_slug(Git(config.repo_root).remote_url(config.remote))
                except GitError:
                    slug = None
            host = GitHubClient(slug, config.github_token)
        self.host = host
        self.on_merged = on_merged
        self.progress = progress

    @classmethod
    def create(cls, config: ForgeConfig, model: Any, tasks: TaskManager, **kwargs: Any) -> Forge:
        return cls(config, Developer(model, tasks, max_steps=config.agent_max_steps), **kwargs)

    def _step(self, report: ForgeReport, text: str) -> None:
        report.note(text)
        if self.progress:
            try:
                self.progress(report, text)
            except Exception:
                pass

    def run(self, goal: str) -> ForgeReport:
        sandbox = ForgeSandbox(self.config, goal)
        report = ForgeReport(id=sandbox.id, goal=goal, branch=sandbox.branch)
        try:
            self._step(report, "criando cópia isolada")
            sandbox.create()
            self._develop_and_ship(sandbox, report)
        except Exception as exc:
            report.status = ForgeStatus.FAILED
            report.error = f"{type(exc).__name__}: {exc}"
            self._step(report, f"erro: {report.error}")
        finally:
            sandbox.cleanup()
            report.finished_at = time.time()
            self._save(report)
        if report.status == ForgeStatus.MERGED and self.on_merged:
            self.on_merged(report)
        return report

    def _develop_and_ship(self, sandbox: ForgeSandbox, report: ForgeReport) -> None:
        tools = SandboxTools(sandbox.path, self.gate, sandbox.diff)
        feedback: str | None = None
        # SHA -> falhas do CI: o mesmo commit não é esperado de novo.
        failed_ci: dict[str, list[str]] = {}

        for round_number in range(1, self.config.max_rounds + 1):
            report.rounds = round_number
            self._step(report, f"rodada {round_number}: agente programando")
            result = self.developer.develop(report.goal, tools, feedback)
            report.message = result.message
            if not result.success:
                self._step(report, f"agente não concluiu: {result.error}")

            changes = sandbox.changes()
            report.changed_files = [f"{change.status} {change.path}" for change in changes]
            if not changes:
                report.status = ForgeStatus.NO_CHANGES if result.success else ForgeStatus.FAILED
                report.error = None if result.success else result.error
                return

            self._step(report, "verificação independente (compilação, testes, lint)")
            gate = self.gate.run(sandbox.path)
            report.checks = gate.summary()
            if not gate.passed:
                feedback = gate.failure_report()
                self._step(report, f"verificação falhou: {report.checks}")
                continue

            verdict = check_changes(changes, self.config.protected)
            report.approval_reasons = list(verdict.reasons)
            report.commit = sandbox.commit(self._commit_message(report)) or sandbox.git.head()
            if sandbox.sync_with_base():
                self._step(report, "main mudou; rebaseado, verificando de novo")
                gate = self.gate.run(sandbox.path)
                report.checks = gate.summary()
                if not gate.passed:
                    feedback = gate.failure_report()
                    continue
                report.commit = sandbox.git.head()

            if touches_workflows(changes):
                # Enviar o branch já faria o GitHub rodar o workflow alterado.
                sandbox.keep_branch = True
                report.status = ForgeStatus.AWAITING_APPROVAL
                report.approval_reasons.append(
                    f"altera .github/: branch local {sandbox.branch} não foi enviado; revise e envie manualmente"
                )
                return

            self._step(report, f"enviando branch {sandbox.branch}")
            sandbox.push(force=True)
            if report.pr_url is None:
                pull = self.host.create_pull(sandbox.branch, self.config.base_branch, f"Forja: {report.goal}"[:120], self._pr_body(report))
                report.pr_url = pull.url if pull else None

            if not self.config.auto_merge or not verdict.auto_merge_allowed:
                report.status = ForgeStatus.AWAITING_APPROVAL
                if not self.config.auto_merge:
                    report.approval_reasons.append("merge automático desativado")
                return

            if self.config.require_ci:
                head = sandbox.git.head()
                if head in failed_ci:
                    # Nada mudou desde a falha: esperar o CI de novo daria o mesmo resultado.
                    feedback = "O CI no GitHub (Windows) falhou e nada foi alterado desde então:\n" + "\n".join(failed_ci[head])
                    self._step(report, "commit igual ao que falhou no CI; nova rodada de correção")
                    continue
                self._step(report, "aguardando CI no GitHub")
                ci = self.host.wait_for_checks(
                    head,
                    timeout=self.config.ci_timeout_seconds,
                    poll=self.config.ci_poll_seconds,
                    grace=self.config.ci_grace_seconds,
                )
                report.ci = ci.state
                if ci.state == "failure":
                    failed_ci[head] = list(ci.failures)
                    feedback = "O CI no GitHub (Windows) falhou:\n" + "\n".join(ci.failures)
                    self._step(report, "CI falhou; nova rodada de correção")
                    continue
                if ci.state != "success":
                    report.status = ForgeStatus.AWAITING_APPROVAL
                    detail = f"{ci.state}: {ci.reason}" if ci.reason else ci.state
                    report.approval_reasons.append(f"CI não confirmou ({detail})")
                    return

            try:
                report.commit = sandbox.merge_into_base()
            except GitError as exc:
                report.status = ForgeStatus.AWAITING_APPROVAL
                report.approval_reasons.append(f"main mudou durante o processo: {exc}")
                return
            report.status = ForgeStatus.MERGED
            self._step(report, f"merge no {self.config.base_branch}: {report.commit[:10]}")
            return

        report.status = ForgeStatus.FAILED
        report.error = f"não passou na verificação após {self.config.max_rounds} rodada(s)"

    @staticmethod
    def _commit_message(report: ForgeReport) -> str:
        title = f"forja: {report.goal}".splitlines()[0][:72]
        body = report.message.strip()[:2000]
        return f"{title}\n\n{body}\n\nVerificação: {report.checks}\nGerado pela Forja do Duque ({report.id})."

    @staticmethod
    def _pr_body(report: ForgeReport) -> str:
        files = "\n".join(f"- `{item}`" for item in report.changed_files[:50])
        approval = "\n".join(f"- {reason}" for reason in report.approval_reasons) or "- nenhum (elegível a merge automático)"
        return (
            f"## Objetivo\n{report.goal}\n\n## O que o agente fez\n{report.message or '-'}\n\n"
            f"## Verificação local\n{report.checks}\n\n## Arquivos\n{files}\n\n"
            f"## Exige aprovação humana\n{approval}\n\n_Gerado pela Forja do Duque ({report.id})._"
        )

    def _save(self, report: ForgeReport) -> None:
        try:
            folder = self.config.forge_dir / "reports"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{report.id}.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

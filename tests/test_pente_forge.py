"""Pente fino da Forja, do supervisor e do atualizador (regressões)."""

from __future__ import annotations

import subprocess
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from forge.config import ForgeConfig
from forge.forge import ForgeReport, ForgeStatus
from forge.git import Git, GitError
from forge.github import CIStatus, GitHubClient
from forge.guard import FileChange, check_changes
from forge.quality import QualityGate, sandbox_env
from forge.service import ForgeService
from forge.supervisor import Supervisor
from forge.updater import Updater, read_state
from tests.test_forge import CALC, MUL_TEST, GitRepoTestCase, act, done, git


class SandboxEnvTests(unittest.TestCase):
    def test_secrets_and_live_install_never_reach_agent_code(self) -> None:
        base = {
            "PATH": "/bin",
            "SYSTEMROOT": "C:\\Windows",
            "OPENAI_API_KEY": "sk-x",
            "ANTHROPIC_API_KEY": "a",
            "FISH_API_KEY": "f",
            "GITHUB_TOKEN": "g",
            "DUQUE_GITHUB_TOKEN": "g2",
            "DUQUE_WORKSPACE_ROOT": "C:\\Duque",
            "DUQUE_VOICE": "openai",
            "AWS_SECRET_ACCESS_KEY": "s",
        }
        env = sandbox_env(Path("/tmp/copia"), base)
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FISH_API_KEY", "GITHUB_TOKEN",
                     "DUQUE_GITHUB_TOKEN", "DUQUE_VOICE", "AWS_SECRET_ACCESS_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["DUQUE_WORKSPACE_ROOT"], str(Path("/tmp/copia")))
        self.assertEqual(env["PYTHONPATH"], str(Path("/tmp/copia")))
        self.assertEqual(env["PATH"], "/bin")

    def test_gate_uses_clean_env(self) -> None:
        with mock.patch("forge.quality.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-x"}):
                QualityGate(("compile",)).run(Path(__file__).resolve().parent)
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])

    def test_gate_reports_missing_tool_instead_of_crashing(self) -> None:
        with mock.patch("forge.quality.subprocess.run", side_effect=FileNotFoundError("python")):
            result = QualityGate(("compile",)).run(Path(__file__).resolve().parent)
        self.assertFalse(result.passed)

    def test_default_checks_match_ci(self) -> None:
        self.assertIn("pyright", ForgeConfig(Path("."), Path(".")).checks)
        workflows = sorted(p.name for p in (Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))
        self.assertEqual(workflows, ["quality.yml"])  # um workflow só: checks não duplicados


class GuardBypassTests(unittest.TestCase):
    def test_gate_config_and_python_hooks_need_approval(self) -> None:
        protected = ForgeConfig(Path("."), Path(".")).protected
        for path in ("conftest.py", "tests/conftest.py", "pytest.ini", "setup.cfg", "tox.ini",
                     "sitecustomize.py", "brain/sitecustomize.py", "x.pth", "TELEX_oculto.vbs",
                     "reiniciar_duque.bat", "ruff.toml"):
            with self.subTest(path=path):
                self.assertFalse(check_changes([FileChange("A", path)], protected).auto_merge_allowed)

    def test_changing_existing_test_needs_approval_but_new_test_does_not(self) -> None:
        protected = ForgeConfig(Path("."), Path(".")).protected
        self.assertFalse(check_changes([FileChange("M", "tests/test_core.py")], protected).auto_merge_allowed)
        self.assertTrue(check_changes([FileChange("A", "tests/test_novo.py")], protected).auto_merge_allowed)


class GitErrorTests(unittest.TestCase):
    def test_timeout_and_missing_git_become_git_error(self) -> None:
        with mock.patch("forge.git.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 1)):
            with self.assertRaises(GitError):
                Git(".").run("fetch")
        with mock.patch("forge.git.subprocess.run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(GitError):
                Git(".").run("status")


class GitHubClientTests(unittest.TestCase):
    def test_read_timeout_while_waiting_ci_is_not_fatal(self) -> None:
        client = GitHubClient("dono/repo", sleep=lambda _s: None)
        calls = iter([TimeoutError("lento"), CIStatus("success")])

        def checks(_sha: str) -> CIStatus:
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(client, "commit_checks", side_effect=checks):
            self.assertEqual(client.wait_for_checks("abc", timeout=10, poll=1, grace=5).state, "success")

    def test_pull_request_network_error_returns_none(self) -> None:
        client = GitHubClient("dono/repo", "token")
        with mock.patch.object(client, "_request", side_effect=TimeoutError("sem rede")):
            self.assertIsNone(client.create_pull("a", "main", "t", "b"))


class UpdaterLoopTests(GitRepoTestCase):
    def push_broken(self) -> str:
        other = self.tmp / "other"
        git(self.tmp, "clone", str(self.remote), str(other))
        git(other, "config", "user.name", "Outro")
        git(other, "config", "user.email", "outro@example.test")
        (other / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
        git(other, "commit", "-am", "quebra")
        git(other, "push", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def test_failed_version_is_not_applied_again(self) -> None:
        broken = self.push_broken()
        updater = Updater(self.live, smoke=QualityGate(("compile", "pytest")))
        self.assertEqual(updater.apply().status, "rolled_back")
        self.assertEqual(read_state(self.live / "duque_data" / "update_state.json")["failed"], broken)
        with mock.patch.object(updater.smoke, "run") as smoke:
            result = updater.apply()
        self.assertEqual(result.status, "refused", result.message)
        smoke.assert_not_called()
        self.assertNotEqual(git(self.live, "rev-parse", "HEAD"), broken)


class _Proc:
    def __init__(self, ignores_terminate: bool = False) -> None:
        self.ignores_terminate = ignores_terminate
        self.killed = False
        self.terminated = False

    def poll(self) -> int | None:
        if self.killed or (self.terminated and not self.ignores_terminate):
            return 1
        return None

    def wait(self) -> int:
        return 1

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class SupervisorRobustnessTests(unittest.TestCase):
    def make(self, spawn: Any) -> Supervisor:
        clock = {"now": 0.0}

        def sleep(seconds: float) -> None:
            clock["now"] += seconds

        return Supervisor(Path("."), ["duque"], spawn=spawn, health=lambda: False, sleep=sleep,
                          clock=lambda: clock["now"], log=lambda _m: None)

    def test_spawn_failure_does_not_crash_supervisor(self) -> None:
        def spawn(*_args: Any) -> Any:
            raise FileNotFoundError("pythonw.exe")

        self.assertEqual(self.make(spawn).run(), 1)

    def test_stop_kills_process_that_ignores_terminate(self) -> None:
        process = _Proc(ignores_terminate=True)
        self.make(lambda *_a: process)._stop(process)  # type: ignore[arg-type]
        self.assertTrue(process.killed)


class _OneShotForge:
    def __init__(self) -> None:
        self.progress = None
        self.goals: list[str] = []

    def run(self, goal: str) -> ForgeReport:
        self.goals.append(goal)
        return ForgeReport(id="x", goal=goal, status=ForgeStatus.NO_CHANGES)


class ForgeServiceRaceTests(unittest.TestCase):
    def test_job_submitted_while_worker_exits_still_runs(self) -> None:
        forge = _OneShotForge()
        service = ForgeService(forge)  # type: ignore[arg-type]
        # Simula a thread antiga ainda viva, mas já decidida a sair.
        release = threading.Event()
        old = threading.Thread(target=release.wait, daemon=True)
        old.start()
        service._thread = old
        service._worker_exiting = True
        try:
            service.submit("tarefa")
            deadline = time.monotonic() + 5
            while not forge.goals and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(forge.goals, ["tarefa"])
        finally:
            release.set()


class GithubChangesStayLocalTests(GitRepoTestCase):
    def test_workflow_change_is_not_pushed_before_approval(self) -> None:
        from tests.test_forge import FakeHost

        workflow = "name: x\non: push\njobs: {}\n"
        forge, _model, host = self.forge([
            act("write_file", path=".github/workflows/novo.yml", content=workflow),
            act("write_file", path="tests/test_mul.py", content=MUL_TEST),
            act("edit_file", path="calc.py", old=CALC, new=CALC + "\n\ndef multiplica(a, b):\n    return a * b\n"),
            done("workflow novo"),
        ], host=FakeHost())
        report = forge.run("adicionar workflow")
        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL, "\n".join(report.log))
        remote_branches = git(self.remote, "branch", "--list")
        self.assertNotIn(report.branch, remote_branches)  # nada enviado ao GitHub
        self.assertIn(report.branch, git(self.live, "branch", "--list"))  # fica para revisão
        self.assertEqual(host.pulls, [])
        self.assertFalse((self.live / "duque_data" / "forja" / "work" / report.id).exists())


if __name__ == "__main__":
    unittest.main()

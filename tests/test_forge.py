from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from brain.providers.anthropic_provider import ClaudeAdapter, to_anthropic_messages
from forge.config import ForgeConfig, parse_github_slug
from forge.developer import Developer, SandboxTools
from forge.forge import Forge, ForgeStatus
from forge.github import CIStatus, GitHubClient, PullRequest
from forge.guard import FileChange, check_changes
from forge.quality import QualityGate, sandbox_env
from forge.service import ForgeService
from forge.supervisor import Supervisor
from forge.updater import RESTART_EXIT_CODE, Updater, read_state, write_state
from tests.helpers import ScriptedModel, TempDirTestCase

CALC = "def soma(a, b):\n    return a + b\n"
CALC_TEST = (
    "import unittest\n\nfrom calc import soma\n\n\n"
    "class SomaTest(unittest.TestCase):\n"
    "    def test_soma(self):\n        self.assertEqual(soma(2, 3), 5)\n"
)
MUL_TEST = (
    "import unittest\n\nfrom calc import multiplica\n\n\n"
    "class MultiplicaTest(unittest.TestCase):\n"
    "    def test_multiplica(self):\n        self.assertEqual(multiplica(2, 3), 6)\n"
)
MUL = "\n\ndef multiplica(a, b):\n    return a * b\n"


def act(tool: str, **arguments) -> str:
    return json.dumps({"action": "tool", "tool": tool, "arguments": arguments})


def done(message: str = "feito e verificado") -> str:
    return json.dumps({"action": "finish", "message": message})


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return completed.stdout.strip()


class FakeHost:
    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = list(statuses or ["success"])
        self.pulls: list[tuple[str, str]] = []
        self.checked: list[str] = []

    def create_pull(self, head: str, base: str, title: str, body: str) -> PullRequest | None:
        self.pulls.append((head, title))
        return PullRequest(len(self.pulls), f"https://example.test/pull/{len(self.pulls)}")

    def wait_for_checks(self, sha: str, *, timeout: int, poll: int, grace: int) -> CIStatus:
        self.checked.append(sha)
        state = self.statuses.pop(0) if self.statuses else "success"
        return CIStatus(state, ["tests/test_calc.py:8 AssertionError: 5 != 6"] if state == "failure" else [])


class GitRepoTestCase(TempDirTestCase):
    """Remoto 'bare' + clone que faz o papel da instalação do Duque."""

    def setUp(self) -> None:
        super().setUp()
        self.remote = self.tmp / "remote.git"
        self.live = self.tmp / "live"
        git(self.tmp, "init", "--bare", "-b", "main", str(self.remote))
        git(self.tmp, "clone", str(self.remote), str(self.live))
        for key, value in (("user.name", "Teste"), ("user.email", "teste@example.test")):
            git(self.live, "config", key, value)
        git(self.live, "checkout", "-b", "main")
        (self.live / "calc.py").write_text(CALC, encoding="utf-8")
        (self.live / "tests").mkdir()
        (self.live / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.live / "tests" / "test_calc.py").write_text(CALC_TEST, encoding="utf-8")
        (self.live / "core").mkdir()
        (self.live / "core" / "security.py").write_text("NIVEL = 'alto'\n", encoding="utf-8")
        (self.live / ".gitignore").write_text("duque_data/\n__pycache__/\n", encoding="utf-8")
        git(self.live, "add", "-A")
        git(self.live, "commit", "-m", "inicial")
        git(self.live, "push", "-u", "origin", "main")

    def remote_main_file(self, path: str) -> str:
        return git(self.remote, "show", f"main:{path}")

    def config(self, **overrides) -> ForgeConfig:
        values = dict(
            repo_root=self.live,
            forge_dir=self.live / "duque_data" / "forja",
            checks=("compile", "pytest"),
            ci_poll_seconds=0,
            ci_grace_seconds=0,
            github_slug="dono/duque",
        )
        values.update(overrides)
        return ForgeConfig(**values)

    def forge(self, replies: list[str], host: FakeHost | None = None, **overrides) -> tuple[Forge, ScriptedModel, FakeHost]:
        model = ScriptedModel(replies)
        host = host or FakeHost()
        config = self.config(**overrides)
        forge = Forge(config, Developer(model, self.tasks, max_steps=20), gate=QualityGate(config.checks), host=host)
        return forge, model, host


ADD_MUL = [
    act("read_file", path="calc.py"),
    act("edit_file", path="calc.py", old="    return a + b\n", new="    return a + b\n" + MUL),
    act("write_file", path="tests/test_mul.py", content=MUL_TEST),
    act("run_checks"),
    done("adicionei multiplica com teste"),
]


class ForgeFlowTests(GitRepoTestCase):
    def test_change_is_verified_pushed_and_merged(self) -> None:
        forge, _model, host = self.forge(ADD_MUL)
        report = forge.run("adicionar multiplicação")

        self.assertEqual(report.status, ForgeStatus.MERGED, report.summary() + "\n" + "\n".join(report.log))
        self.assertIn("multiplica", self.remote_main_file("calc.py"))
        self.assertIn("multiplica", self.remote_main_file("tests/test_mul.py"))
        self.assertEqual(len(host.pulls), 1)
        self.assertEqual(host.checked, [report.commit])
        # a instalação ao vivo não foi tocada pela Forja
        self.assertNotIn("multiplica", (self.live / "calc.py").read_text(encoding="utf-8"))

    def test_sandbox_is_removed_after_run(self) -> None:
        forge, _model, _host = self.forge(ADD_MUL)
        report = forge.run("adicionar multiplicação")
        self.assertFalse((self.live / "duque_data" / "forja" / "work" / report.id).exists())
        self.assertNotIn(report.branch, git(self.live, "branch", "--list"))
        saved = json.loads((self.live / "duque_data" / "forja" / "reports" / f"{report.id}.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "merged")

    def test_failed_verification_feeds_back_into_next_round(self) -> None:
        forge, model, _host = self.forge([
            act("write_file", path="calc.py", content="def soma(a, b)\n    return a + b\n"),
            act("show_diff"),
            done("pronto"),
            act("write_file", path="calc.py", content=CALC + MUL),
            act("write_file", path="tests/test_mul.py", content=MUL_TEST),
            act("run_checks"),
            done("corrigido"),
        ])
        report = forge.run("adicionar multiplicação")

        self.assertEqual(report.status, ForgeStatus.MERGED, "\n".join(report.log))
        self.assertEqual(report.rounds, 2)
        second_round_goal = next(call for call in model.calls if "ATENÇÃO" in call[1]["content"])
        self.assertIn("compile", second_round_goal[1]["content"])

    def test_gives_up_after_max_rounds_without_pushing(self) -> None:
        broken = [act("write_file", path="calc.py", content="def soma(:\n"), act("show_diff"), done("pronto")]
        forge, _model, host = self.forge(broken * 2, max_rounds=2)
        report = forge.run("quebrar")
        self.assertEqual(report.status, ForgeStatus.FAILED)
        self.assertEqual(host.pulls, [])
        self.assertEqual(self.remote_main_file("calc.py"), CALC.strip())

    def test_protected_file_waits_for_human_approval(self) -> None:
        forge, _model, host = self.forge([
            act("write_file", path="core/security.py", content="NIVEL = 'baixo'\n"),
            act("run_checks"),
            done("baixei a segurança"),
        ])
        report = forge.run("mexer na segurança")

        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL)
        self.assertTrue(any("core/security.py" in reason for reason in report.approval_reasons))
        self.assertEqual(self.remote_main_file("core/security.py"), "NIVEL = 'alto'")
        self.assertIn(report.branch, git(self.remote, "branch", "--list"))
        self.assertEqual(host.checked, [])

    def test_ci_failure_triggers_fix_round(self) -> None:
        host = FakeHost(["failure", "success"])
        fix = act("edit_file", path="calc.py", old="    return a * b\n", new="    return a * b  # revisado\n")
        forge, model, _ = self.forge(ADD_MUL + [fix, done("revisado após CI")], host=host)
        report = forge.run("adicionar multiplicação")

        self.assertEqual(report.status, ForgeStatus.MERGED, "\n".join(report.log))
        self.assertEqual(len(host.checked), 2)
        self.assertTrue(any("CI no GitHub" in call[1]["content"] for call in model.calls))

    def test_ci_without_result_does_not_merge(self) -> None:
        forge, _model, _host = self.forge(ADD_MUL, host=FakeHost(["none"]))
        report = forge.run("adicionar multiplicação")
        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL)
        self.assertNotIn("multiplica", self.remote_main_file("calc.py"))

    def test_auto_merge_disabled_leaves_pr_open(self) -> None:
        forge, _model, _host = self.forge(ADD_MUL, auto_merge=False)
        report = forge.run("adicionar multiplicação")
        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL)
        self.assertIsNotNone(report.pr_url)

    def test_no_changes(self) -> None:
        forge, _model, host = self.forge([act("list_files"), done("já estava certo")])
        report = forge.run("verificar")
        self.assertEqual(report.status, ForgeStatus.NO_CHANGES)
        self.assertEqual(host.pulls, [])

    def test_rebases_when_main_moves(self) -> None:
        other = self.tmp / "other"
        git(self.tmp, "clone", str(self.remote), str(other))
        git(other, "config", "user.name", "Outro")
        git(other, "config", "user.email", "outro@example.test")
        (other / "LEIAME.md").write_text("novo\n", encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-m", "mudança paralela")

        replies = list(ADD_MUL)
        # empurra a mudança paralela enquanto o agente ainda está trabalhando
        replies.insert(1, act("list_files"))
        forge, _model, _host = self.forge(replies)
        original = forge.developer.develop

        def develop_and_race(goal, tools, feedback=None):
            git(other, "push", "origin", "HEAD:main")
            return original(goal, tools, feedback)

        forge.developer.develop = develop_and_race  # type: ignore[method-assign]
        report = forge.run("adicionar multiplicação")

        self.assertEqual(report.status, ForgeStatus.MERGED, "\n".join(report.log))
        self.assertEqual(self.remote_main_file("LEIAME.md"), "novo")
        self.assertIn("multiplica", self.remote_main_file("calc.py"))


    def test_workflow_changes_are_never_pushed(self) -> None:
        forge, _model, host = self.forge([
            act("write_file", path=".github/workflows/x.yml", content="name: x\n"),
            act("write_file", path="tests/test_mul.py", content=MUL_TEST.replace("multiplica", "soma").replace("6", "5")),
            done("mexi no CI"),
        ])
        report = forge.run("mexer no CI")

        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL, "\n".join(report.log))
        self.assertEqual(host.pulls, [])
        self.assertNotIn(report.branch, git(self.remote, "branch", "--list"))
        # o branch fica na instalação local para revisão humana
        self.assertIn(report.branch, git(self.live, "branch", "--list"))

    def test_same_failed_sha_is_not_rechecked(self) -> None:
        host = FakeHost(["failure", "success"])
        forge, _model, _ = self.forge(ADD_MUL + [act("list_files"), done("nada mudou")], host=host, max_rounds=2)
        report = forge.run("adicionar multiplicação")

        self.assertEqual(report.status, ForgeStatus.FAILED, "\n".join(report.log))
        self.assertEqual(len(host.checked), 1)

    def test_modifying_existing_test_needs_approval(self) -> None:
        forge, _model, host = self.forge([
            act("write_file", path="tests/test_calc.py", content=CALC_TEST.replace("5)", "5)  # revisado")),
            done("ajustei teste"),
        ])
        report = forge.run("ajustar teste")
        self.assertEqual(report.status, ForgeStatus.AWAITING_APPROVAL, "\n".join(report.log))
        self.assertTrue(any("altera teste existente" in reason for reason in report.approval_reasons))
        self.assertEqual(host.checked, [])


class ForgeServiceTests(unittest.TestCase):
    def test_worker_restarts_after_idle_exit(self) -> None:
        import threading

        ran: list[str] = []
        finished = threading.Event()

        class StubForge:
            progress = None

            def run(self, goal: str):
                ran.append(goal)
                finished.set()
                from forge.forge import ForgeReport
                return ForgeReport(id="x", goal=goal, status=ForgeStatus.NO_CHANGES)

        service = ForgeService(StubForge())  # type: ignore[arg-type]
        service.submit("um")
        self.assertTrue(finished.wait(5))
        # simula o worker que saiu por ociosidade
        thread = service._thread
        if thread is not None:
            with service._worker_lock:
                service._thread = None
        finished.clear()
        service.submit("dois")
        self.assertTrue(finished.wait(5))
        self.assertEqual(ran, ["um", "dois"])


class SandboxToolsTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.tmp / "projeto"
        self.root.mkdir()
        (self.root / "a.py").write_text("x = 1\nx = 1\ny = 2\n", encoding="utf-8")
        self.tools = SandboxTools(self.root, QualityGate(("compile",)), lambda: "")

    def test_edit_requires_unique_match(self) -> None:
        self.assertFalse(self.tools.edit_file("a.py", "x = 1\n", "x = 3\n")["success"])
        self.tools.edit_file("a.py", "y = 2", "y = 3")
        self.assertIn("y = 3", (self.root / "a.py").read_text(encoding="utf-8"))

    def test_paths_escape_is_blocked(self) -> None:
        with self.assertRaises(PermissionError):
            self.tools.write_file("../fora.py", "x")

    def test_git_internals_are_refused(self) -> None:
        (self.root / ".git").mkdir()
        with self.assertRaises(PermissionError):
            self.tools.write_file(".git/hooks/pre-commit", "x")

    def test_interface_is_visible(self) -> None:
        (self.root / "interface").mkdir()
        (self.root / "interface" / "index.html").write_text("<p>x = 1</p>\n", encoding="utf-8")
        self.assertIn("interface/index.html", self.tools.list_files()["files"])

    def test_search_and_list_skip_internal_dirs(self) -> None:
        (self.root / "duque_data").mkdir()
        (self.root / "duque_data" / "b.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(self.tools.list_files()["files"], ["a.py"])
        self.assertEqual(len(self.tools.search_code(r"x = 1")["matches"]), 2)


class GuardAndConfigTests(unittest.TestCase):
    def test_guard(self) -> None:
        protected = ForgeConfig(Path("."), Path(".")).protected
        self.assertTrue(check_changes([FileChange("M", "brain/agent_loop.py"), FileChange("A", "tests/test_x.py")], protected).auto_merge_allowed)
        for change in (FileChange("M", "core/security.py"), FileChange("M", "forge/forge.py"), FileChange("M", ".github/workflows/ci.yml"), FileChange("D", "tests/test_core.py")):
            with self.subTest(change=change):
                self.assertFalse(check_changes([change], protected).auto_merge_allowed)

    def test_guard_protects_test_configuration(self) -> None:
        protected = ForgeConfig(Path("."), Path(".")).protected
        for path in ("pytest.ini", "setup.cfg", "tox.ini", "conftest.py", "tests/conftest.py", "a/b/conftest.py",
                     "sitecustomize.py", "usercustomize.py", ".gitignore", ".gitattributes"):
            with self.subTest(path=path):
                self.assertFalse(check_changes([FileChange("A", path)], protected).auto_merge_allowed)
        self.assertFalse(check_changes([FileChange("M", "tests/test_core.py")], protected).auto_merge_allowed)

    def test_quality_env_strips_secrets(self) -> None:
        base = {
            "PATH": "/bin", "OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t",
            "DUQUE_GITHUB_TOKEN": "t", "DUQUE_FORGE_DIR": "/forja", "DUQUE_WORKSPACE_ROOT": "/ao-vivo",
        }
        env = sandbox_env(Path("/sandbox"), base)
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "DUQUE_GITHUB_TOKEN", "DUQUE_FORGE_DIR"):
            self.assertNotIn(key, env)
        self.assertEqual(env["DUQUE_WORKSPACE_ROOT"], str(Path("/sandbox")))
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_strict_gate_fails_without_tool(self) -> None:
        gate = QualityGate(("ruff",), strict=True)
        gate._tool_command = lambda name: None  # type: ignore[method-assign]
        self.assertFalse(gate.run(Path(".")).passed)

    def test_checks_without_access_are_final(self) -> None:
        import urllib.error

        client = GitHubClient("dono/repo", sleep=lambda _s: None)

        def forbidden(*_args, **_kwargs):
            raise urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", None, None)  # type: ignore[arg-type]

        client._request = forbidden  # type: ignore[method-assign]
        status = client.wait_for_checks("abc", timeout=100, poll=1, grace=50)
        self.assertEqual(status.state, "none")
        self.assertIn("403", status.reason)

    def test_parse_github_slug(self) -> None:
        self.assertEqual(parse_github_slug("https://github.com/zaninieduardo0-prog/Duque.git"), "zaninieduardo0-prog/Duque")
        self.assertEqual(parse_github_slug("git@github.com:dono/repo.git"), "dono/repo")
        self.assertIsNone(parse_github_slug("https://gitlab.com/dono/repo.git"))


class ClaudeAdapterTests(unittest.TestCase):
    def test_message_conversion(self) -> None:
        system, messages = to_anthropic_messages([
            {"role": "system", "content": "regras"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ])
        self.assertEqual(system, "regras")
        self.assertEqual(messages, [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "c"}])

    def test_conversation_always_starts_with_user(self) -> None:
        _system, messages = to_anthropic_messages([{"role": "assistant", "content": "oi"}])
        self.assertEqual(messages[0]["role"], "user")

    def test_respond_uses_client(self) -> None:
        class Block:
            type = "text"
            text = '{"action":"finish","message":"ok"}'

        class Response:
            content = [Block()]

        class Messages:
            def __init__(self) -> None:
                self.params: dict = {}

            def create(self, **params):
                self.params = params
                return Response()

        class Client:
            messages = Messages()

        client = Client()
        adapter = ClaudeAdapter("modelo-teste", client=client)
        reply = adapter.respond([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        self.assertEqual(reply.text, '{"action":"finish","message":"ok"}')
        self.assertEqual(client.messages.params["system"], "s")
        self.assertEqual(client.messages.params["model"], "modelo-teste")


class UpdaterTests(GitRepoTestCase):
    def push_from_other(self, files: dict[str, str]) -> str:
        other = self.tmp / "other"
        if not other.exists():
            git(self.tmp, "clone", str(self.remote), str(other))
            git(other, "config", "user.name", "Outro")
            git(other, "config", "user.email", "outro@example.test")
        for path, content in files.items():
            (other / path).write_text(content, encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-m", "atualização")
        git(other, "push", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def updater(self) -> Updater:
        return Updater(self.live, smoke=QualityGate(("compile", "pytest")))

    def test_up_to_date(self) -> None:
        self.assertEqual(self.updater().apply().status, "up_to_date")

    def test_updates_and_marks_pending_restart(self) -> None:
        target = self.push_from_other({"calc.py": CALC + MUL})
        result = self.updater().apply()
        self.assertEqual(result.status, "updated", result.message)
        self.assertEqual(git(self.live, "rev-parse", "HEAD"), target)
        state_path = self.live / "duque_data" / "update_state.json"
        # sem reinício garantido, o supervisor não deve colocar a versão em observação
        self.assertEqual(read_state(state_path)["status"], "updated")
        self.updater().mark_pending_restart(result)
        state = read_state(state_path)
        self.assertEqual(state["status"], "pending_restart")
        self.assertEqual(state["current"], target)

    def test_broken_update_is_rolled_back(self) -> None:
        previous = git(self.live, "rev-parse", "HEAD")
        self.push_from_other({"calc.py": "def soma(a, b):\n    return a - b\n"})
        result = self.updater().apply()
        self.assertEqual(result.status, "rolled_back", result.message)
        self.assertEqual(git(self.live, "rev-parse", "HEAD"), previous)

    def test_does_not_reapply_failed_version(self) -> None:
        previous = git(self.live, "rev-parse", "HEAD")
        self.push_from_other({"calc.py": "def soma(a, b):\n    return a - b\n"})
        self.assertEqual(self.updater().apply().status, "rolled_back")
        result = self.updater().apply()
        self.assertEqual(result.status, "refused", result.message)
        self.assertEqual(git(self.live, "rev-parse", "HEAD"), previous)

    def test_never_discards_local_changes(self) -> None:
        self.push_from_other({"calc.py": CALC + MUL})
        (self.live / "calc.py").write_text(CALC + "# edição do Du\n", encoding="utf-8")
        result = self.updater().apply()
        self.assertEqual(result.status, "refused")
        self.assertIn("edição do Du", (self.live / "calc.py").read_text(encoding="utf-8"))


class FakeProcess:
    def __init__(self, code: int, alive_checks: int = 0) -> None:
        self.code = code
        self.alive_checks = alive_checks
        self.terminated = False

    def poll(self) -> int | None:
        if self.terminated:
            return self.code
        if self.alive_checks > 0:
            self.alive_checks -= 1
            return None
        return self.code

    def wait(self) -> int:
        return self.code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class SupervisorTests(GitRepoTestCase):
    def supervisor(self, processes: list[FakeProcess], healthy: list[bool]) -> Supervisor:
        clock = {"now": 0.0}

        def sleep(seconds: float) -> None:
            clock["now"] += seconds

        return Supervisor(
            self.live,
            ["duque"],
            spawn=lambda command, env, cwd: processes.pop(0),
            health=lambda: healthy.pop(0) if healthy else False,
            sleep=sleep,
            clock=lambda: clock["now"],
            probation_seconds=10,
            log=lambda message: None,
        )

    def test_restart_request_then_clean_exit(self) -> None:
        processes = [FakeProcess(RESTART_EXIT_CODE), FakeProcess(0)]
        self.assertEqual(self.supervisor(processes, []).run(), 0)
        self.assertEqual(processes, [])

    def test_healthy_update_is_confirmed(self) -> None:
        head = git(self.live, "rev-parse", "HEAD")
        state_path = self.live / "duque_data" / "update_state.json"
        write_state(state_path, status="pending_restart", previous=head, current=head)
        self.supervisor([FakeProcess(0, alive_checks=5)], [False, True]).run()
        self.assertEqual(read_state(state_path)["status"], "ok")

    def test_unhealthy_update_is_rolled_back(self) -> None:
        previous = git(self.live, "rev-parse", "HEAD")
        (self.live / "calc.py").write_text(CALC + MUL, encoding="utf-8")
        git(self.live, "commit", "-am", "nova versão")
        current = git(self.live, "rev-parse", "HEAD")
        state_path = self.live / "duque_data" / "update_state.json"
        write_state(state_path, status="pending_restart", previous=previous, current=current)

        self.supervisor([FakeProcess(1, alive_checks=100), FakeProcess(0)], []).run()

        self.assertEqual(git(self.live, "rev-parse", "HEAD"), previous)
        self.assertEqual(read_state(state_path)["status"], "rolled_back")

    def test_rollback_refuses_dirty_tree(self) -> None:
        previous = git(self.live, "rev-parse", "HEAD")
        (self.live / "calc.py").write_text(CALC + MUL, encoding="utf-8")
        git(self.live, "commit", "-am", "nova versão")
        current = git(self.live, "rev-parse", "HEAD")
        (self.live / "calc.py").write_text(CALC + MUL + "# edição do Du\n", encoding="utf-8")
        state_path = self.live / "duque_data" / "update_state.json"
        write_state(state_path, status="pending_restart", previous=previous, current=current)

        self.supervisor([FakeProcess(1, alive_checks=100), FakeProcess(0)], []).run()

        self.assertEqual(git(self.live, "rev-parse", "HEAD"), current)
        self.assertIn("edição do Du", (self.live / "calc.py").read_text(encoding="utf-8"))
        self.assertEqual(read_state(state_path)["status"], "rollback_refused")

    def test_stops_after_repeated_crashes(self) -> None:
        processes = [FakeProcess(1) for _ in range(5)]
        self.assertEqual(self.supervisor(processes, []).run(), 1)


if __name__ == "__main__":
    unittest.main()
